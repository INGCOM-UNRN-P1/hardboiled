"""Protocolo de mensajes inmutables entre la vista y el motor de emulación.

Los comandos viajan de la UI al motor por `cmd_queue`; los eventos, del motor a
la UI por `evt_queue`. Ambos lados sólo comparten estos tipos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Comandos (UI -> Motor)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CmdStepInto:
    pass


@dataclass(frozen=True)
class CmdStepOver:
    pass


@dataclass(frozen=True)
class CmdContinue:
    pass


@dataclass(frozen=True)
class CmdStepOut:
    """Ejecuta hasta volver a la función llamadora (finish)."""


@dataclass(frozen=True)
class CmdStepBack:
    """Vuelve al estado anterior al último comando de ejecución (paso atrás)."""


@dataclass(frozen=True)
class CmdStepInstruction:
    """Ejecuta una única instrucción de máquina (stepi)."""


@dataclass(frozen=True)
class CmdToggleBreakpoint:
    """Breakpoint por línea de C. Sin `source_file` se usa el archivo actual."""

    line_number: int
    source_file: str | None = None


@dataclass(frozen=True)
class CmdRunToLine:
    """Ejecuta hasta una línea de C sin dejar un breakpoint (run to cursor)."""

    line_number: int
    source_file: str | None = None


@dataclass(frozen=True)
class CmdSelectFrame:
    """Pide las variables locales de un marco de la pila de llamadas."""

    index: int


@dataclass(frozen=True)
class CmdToggleAddressBreakpoint:
    address: int


@dataclass(frozen=True)
class CmdSetBreakpointCondition:
    """Breakpoint en una línea que sólo detiene si `condition` es verdadera y/o
    a partir de la pasada `hit_count`. Sin ninguna de las dos queda incondicional."""

    line_number: int
    source_file: str | None = None
    condition: str | None = None
    hit_count: int | None = None


@dataclass(frozen=True)
class CmdToggleWatchpoint:
    """Vigila (o deja de vigilar) una expresión C: `results[1]`, `f->color`, `total`."""

    expression: str


@dataclass(frozen=True)
class CmdReadMemory:
    """Pide un volcado de memoria: `where` es una dirección, un símbolo o una expresión C."""

    where: str
    length: int = 256


@dataclass(frozen=True)
class CmdToggleSwitch:
    pin_index: int


@dataclass(frozen=True)
class CmdPause:
    """Interrumpe una ejecución en curso (Continue o un step largo)."""


@dataclass(frozen=True)
class CmdReset:
    """Reinicia la placa y vuelve a cargar el binario."""


@dataclass(frozen=True)
class CmdShutdown:
    """Termina el hilo de trabajo."""


Command = (
    CmdStepInto
    | CmdStepOver
    | CmdContinue
    | CmdStepInstruction
    | CmdStepOut
    | CmdStepBack
    | CmdRunToLine
    | CmdSelectFrame
    | CmdToggleBreakpoint
    | CmdToggleAddressBreakpoint
    | CmdToggleWatchpoint
    | CmdSetBreakpointCondition
    | CmdReadMemory
    | CmdToggleSwitch
    | CmdPause
    | CmdReset
    | CmdShutdown
)

# --------------------------------------------------------------------------
# Eventos (Motor -> UI)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PeripheralInfo:
    name: str
    kind: str
    offset: int
    width_bits: int


@dataclass(frozen=True)
class VariableInfo:
    """Valor de una variable (o de un elemento/miembro) listo para mostrar."""

    name: str
    type_name: str
    value: str
    address: int | None
    children: tuple[VariableInfo, ...] = ()
    # Ruta estable ("datos.pos[1].x") para conservar qué nodos están expandidos.
    path: str = ""


@dataclass(frozen=True)
class DisasmLine:
    """Una instrucción desensamblada con la línea de C a la que pertenece."""

    address: int
    raw: str  # bytes en hexadecimal ("fe010113" o "1141")
    text: str  # "addi sp, sp, -32"
    source_file: str | None
    source_line: int | None


@dataclass(frozen=True)
class StackSlot:
    """Una palabra de la pila con su marco y lo que contiene."""

    address: int
    value: int
    frame_index: int | None  # None: por debajo de sp (libre)
    frame_label: str | None
    note: str | None  # "ra guardado → main+0x28", "total", "IRQ 0: pc guardado"


@dataclass(frozen=True)
class FrameInfo:
    """Un marco de la pila de llamadas (el 0 es la función en curso)."""

    index: int
    pc: int
    label: str  # "square" o, sin información, "_start+0x40"
    source_file: str | None
    source_line: int | None
    # Entrada de interrupción: el marco siguiente es el código interrumpido.
    irq_line: int | None = None


@dataclass(frozen=True)
class EvtProgramLoaded:
    elf_path: str
    board_name: str
    entry_point: int
    source_files: tuple[str, ...]
    peripherals: tuple[PeripheralInfo, ...]


@dataclass(frozen=True)
class EvtCpuRunning:
    """La CPU comenzó a ejecutar (step o continue)."""


@dataclass(frozen=True)
class EvtCpuSuspended:
    pc: int
    source_file: str | None
    source_line: int | None
    registers: dict[str, int]
    cycle_count: int
    reason: str = ""
    function: str | None = None
    # Palabras (dirección, valor) alrededor de sp, de direcciones bajas a altas.
    stack: tuple[tuple[int, int], ...] = field(default=())
    frames: tuple[FrameInfo, ...] = field(default=())
    # Variables locales del marco 0 y globales del programa.
    locals: tuple[VariableInfo, ...] = field(default=())
    global_vars: tuple[VariableInfo, ...] = field(default=())
    # Instrucciones de la función en curso (o alrededor del PC si no hay función).
    disassembly: tuple[DisasmLine, ...] = field(default=())
    # La pila por marcos (desde un poco por debajo de sp hacia arriba).
    stack_slots: tuple[StackSlot, ...] = field(default=())
    # Registros que contienen una dirección con nombre: {"x1": "main+0x2c", ...}.
    register_symbols: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EvtFrameVariables:
    """Variables locales del marco pedido con CmdSelectFrame."""

    frame_index: int
    label: str
    locals: tuple[VariableInfo, ...]


@dataclass(frozen=True)
class EvtMemoryDump:
    where: str  # lo que pidió el usuario
    address: int
    data: bytes  # vacío si no se pudo leer
    error: str | None = None
    # (dirección, nombre) de las variables globales que empiezan en el rango.
    labels: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class EvtHardwareUpdated:
    device_name: str
    register_offset: int
    value: int


@dataclass(frozen=True)
class EvtUartOutput:
    char_code: int


@dataclass(frozen=True)
class EvtTrap:
    reason: str
    fault_address: int | None
    # Dónde ocurrió: la instrucción que falló y su ubicación en el código.
    pc: int | None = None
    instruction: str | None = None
    function: str | None = None
    source_file: str | None = None
    source_line: int | None = None


@dataclass(frozen=True)
class EvtProgramExited:
    exit_code: int


@dataclass(frozen=True)
class WatchInfo:
    expression: str
    address: int
    size: int
    type_name: str


@dataclass(frozen=True)
class ConditionInfo:
    source_file: str | None
    line: int | None
    address: int
    condition: str | None
    hit_count: int | None
    hits: int

    def describe(self) -> str:
        parts = [f"si {self.condition}"] if self.condition else []
        if self.hit_count:
            parts.append(f"desde la pasada {self.hit_count}")
        return ", ".join(parts) + f" ({self.hits} pasadas)"


@dataclass(frozen=True)
class EvtBreakpointsChanged:
    lines: frozenset[tuple[str, int]]
    addresses: frozenset[int]
    watches: tuple[WatchInfo, ...] = ()
    conditions: tuple[ConditionInfo, ...] = ()


@dataclass(frozen=True)
class EvtMessage:
    """Aviso informativo para mostrar al usuario."""

    text: str


Event = (
    EvtProgramLoaded
    | EvtCpuRunning
    | EvtCpuSuspended
    | EvtFrameVariables
    | EvtMemoryDump
    | EvtHardwareUpdated
    | EvtUartOutput
    | EvtTrap
    | EvtProgramExited
    | EvtBreakpointsChanged
    | EvtMessage
)


def collapse_frames(frames: tuple[FrameInfo, ...]) -> list[tuple[FrameInfo, int]]:
    """Agrupa marcos consecutivos idénticos (recursión): [(primer marco, cantidad)]."""
    groups: list[tuple[FrameInfo, int]] = []
    for frame in frames:
        if groups:
            first, count = groups[-1]
            same = (first.label, first.source_file, first.source_line, first.irq_line) == (
                frame.label,
                frame.source_file,
                frame.source_line,
                frame.irq_line,
            )
            if same and frame.irq_line is None:
                groups[-1] = (first, count + 1)
                continue
        groups.append((frame, 1))
    return groups
