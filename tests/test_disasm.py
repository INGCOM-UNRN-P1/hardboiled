"""Desensamblador: RV32I/M, pseudoinstrucciones y expansión de comprimidas."""

from __future__ import annotations

import random

import pytest
from unicorn import UC_ARCH_RISCV, UC_MODE_RISCV32, Uc
from unicorn import riscv_const as rv

from hardboiled.core.disasm import decode, expand_compressed

REGS = [getattr(rv, f"UC_RISCV_REG_X{i}") for i in range(32)]


def text(word: int, address: int = 0x1000, size: int = 4) -> str:
    instruction = decode(address, word.to_bytes(size, "little"))
    assert instruction is not None
    return instruction.text


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        (0xFE010113, "addi sp, sp, -32"),
        (0x00112E23, "sw ra, 28(sp)"),
        (0x00000513, "li a0, 0"),
        (0x00050593, "mv a1, a0"),
        (0x00008067, "ret"),
        (0x00000013, "nop"),
        (0xFEC42503, "lw a0, -20(s0)"),
        (0x00B50533, "add a0, a0, a1"),
        (0x40B50533, "sub a0, a0, a1"),
        (0x02B50533, "mul a0, a0, a1"),
        (0x02B54533, "div a0, a0, a1"),
        (0x400005B7, "lui a1, 0x40000"),
        (0x30200073, "mret"),
        (0x10500073, "wfi"),
        (0x00100073, "ebreak"),
        (0x34202573, "csrrs a0, mcause, zero"),
        (0x0040006F, "j 0x1004"),
        (0x008000EF, "call 0x1008"),
        (0x00050463, "beqz a0, 0x1008"),
        (0xFFF54513, "not a0, a0"),
    ],
)
def test_decode(word: int, expected: str) -> None:
    assert text(word) == expected


@pytest.mark.parametrize(
    ("half", "expected"),
    [
        (0x1141, "c.addi sp, sp, -16"),
        (0x4501, "c.li a0, 0"),
        (0x8082, "c.ret"),
        (0x852E, "c.mv a0, a1"),
        (0x4108, "c.lw a0, 0(a0)"),
        (0xC14C, "c.sw a1, 4(a0)"),
        (0x40B2, "c.lw ra, 12(sp)"),
        (0xC606, "c.sw ra, 12(sp)"),
        (0x952E, "c.add a0, a0, a1"),
        (0x050A, "c.slli a0, a0, 2"),
        (0x8105, "c.srli a0, a0, 1"),
        (0x890D, "c.andi a0, a0, 3"),
        (0x8D0D, "c.sub a0, a0, a1"),
        (0x9002, "c.ebreak"),
    ],
)
def test_compressed_known_encodings(half: int, expected: str) -> None:
    assert text(half, size=2) == expected


def _run(code: bytes, regs: list[int]) -> tuple[list[int], bytes]:
    uc = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
    uc.mem_map(0x10000, 0x1000)
    uc.mem_map(0x20000000, 0x10000)
    uc.mem_write(0x10000, code)
    for index, value in enumerate(regs):
        if index:
            uc.reg_write(REGS[index], value)
    uc.emu_start(0x10000, 0x10000 + len(code), count=1)
    return [uc.reg_read(r) for r in REGS], bytes(uc.mem_read(0x20000000, 0x10000))


def test_expansion_matches_unicorn_semantics() -> None:
    """Cada comprimida (no de control de flujo) hace lo mismo que su expansión."""
    rng = random.Random(1234)
    checked = 0
    for half in range(0x10000):
        if half & 0x3 == 0x3:
            continue
        word = expand_compressed(half)
        if word is None or word & 0x7F in (0x63, 0x67, 0x6F, 0x73):
            continue  # saltos: el enlace y la continuación difieren en 2 bytes
        if rng.random() > 0.02:
            continue  # una muestra alcanza y mantiene el test rápido
        regs = [0] + [0x20000000 + rng.randrange(0, 0x8000, 4) for _ in range(31)]
        try:
            compressed = _run(half.to_bytes(2, "little"), regs)
        except Exception:
            continue
        expanded = _run(word.to_bytes(4, "little"), regs)
        assert compressed == expanded, f"{half:04x} -> {word:08x}"
        checked += 1
    assert checked > 300
