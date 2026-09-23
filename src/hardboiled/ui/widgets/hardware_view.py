"""Periféricos interactivos: barra de LEDs, switches y estado de timers."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, Label, Static

from hardboiled.core.events import PeripheralInfo
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


class TimerView(Static):
    DEFAULT_CSS = """
    TimerView { height: 1; }
    """

    def __init__(self, info: PeripheralInfo) -> None:
        super().__init__()
        self.info = info
        self.ctrl = 0
        self.reload = 0

    def set_register(self, offset: int, value: int) -> None:
        if offset == 0:
            self.ctrl = value
        elif offset == 4:
            self.reload = value
        self.refresh()

    def render(self) -> Text:
        text = Text.assemble((f"{self.info.name:<9}", "bold"))
        if self.ctrl & 1:
            irq = " + IRQ" if self.ctrl & 2 else ""
            text.append(f"activo, período {self.reload} ciclos{irq}", style="green")
        else:
            text.append("detenido", style="dim")
        return text


class HardwareView(Vertical):
    DEFAULT_CSS = """
    HardwareView { height: auto; border: round $primary; padding: 0 1; }
    """

    def configure(self, peripherals: tuple[PeripheralInfo, ...]) -> None:
        self.remove_children()
        widgets: list[Static | Horizontal] = []
        for info in peripherals:
            if info.kind == "gpio_out":
                widgets.append(LedBarView(info))
            elif info.kind == "gpio_in":
                widgets.append(SwitchBankView(info))
            elif info.kind == "timer":
                widgets.append(TimerView(info))
        self.mount_all(widgets)

    def update_device(self, name: str, offset: int, value: int) -> None:
        for widget in self.children:
            info = getattr(widget, "info", None)
            if info is None or info.name != name:
                continue
            if isinstance(widget, LedBarView | SwitchBankView):
                widget.set_value(value)
            elif isinstance(widget, TimerView):
                widget.set_register(offset, value)
