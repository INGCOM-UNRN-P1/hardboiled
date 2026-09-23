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

Modo rápido: un hook por instrucción cuesta una llamada a Python cada vez. Si
el depurador no necesita evaluar una condición en cada instrucción (Continue,
Run to, Step Out; ver `stop_addresses`), el hook global se reemplaza por uno de
bloque, que cuenta instrucciones y atiende IRQ, cuota, pausas y vencimientos
una vez por bloque básico, y por hooks puntuales sólo en las direcciones que
importan: breakpoints, `mret`/`wfi`/`ebreak`, divisiones, la instrucción
siguiente a cada escritura de `sp` y los accesos a memoria que podrían estar
desalineados. Las IRQ se toman entonces al comienzo de un bloque.
"""

from __future__ import annotations

import ctypes
import struct
import time
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Protocol

from unicorn import (
    UC_ARCH_RISCV,
    UC_HOOK_BLOCK,
    UC_HOOK_CODE,
    UC_HOOK_MEM_INVALID,
    UC_HOOK_MEM_READ,
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
from hardboiled.i18n import N_, _

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
_JUMP_OPCODES = frozenset({0x67, 0x6F})
# Registros base que el ABI mantiene alineados: sp, gp (y s0 donde es frame pointer).
_ALIGNED_BASES = frozenset({2, 3})

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
    LIMIT = "limit"  # cuota de instrucciones agotada: se puede seguir (otra cuota más)


@dataclass(frozen=True)
class StopInfo:
    reason: StopReason
    pc: int
    message: str = ""
    fault_address: int | None = None
    exit_code: int | None = None
    watch: WatchHit | None = None
    kind: str | None = None  # tipo de trampa ("null-pointer", "stack-overflow"…)


class Tracer(Protocol):
    """Recibe cada instrucción justo antes de ejecutarse (ver core.trace)."""

    def step(self, pc: int) -> None: ...
    def event(self, text: str) -> None: ...


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
    DIAGNOSTIC = auto()  # un aviso configurado para detener ("break")


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
    isr_frames: tuple[int, ...]
    shadow: bytes | None = None
    last_sp: int = 0


@dataclass(frozen=True)
class Diagnostic:
    """Un aviso (no una trampa): algo sospechoso que el programa hizo y siguió."""

    kind: str  # "div0", "uninit"
    pc: int  # dónde ocurrió (para una rutina de biblioteca, la llamada)
    message: str


# Rutinas de división por software de libgcc/compiler-rt: (divisor en a1, operación).
DIVISION = N_("división")
REMAINDER = N_("resto (%)")
SOFTWARE_DIVISION = {
    "__divsi3": DIVISION,
    "__udivsi3": DIVISION,
    "__modsi3": REMAINDER,
    "__umodsi3": REMAINDER,
}


@dataclass
class _Watch:
    watch_id: int
    address: int
    size: int
    handle: int | None = None


_ACCESS_KIND = {
    UC_MEM_READ_UNMAPPED: N_("lectura"),
    UC_MEM_READ_PROT: N_("lectura"),
    UC_MEM_WRITE_UNMAPPED: N_("escritura"),
    UC_MEM_WRITE_PROT: N_("escritura"),
    UC_MEM_FETCH_UNMAPPED: N_("ejecución"),
    UC_MEM_FETCH_PROT: N_("ejecución"),
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
        stack_guard: str = "globals",
        misaligned: str = "trap",
        div_by_zero: str = "warn",
        uninitialized: str = "warn",
        isa: str = "rv32i",
    ) -> None:
        self.memory = memory
        self.isa = isa
        self.uninitialized = uninitialized
        # Memoria "sombra": 1 = byte de la SRAM ya escrito. None si la verificación está apagada.
        self._shadow: bytearray | None = (
            bytearray(memory.sram_size) if uninitialized != "off" else None
        )
        self._last_sp = memory.sram_end
        # Nombra una dirección (p. ej. la variable local que vive ahí); lo provee el depurador.
        self.name_address: Callable[[int], str | None] | None = None
        self.misaligned = misaligned
        self.div_by_zero = div_by_zero
        self.bus = bus
        self.pic = pic
        self.clock = bus.clock
        self.max_instructions = max_instructions
        self.quota_step = max_instructions
        self.clock_hz = clock_hz
        self.stack_guard = stack_guard
        self.stack_floor = memory.sram_base
        # Con interfaz, `wfi` puede esperar estímulos del usuario (UART, botones).
        self.interactive = False
        # Condición del depurador evaluada antes de cada instrucción.
        self.stop_check: Callable[[int], bool] | None = None
        # Consultado periódicamente durante la ejecución; True = pausar.
        self.poll: Callable[[], bool] | None = None
        # Si no es None, `stop_check` sólo puede cumplirse en estas direcciones: la
        # ejecución usa el modo rápido (hooks por bloque en vez de por instrucción).
        self.stop_addresses: frozenset[int] | None = None
        # Traza de ejecución: obliga a correr instrucción por instrucción.
        self.tracer: Tracer | None = None
        self._gpr_view: tuple[Any, int] | bool | None = False  # False = sin calibrar
        # dirección de cada llamada (jal/jalr a ra, también comprimidas) -> su tamaño
        self.call_sites: dict[int, int] = {}
        self.halted: StopInfo | None = None
        self.instructions = 0
        self._image: ElfImage | None = None
        self._special: dict[int, _Halt] = {}
        self._sp_writers: frozenset[int] = frozenset()
        self._memory_ops: dict[int, tuple[int, int, int, bool]] = {}
        # dirección -> (registro divisor, operación, es llamada a biblioteca)
        self._divisions: dict[int, tuple[int, str, bool]] = {}
        self.diagnostics: list[Diagnostic] = []
        self._warned: set[tuple[str, int]] = set()
        self._vector_table: int | None = None
        self._isr_frames: list[int] = []  # marcos guardados, el último es el más interno
        self._watches: dict[int, _Watch] = {}
        self._next_watch = 0
        self._watch_hit: WatchHit | None = None
        # Modo rápido: direcciones con hook puntual (sin contar breakpoints) y conteo
        # de instrucciones por bloque (con la extensión C no alcanza con bytes / 4).
        self._fast_points: frozenset[int] = frozenset()
        self._sp_checks: frozenset[int] = frozenset()
        self._insn_addresses: list[int] | None = None
        self._block_counts: dict[tuple[int, int], int] = {}
        self._hooks: list[int] = []
        self._hook_key: tuple[object, ...] | None = None
        self._stepping = True
        # Estado de encendido (registros y SRAM tras cargar el programa) para Reset.
        self._power_on: tuple[Any, bytes] | None = None
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
        # Los hooks de ejecución (por instrucción o por bloque) se instalan en run().
        self._hooks = []
        self._hook_key = None
        uc.hook_add(UC_HOOK_MEM_INVALID, self._on_invalid)
        if getattr(self, "uninitialized", "off") != "off":
            end = mem.sram_base + mem.sram_size - 1
            uc.hook_add(UC_HOOK_MEM_WRITE, self._on_sram_write, begin=mem.sram_base, end=end)
            uc.hook_add(UC_HOOK_MEM_READ, self._on_sram_read, begin=mem.sram_base, end=end)
        return uc

    # ------------------------------------------------------------ watchpoints

    def add_watch(self, address: int, size: int) -> int:
        """Vigila escrituras que cambien [address, address + size). Devuelve un id."""
        if self._region_of(address, size) != "sram":
            raise ValueError(_("sólo se pueden vigilar variables en la SRAM"))
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
            self._watch_hit = WatchHit(watch.watch_id, self._insn_pc(uc), old, bytes(new))
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
            isr_frames=tuple(self._isr_frames),
            shadow=bytes(self._shadow) if self._shadow is not None else None,
            last_sp=self._last_sp,
        )

    def restore(self, snap: CpuSnapshot) -> None:
        self._uc.context_restore(snap.context)
        self._uc.mem_write(self.memory.sram_base, snap.sram)
        self.instructions = snap.instructions
        self.clock.cycles = snap.cycles
        self.halted = snap.halted
        self._isr_frames = list(snap.isr_frames)
        if snap.shadow is not None and self._shadow is not None:
            self._shadow[:] = snap.shadow
            self._last_sp = snap.last_sp
        self._sp_dirty = False
        self._refresh_deadline()

    def _reset_run_state(self) -> None:
        if getattr(self, "_shadow", None) is not None:
            self._shadow = bytearray(self.memory.sram_size)
        self._last_sp = self.memory.sram_end
        self.diagnostics = []
        self._warned = set()
        self.halted = None
        self.instructions = 0
        self.max_instructions = getattr(self, "quota_step", self.max_instructions)
        self.clock.cycles = 0
        self._isr_frames = []
        self._sp_dirty = False
        self._current_pc = 0
        self._pending_halt: _Halt | None = None
        self._fault: StopInfo | None = None
        self._invalid_access: tuple[int, int] | None = None
        self._deadline = _NO_DEADLINE
        self._pace_origin = (time.monotonic(), 0)
        self._next_poll = 0
        # Perfil: ejecuciones por PC (paso a paso) y por bloque (modo rápido), menos
        # los tramos de bloques que no llegaron a ejecutarse enteros.
        self._pc_hits: dict[int, int] = {}
        self._block_hits: dict[tuple[int, int], int] = {}
        self._unexecuted: dict[tuple[int, int], int] = {}
        self._block_pc = 0
        self._block_base = 0
        self._block_cycles = 0
        self._block_size = 0
        self._cycles_ahead = 0
        self._counted = False

    def check_isa(self, image: ElfImage) -> None:
        """Rechaza programas que usan extensiones que la CPU de la placa no tiene."""
        supported = set(self.isa.removeprefix("rv32i"))
        missing = sorted(image.extensions - supported)
        if not missing:
            return
        names = {
            "m": N_("M (multiplicación/división)"),
            "c": N_("C (comprimidas)"),
            "a": N_("A (atómicas)"),
            "f": N_("F (punto flotante)"),
            "d": N_("D (doble precisión)"),
        }
        listed = ", ".join(_(names[ext]) if ext in names else ext.upper() for ext in missing)
        arch = f" ({image.arch})" if image.arch else ""
        raise ElfLoadError(
            _(
                "{program} usa la extensión {extensions}{arch}, pero la placa es {isa}: "
                "compilá con --march {isa} o declará isa en [board] de board.toml",
                program=image.path.name,
                extensions=listed,
                arch=arch,
                isa=self.isa,
            )
        )

    def load(self, image: ElfImage) -> None:
        """Mapea los segmentos PT_LOAD en su dirección física (LMA) e indexa el código."""
        self.check_isa(image)
        for seg in image.segments:
            if not seg.data:
                continue
            region = self._region_of(seg.paddr, len(seg.data))
            if region not in ("flash", "sram"):
                raise ElfLoadError(
                    _(
                        "el segmento en {address} ({size} bytes) no entra en Flash ni en "
                        "SRAM: ¿se enlazó con el hardboiled.ld del runtime?",
                        address=f"0x{seg.paddr:08x}",
                        size=len(seg.data),
                    )
                )
            self._uc.mem_write(seg.paddr, seg.data)
        self._image = image
        self._index_code(image)
        self.stack_floor = self._compute_stack_floor(image)
        self._vector_table = image.symbol_address("__vector_table")
        self._uc.reg_write(_PC, image.entry)
        mem = self.memory
        self._power_on = (
            self._uc.context_save(),
            bytes(self._uc.mem_read(mem.sram_base, mem.sram_size)),
        )

    def _compute_stack_floor(self, image: ElfImage) -> int:
        """Hasta dónde puede bajar sp: el fin de .bss (o __stack_limit), o la SRAM.

        Con stack_guard = "sram" sólo se detecta al salir de la SRAM (más tarde:
        para entonces la pila ya pisó las globales).
        """
        base, end = self.memory.sram_base, self.memory.sram_end
        if self.stack_guard == "sram":
            return base
        for symbol in ("__stack_limit", "_end", "__bss_end"):
            address = image.symbol_address(symbol)
            if address is not None and base <= address < end:
                return (address + 3) & ~3
        return base

    def reset(self) -> None:
        """Placa recién encendida: memoria limpia, registros en cero, periféricos reseteados.

        No se recrea el motor ni se vuelve a indexar el código: la Flash es de
        sólo lectura, así que alcanza con restaurar registros y SRAM al estado
        guardado al cargar. Los hooks (watchpoints incluidos) siguen instalados.
        """
        self._reset_run_state()
        self.bus.reset()
        if self._power_on is not None:
            context, sram = self._power_on
            self._uc.context_restore(context)
            self._uc.mem_write(self.memory.sram_base, sram)

    def _index_code(self, image: ElfImage) -> None:
        special: dict[int, _Halt] = {}
        calls: dict[int, int] = {}
        sp_writers: set[int] = set()
        # dirección -> (registro base, offset, tamaño, es escritura) de lh/lhu/lw/sh/sw
        memory_ops: dict[int, tuple[int, int, int, bool]] = {}
        divisions: dict[int, tuple[int, str, bool]] = {}
        sp_checks: set[int] = set()
        frame_functions: set[int] = set()  # funciones que arman s0 = sp + n (frame pointer)
        addresses: list[int] = []
        functions = sorted(
            (s.address, s.address + s.size)
            for s in image.symbols.values()
            if s.kind == "func" and s.size
        )
        starts = [start for start, _ in functions]

        def function_of(address: int) -> int | None:
            index = bisect_left(starts, address + 1) - 1
            if index >= 0 and address < functions[index][1]:
                return starts[index]
            return None

        for address, size, word in image.instructions():
            addresses.append(address)
            if word == INSN_MRET:
                special[address] = _Halt.MRET
            elif word == INSN_WFI:
                special[address] = _Halt.WFI
            elif word in (INSN_EBREAK, INSN_ECALL):
                special[address] = _Halt.EXIT
            opcode = word & 0x7F
            rd = (word >> 7) & 0x1F
            funct3 = (word >> 12) & 0x7
            rs1 = (word >> 15) & 0x1F
            if opcode == 0x33 and word >> 25 == 1 and funct3 >= 4:  # div, divu, rem, remu
                operation = DIVISION if funct3 < 6 else REMAINDER
                divisions[address] = ((word >> 20) & 0x1F, operation, False)
            if opcode == 0x03 and funct3 in (1, 2, 5):  # lh, lw, lhu
                offset = word >> 20
                offset -= (offset & 0x800) << 1
                memory_ops[address] = (rs1, offset, 4 if funct3 == 2 else 2, False)
            elif opcode == 0x23 and funct3 in (1, 2):  # sh, sw
                offset = ((word >> 25) << 5) | ((word >> 7) & 0x1F)
                offset -= (offset & 0x800) << 1
                memory_ops[address] = (rs1, offset, 4 if funct3 == 2 else 2, True)
            if opcode in _CALL_OPCODES and rd == 1:
                calls[address] = size
            if opcode in _RD_OPCODES and rd == 2:
                sp_writers.add(address)
                if opcode not in _JUMP_OPCODES:
                    sp_checks.add(address + size)  # se verifica antes de la siguiente
            if opcode == 0x13 and funct3 == 0 and rd == 8 and rs1 == 2:  # addi s0, sp, n
                function = function_of(address)
                if function is not None:
                    frame_functions.add(function)
        self._special = special
        self._memory_ops = memory_ops if self.misaligned == "trap" else {}
        # En modo rápido no se vigilan los accesos relativos a registros que el ABI
        # mantiene alineados (sp, gp, y s0 en funciones con frame pointer).
        risky = {
            address
            for address, (base, offset, size, _) in self._memory_ops.items()
            if offset % size
            or not (
                base in _ALIGNED_BASES or (base == 8 and function_of(address) in frame_functions)
            )
        }
        self._sp_checks = frozenset(sp_checks)
        self._insn_addresses = addresses if "c" in image.extensions else None
        self._block_counts = {}
        if self.div_by_zero != "off":
            for name, operation in SOFTWARE_DIVISION.items():
                entry = image.symbol_address(name)
                if entry is not None:
                    divisions[entry] = (11, operation, True)  # divisor en a1
            self._divisions = divisions
        else:
            self._divisions = {}
        self.call_sites = calls
        self._sp_writers = frozenset(sp_writers)
        self._fast_points = (
            frozenset(special) | risky | frozenset(self._divisions) | self._sp_checks
        )
        self._hook_key = None

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

    def register_values(self) -> tuple[int, ...]:
        """x0..x31 de una vez (para la traza, que los lee en cada instrucción).

        Leer el contexto de Unicorn y tomar los registros de su buffer es ~15 veces
        más rápido que `reg_read_batch`. El offset se calibra una vez escribiendo
        valores conocidos; si no se encuentran, se usa la lectura normal.
        """
        if self._gpr_view is False:
            self._gpr_view = self._calibrate_gpr_view()
        view = self._gpr_view
        if isinstance(view, tuple):
            context, offset = view
            self._uc.context_update(context)
            raw = ctypes.string_at(context._context.value + offset, 128)
            return struct.unpack("<32I", raw)
        return tuple(self.read_register(index) for index in range(32))

    def _calibrate_gpr_view(self) -> tuple[Any, int] | None:
        uc = self._uc
        saved = uc.context_save()
        try:
            probe = [0x5EED_0000 + index for index in range(1, 32)]
            for index, value in enumerate(probe, start=1):
                uc.reg_write(_REG_IDS[index], value)
            context = uc.context_save()
            raw = ctypes.string_at(context._context.value, context.size)
            found = raw.find(struct.pack("<31I", *probe))
            return (context, found - 4) if found >= 4 else None
        except (AttributeError, TypeError, ValueError):
            return None
        finally:
            uc.context_restore(saved)

    def registers(self) -> dict[str, int]:
        regs = {f"x{i}": self.read_register(i) for i in range(32)}
        regs["pc"] = self.pc
        return regs

    @property
    def isr_frames(self) -> tuple[tuple[int, int], ...]:
        """Marcos de interrupción activos: (dirección del marco en la pila, línea de IRQ)."""
        return tuple(zip(self._isr_frames, self.pic.active, strict=False))

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
        if self.instructions >= self.max_instructions:
            # Seguir después de agotar la cuota habilita otra cuota igual.
            self.max_instructions += self.quota_step
        self._refresh_deadline()
        self._pace_origin = (time.monotonic(), self.clock.cycles)
        self._install_hooks()
        while True:
            self._pending_halt = None
            self._watch_hit = None
            self._fault = None
            self._invalid_access = None
            self._counted = False
            try:
                self._uc.emu_start(self.pc, _UNTIL)
            except UcError as exc:
                if (
                    not self._stepping
                    and self._invalid_access is not None
                    and (self._invalid_access[0] in (UC_MEM_FETCH_PROT, UC_MEM_FETCH_UNMAPPED))
                ):
                    # Tras un salto a una dirección inválida el PC no es preciso: el
                    # culpable es el salto, la última instrucción del bloque.
                    self._current_pc = self._last_in_block()
                else:
                    self._sync_count()
                return self._terminate(self._trap_from_error(exc))
            self._sync_count()
            halt = self._pending_halt
            pc = self.pc
            if halt is _Halt.CHECK:
                return StopInfo(StopReason.BREAK, pc)
            if halt is _Halt.DIAGNOSTIC and self.diagnostics:
                return StopInfo(StopReason.BREAK, pc, self.diagnostics[-1].message)
            if halt is _Halt.WATCH and self._watch_hit is not None:
                return StopInfo(StopReason.BREAK, pc, "watchpoint", watch=self._watch_hit)
            if halt is _Halt.PAUSE:
                return StopInfo(StopReason.PAUSED, pc, _("ejecución pausada"))
            if halt is _Halt.EXIT:
                if self.tracer is not None:
                    self.tracer.step(pc)
                code = _signed32(self._uc.reg_read(_A0))
                return self._terminate(
                    StopInfo(
                        StopReason.EXITED,
                        pc,
                        _("programa terminado ({code})", code=code),
                        exit_code=code,
                    )
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
            return StopInfo(
                StopReason.LIMIT,
                pc,
                _(
                    "se alcanzó el límite de {count} instrucciones (¿un bucle infinito?)",
                    count=f"{self.max_instructions:,}",
                ),
            )
        if halt is _Halt.STACK:
            return self._stack_overflow(pc)
        return self._trap(
            pc,
            _("la ejecución se detuvo en {pc} sin motivo conocido", pc=f"0x{pc:08x}"),
            kind="exception",
        )

    def _terminate(self, info: StopInfo) -> StopInfo:
        self.halted = info
        return info

    def _trap(self, pc: int, message: str, address: int | None = None, *, kind: str) -> StopInfo:
        return StopInfo(StopReason.TRAP, pc, message, address, kind=kind)

    def _stack_overflow(self, pc: int) -> StopInfo:
        sp = self.sp
        if self.stack_floor > self.memory.sram_base:
            victim = self._image.object_at(sp) if self._image is not None else None
            target = _(": pisaría la variable `{name}`", name=victim) if victim else ""
            if sp < self.memory.sram_base:
                target = _(" y quedó fuera de la SRAM")
            where = _(
                "invadió las variables globales (el fin de .bss es {end}){target}",
                end=f"0x{self.stack_floor:08x}",
                target=target,
            )
        else:
            where = _(
                "quedó por debajo del inicio de la SRAM ({base})",
                base=f"0x{self.memory.sram_base:08x}",
            )
        return self._trap(
            pc,
            _(
                "stack overflow: sp = {sp} {where}. "
                "¿Recursión sin caso base o arreglos locales enormes?",
                sp=f"0x{sp:08x}",
                where=where,
            ),
            sp,
            kind="stack-overflow",
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

    def set_clock(self, hz: int | None) -> None:
        """Cambia la frecuencia nominal; el acompasado arranca de cero desde ahora."""
        self.clock_hz = hz
        self._pace_origin = (time.monotonic(), self.clock.cycles)

    def refresh_deadline(self) -> None:
        """Recalcula el próximo evento temporal (tras un estímulo externo)."""
        self._refresh_deadline()

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
        access = self._memory_ops.get(address)
        if access is not None and self._misaligned_access(uc, access):
            self._halt(uc, _Halt.FAULT)
            return
        division = self._divisions.get(address)
        if division is not None and self._division_by_zero(uc, address, division):
            self._halt(uc, _Halt.DIAGNOSTIC)
            return
        if self.pic.ready:
            self._halt(uc, _Halt.IRQ)
            return
        if self.instructions >= self.max_instructions:
            self._halt(uc, _Halt.QUOTA)
            return
        if self._sp_dirty:
            sp = uc.reg_read(_SP)
            if sp < self.stack_floor:
                self._halt(uc, _Halt.STACK)
                return
            if self._shadow is not None:
                self._track_stack(sp)
        if not self.instructions & POLL_INTERVAL_MASK and self._pace_and_poll():
            self._halt(uc, _Halt.PAUSE)
            return
        if self.tracer is not None:
            self.tracer.step(address)
        hits = self._pc_hits
        hits[address] = hits.get(address, 0) + 1
        self._sp_dirty = address in self._sp_writers
        self.instructions += 1
        clock = self.clock
        clock.cycles += 1
        if clock.cycles >= self._deadline:
            self.bus.service(clock.cycles)
            self._refresh_deadline()

    # ------------------------------------------------------------ modo rápido

    def _install_hooks(self) -> None:
        """Instala el hook por instrucción o, si alcanza, los del modo rápido."""
        stops = self.stop_addresses
        stepping = (self.stop_check is not None and stops is None) or self.tracer is not None
        key: tuple[object, ...] = ("step",) if stepping else ("fast", stops or frozenset())
        if key == self._hook_key:
            return
        uc = self._uc
        for handle in self._hooks:
            uc.hook_del(handle)
        if stepping:
            self._hooks = [uc.hook_add(UC_HOOK_CODE, self._on_code)]
        else:
            mmio_end = self.memory.mmio_base + self.memory.mmio_size - 1
            self._hooks = [
                uc.hook_add(UC_HOOK_BLOCK, self._on_block),
                uc.hook_add(
                    UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE,
                    self._on_mmio_access,
                    begin=self.memory.mmio_base,
                    end=mmio_end,
                ),
            ]
            for address in sorted(self._fast_points | (stops or frozenset())):
                handle = uc.hook_add(UC_HOOK_CODE, self._on_point, begin=address, end=address)
                self._hooks.append(handle)
        self._stepping = stepping
        self._hook_key = key

    def _count(self, address: int, length: int) -> int:
        """Instrucciones en [address, address + length)."""
        addresses = self._insn_addresses
        if addresses is None:
            return length >> 2
        return bisect_left(addresses, address + length) - bisect_left(addresses, address)

    def _last_in_block(self) -> int:
        end = self._block_pc + self._block_size
        addresses = self._insn_addresses
        if addresses is None:
            return end - 4
        return addresses[max(bisect_left(addresses, end) - 1, 0)]

    def _on_mmio_access(
        self, uc: Uc, access: int, address: int, size: int, value: int, _data: Any
    ) -> None:
        """Antes de un acceso MMIO: el reloj pasa al ciclo exacto de la instrucción
        (el bloque lo había adelantado entero) para que el periférico lo vea bien."""
        pc: int = uc.reg_read(_PC)
        self._current_pc = pc
        precise = self._block_cycles + self._count(self._block_pc, pc - self._block_pc) + 1
        self._cycles_ahead = self.clock.cycles - precise
        self.clock.cycles = precise

    def _catch_up(self) -> None:
        if self._cycles_ahead:
            self.clock.cycles += self._cycles_ahead
            self._cycles_ahead = 0

    def _halt_counted(self, uc: Uc, reason: _Halt) -> None:
        self._counted = True
        self._halt(uc, reason)

    def _sync_count(self) -> None:
        """Tras detenerse fuera de los hooks de bloque/punto (memoria, MMIO, falla),
        ajusta los contadores a las instrucciones del bloque que llegaron a ejecutarse."""
        if self._stepping or self._counted:
            return
        pc = self.pc
        if not 0 <= pc - self._block_pc < 0x1_0000:
            return
        done = self._block_base + self._count(self._block_pc, pc - self._block_pc)
        self.clock.cycles -= self.instructions - done
        self.instructions = done
        self._current_pc = pc
        self._not_executed(pc)

    def _not_executed(self, pc: int) -> None:
        """El bloque en curso se cortó en `pc`: desde ahí no se ejecutó (para el perfil)."""
        end = self._block_pc + self._block_size
        if self._block_pc <= pc < end:
            key = (pc, end)
            self._unexecuted[key] = self._unexecuted.get(key, 0) + 1

    def _addresses_in(self, start: int, end: int) -> range | list[int]:
        addresses = self._insn_addresses
        if addresses is None:
            return range(start, end, 4)
        return addresses[bisect_left(addresses, start) : bisect_left(addresses, end)]

    def execution_counts(self) -> dict[int, int]:
        """Cuántas veces se ejecutó cada instrucción desde el último Reset."""
        counts = dict(self._pc_hits)
        for (start, size), times in self._block_hits.items():
            for address in self._addresses_in(start, start + size):
                counts[address] = counts.get(address, 0) + times
        for (start, end), times in self._unexecuted.items():
            for address in self._addresses_in(start, end):
                left = counts.get(address, 0) - times
                if left > 0:
                    counts[address] = left
                else:
                    counts.pop(address, None)
        return counts

    def _on_block(self, uc: Uc, address: int, size: int, _data: Any) -> None:
        if self._pending_halt is not None:
            uc.emu_stop()
            return
        self._block_pc = address
        self._block_base = self.instructions
        self._current_pc = address
        if self.pic.ready:
            self._halt_counted(uc, _Halt.IRQ)
            return
        if self.instructions >= self.max_instructions:
            self._halt_counted(uc, _Halt.QUOTA)
            return
        if self.instructions >= self._next_poll:
            self._next_poll = (self.instructions | POLL_INTERVAL_MASK) + 1
            if self._pace_and_poll():
                self._halt_counted(uc, _Halt.PAUSE)
                return
        key = (address, size)
        count = self._block_counts.get(key)
        if count is None:
            count = self._block_counts[key] = self._count(address, size)
        blocks = self._block_hits
        blocks[key] = blocks.get(key, 0) + 1
        self.instructions += count
        clock = self.clock
        self._block_cycles = clock.cycles
        self._block_size = size
        clock.cycles += count
        if clock.cycles >= self._deadline:
            self.bus.service(clock.cycles)
            self._refresh_deadline()

    def _on_point(self, uc: Uc, address: int, size: int, _data: Any) -> None:
        """Hook puntual del modo rápido: las verificaciones de `_on_code` que aplican acá."""
        if self._pending_halt is not None:
            uc.emu_stop()
            return
        self._current_pc = address
        full = self.instructions
        before = self._count(self._block_pc, address - self._block_pc)
        self.instructions = self._block_base + before  # las anteriores a ésta en el bloque
        halt = self._point_halt(uc, address)
        if halt is None:
            self.instructions = full
            return
        self.clock.cycles = self._block_cycles + before
        self._not_executed(address)
        self._halt_counted(uc, halt)

    def _point_halt(self, uc: Uc, address: int) -> _Halt | None:
        check = self.stop_check
        if check is not None and check(address):
            return _Halt.CHECK
        special = self._special.get(address)
        if special is not None:
            return special
        access = self._memory_ops.get(address)
        if access is not None and self._misaligned_access(uc, access):
            return _Halt.FAULT
        division = self._divisions.get(address)
        if division is not None and self._division_by_zero(uc, address, division):
            return _Halt.DIAGNOSTIC
        if address in self._sp_checks:
            sp = uc.reg_read(_SP)
            if sp < self.stack_floor:
                return _Halt.STACK
            if self._shadow is not None:
                self._track_stack(sp)
        return None

    def _insn_pc(self, uc: Uc) -> int:
        """PC de la instrucción en curso desde un hook de memoria (preciso en ambos modos)."""
        if self._stepping:
            return self._current_pc
        pc: int = uc.reg_read(_PC)
        return pc

    def _on_invalid(
        self, uc: Uc, access: int, address: int, size: int, value: int, _data: Any
    ) -> bool:
        self._invalid_access = (access, address)
        return False

    def _division_by_zero(self, uc: Uc, address: int, division: tuple[int, str, bool]) -> bool:
        """Registra una división por cero (RISC-V no la atrapa). True si hay que detenerse."""
        register, operation, library = division
        if uc.reg_read(_REG_IDS[register]) != 0:
            return False
        if library:
            # El lugar interesante es la llamada del programa, no la de otra rutina
            # de la biblioteca (__divsi3 llama a __udivsi3).
            site = (uc.reg_read(_REG_IDS[1]) - 4) & 0xFFFF_FFFF
            caller = self._image.function_at(site) if self._image is not None else None
            if caller is None or caller.startswith("__"):
                return False
            result = _("el resultado no está definido (depende de la biblioteca)")
        else:
            site = address
            result = (
                _("el cociente queda en -1")
                if operation == DIVISION
                else _("el resto es el dividendo")
            )
        return self._diagnose(
            "div0",
            site,
            _(
                "{operation} por cero: RISC-V no genera una excepción; {result} y el "
                "programa sigue como si nada",
                operation=_(operation),
                result=result,
            ),
            self.div_by_zero,
        )

    # ------------------------------------------------------ memoria sombra

    def _mark(self, address: int, size: int, value: int) -> None:
        if self._shadow is None:
            return
        start = address - self.memory.sram_base
        stop = min(start + size, len(self._shadow))
        if start >= 0:
            self._shadow[start:stop] = bytes([value]) * (stop - start)

    def _on_sram_write(
        self, uc: Uc, access: int, address: int, size: int, value: int, _data: Any
    ) -> None:
        self._mark(address, size, 1)

    def _on_sram_read(
        self, uc: Uc, access: int, address: int, size: int, value: int, _data: Any
    ) -> None:
        shadow = self._shadow
        if shadow is None:
            return
        start = address - self.memory.sram_base
        if all(shadow[start : start + size]):
            return
        pc = self._insn_pc(uc)
        name = self.name_address(address) if self.name_address is not None else None
        what = (
            f"`{name}`"
            if name
            else _("memoria de la pila en {address}", address=f"0x{address:08x}")
        )
        message = _(
            "lectura de {what} sin inicializar: su valor es indefinido "
            "(suele ser lo que dejó una llamada anterior)",
            what=what,
        )
        if self._diagnose("uninit", pc, message, self.uninitialized):
            self._halt(uc, _Halt.DIAGNOSTIC)

    def _track_stack(self, sp: int) -> None:
        """Al reservar pila (sp baja), lo reservado todavía no tiene valores."""
        if sp < self._last_sp:
            self._mark(sp, self._last_sp - sp, 0)
        self._last_sp = sp

    def _diagnose(self, kind: str, site: int, message: str, mode: str) -> bool:
        """Anota un aviso (una vez por lugar). True si el modo pide detenerse."""
        if (kind, site) not in self._warned:
            self._warned.add((kind, site))
            self.diagnostics.append(Diagnostic(kind, site, message))
            return mode == "break"
        return False

    def take_diagnostics(self) -> list[Diagnostic]:
        """Avisos nuevos desde la última consulta."""
        taken, self.diagnostics = self.diagnostics, []
        return taken

    def _misaligned_access(self, uc: Uc, access: tuple[int, int, int, bool]) -> bool:
        """¿La instrucción de memoria en curso accedería a una dirección desalineada?

        Unicorn resuelve esos accesos en silencio (y los hooks de memoria los ven
        partidos en bytes), así que se calcula la dirección efectiva antes de ejecutar.
        """
        base, offset, size, is_store = access
        address = (uc.reg_read(_REG_IDS[base]) + offset) & 0xFFFF_FFFF
        if address % size == 0 or self.is_mmio(address):
            return False  # el bus MMIO ya reporta sus propios desalineados
        kind = _("escritura") if is_store else _("lectura")
        unit = _("media palabra (2 bytes)") if size == 2 else _("palabra (4 bytes)")
        self._fault = self._trap(
            self._current_pc,
            _(
                "acceso desalineado: {kind} de una {unit} en {address}, que no es "
                "múltiplo de {size}. ¿Un puntero a int que apunta dentro de un char[]?",
                kind=kind,
                unit=unit,
                address=f"0x{address:08x}",
                size=size,
            ),
            address,
            kind="misaligned",
        )
        return True

    def _mmio_fault(self, uc: Uc, fault: MmioFault, offset: int) -> None:
        self._fault = self._trap(
            self._current_pc,
            _("acceso MMIO inválido: {fault}", fault=fault),
            self.memory.mmio_base + offset,
            kind="mmio",
        )
        self._halt(uc, _Halt.FAULT)

    def _mmio_read(self, uc: Uc, offset: int, size: int, _data: Any) -> int:
        try:
            return self.bus.read(offset, size)
        except MmioFault as fault:
            self._mmio_fault(uc, fault, offset)
            return 0
        finally:
            self._catch_up()

    def _mmio_write(self, uc: Uc, offset: int, size: int, value: int, _data: Any) -> None:
        try:
            self.bus.write(offset, size, value)
        except MmioFault as fault:
            self._mmio_fault(uc, fault, offset)
            return
        finally:
            self._catch_up()
        self._refresh_deadline()

    # -------------------------------------------------------- interrupciones

    def _enter_isr(self, pc: int) -> StopInfo | None:
        line = self.pic.next_irq()
        if line is None:
            return None
        if self._vector_table is None:
            return self._trap(
                pc,
                _("llegó la IRQ {line} pero el binario no define __vector_table", line=line),
                kind="vector",
            )
        raw = self.read_memory(self._vector_table + 4 * line, 4)
        handler = int.from_bytes(raw, "little") if raw is not None else 0
        if self._region_of(handler, 4) != "flash":
            return self._trap(
                pc,
                _(
                    "IRQ {line}: el vector apunta a {handler}, fuera de Flash",
                    line=line,
                    handler=f"0x{handler:08x}",
                ),
                kind="vector",
            )
        frame = self.sp - ISR_FRAME_SIZE
        if frame < self.stack_floor:
            return self._stack_overflow(pc)
        if self.tracer is not None:
            self.tracer.event(f"IRQ {line}")
        words = [pc, *(self.read_register(r) for r in ISR_SAVED_REGS)]
        words += [0] * (ISR_FRAME_SIZE // 4 - len(words))
        self._uc.mem_write(frame, struct.pack(f"<{len(words)}I", *words))
        self._mark(frame, ISR_FRAME_SIZE, 1)  # la CPU guardó el contexto: está inicializado
        self._last_sp = frame
        self.write_register(2, frame)
        self.set_pc(handler)
        self._isr_frames.append(frame)
        self.pic.acknowledge(line)
        return None

    def _return_from_isr(self, pc: int) -> StopInfo | None:
        if not self.pic.in_isr or not self._isr_frames:
            return self._trap(
                pc, _("mret ejecutado fuera de una rutina de interrupción"), kind="isr-stack"
            )
        frame = self.sp
        expected = self._isr_frames[-1]
        if frame != expected:
            return self._trap(
                pc,
                _(
                    "la ISR dejó la pila desbalanceada: sp = {sp}, se esperaba {expected}",
                    sp=f"0x{frame:08x}",
                    expected=f"0x{expected:08x}",
                ),
                kind="isr-stack",
            )
        if self.tracer is not None:
            self.tracer.step(pc)
        self._pc_hits[pc] = self._pc_hits.get(pc, 0) + 1
        raw = bytes(self._uc.mem_read(frame, ISR_FRAME_SIZE))
        saved_pc, *regs = struct.unpack(f"<{ISR_FRAME_SIZE // 4}I", raw)
        for index, value in zip(ISR_SAVED_REGS, regs, strict=False):
            self.write_register(index, value)
        self.write_register(2, frame + ISR_FRAME_SIZE)
        self.set_pc(saved_pc)
        self._isr_frames.pop()
        self.pic.complete()
        self.instructions += 1  # mret también es una instrucción ejecutada
        self.clock.cycles += 1
        return None

    def _wait_for_interrupt(self, pc: int) -> StopInfo | None:
        """`wfi`: adelanta el reloj hasta que haya una IRQ habilitada pendiente."""
        if self.tracer is not None:
            self.tracer.step(pc)
        self._pc_hits[pc] = self._pc_hits.get(pc, 0) + 1
        for _attempt in range(1024):
            if self.pic.wake_pending():
                break
            deadline = self.bus.next_deadline()
            if deadline is None:
                break
            self.clock.cycles = max(self.clock.cycles, deadline)
            self.bus.service(self.clock.cycles)
        if not self.pic.wake_pending() and self.interactive and self.bus.can_wake():
            # Nada programado, pero el usuario puede escribir o apretar algo: se espera.
            while not self.pic.wake_pending():
                if self._pace_and_poll(max_sleep=0.02):
                    return StopInfo(StopReason.PAUSED, pc, _("ejecución pausada (esperando datos)"))
                time.sleep(0.02)
        if not self.pic.wake_pending():
            return self._trap(
                pc,
                _(
                    "wfi: la CPU se durmió sin ninguna interrupción habilitada que pueda "
                    "despertarla (deadlock)"
                ),
                kind="wfi-deadlock",
            )
        self._refresh_deadline()
        self.instructions += 1
        self.set_pc(pc + 4)
        # Dormir de verdad el tiempo "salteado", atendiendo pausas mientras tanto.
        paused = self._pace_and_poll()
        while not paused and self._behind_schedule():
            paused = self._pace_and_poll()
        return StopInfo(StopReason.PAUSED, self.pc, _("ejecución pausada")) if paused else None

    # ----------------------------------------------------------------- trampas

    def _trap_from_error(self, exc: UcError) -> StopInfo:
        pc = self._current_pc
        if self._invalid_access is None:
            return self._trap(
                pc,
                _(
                    "excepción de la CPU en {pc}: {error} "
                    "(¿instrucción ilegal o acceso a memoria desalineado?)",
                    pc=f"0x{pc:08x}",
                    error=exc,
                ),
                kind="exception",
            )
        access, address = self._invalid_access
        kind = _(_ACCESS_KIND.get(access, N_("acceso")))
        region = self._region_of(address)
        sram = self.memory.sram_base
        at = f"0x{address:08x}"
        if region == "null":
            message = _("desreferencia de puntero nulo: {kind} en {address}", kind=kind, address=at)
            trap_kind = "null-pointer"
        elif access in (UC_MEM_FETCH_PROT, UC_MEM_FETCH_UNMAPPED):
            where = (
                _("la SRAM (no es ejecutable)") if region == "sram" else _("una zona sin código")
            )
            message = _("salto a {address}, en {where}", address=at, where=where)
            trap_kind = "bad-jump"
        elif access == UC_MEM_WRITE_PROT and region == "flash":
            message = _("escritura en Flash (memoria de sólo lectura) en {address}", address=at)
            trap_kind = "flash-write"
        elif sram - 0x1_0000 <= address < sram and self.sp < sram:
            return self._stack_overflow(pc)
        else:
            message = _("{kind} en memoria no mapeada: {address}", kind=kind, address=at)
            trap_kind = "unmapped"
        return self._trap(pc, message, address, kind=trap_kind)
