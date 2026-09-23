"""Colores de la interfaz según el tema (oscuro/claro) y el modo para daltonismo.

El modo para daltonismo usa la paleta Okabe-Ito (azul/naranja, distinguibles
con las deficiencias de color más comunes) y agrega forma y subrayado donde
antes sólo había color: LEDs ■/□ y valores cambiados subrayados.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.style import Style


@dataclass(frozen=True)
class Palette:
    syntax_theme: str
    active_bg: Style
    cursor_bg: Style
    frame_bg: Style
    trap_bg: Style
    led_on: str
    led_off: str
    led_on_style: str
    led_off_style: str
    changed: str  # valores que cambiaron desde la detención anterior
    breakpoint: str


DARK = Palette(
    syntax_theme="monokai",
    active_bg=Style(bgcolor="#2d3f5f"),
    cursor_bg=Style(bgcolor="#262626"),
    frame_bg=Style(bgcolor="#3b2f4a"),
    trap_bg=Style(bgcolor="#5c1f1f"),
    led_on="●",
    led_off="○",
    led_on_style="bold bright_red",
    led_off_style="grey35",
    changed="bold yellow",
    breakpoint="bold red",
)

LIGHT = Palette(
    syntax_theme="friendly",
    active_bg=Style(bgcolor="#cfe2ff"),
    cursor_bg=Style(bgcolor="#ececec"),
    frame_bg=Style(bgcolor="#e6dcf5"),
    trap_bg=Style(bgcolor="#f8d0d0"),
    led_on="●",
    led_off="○",
    led_on_style="bold #d00000",
    led_off_style="#b0b0b0",
    changed="bold #b35900",
    breakpoint="bold #c00000",
)

OKABE_BLUE = "#0072B2"
OKABE_ORANGE = "#E69F00"


def palette_for(theme: str, colorblind: bool) -> Palette:
    base = LIGHT if theme == "light" else DARK
    if not colorblind:
        return base
    return Palette(
        syntax_theme=base.syntax_theme,
        active_bg=Style(bgcolor="#1f4f7a") if base is DARK else Style(bgcolor="#bcdcf5"),
        cursor_bg=base.cursor_bg,
        frame_bg=base.frame_bg,
        trap_bg=Style(bgcolor="#6b4a00") if base is DARK else Style(bgcolor="#ffe3a3"),
        led_on="■",
        led_off="□",
        led_on_style=f"bold {OKABE_ORANGE}",
        led_off_style=base.led_off_style,
        changed=f"bold underline {OKABE_ORANGE}",
        breakpoint=f"bold {OKABE_BLUE}",
    )


def current_palette(widget: object) -> Palette:
    """La paleta de la App del widget, o la oscura si no hay (tests aislados)."""
    try:
        app = getattr(widget, "app", None)
    except Exception:  # NoActiveAppError: widget fuera de una App
        return DARK
    palette = getattr(app, "palette", None)
    return palette if isinstance(palette, Palette) else DARK
