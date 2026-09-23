"""Ayuda (`?`): atajos vigentes, marcadores y mapa de memoria de la placa."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from hardboiled.core.events import EvtProgramLoaded
from hardboiled.i18n import N_, _

# Descripción de cada acción de la App (las que no figuran no se listan).
ACTION_HELP: dict[str, str] = {
    "continue": N_("Continue: corre hasta un breakpoint, una trampa o el fin"),
    "pause": N_("Pausa una ejecución en curso"),
    "toggle_breakpoint": N_("Pone/quita un breakpoint en la línea del cursor"),
    "conditional_breakpoint": N_("Breakpoint condicional (`i == 3`, `#5`)"),
    "step_over": N_("Step Over: siguiente línea sin entrar en funciones"),
    "step_into": N_("Step Into: siguiente línea, entrando en funciones"),
    "step_out": N_("Step Out: termina la función actual"),
    "step_instruction": N_("Stepi: una instrucción de máquina"),
    "step_back": N_("Paso atrás: deshace el último paso"),
    "run_to_cursor": N_("Ejecuta hasta la línea del cursor"),
    "watch": N_("Watchpoint: detiene cuando cambia una expresión"),
    "toggle_disassembly": N_("Muestra u oculta el desensamblado"),
    "toggle_profile": N_("Mapa de calor: instrucciones ejecutadas por línea"),
    "register_format": N_("Cambia el formato de los registros"),
    "open_file": N_("Abre otro archivo fuente"),
    "search": N_("Busca en el código"),
    "search_next": N_("Siguiente coincidencia"),
    "search_previous": N_("Coincidencia anterior"),
    "goto_line": N_("Va a una línea"),
    "clock_faster": N_("Duplica la frecuencia del reloj de la CPU"),
    "clock_slower": N_("Reduce el reloj a la mitad (cámara lenta)"),
    "clock_unlimited": N_("Alterna entre reloj fijo y sin límite"),
    "reset": N_("Reinicia la placa"),
    "help": N_("Esta ayuda"),
    "quit": N_("Salir"),
}

MARKERS = [
    ("●", "bold red", N_("breakpoint")),
    ("◆", "bold red", N_("breakpoint condicional")),
    ("▶", "bold yellow", N_("línea (o instrucción) en ejecución")),
    ("▷", "bold yellow", N_("línea del marco elegido en Llamadas")),
    ("✖", "bold bright_red", N_("línea donde ocurrió una trampa")),
    ("◉", "bold magenta", N_("watchpoint (pestaña Puntos)")),
]


def _key_label(key: str) -> str:
    """`shift+f11` -> `Shift+F11`, `slash` -> `/`."""
    names = {"slash": "/", "colon": ":", "question_mark": "?", "delete": "Supr"}
    parts = key.split("+")
    pretty = []
    for part in parts:
        if part in names:
            pretty.append(names[part])
        elif part in ("shift", "ctrl", "alt"):
            pretty.append(part.capitalize())
        elif part.startswith("f") and part[1:].isdigit():
            pretty.append(part.upper())
        else:
            pretty.append(part)
    return "+".join(pretty)


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > VerticalScroll {
        width: 100; height: 90%; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    HelpScreen .section { margin-top: 1; text-style: bold; color: $accent; }
    """

    BINDINGS = [  # noqa: RUF012
        Binding("escape", "close", _("Cerrar")),
        Binding("question_mark", "close", show=False),
        Binding("q", "close", show=False),
    ]

    def __init__(self, keys: dict[str, list[str]], program: EvtProgramLoaded | None) -> None:
        super().__init__()
        self.keys = keys
        self.program = program

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label(_("Ayuda de hardboiled (Esc cierra)"), classes="section")
            yield Static(self._keys_table())
            yield Label(_("Marcadores"), classes="section")
            markers = Text()
            for symbol, style, meaning in MARKERS:
                markers.append(f" {symbol} ", style=style)
                markers.append(f"{_(meaning)}\n")
            markers.rstrip()
            yield Static(markers)
            yield Label(_("Mapa de memoria"), classes="section")
            yield Static(self._memory_table())

    def _keys_table(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold yellow", no_wrap=True)
        table.add_column()
        for action, description in ACTION_HELP.items():
            keys = self.keys.get(action)
            if keys:
                table.add_row(" / ".join(_key_label(k) for k in keys), _(description))
        table.add_row("0-7", _("Conmuta un switch"))
        return table

    def _memory_table(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim")
        table.add_column()
        memory = dict(
            (name, (base, size))
            for name, base, size in (self.program.memory if self.program else ())
        )
        descriptions = {
            "flash": _("Flash (R X): código, constantes, imagen de .data"),
            "sram": _("SRAM (R W): .data, .bss, heap y pila (crece hacia abajo)"),
            "mmio": _("MMIO: periféricos"),
        }
        table.add_row("0x00000000-0x0000ffff", _("zona de trampa: acceder es un puntero nulo"))
        for name, (base, size) in memory.items():
            table.add_row(f"0x{base:08x}-0x{base + size - 1:08x}", descriptions.get(name, name))
        if self.program is not None and "mmio" in memory:
            mmio = memory["mmio"][0]
            for peripheral in self.program.peripherals:
                table.add_row(
                    f"  0x{mmio + peripheral.offset:08x}",
                    f"{peripheral.name} ({peripheral.kind})",
                )
        return table

    def action_close(self) -> None:
        self.dismiss(None)
