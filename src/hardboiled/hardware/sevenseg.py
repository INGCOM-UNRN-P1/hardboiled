"""Display de 7 segmentos multidígito.

Un byte por dígito (el dígito 0 es el de la derecha), empaquetados en palabras:
    +0x0 DIGITS_0_3  dígitos 0 a 3
    +0x4 DIGITS_4_7  dígitos 4 a 7 (si el display tiene más de 4)

Bits de cada byte: a=0 (arriba), b=1 (arriba derecha), c=2 (abajo derecha),
d=3 (abajo), e=4 (abajo izquierda), f=5 (arriba izquierda), g=6 (medio), dp=7.
"""

from __future__ import annotations

from hardboiled.core.events import EvtHardwareUpdated
from hardboiled.hardware.bus import Peripheral, merge
from hardboiled.i18n import N_

MAX_DIGITS = 8

# Mismo alfabeto que seg_pattern() del SDK: cifras hexadecimales.
FONT = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
        0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71)  # fmt: skip
CHARS = {pattern: "0123456789ABCDEF"[i] for i, pattern in enumerate(FONT)} | {0: " "}


class SevenSegment(Peripheral):
    kind = "sevenseg"
    size = 8

    def __init__(self, name: str, offset: int, digits: int = 4) -> None:
        super().__init__(name, offset, digits * 8)
        self.digits = digits
        self.words = [0, 0]

    def reset(self) -> None:
        self.words = [0, 0]

    def read(self, reg: int) -> int:
        if reg in (0, 4):
            return self.words[reg // 4]
        raise self.fault(reg, N_("registro inexistente"))

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg not in (0, 4):
            raise self.fault(reg, N_("registro inexistente"))
        index = reg // 4
        # Sólo existen los bytes de los dígitos que tiene el display.
        available = min(max(self.digits - 4 * index, 0), 4)
        new = merge(self.words[index], value, mask) & ((1 << (8 * available)) - 1)
        if new != self.words[index]:
            self.words[index] = new
            self.emit(EvtHardwareUpdated(self.name, reg, new))

    def text(self) -> str:
        """Lo que se lee en el display, con el dígito 0 a la derecha.

        Un dígito apagado es un espacio y uno que no forma una cifra, `?`. El
        punto decimal se ignora.
        """
        return "".join(CHARS.get(s & 0x7F, "?") for s in reversed(self.segments()))

    def segments(self) -> list[int]:
        """Segmentos de cada dígito, del 0 (derecha) al último."""
        data = self.words[0] | self.words[1] << 32
        return [(data >> (8 * digit)) & 0xFF for digit in range(self.digits)]
