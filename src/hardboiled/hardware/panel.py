"""Modelos MMIO del panel local. Estado y tiempo pertenecen al motor, no al navegador."""

from __future__ import annotations

import copy
from typing import Any, Literal

PanelKind = Literal["keypad_4x4", "lcd_hd44780", "pwm_rgb"]


class PanelModel:
    def __init__(self) -> None:
        self.registers = [0, 0, 0, 0]

    def read(self, reg: int) -> int:
        return self.registers[reg // 4]

    def write(self, reg: int, value: int) -> None:
        self.registers[reg // 4] = value

    def state(self) -> dict[str, Any]:
        return {"registers": self.registers.copy()}

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(vars(self))

    def restore(self, state: dict[str, Any]) -> None:
        vars(self).update(copy.deepcopy(state))


class KeypadModel(PanelModel):
    """Filas activas en alto, como Keypad4x4; CTRL bit 0 habilita IRQ por contacto."""

    def __init__(self) -> None:
        super().__init__()
        self.pressed: set[tuple[int, int]] = set()

    def read(self, reg: int) -> int:
        if reg == 4:
            return sum(
                1 << col
                for col in range(4)
                if any(
                    self.registers[0] & (1 << row) and (row, col) in self.pressed
                    for row in range(4)
                )
            )
        return super().read(reg)

    def key(self, row: int, col: int, pressed: bool) -> None:
        if not 0 <= row < 4 or not 0 <= col < 4:
            raise ValueError("tecla fuera del teclado 4x4")
        if pressed:
            self.pressed.add((row, col))
        else:
            self.pressed.discard((row, col))

    def state(self) -> dict[str, Any]:
        return {
            "rows": self.registers[0] & 15,
            "columns": self.read(4),
            "pressed": [list(key) for key in sorted(self.pressed)],
        }


class LcdModel(PanelModel):
    """Bus MMIO de bytes completos; comandos HD44780, DDRAM de 2x40 y CGRAM 8x8."""

    def __init__(self) -> None:
        super().__init__()
        self.ddram = [32] * 128
        self.cgram = [0] * 64
        self.address = 0
        self.cgram_mode = False
        self.display = False
        self.cursor = False
        self.blink = False
        self.increment = True
        self.entry_shift = False
        self.shift = 0

    def _move(self, direction: int) -> None:
        if self.cgram_mode:
            self.address = (self.address + direction) % 64
        elif direction > 0:
            self.address = {0x27: 0x40, 0x67: 0}.get(self.address, (self.address + 1) % 128)
        else:
            self.address = {0: 0x67, 0x40: 0x27}.get(self.address, (self.address - 1) % 128)

    def read(self, reg: int) -> int:
        if reg == 8:
            return self.address  # El adaptador completa las operaciones sin tiempo busy.
        return super().read(reg)

    def write(self, reg: int, value: int) -> None:
        super().write(reg, value)
        value &= 255
        if reg == 4:
            if self.cgram_mode:
                self.cgram[self.address % 64] = value & 31
            else:
                self.ddram[self.address] = value
            self._move(1 if self.increment else -1)
            if self.entry_shift and not self.cgram_mode:
                self.shift = (self.shift + (1 if self.increment else -1)) % 40
        elif reg == 0:
            if value & 128:
                self.address, self.cgram_mode = value & 127, False
            elif value & 64:
                self.address, self.cgram_mode = value & 63, True
            elif value & 32:
                pass  # Bus de bytes completo; Function Set no cambia su ancho MMIO.
            elif value & 16:
                direction = 1 if value & 4 else -1
                if value & 8:
                    self.shift = (self.shift - direction) % 40
                else:
                    self._move(direction)
            elif value & 8:
                self.display, self.cursor, self.blink = (
                    bool(value & 4),
                    bool(value & 2),
                    bool(value & 1),
                )
            elif value & 4:
                self.increment, self.entry_shift = bool(value & 2), bool(value & 1)
            elif value & 2:
                self.address, self.shift, self.cgram_mode = 0, 0, False
            elif value & 1:
                self.ddram = [32] * 128
                self.address, self.shift, self.cgram_mode = 0, 0, False

    def state(self) -> dict[str, Any]:
        row, col = divmod(self.address, 64)
        return {
            "cells": [
                [self.ddram[base + (self.shift + i) % 40] for i in range(16)] for base in (0, 64)
            ],
            "ddram": [self.ddram[:40], self.ddram[64:104]],
            "cgram": self.cgram.copy(),
            "display": self.display,
            "cursor": self.cursor,
            "blink": self.blink,
            "cursor_row": row if not self.cgram_mode else -1,
            "cursor_col": (col - self.shift) % 40,
            "address": self.address,
            "increment": self.increment,
            "shift": self.shift,
        }


class PwmModel(PanelModel):
    """PERIOD y compares R/G/B en ticks del reloj de la CPU; 0 detiene la salida."""

    def state(self) -> dict[str, Any]:
        period, *compare = self.registers
        duty = [min(value / period, 1.0) if period else 0.0 for value in compare]
        return {
            "period": period,
            "compare": compare,
            "duty": duty,
            "rgb": [round(value * 255) for value in duty],
        }


def panel_model(kind: PanelKind) -> PanelModel:
    return {"keypad_4x4": KeypadModel, "lcd_hd44780": LcdModel, "pwm_rgb": PwmModel}[kind]()
