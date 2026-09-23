"""Periféricos interactivos: barra de LEDs, switches y estado de timers."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, Label, Static

from hardboiled.core.events import PeripheralInfo
from hardboiled.i18n import _
from hardboiled.ui.palette import current_palette


class LedBarView(Static):
    DEFAULT_CSS = """
    LedBarView { height: 1; }
    """

    def __init__(self, info: PeripheralInfo) -> None:
        super().__init__()
        self.info = info
        self.value = 0

    def set_value(self, value: int) -> None:
        self.value = value
        self.refresh()

    def render(self) -> Text:
        text = Text.assemble((f"{self.info.name:<9}", "bold"))
        # El bit más significativo a la izquierda, como en un número binario.
        palette = current_palette(self)
        for bit in reversed(range(self.info.width_bits)):
            on = bool(self.value >> bit & 1)
            symbol = palette.led_on if on else palette.led_off
            text.append(f"{symbol} ", style=palette.led_on_style if on else palette.led_off_style)
        text.append(f" 0x{self.value:0{(self.info.width_bits + 3) // 4}x}", style="dim")
        return text


class SwitchBankView(Horizontal):
    DEFAULT_CSS = """
    SwitchBankView { height: 1; }
    SwitchBankView Label { width: 9; text-style: bold; }
    SwitchBankView Button { min-width: 7; width: 7; margin: 0 1 0 0; }
    SwitchBankView Button.on { background: $success; }
    """

    class Toggled(Message):
        def __init__(self, pin_index: int) -> None:
            super().__init__()
            self.pin_index = pin_index

    def __init__(self, info: PeripheralInfo) -> None:
        super().__init__()
        self.info = info
        self.value = 0

    def compose(self) -> ComposeResult:
        yield Label(self.info.name)
        for pin in reversed(range(self.info.width_bits)):
            yield Button(f"{pin}:off", id=f"sw-{pin}", compact=True)

    def on_mount(self) -> None:
        self.set_value(self.value)

    def set_value(self, value: int) -> None:
        self.value = value
        for pin in range(self.info.width_bits):
            try:
                button = self.query_one(f"#sw-{pin}", Button)
            except NoMatches:
                return  # todavía no se montaron los botones; on_mount lo aplica
            on = bool(value >> pin & 1)
            button.label = f"{pin}:{'ON' if on else 'off'}"
            button.set_class(on, "on")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id is not None:
            self.post_message(self.Toggled(int(event.button.id.removeprefix("sw-"))))


class ButtonBankView(Horizontal):
    DEFAULT_CSS = """
    ButtonBankView { height: 1; }
    ButtonBankView Label { width: 9; text-style: bold; }
    ButtonBankView Button { min-width: 7; width: 7; margin: 0 1 0 0; }
    ButtonBankView Button.pressed { background: $warning; }
    ButtonBankView Button.pending { text-style: bold underline; }
    """

    class Pressed(Message):
        def __init__(self, pin_index: int) -> None:
            super().__init__()
            self.pin_index = pin_index

    def __init__(self, info: PeripheralInfo) -> None:
        super().__init__()
        self.info = info
        self.value = 0

    def compose(self) -> ComposeResult:
        yield Label(self.info.name)
        for pin in reversed(range(self.info.width_bits)):
            yield Button(f"▣ {pin}", id=f"btn-{pin}", compact=True)

    def set_detail(self, state: dict[str, int]) -> None:
        pending = state.get("pending", 0)
        presses = state.get("presses", 0)
        try:
            label = self.query_one(Label)
        except NoMatches:
            return  # todavía no se montó
        label.tooltip = _(
            "pulsaciones: {presses}, flancos pendientes: {pending}",
            presses=presses,
            pending=f"{pending:04b}",
        )
        for pin in range(self.info.width_bits):
            try:
                button = self.query_one(f"#btn-{pin}", Button)
            except NoMatches:
                return
            button.set_class(bool(pending >> pin & 1), "pending")

    def set_value(self, value: int) -> None:
        self.value = value
        for pin in range(self.info.width_bits):
            try:
                button = self.query_one(f"#btn-{pin}", Button)
            except NoMatches:
                return
            button.set_class(bool(value >> pin & 1), "pressed")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id is not None:
            self.post_message(self.Pressed(int(event.button.id.removeprefix("btn-"))))


# (fila, columna, carácter) de cada segmento en una celda de 3x3.
SEGMENT_CELLS = {
    0: (0, 1, "_"),  # a
    1: (1, 2, "|"),  # b
    2: (2, 2, "|"),  # c
    3: (2, 1, "_"),  # d
    4: (2, 0, "|"),  # e
    5: (1, 0, "|"),  # f
    6: (1, 1, "_"),  # g
}


def render_digits(segments: list[int]) -> list[str]:
    """Tres renglones de texto con los dígitos (el 0 es el de la derecha)."""
    rows = ["", "", ""]
    for pattern in reversed(segments):
        cell = [[" "] * 3 for _ in range(3)]
        for bit, (row, col, char) in SEGMENT_CELLS.items():
            if pattern >> bit & 1:
                cell[row][col] = char
        for row in range(3):
            rows[row] += "".join(cell[row])
        rows[0] += " "
        rows[1] += " "
        rows[2] += "." if pattern & 0x80 else " "
    return rows


class SevenSegView(Static):
    DEFAULT_CSS = """
    SevenSegView { height: 3; }
    """

    def __init__(self, info: PeripheralInfo) -> None:
        super().__init__()
        self.info = info
        self.words = [0, 0]

    def set_register(self, offset: int, value: int) -> None:
        self.words[offset // 4 & 1] = value
        self.refresh()

    def render(self) -> Text:
        data = self.words[0] | self.words[1] << 32
        digits = self.info.digits or 4
        segments = [(data >> (8 * i)) & 0xFF for i in range(digits)]
        rows = render_digits(segments)
        palette = current_palette(self)
        text = Text()
        for index, row in enumerate(rows):
            label = f"{self.info.name:<9}" if index == 1 else " " * 9
            text.append(label, style="bold")
            text.append(row, style=palette.led_on_style)
            if index < 2:
                text.append("\n")
        return text


class TimerView(Static):
    DEFAULT_CSS = """
    TimerView { height: 1; }
    """

    def __init__(self, info: PeripheralInfo) -> None:
        super().__init__()
        self.info = info
        self.ctrl = 0
        self.reload = 0
        self.state: dict[str, int] = {}

    def set_register(self, offset: int, value: int) -> None:
        if offset == 0:
            self.ctrl = value
        elif offset == 4:
            self.reload = value
        self.refresh()

    def set_state(self, state: dict[str, int]) -> None:
        self.state = state
        self.ctrl = state.get("ctrl", self.ctrl)
        self.reload = state.get("reload", self.reload)
        self.refresh()

    def render(self) -> Text:
        text = Text.assemble((f"{self.info.name:<9}", "bold"))
        if self.ctrl & 1:
            irq = " + IRQ" if self.ctrl & 2 else ""
            text.append(_("período {cycles}", cycles=self.reload) + irq, style="green")
            if "count" in self.state:
                text.append(_("  faltan {count}", count=self.state["count"]), style="bold")
        else:
            text.append(_("detenido"), style="dim")
        expirations = self.state.get("expirations")
        if expirations:
            text.append(_("  vencimientos: {count}", count=expirations), style="dim")
        return text


class HardwareView(Vertical):
    DEFAULT_CSS = """
    HardwareView { height: auto; border: round $primary; padding: 0 1; }
    """

    _peripherals: tuple[PeripheralInfo, ...] | None = None

    def configure(self, peripherals: tuple[PeripheralInfo, ...]) -> None:
        """Arma un widget por periférico. Al recargar el programa, la placa es la misma."""
        if peripherals == self._peripherals:
            return
        widgets = self._widgets_for(peripherals)
        if self._peripherals is None:
            self.mount_all(widgets)
        else:
            # Quitar es asíncrono: se monta la placa nueva recién cuando se fue la vieja.
            async def replace() -> None:
                await self.remove_children()
                await self.mount_all(widgets)

            self.call_later(replace)
        self._peripherals = peripherals

    def _widgets_for(self, peripherals: tuple[PeripheralInfo, ...]) -> list[Static | Horizontal]:
        widgets: list[Static | Horizontal] = []
        for info in peripherals:
            if info.kind == "gpio_out":
                widgets.append(LedBarView(info))
            elif info.kind == "gpio_in":
                widgets.append(SwitchBankView(info))
            elif info.kind == "timer":
                widgets.append(TimerView(info))
            elif info.kind == "gpio_irq":
                widgets.append(ButtonBankView(info))
            elif info.kind == "sevenseg":
                widgets.append(SevenSegView(info))
        return widgets

    def update_states(self, devices: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]) -> None:
        """Estado interno de los periféricos en cada detención (timer, UART, botones)."""
        states = {name: dict(items) for name, items in devices}
        for widget in self.children:
            info = getattr(widget, "info", None)
            if info is None or info.name not in states:
                continue
            if isinstance(widget, TimerView):
                widget.set_state(states[info.name])
            elif isinstance(widget, ButtonBankView):
                widget.set_detail(states[info.name])

    def update_device(self, name: str, offset: int, value: int) -> None:
        for widget in self.children:
            info = getattr(widget, "info", None)
            if info is None or info.name != name:
                continue
            if isinstance(widget, LedBarView | SwitchBankView | ButtonBankView):
                widget.set_value(value)
            elif isinstance(widget, TimerView | SevenSegView):
                widget.set_register(offset, value)
