"""Reconstrucción de la pila de llamadas (backtrace).

Estrategia, en orden:

1. **CFI** (`.debug_frame` o `.eh_frame`): para cada PC indica cómo calcular el
   CFA (el sp del llamador) y dónde quedaron guardados `ra` y los registros
   preservados. Funciona incluso en el prólogo y el epílogo.
2. **Frame pointer** si no hay CFI para ese PC: a `-O0`, gcc y clang dejan
   `s0` = CFA, con `ra` en `s0-4` y el `s0` anterior en `s0-8`.
3. **Interrupciones**: al llegar a la entrada de vector de crt0 (que no tiene
   CFI) se lee el marco que la CPU virtual guardó en la pila al atender la IRQ
   y se continúa desde el PC interrumpido.
"""

from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass, field
from pathlib import Path

from elftools.dwarf.callframe import FDE
from elftools.elf.elffile import ELFFile

from hardboiled.core.cpu import INSN_MRET, ISR_FRAME_SIZE, ISR_SAVED_REGS, Cpu
from hardboiled.core.dwarf import LineTable, SourceLocation
from hardboiled.core.elf import ElfImage

# 64 KB de SRAM con marcos de al menos 16 bytes: nunca puede haber más.
MAX_FRAMES = 4096
RA, SP, FP = 1, 2, 8


@dataclass(frozen=True)
class CfaRow:
    pc: int
    cfa_reg: int
    cfa_offset: int
    # registro -> offset respecto del CFA donde está guardado
    saved: dict[int, int]


class CallFrameTable:
    def __init__(self, fdes: list[tuple[int, int, list[CfaRow]]]) -> None:
        self._fdes = sorted(fdes, key=lambda fde: fde[0])
        self._starts = [start for start, _, _ in self._fdes]

    @classmethod
    def empty(cls) -> CallFrameTable:
        return cls([])

    @classmethod
    def from_elf(cls, path: str | Path) -> CallFrameTable:
        with Path(path).open("rb") as stream:
            elf = ELFFile(stream)
            if not elf.has_dwarf_info():
                return cls.empty()
            dwarf = elf.get_dwarf_info()
            if dwarf.has_CFI():
                entries = dwarf.CFI_entries()
            elif dwarf.has_EH_CFI():
                entries = dwarf.EH_CFI_entries()
            else:
                return cls.empty()
            fdes: list[tuple[int, int, list[CfaRow]]] = []
            for entry in entries:
                if not isinstance(entry, FDE):
                    continue
                start = entry.header["initial_location"]
                end = start + entry.header["address_range"]
                if start == 0:  # funciones descartadas por --gc-sections
                    continue
                rows = []
                for row in entry.get_decoded().table:
                    cfa = row["cfa"]
                    if cfa.expr is not None:
                        continue  # expresiones DWARF: no se generan a -O0
                    saved = {
                        reg: rule.arg
                        for reg, rule in row.items()
                        if isinstance(reg, int) and rule.type == "OFFSET"
                    }
                    rows.append(CfaRow(row["pc"], cfa.reg, cfa.offset, saved))
                if rows:
                    fdes.append((start, end, rows))
        return cls(fdes)

    def lookup(self, pc: int) -> CfaRow | None:
        idx = bisect.bisect_right(self._starts, pc) - 1
        if idx < 0:
            return None
        start, end, rows = self._fdes[idx]
        if not start <= pc < end:
            return None
        found = None
        for row in rows:
            if row.pc > pc:
                break
            found = row
        return found


@dataclass(frozen=True)
class Frame:
    index: int
    pc: int
    # Dirección que identifica el punto del código: el PC en curso, o la
    # instrucción de la llamada (dirección de retorno - 1) en los marcos llamadores.
    site: int
    function: str | None
    location: SourceLocation | None
    cfa: int | None
    # Registros conocidos en ese marco (siempre sp; s0 y otros si se pudieron recuperar).
    regs: dict[int, int] = field(default_factory=dict)
    # Entrada de interrupción: el marco siguiente es el código interrumpido.
    irq_line: int | None = None


