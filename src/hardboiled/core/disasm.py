"""Desensamblador RV32I + M + Zicsr + C (comprimidas).

Las instrucciones comprimidas (16 bits) se expanden a su equivalente de 32 bits
y se muestran con el prefijo `c.`; así el resto del código (y el alumno) ve una
sola forma de cada instrucción. Se usan los nombres ABI de los registros y las
pseudoinstrucciones habituales de `objdump` (li, mv, j, ret, call, beqz…).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hardboiled.core.cpu import ABI_NAMES

Symbolizer = Callable[[int], str | None]

CSR_NAMES = {
    0x300: "mstatus",
    0x304: "mie",
    0x305: "mtvec",
    0x340: "mscratch",
    0x341: "mepc",
    0x342: "mcause",
    0x343: "mtval",
    0x344: "mip",
    0xC00: "cycle",
    0xC01: "time",
    0xC02: "instret",
}


@dataclass(frozen=True)
class Instruction:
    address: int
    size: int  # 2 (comprimida) o 4
    raw: int  # como está en memoria
    word: int  # equivalente de 32 bits
    mnemonic: str
    operands: str
    target: int | None = None  # destino de saltos y branches

    @property
    def text(self) -> str:
        return f"{self.mnemonic} {self.operands}".rstrip()

    @property
    def is_call(self) -> bool:
        opcode = self.word & 0x7F
        return opcode in (0x6F, 0x67) and (self.word >> 7) & 0x1F == 1


def _sign(value: int, bits: int) -> int:
    return value - (1 << bits) if value >> (bits - 1) & 1 else value


def _reg(index: int) -> str:
    return ABI_NAMES[index]


# ------------------------------------------------------------ campos 32 bits


def _imm_i(w: int) -> int:
    return _sign(w >> 20, 12)


def _imm_s(w: int) -> int:
    return _sign(((w >> 25) << 5) | ((w >> 7) & 0x1F), 12)


def _imm_b(w: int) -> int:
    value = (
        ((w >> 31) & 1) << 12
        | ((w >> 7) & 1) << 11
        | ((w >> 25) & 0x3F) << 5
        | ((w >> 8) & 0xF) << 1
    )
    return _sign(value, 13)


def _imm_j(w: int) -> int:
    value = (
        ((w >> 31) & 1) << 20
        | ((w >> 12) & 0xFF) << 12
        | ((w >> 20) & 1) << 11
        | ((w >> 21) & 0x3FF) << 1
    )
    return _sign(value, 21)


# ------------------------------------------------------- codificadores (RVC)


def _enc_r(funct7: int, rs2: int, rs1: int, funct3: int, rd: int, opcode: int) -> int:
    return funct7 << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def _enc_i(imm: int, rs1: int, funct3: int, rd: int, opcode: int) -> int:
    return (imm & 0xFFF) << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def _enc_s(imm: int, rs2: int, rs1: int, funct3: int, opcode: int) -> int:
    imm &= 0xFFF
    return (imm >> 5) << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | (imm & 0x1F) << 7 | opcode


def _enc_b(imm: int, rs2: int, rs1: int, funct3: int) -> int:
    imm &= 0x1FFF
    return (
        ((imm >> 12) & 1) << 31
        | ((imm >> 5) & 0x3F) << 25
        | rs2 << 20
        | rs1 << 15
        | funct3 << 12
        | ((imm >> 1) & 0xF) << 8
        | ((imm >> 11) & 1) << 7
        | 0x63
    )


def _enc_j(imm: int, rd: int) -> int:
    imm &= 0x1FFFFF
    return (
        ((imm >> 20) & 1) << 31
        | ((imm >> 1) & 0x3FF) << 21
        | ((imm >> 11) & 1) << 20
        | ((imm >> 12) & 0xFF) << 12
        | rd << 7
        | 0x6F
    )


def _enc_u(imm20: int, rd: int, opcode: int) -> int:
    return (imm20 & 0xFFFFF) << 12 | rd << 7 | opcode


def expand_compressed(half: int) -> int | None:
    """Instrucción de 32 bits equivalente a una comprimida (None si es ilegal)."""
    op = half & 0x3
    funct3 = half >> 13

    def bits(high: int, low: int) -> int:
        return (half >> low) & ((1 << (high - low + 1)) - 1)

    rd_p = bits(4, 2) + 8  # rd'/rs2' en [4:2]
    rs1_p = bits(9, 7) + 8  # rs1' en [9:7]
    rd = bits(11, 7)
    rs2 = bits(6, 2)
    if half == 0:
        return None
    if op == 0:
        if funct3 == 0:  # c.addi4spn
            imm = bits(10, 7) << 6 | bits(12, 11) << 4 | bits(5, 5) << 3 | bits(6, 6) << 2
            return _enc_i(imm, 2, 0, rd_p, 0x13) if imm else None
        if funct3 == 2:  # c.lw
            imm = bits(5, 5) << 6 | bits(12, 10) << 3 | bits(6, 6) << 2
            return _enc_i(imm, rs1_p, 2, rd_p, 0x03)
        if funct3 == 6:  # c.sw
            imm = bits(5, 5) << 6 | bits(12, 10) << 3 | bits(6, 6) << 2
            return _enc_s(imm, rd_p, rs1_p, 2, 0x23)
        return None
    if op == 1:
        imm6 = _sign(bits(12, 12) << 5 | bits(6, 2), 6)
        if funct3 == 0:  # c.addi / c.nop
            return _enc_i(imm6, rd, 0, rd, 0x13)
        if funct3 in (1, 5):  # c.jal (RV32) / c.j
            imm = _sign(
                bits(12, 12) << 11
                | bits(8, 8) << 10
                | bits(10, 9) << 8
                | bits(6, 6) << 7
                | bits(7, 7) << 6
                | bits(2, 2) << 5
                | bits(11, 11) << 4
                | bits(5, 3) << 1,
                12,
            )
            return _enc_j(imm, 1 if funct3 == 1 else 0)
        if funct3 == 2:  # c.li
            return _enc_i(imm6, 0, 0, rd, 0x13)
        if funct3 == 3:
            if rd == 2:  # c.addi16sp
                imm = _sign(
                    bits(12, 12) << 9
                    | bits(4, 3) << 7
                    | bits(5, 5) << 6
                    | bits(2, 2) << 5
                    | bits(6, 6) << 4,
                    10,
                )
                return _enc_i(imm, 2, 0, 2, 0x13) if imm else None
            return _enc_u(imm6, rd, 0x37) if imm6 else None  # c.lui
        if funct3 == 4:
            kind = bits(11, 10)
            shamt = bits(6, 2)
            if kind in (0, 1) and bits(12, 12):
                return None  # desplazamientos >= 32: reservados en RV32
            if kind == 0:  # c.srli
                return _enc_i(shamt, rs1_p, 5, rs1_p, 0x13)
            if kind == 1:  # c.srai
                return _enc_i(0x400 | shamt, rs1_p, 5, rs1_p, 0x13)
            if kind == 2:  # c.andi
                return _enc_i(imm6, rs1_p, 7, rs1_p, 0x13)
            if bits(12, 12) == 0:
                sub = bits(6, 5)
                funct = {0: (0x20, 0), 1: (0, 4), 2: (0, 6), 3: (0, 7)}[sub]
                return _enc_r(funct[0], rd_p, rs1_p, funct[1], rs1_p, 0x33)
            return None
        if funct3 in (6, 7):  # c.beqz / c.bnez
            imm = _sign(
                bits(12, 12) << 8
                | bits(6, 5) << 6
                | bits(2, 2) << 5
                | bits(11, 10) << 3
                | bits(4, 3) << 1,
                9,
            )
            return _enc_b(imm, 0, rs1_p, 0 if funct3 == 6 else 1)
        return None
    if op == 2:
        if funct3 == 0:  # c.slli (el bit 12 en 1 es reservado en RV32)
            return None if bits(12, 12) else _enc_i(bits(6, 2), rd, 1, rd, 0x13)
        if funct3 == 2:  # c.lwsp
            imm = bits(3, 2) << 6 | bits(12, 12) << 5 | bits(6, 4) << 2
            return _enc_i(imm, 2, 2, rd, 0x03) if rd else None
        if funct3 == 4:
            if bits(12, 12) == 0:
                if rs2 == 0:  # c.jr
                    return _enc_i(0, rd, 0, 0, 0x67) if rd else None
                return _enc_r(0, rs2, 0, 0, rd, 0x33)  # c.mv
            if rd == 0 and rs2 == 0:
                return 0x00100073  # c.ebreak
            if rs2 == 0:  # c.jalr
                return _enc_i(0, rd, 0, 1, 0x67)
            return _enc_r(0, rs2, rd, 0, rd, 0x33)  # c.add
        if funct3 == 6:  # c.swsp
            imm = bits(8, 7) << 6 | bits(12, 9) << 2
            return _enc_s(imm, rs2, 2, 2, 0x23)
    return None


# ----------------------------------------------------------- decodificación


def _format(word: int, address: int, symbolize: Symbolizer | None) -> tuple[str, str, int | None]:
    opcode = word & 0x7F
    rd = (word >> 7) & 0x1F
    rs1 = (word >> 15) & 0x1F
    rs2 = (word >> 20) & 0x1F
    funct3 = (word >> 12) & 0x7
    funct7 = word >> 25

    def label(target: int) -> str:
        name = symbolize(target) if symbolize is not None else None
        return f"0x{target:x}" + (f" <{name}>" if name else "")

    if opcode == 0x37:
        return "lui", f"{_reg(rd)}, 0x{word >> 12:x}", None
    if opcode == 0x17:
        return "auipc", f"{_reg(rd)}, 0x{word >> 12:x}", None
    if opcode == 0x6F:
        target = (address + _imm_j(word)) & 0xFFFF_FFFF
        if rd == 0:
            return "j", label(target), target
        if rd == 1:
            return "call", label(target), target
        return "jal", f"{_reg(rd)}, {label(target)}", target
    if opcode == 0x67 and funct3 == 0:
        imm = _imm_i(word)
        if rd == 0 and rs1 == 1 and imm == 0:
            return "ret", "", None
        if rd == 0 and imm == 0:
            return "jr", _reg(rs1), None
        if rd == 1 and imm == 0:
            return "jalr", _reg(rs1), None
        return "jalr", f"{_reg(rd)}, {imm}({_reg(rs1)})", None
    if opcode == 0x63:
        names = {0: "beq", 1: "bne", 4: "blt", 5: "bge", 6: "bltu", 7: "bgeu"}
        if funct3 not in names:
            return "?", f"0x{word:08x}", None
        target = (address + _imm_b(word)) & 0xFFFF_FFFF
        name = names[funct3]
        if rs2 == 0 and name in ("beq", "bne", "blt", "bge"):
            zero = {"beq": "beqz", "bne": "bnez", "blt": "bltz", "bge": "bgez"}[name]
            return zero, f"{_reg(rs1)}, {label(target)}", target
        return name, f"{_reg(rs1)}, {_reg(rs2)}, {label(target)}", target
    if opcode == 0x03:
        names = {0: "lb", 1: "lh", 2: "lw", 4: "lbu", 5: "lhu"}
        if funct3 not in names:
            return "?", f"0x{word:08x}", None
        return names[funct3], f"{_reg(rd)}, {_imm_i(word)}({_reg(rs1)})", None
    if opcode == 0x23:
        names = {0: "sb", 1: "sh", 2: "sw"}
        if funct3 not in names:
            return "?", f"0x{word:08x}", None
        return names[funct3], f"{_reg(rs2)}, {_imm_s(word)}({_reg(rs1)})", None
    if opcode == 0x13:
        imm = _imm_i(word)
        if funct3 == 0:
            if rd == 0 and rs1 == 0 and imm == 0:
                return "nop", "", None
            if rs1 == 0:
                return "li", f"{_reg(rd)}, {imm}", None
            if imm == 0:
                return "mv", f"{_reg(rd)}, {_reg(rs1)}", None
            return "addi", f"{_reg(rd)}, {_reg(rs1)}, {imm}", None
        if funct3 == 1:
            return "slli", f"{_reg(rd)}, {_reg(rs1)}, {rs2}", None
        if funct3 == 5:
            name = "srai" if funct7 & 0x20 else "srli"
            return name, f"{_reg(rd)}, {_reg(rs1)}, {rs2}", None
        if funct3 == 3 and imm == 1:
            return "seqz", f"{_reg(rd)}, {_reg(rs1)}", None
        if funct3 == 4 and imm == -1:
            return "not", f"{_reg(rd)}, {_reg(rs1)}", None
        names = {2: "slti", 3: "sltiu", 4: "xori", 6: "ori", 7: "andi"}
        return names[funct3], f"{_reg(rd)}, {_reg(rs1)}, {imm}", None
    if opcode == 0x33:
        if funct7 == 1:
            m_ops = ["mul", "mulh", "mulhsu", "mulhu", "div", "divu", "rem", "remu"]
            return m_ops[funct3], f"{_reg(rd)}, {_reg(rs1)}, {_reg(rs2)}", None
        base = {
            (0, 0): "add",
            (0x20, 0): "sub",
            (0, 1): "sll",
            (0, 2): "slt",
            (0, 3): "sltu",
            (0, 4): "xor",
            (0, 5): "srl",
            (0x20, 5): "sra",
            (0, 6): "or",
            (0, 7): "and",
        }
        op_name = base.get((funct7, funct3))
        if op_name is None:
            return "?", f"0x{word:08x}", None
        name = op_name
        if name == "add" and rs1 == 0:
            return "mv", f"{_reg(rd)}, {_reg(rs2)}", None
        if name == "sub" and rs1 == 0:
            return "neg", f"{_reg(rd)}, {_reg(rs2)}", None
        if name == "sltu" and rs1 == 0:
            return "snez", f"{_reg(rd)}, {_reg(rs2)}", None
        return name, f"{_reg(rd)}, {_reg(rs1)}, {_reg(rs2)}", None
    if opcode == 0x0F:
        return "fence", "", None
    if opcode == 0x73:
        specials = {
            0x00000073: "ecall",
            0x00100073: "ebreak",
            0x30200073: "mret",
            0x10500073: "wfi",
        }
        if word in specials:
            return specials[word], "", None
        csr = word >> 20
        csr_name = CSR_NAMES.get(csr, f"0x{csr:x}")
        names = {1: "csrrw", 2: "csrrs", 3: "csrrc", 5: "csrrwi", 6: "csrrsi", 7: "csrrci"}
        if funct3 in names:
            source = str(rs1) if funct3 >= 5 else _reg(rs1)
            return names[funct3], f"{_reg(rd)}, {csr_name}, {source}", None
    return "?", f"0x{word:08x}", None


def decode(address: int, data: bytes, symbolize: Symbolizer | None = None) -> Instruction | None:
    """Decodifica la instrucción que empieza en `data[0]` (necesita 2 o 4 bytes)."""
    if len(data) < 2:
        return None
    half = int.from_bytes(data[:2], "little")
    if half & 0x3 != 0x3:
        word = expand_compressed(half)
        if word is None:
            return Instruction(address, 2, half, 0, "?", f"0x{half:04x}")
        mnemonic, operands, target = _format(word, address, symbolize)
        return Instruction(address, 2, half, word, f"c.{mnemonic}", operands, target)
    if len(data) < 4:
        return None
    word = int.from_bytes(data[:4], "little")
    mnemonic, operands, target = _format(word, address, symbolize)
    return Instruction(address, 4, word, word, mnemonic, operands, target)


def disassemble(
    read: Callable[[int, int], bytes | None],
    start: int,
    end: int,
    symbolize: Symbolizer | None = None,
    limit: int = 4096,
) -> list[Instruction]:
    """Desensambla de `start` a `end` (secuencial: debe empezar en una instrucción)."""
    instructions: list[Instruction] = []
    address = start
    while address < end and len(instructions) < limit:
        data = read(address, 4) or read(address, 2)
        if data is None:
            break
        instruction = decode(address, data, symbolize)
        if instruction is None:
            break
        instructions.append(instruction)
        address += instruction.size
    return instructions
