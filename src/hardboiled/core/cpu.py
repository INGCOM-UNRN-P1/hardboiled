"""Wrapper de Unicorn para un RV32I bare-metal.

Toda la política de ejecución vive en el hook de ciclo (`UC_HOOK_CODE`), que
corre *antes* de cada instrucción. Cuando hay que intervenir (breakpoint,
`mret`, IRQ, `wfi`, fin de programa, cuota, stack overflow) el hook llama a
`emu_stop()`, lo que impide que la instrucción se ejecute, y `run()` resuelve
la situación desde fuera de Unicorn antes de reanudar.

Para que el hook sea barato, el código (que vive en Flash, de sólo lectura) se
escanea una única vez al cargar: se indexan las direcciones de `mret`, `wfi`,
`ebreak`/`ecall`, las llamadas (`jal`/`jalr` con rd = ra) y las instrucciones
que escriben `sp`.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from unicorn import (
    UC_ARCH_RISCV,
    UC_HOOK_CODE,
    UC_HOOK_MEM_INVALID,
    UC_HOOK_MEM_WRITE,
    UC_MEM_FETCH_PROT,
    UC_MEM_FETCH_UNMAPPED,
    UC_MEM_READ_PROT,
    UC_MEM_READ_UNMAPPED,
    UC_MEM_WRITE_PROT,
    UC_MEM_WRITE_UNMAPPED,
    UC_MODE_RISCV32,
    UC_PROT_EXEC,
    UC_PROT_NONE,
    UC_PROT_READ,
    UC_PROT_WRITE,
    Uc,
    UcError,
)
from unicorn import riscv_const as rv

from hardboiled.config import NULL_GUARD_END, MemoryConfig
from hardboiled.core.elf import ElfImage, ElfLoadError
from hardboiled.core.pic import InterruptController
from hardboiled.hardware.bus import MmioBus, MmioFault

ABI_NAMES = (
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)  # fmt: skip

_REG_IDS: tuple[int, ...] = tuple(getattr(rv, f"UC_RISCV_REG_X{i}") for i in range(32))
_PC = rv.UC_RISCV_REG_PC
_SP = rv.UC_RISCV_REG_X2
_A0 = rv.UC_RISCV_REG_X10

# Nunca se alcanza: los saltos RISC-V limpian el bit 0 del destino.
_UNTIL = 0xFFFF_FFFF
_NO_DEADLINE = 1 << 64

INSN_MRET = 0x3020_0073
INSN_WFI = 0x1050_0073
INSN_EBREAK = 0x0010_0073
INSN_ECALL = 0x0000_0073

# Opcodes RV32I con campo rd (LOAD, OP-IMM, AUIPC, OP, LUI, JALR, JAL).
_RD_OPCODES = frozenset({0x03, 0x13, 0x17, 0x33, 0x37, 0x67, 0x6F})
_CALL_OPCODES = frozenset({0x67, 0x6F})

# Contexto que la CPU virtual salva al entrar a una ISR: los registros que el
# ABI no obliga a preservar (ra, t0-t6, a0-a7). El marco es [pc, registros...,
# relleno] y se redondea a 16 bytes para respetar la alineación de pila del ABI.
ISR_SAVED_REGS = (1, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17, 28, 29, 30, 31)
ISR_FRAME_SIZE = (4 * (1 + len(ISR_SAVED_REGS)) + 15) & ~15

# Cada cuántas instrucciones se consulta `poll` (comandos en vivo de la UI).
POLL_INTERVAL_MASK = 0x3FF


class StopReason(Enum):
    BREAK = "break"  # condición del depurador: breakpoint o fin de un step
    PAUSED = "paused"
    TRAP = "trap"
    EXITED = "exited"


@dataclass(frozen=True)
class StopInfo:
    reason: StopReason
    pc: int
    message: str = ""
    fault_address: int | None = None
    exit_code: int | None = None
    watch: WatchHit | None = None


class _Halt(Enum):
    CHECK = auto()
    PAUSE = auto()
    IRQ = auto()
    MRET = auto()
    WFI = auto()
    EXIT = auto()
    QUOTA = auto()
    STACK = auto()
    FAULT = auto()
    WATCH = auto()


@dataclass(frozen=True)
class WatchHit:
    """Una escritura que cambió una región vigilada."""

    watch_id: int
    pc: int  # la instrucción que escribió
    old: bytes
    new: bytes


@dataclass(frozen=True)
class CpuSnapshot:
    context: Any  # UcContext: registros (incluido pc)
    sram: bytes
    instructions: int
    cycles: int
    halted: StopInfo | None
    isr_frame: int | None


@dataclass
class _Watch:
    watch_id: int
    address: int
    size: int
    handle: int | None = None


_ACCESS_KIND = {
    UC_MEM_READ_UNMAPPED: "lectura",
    UC_MEM_READ_PROT: "lectura",
    UC_MEM_WRITE_UNMAPPED: "escritura",
    UC_MEM_WRITE_PROT: "escritura",
    UC_MEM_FETCH_UNMAPPED: "ejecución",
    UC_MEM_FETCH_PROT: "ejecución",
}


def _signed32(value: int) -> int:
    return value - (1 << 32) if value & 0x8000_0000 else value


class Cpu:
    def __init__(
        self,
        memory: MemoryConfig,
        bus: MmioBus,
        pic: InterruptController,
        max_instructions: int = 1_000_000,
        clock_hz: int | None = None,
    ) -> None:
        self.memory = memory
        self.bus = bus
        self.pic = pic
        self.clock = bus.clock
        self.max_instructions = max_instructions
        self.clock_hz = clock_hz
        # Condición del depurador evaluada antes de cada instrucción.
        self.stop_check: Callable[[int], bool] | None = None
        # Consultado periódicamente durante la ejecución; True = pausar.
        self.poll: Callable[[], bool] | None = None
        self.call_sites: frozenset[int] = frozenset()
        self.halted: StopInfo | None = None
        self.instructions = 0
        self._image: ElfImage | None = None
        self._special: dict[int, _Halt] = {}
        self._sp_writers: frozenset[int] = frozenset()
        self._vector_table: int | None = None
        self._isr_frame: int | None = None
        self._watches: dict[int, _Watch] = {}
        self._next_watch = 0
        self._watch_hit: WatchHit | None = None
        self._uc = self._create_engine()
        self._reset_run_state()

    # ------------------------------------------------------------------ setup

    def _create_engine(self) -> Uc:
        mem = self.memory
        uc = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        uc.mem_map(0, NULL_GUARD_END, UC_PROT_NONE)
        uc.mem_map(mem.flash_base, mem.flash_size, UC_PROT_READ | UC_PROT_EXEC)
        uc.mem_map(mem.sram_base, mem.sram_size, UC_PROT_READ | UC_PROT_WRITE)
        uc.mmio_map(mem.mmio_base, mem.mmio_size, self._mmio_read, None, self._mmio_write, None)
        uc.hook_add(UC_HOOK_CODE, self._on_code)
        uc.hook_add(UC_HOOK_MEM_INVALID, self._on_invalid)
        for watch in getattr(self, "_watches", {}).values():  # tras un reset
            watch.handle = self._install_watch(uc, watch)
        return uc

    # ------------------------------------------------------------ watchpoints

    def add_watch(self, address: int, size: int) -> int:
        """Vigila escrituras que cambien [address, address + size). Devuelve un id."""
        if self._region_of(address, size) != "sram":
            raise ValueError("sólo se pueden vigilar variables en la SRAM")
        self._next_watch += 1
        watch = _Watch(self._next_watch, address, size)
        watch.handle = self._install_watch(self._uc, watch)
        self._watches[watch.watch_id] = watch
        return watch.watch_id

    def remove_watch(self, watch_id: int) -> None:
        watch = self._watches.pop(watch_id, None)
        if watch is not None and watch.handle is not None:
            self._uc.hook_del(watch.handle)

    def _install_watch(self, uc: Uc, watch: _Watch) -> int:
        # El rango del hook se compara con la dirección de inicio del acceso: se
        # extiende 3 bytes hacia abajo para ver también un `sw` que la pisa en parte.
        begin = max(watch.address - 3, 0)
        end = watch.address + watch.size - 1

        def on_write(uc: Uc, access: int, address: int, size: int, value: int, _data: Any) -> None:
            self._check_watch(uc, watch, address, size, value)

        handle: int = uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=begin, end=end)
        return handle

    def _check_watch(self, uc: Uc, watch: _Watch, address: int, size: int, value: int) -> None:
        start = max(address, watch.address)
        stop = min(address + size, watch.address + watch.size)
        if start >= stop or self._pending_halt is not None:
            return
        old = bytes(uc.mem_read(watch.address, watch.size))
        new = bytearray(old)
        incoming = (value & ((1 << (size * 8)) - 1)).to_bytes(size, "little")
        for offset in range(start, stop):
            new[offset - watch.address] = incoming[offset - address]
        if bytes(new) != old:
            self._watch_hit = WatchHit(watch.watch_id, self._current_pc, old, bytes(new))
            self._halt(uc, _Halt.WATCH)

    # ------------------------------------------------------------ instantáneas

    def snapshot(self) -> CpuSnapshot:
        """Registros, SRAM y contadores: lo necesario para volver a este instante."""
        mem = self.memory
        return CpuSnapshot(
            context=self._uc.context_save(),
            sram=bytes(self._uc.mem_read(mem.sram_base, mem.sram_size)),
            instructions=self.instructions,
            cycles=self.clock.cycles,
            halted=self.halted,
            isr_frame=self._isr_frame,
        )

    def restore(self, snap: CpuSnapshot) -> None:
        self._uc.context_restore(snap.context)
        self._uc.mem_write(self.memory.sram_base, snap.sram)
        self.instructions = snap.instructions
        self.clock.cycles = snap.cycles
        self.halted = snap.halted
        self._isr_frame = snap.isr_frame
        self._sp_dirty = False
        self._refresh_deadline()

    def _reset_run_state(self) -> None:
        self.halted = None
        self.instructions = 0
        self.clock.cycles = 0
        self._isr_frame = None
        self._sp_dirty = False
        self._current_pc = 0
        self._pending_halt: _Halt | None = None
        self._fault: StopInfo | None = None
        self._invalid_access: tuple[int, int] | None = None
        self._deadline = _NO_DEADLINE
        self._pace_origin = (time.monotonic(), 0)

    def load(self, image: ElfImage) -> None:
        """Mapea los segmentos PT_LOAD en su dirección física (LMA) e indexa el código."""
        for seg in image.segments:
            if not seg.data:
                continue
            region = self._region_of(seg.paddr, len(seg.data))
            if region not in ("flash", "sram"):
                raise ElfLoadError(
                    f"el segmento en 0x{seg.paddr:08x} ({len(seg.data)} bytes) no entra en "
                    "Flash ni en SRAM: ¿se enlazó con el hardboiled.ld del runtime?"
                )
            self._uc.mem_write(seg.paddr, seg.data)
        self._image = image
        self._index_code(image)
        self._vector_table = image.symbol_address("__vector_table")
        self._uc.reg_write(_PC, image.entry)

    def reset(self) -> None:
        """Placa recién encendida: memoria limpia, registros en cero, periféricos reseteados."""
        self._uc = self._create_engine()
        self._reset_run_state()
        self.bus.reset()
        if self._image is not None:
            self.load(self._image)

    def _index_code(self, image: ElfImage) -> None:
        special: dict[int, _Halt] = {}
        calls: set[int] = set()
        sp_writers: set[int] = set()
        for address, word in image.code_words():
            if word == INSN_MRET:
                special[address] = _Halt.MRET
            elif word == INSN_WFI:
                special[address] = _Halt.WFI
            elif word in (INSN_EBREAK, INSN_ECALL):
                special[address] = _Halt.EXIT
            opcode = word & 0x7F
            rd = (word >> 7) & 0x1F
            if opcode in _CALL_OPCODES and rd == 1:
                calls.add(address)
            if opcode in _RD_OPCODES and rd == 2:
                sp_writers.add(address)
        self._special = special
        self.call_sites = frozenset(calls)
        self._sp_writers = frozenset(sp_writers)

    def _region_of(self, address: int, size: int = 1) -> str | None:
        if address + size <= NULL_GUARD_END:
            return "null"
        for name, (base, length) in self.memory.regions().items():
            if base <= address and address + size <= base + length:
                return name
        return None

    # ------------------------------------------------------------- registros

    @property
    def pc(self) -> int:
        value: int = self._uc.reg_read(_PC)
        return value

    @property
    def current_pc(self) -> int:
        """PC de la instrucción que se está ejecutando (válido también dentro de hooks)."""
        return self._current_pc

    @property
    def sp(self) -> int:
        value: int = self._uc.reg_read(_SP)
        return value

    def read_register(self, index: int) -> int:
        value: int = self._uc.reg_read(_REG_IDS[index])
        return value

    def write_register(self, index: int, value: int) -> None:
        if index != 0:
            self._uc.reg_write(_REG_IDS[index], value & 0xFFFF_FFFF)

    def set_pc(self, value: int) -> None:
        self._uc.reg_write(_PC, value)

    def registers(self) -> dict[str, int]:
        regs = {f"x{i}": self.read_register(i) for i in range(32)}
        regs["pc"] = self.pc
        return regs

    @property
    def isr_frames(self) -> tuple[tuple[int, int], ...]:
        """Marcos de interrupción activos: (dirección del marco en la pila, línea de IRQ)."""
        line = self.pic.active_line
        if self._isr_frame is None or line is None:
            return ()
        return ((self._isr_frame, line),)

    def is_mmio(self, address: int) -> bool:
        base, size = self.memory.mmio_base, self.memory.mmio_size
        return base <= address < base + size

    def read_word(self, address: int) -> int | None:
        data = self.read_memory(address, 4)
        return int.from_bytes(data, "little") if data is not None else None

    def read_memory(self, address: int, size: int) -> bytes | None:
        """Lee Flash/SRAM sin efectos laterales (nunca toca el espacio MMIO)."""
        if self._region_of(address, size) not in ("flash", "sram"):
            return None
        return bytes(self._uc.mem_read(address, size))

    def stack_words(self, below: int = 4, above: int = 12) -> tuple[tuple[int, int], ...]:
        """Palabras alrededor de `sp`, recortadas a la SRAM."""
        sp = self.sp & ~3
        lo = max(sp - 4 * below, self.memory.sram_base)
        hi = min(sp + 4 * above, self.memory.sram_end)
        if lo >= hi:
            return ()
        data = self.read_memory(lo, hi - lo)
        if data is None:
            return ()
        return tuple(
            (lo + off, int.from_bytes(data[off : off + 4], "little"))
            for off in range(0, len(data), 4)
        )

    # -------------------------------------------------------------- ejecución

    def run(self) -> StopInfo:
        """Ejecuta hasta un alto del depurador, una pausa, una trampa o el fin del programa."""
        if self.halted is not None:
            return self.halted
        if self._image is None:
            raise RuntimeError("no hay ningún programa cargado")
        self._refresh_deadline()
        self._pace_origin = (time.monotonic(), self.clock.cycles)
        while True:
            self._pending_halt = None
            self._watch_hit = None
            self._fault = None
            self._invalid_access = None
            try:
                self._uc.emu_start(self.pc, _UNTIL)
            except UcError as exc:
                return self._terminate(self._trap_from_error(exc))
            halt = self._pending_halt
            pc = self.pc
            if halt is _Halt.CHECK:
                return StopInfo(StopReason.BREAK, pc)
            if halt is _Halt.WATCH and self._watch_hit is not None:
                return StopInfo(StopReason.BREAK, pc, "watchpoint", watch=self._watch_hit)
            if halt is _Halt.PAUSE:
                return StopInfo(StopReason.PAUSED, pc, "ejecución pausada")
            if halt is _Halt.EXIT:
                code = _signed32(self._uc.reg_read(_A0))
                return self._terminate(
                    StopInfo(StopReason.EXITED, pc, f"programa terminado ({code})", exit_code=code)
                )
            if halt is _Halt.FAULT and self._fault is not None:
                return self._terminate(self._fault)
            stop = self._resolve(halt, pc)
            if stop is not None:
                return self._terminate(stop) if stop.reason is StopReason.TRAP else stop

    def _resolve(self, halt: _Halt | None, pc: int) -> StopInfo | None:
        """Resuelve un alto transparente (IRQ, mret, wfi). Devuelve una trampa o una pausa."""
        if halt is _Halt.IRQ:
            return self._enter_isr(pc)
        if halt is _Halt.MRET:
            return self._return_from_isr(pc)
        if halt is _Halt.WFI:
            return self._wait_for_interrupt(pc)
        if halt is _Halt.QUOTA:
            return self._trap(
                pc,
                f"se alcanzó el límite de {self.max_instructions:,} instrucciones "
                "(¿un bucle infinito?)",
            )
        if halt is _Halt.STACK:
            return self._stack_overflow(pc)
        return self._trap(pc, f"la ejecución se detuvo en 0x{pc:08x} sin motivo conocido")

    def _terminate(self, info: StopInfo) -> StopInfo:
        self.halted = info
        return info

    def _trap(self, pc: int, message: str, address: int | None = None) -> StopInfo:
        return StopInfo(StopReason.TRAP, pc, message, address)

    def _stack_overflow(self, pc: int) -> StopInfo:
        sp = self.sp
        return self._trap(
            pc,
            f"stack overflow: sp = 0x{sp:08x} quedó por debajo del inicio de la SRAM "
            f"(0x{self.memory.sram_base:08x}). "
            "¿Recursión sin caso base o arreglos locales enormes?",
            sp,
        )

    def _pace_and_poll(self, max_sleep: float = 0.02) -> bool:
        """Acompasa al reloj real (si hay `clock_hz`) y consulta `poll`. True = pausar."""
        if self.clock_hz:
            origin_time, origin_cycles = self._pace_origin
            target = origin_time + (self.clock.cycles - origin_cycles) / self.clock_hz
            delay = target - time.monotonic()
            if delay > 0.001:
                time.sleep(min(delay, max_sleep))
        return self.poll is not None and self.poll()

    def _behind_schedule(self) -> bool:
        if not self.clock_hz:
            return False
        origin_time, origin_cycles = self._pace_origin
        return origin_time + (self.clock.cycles - origin_cycles) / self.clock_hz > time.monotonic()

    def _refresh_deadline(self) -> None:
        deadline = self.bus.next_deadline()
        self._deadline = _NO_DEADLINE if deadline is None else deadline

    # ------------------------------------------------------------------ hooks

    def _halt(self, uc: Uc, reason: _Halt) -> None:
        self._pending_halt = reason
        uc.emu_stop()

    def _on_code(self, uc: Uc, address: int, size: int, _data: Any) -> None:
        self._current_pc = address
        if self._pending_halt is not None:  # falla MMIO en la instrucción anterior
            uc.emu_stop()
            return
        check = self.stop_check
        if check is not None and check(address):
            self._halt(uc, _Halt.CHECK)
            return
        special = self._special.get(address)
        if special is not None:
            self._halt(uc, special)
            return
        if self.pic.ready:
            self._halt(uc, _Halt.IRQ)
            return
        if self.instructions >= self.max_instructions:
            self._halt(uc, _Halt.QUOTA)
            return
        if self._sp_dirty and uc.reg_read(_SP) < self.memory.sram_base:
            self._halt(uc, _Halt.STACK)
            return
        if not self.instructions & POLL_INTERVAL_MASK and self._pace_and_poll():
            self._halt(uc, _Halt.PAUSE)
            return
        self._sp_dirty = address in self._sp_writers
        self.instructions += 1
        clock = self.clock
        clock.cycles += 1
        if clock.cycles >= self._deadline:
            self.bus.service(clock.cycles)
            self._refresh_deadline()

    def _on_invalid(
        self, uc: Uc, access: int, address: int, size: int, value: int, _data: Any
    ) -> bool:
        self._invalid_access = (access, address)
        return False

    def _mmio_fault(self, uc: Uc, fault: MmioFault, offset: int) -> None:
        self._fault = self._trap(
            self._current_pc, f"acceso MMIO inválido: {fault}", self.memory.mmio_base + offset
        )
        self._halt(uc, _Halt.FAULT)

    def _mmio_read(self, uc: Uc, offset: int, size: int, _data: Any) -> int:
        try:
            return self.bus.read(offset, size)
        except MmioFault as fault:
            self._mmio_fault(uc, fault, offset)
            return 0

    def _mmio_write(self, uc: Uc, offset: int, size: int, value: int, _data: Any) -> None:
        try:
            self.bus.write(offset, size, value)
        except MmioFault as fault:
            self._mmio_fault(uc, fault, offset)
            return
        self._refresh_deadline()

    # -------------------------------------------------------- interrupciones

    def _enter_isr(self, pc: int) -> StopInfo | None:
        line = self.pic.next_irq()
        if line is None:
            return None
        if self._vector_table is None:
            return self._trap(pc, f"llegó la IRQ {line} pero el binario no define __vector_table")
        raw = self.read_memory(self._vector_table + 4 * line, 4)
        handler = int.from_bytes(raw, "little") if raw is not None else 0
        if self._region_of(handler, 4) != "flash":
            return self._trap(pc, f"IRQ {line}: el vector apunta a 0x{handler:08x}, fuera de Flash")
        frame = self.sp - ISR_FRAME_SIZE
        if frame < self.memory.sram_base:
            return self._stack_overflow(pc)
        words = [pc, *(self.read_register(r) for r in ISR_SAVED_REGS)]
        words += [0] * (ISR_FRAME_SIZE // 4 - len(words))
        self._uc.mem_write(frame, struct.pack(f"<{len(words)}I", *words))
        self.write_register(2, frame)
        self.set_pc(handler)
        self._isr_frame = frame
        self.pic.acknowledge(line)
        return None

    def _return_from_isr(self, pc: int) -> StopInfo | None:
        if not self.pic.in_isr or self._isr_frame is None:
            return self._trap(pc, "mret ejecutado fuera de una rutina de interrupción")
        frame = self.sp
        if frame != self._isr_frame:
            return self._trap(
                pc,
                f"la ISR dejó la pila desbalanceada: sp = 0x{frame:08x}, "
                f"se esperaba 0x{self._isr_frame:08x}",
            )
        raw = bytes(self._uc.mem_read(frame, ISR_FRAME_SIZE))
        saved_pc, *regs = struct.unpack(f"<{ISR_FRAME_SIZE // 4}I", raw)
        for index, value in zip(ISR_SAVED_REGS, regs, strict=False):
            self.write_register(index, value)
        self.write_register(2, frame + ISR_FRAME_SIZE)
        self.set_pc(saved_pc)
        self._isr_frame = None
        self.pic.complete()
        return None

    def _wait_for_interrupt(self, pc: int) -> StopInfo | None:
        """`wfi`: adelanta el reloj hasta que haya una IRQ habilitada pendiente."""
        for _ in range(1024):
            if self.pic.wake_pending():
                break
            deadline = self.bus.next_deadline()
            if deadline is None:
                break
            self.clock.cycles = max(self.clock.cycles, deadline)
            self.bus.service(self.clock.cycles)
        if not self.pic.wake_pending():
            return self._trap(
                pc,
                "wfi: la CPU se durmió sin ninguna interrupción habilitada que pueda "
                "despertarla (deadlock)",
            )
        self._refresh_deadline()
        self.instructions += 1
        self.set_pc(pc + 4)
        # Dormir de verdad el tiempo "salteado", atendiendo pausas mientras tanto.
        paused = self._pace_and_poll()
        while not paused and self._behind_schedule():
            paused = self._pace_and_poll()
        return StopInfo(StopReason.PAUSED, self.pc, "ejecución pausada") if paused else None

    # ----------------------------------------------------------------- trampas

    def _trap_from_error(self, exc: UcError) -> StopInfo:
        pc = self._current_pc
        if self._invalid_access is None:
            return self._trap(
                pc,
                f"excepción de la CPU en 0x{pc:08x}: {exc} "
                "(¿instrucción ilegal o acceso a memoria desalineado?)",
            )
        access, address = self._invalid_access
        kind = _ACCESS_KIND.get(access, "acceso")
        region = self._region_of(address)
        sram = self.memory.sram_base
        if region == "null":
            message = f"desreferencia de puntero nulo: {kind} en 0x{address:08x}"
        elif access in (UC_MEM_FETCH_PROT, UC_MEM_FETCH_UNMAPPED):
            where = "la SRAM (no es ejecutable)" if region == "sram" else "una zona sin código"
            message = f"salto a 0x{address:08x}, en {where}"
        elif access == UC_MEM_WRITE_PROT and region == "flash":
            message = f"escritura en Flash (memoria de sólo lectura) en 0x{address:08x}"
        elif sram - 0x1_0000 <= address < sram and self.sp < sram:
            return self._stack_overflow(pc)
        else:
            message = f"{kind} en memoria no mapeada: 0x{address:08x}"
        return self._trap(pc, message, address)
