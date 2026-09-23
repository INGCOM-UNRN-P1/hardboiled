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
    | CmdRunToLine
    | CmdSelectFrame
    | CmdToggleBreakpoint
    | CmdToggleAddressBreakpoint
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


@dataclass(frozen=True)
class EvtFrameVariables:
    """Variables locales del marco pedido con CmdSelectFrame."""

    frame_index: int
    label: str
    locals: tuple[VariableInfo, ...]


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


@dataclass(frozen=True)
class EvtProgramExited:
    exit_code: int


@dataclass(frozen=True)
class EvtBreakpointsChanged:
    lines: frozenset[tuple[str, int]]
    addresses: frozenset[int]


@dataclass(frozen=True)
class EvtMessage:
    """Aviso informativo para mostrar al usuario."""

    text: str


Event = (
    EvtProgramLoaded
    | EvtCpuRunning
    | EvtCpuSuspended
    | EvtFrameVariables
    | EvtHardwareUpdated
    | EvtUartOutput
    | EvtTrap
    | EvtProgramExited
    | EvtBreakpointsChanged
    | EvtMessage
)
