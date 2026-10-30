"""Periférico externo de referencia: Teclado Matricial 4x4.

El teclado matricial se conecta a hardboiled como periférico externo (o mediante
su controlador en Python). Mapea dos registros de 32 bits:
  - Offset 0x00: FILAS (escrito por el microcontrolador; activa una fila poniendo el bit en 0 o 1).
  - Offset 0x04: COLUMNAS (leído por el microcontrolador; refleja qué columnas detectan contacto).
  - Offset 0x08: ESTADO / CONTROL e IRQ.
"""

from __future__ import annotations

from typing import ClassVar


class Keypad4x4:
    """Modelo de teclado matricial 4x4 independiente."""

    KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("1", "2", "3", "A"),
        ("4", "5", "6", "B"),
        ("7", "8", "9", "C"),
        ("*", "0", "#", "D"),
    )

    def __init__(self, pull_up: bool = True) -> None:
        self.pull_up = pull_up
        self.filas: int = 0  # Nibble bajo: bits 0..3
        self.pressed_keys: set[tuple[int, int]] = set()  # (row, col)

    def press(self, row: int, col: int) -> None:
        """Presiona una tecla en (fila, columna)."""
        if 0 <= row < 4 and 0 <= col < 4:
            self.pressed_keys.add((row, col))

    def release(self, row: int, col: int) -> None:
        """Suelta una tecla."""
        self.pressed_keys.discard((row, col))

    def write_filas(self, value: int) -> None:
        """El microcontrolador escribe el patrón de barrido de filas."""
        self.filas = value & 0x0F

    def read_columnas(self) -> int:
        """Calcula el estado de las 4 columnas según las filas activas y teclas apretadas.

        Con lógica de pull-up (habitual en microcontroladores):
        Las filas se ponen en 0 (activo bajo) de a una. Si se presiona una tecla,
        la columna correspondiente se pone en 0.
        """
        cols = 0x00
        for row, col in self.pressed_keys:
            # Si la fila correspondiente está activa en el barrido (bit en 1)
            if (self.filas & (1 << row)) != 0:
                cols |= 1 << col
        return cols