class Unwinder:
    def __init__(self, image: ElfImage, lines: LineTable, cfi: CallFrameTable) -> None:
        self.image = image
        self.lines = lines
        self.cfi = cfi
        self._stub = self._irq_stub_range(image)

    @staticmethod
    def _irq_stub_range(image: ElfImage) -> tuple[int, int] | None:
        """Del __vector_table al mret del despachador de crt0."""
        start = image.symbol_address("__vector_table")
        dispatch = image.symbol_address("__irq_dispatch")
        if start is None or dispatch is None:
            return None
        for address, word in image.code_words():
            if address >= dispatch and word == INSN_MRET:
                return start, address + 4
        return None

    def _in_stub(self, pc: int) -> bool:
        return self._stub is not None and self._stub[0] <= pc < self._stub[1]

    def current_cfa(self, cpu: Cpu) -> int | None:
        """CFA del marco en curso sin recorrer toda la pila (barato para condiciones)."""
        pc = cpu.pc
        row = self.cfi.lookup(pc)
        if row is not None:
            return (cpu.read_register(row.cfa_reg) + row.cfa_offset) & 0xFFFF_FFFF
        return cpu.read_register(FP) if self.image.function_at(pc) is not None else None

    def unwind(self, cpu: Cpu) -> list[Frame]:
        regs = {index: cpu.read_register(index) for index in range(32)}
        pc = cpu.pc
        exact = True  # el PC es la instrucción en curso (no una dirección de retorno)
        isr_stack = list(cpu.isr_frames)
        frames: list[Frame] = []
        while len(frames) < MAX_FRAMES:
            lookup = pc if exact else pc - 1
            if self._in_stub(pc) and isr_stack:
                frame_addr, line = isr_stack.pop()
                frames.append(
                    Frame(len(frames), pc, pc, None, None, None, {SP: regs[SP]}, irq_line=line)
                )
                raw = cpu.read_memory(frame_addr, ISR_FRAME_SIZE)
                if raw is None:
                    break
                saved_pc, *values = struct.unpack(f"<{ISR_FRAME_SIZE // 4}I", raw)
                regs.update(zip(ISR_SAVED_REGS, values, strict=False))
                regs[SP] = frame_addr + ISR_FRAME_SIZE
                pc, exact = saved_pc, True
                continue

            row = self.cfi.lookup(lookup)
            function = self.image.function_at(lookup)
            cfa: int | None = None
            new_regs = dict(regs)
            if row is not None:
                cfa = (regs[row.cfa_reg] + row.cfa_offset) & 0xFFFF_FFFF
                for reg, offset in row.saved.items():
                    value = cpu.read_word(cfa + offset)
                    if value is None:
                        break
                    new_regs[reg] = value
            elif function is not None and cpu.read_word(regs[FP] - 4) is not None:
                cfa = regs[FP]
                new_regs[RA] = cpu.read_word(cfa - 4) or 0
                new_regs[FP] = cpu.read_word(cfa - 8) or 0

            frames.append(
                Frame(
                    len(frames),
                    pc,
                    lookup,
                    function,
                    self.lines.lookup(lookup),
                    cfa,
                    {SP: regs[SP], FP: regs[FP], **{r: regs[r] for r in range(18, 28)}},
                )
            )
            if cfa is None:
                break  # sin CFI ni frame pointer (p. ej. _start): fin de la cadena
            return_address = new_regs[RA]
            if return_address == 0 or (return_address == pc and cfa == regs[SP]):
                break  # fin de la cadena o sin progreso
            new_regs[SP] = cfa
            regs = new_regs
            pc, exact = return_address, False
            if cpu.read_memory(pc, 4) is None or pc < self.image.entry:
                break
        return frames
