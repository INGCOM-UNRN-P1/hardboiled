"""Puerto GPIO bidireccional con pull-ups, IRQ por pin y detección de cortocircuitos (qol.md #69).

Registros:
    +0x00 DIR      un bit por pin: 1 = salida, 0 = entrada
    +0x04 OUT      nivel que sacan los pines de salida
    +0x08 IN       sólo lectura: nivel actual de cada pin (salidas incluidas)
    +0x0C PULL     1 = pull-up: una entrada que nadie maneja lee 1 (sin pull-up, 0)
    +0x10 IRQ_EN   pines que piden la IRQ en su flanco
    +0x14 EDGE     por pin: 0 = flanco de subida, 1 = de bajada
    +0x18 PENDING  flancos detectados; escribir 1 limpia (y retira la IRQ)
    +0x1C SHORT    sólo lectura: pines en cortocircuito (una salida contra un nivel de afuera)

Desde afuera (la interfaz, el guion de entrada o un test) cada pin puede quedar suelto o manejado a
alto o bajo. Si el firmware lo configura como salida con el nivel contrario, hay cortocircuito: en
una placa real se quema el pin; acá se marca en SHORT y se avisa. Es la base del bit-banging (DHT22,
SPI por software) y reemplaza al par fijo de LEDs y switches en placas personalizadas.
"""

from __future__ import annotations

from collections.abc import Callable

from hardboiled.core.events import EvtHardwareUpdated, EvtMessage
from hardboiled.hardware import rebote
from hardboiled.hardware.bus import Peripheral, merge
from hardboiled.i18n import N_, _

DIR = 0x00
OUT = 0x04
IN = 0x08
PULL = 0x0C
IRQ_EN = 0x10
EDGE = 0x14
PENDING = 0x18
SHORT = 0x1C

# Ciclo de estados al hacer clic en un pin desde la interfaz.
SIGUIENTE_MANEJO = {None: 1, 1: 0, 0: None}


class GpioPort(Peripheral):
    kind = "gpio"
    size = 32

    def __init__(
        self,
        name: str,
        offset: int,
        width_bits: int = 8,
        irq_line: int | None = None,
        raise_irq: Callable[[int], None] | None = None,
        lower_irq: Callable[[int], None] | None = None,
        bounce_cycles: int = 0,
    ) -> None:
        super().__init__(name, offset, width_bits)
        self.bounce_cycles = bounce_cycles
        self._rebotes: rebote.Pendientes = []
        self.irq_line = irq_line
        self._raise_irq = raise_irq
        self._lower_irq = lower_irq
        self._mask = (1 << width_bits) - 1
        # Lo que maneja cada pin desde afuera (pin -> 0/1; ausente = suelto). Es "físico": sobrevive
        # a un reset de la placa, como la posición de un switch.
        self.external: dict[int, int] = {}
        self.reset()

    def reset(self) -> None:
        # Un rebote a mitad de camino termina en su nivel final (el reloj vuelve a 0).
        self.external.update(rebote.finales(self._rebotes))
        self._rebotes = []
        self.direction = 0
        self.out = 0
        self.pull = 0
        self.irq_enable = 0
        self.edge = 0
        self.pending = 0
        self.short = 0
        self.level = self._compute()[0]

    # ------------------------------------------------------------- niveles

    def _compute(self) -> tuple[int, int]:
        """(nivel de cada pin, pines en cortocircuito)."""
        level = short = 0
        for pin in range(self.width_bits):
            bit = 1 << pin
            driven = self.external.get(pin)
            if self.direction & bit:
                high = bool(self.out & bit)
                if driven is not None and driven != int(high):
                    short |= bit
            elif driven is not None:
                high = bool(driven)
            else:
                high = bool(self.pull & bit)  # suelto: el pull-up lo lleva a 1; sin él, 0
            if high:
                level |= bit
        return level, short

    def _update(self) -> None:
        level, short = self._compute()
        changed = level ^ self.level
        if changed:
            rising = changed & level
            falling = changed & ~level
            self.pending |= (rising & ~self.edge) | (falling & self.edge)
            self.level = level
            self.emit(EvtHardwareUpdated(self.name, IN, level))
        nuevos = short & ~self.short
        self.short = short
        if nuevos:
            pines = ", ".join(str(pin) for pin in range(self.width_bits) if nuevos >> pin & 1)
            self.emit(
                EvtMessage(
                    _(
                        "{device}: cortocircuito en el pin {pins}: el programa lo saca como "
                        "salida con un nivel y algo de afuera lo maneja con el otro (en una "
                        "placa real se quema el pin)",
                        device=self.name,
                        pins=pines,
                    )
                )
            )
        self._update_irq()

    def _update_irq(self) -> None:
        if self.irq_line is None:
            return
        if self.pending & self.irq_enable:
            if self._raise_irq is not None:
                self._raise_irq(self.irq_line)
        elif self._lower_irq is not None:
            self._lower_irq(self.irq_line)

    # ------------------------------------------------------------ estímulos

    def _check_pin(self, pin: int) -> None:
        if not 0 <= pin < self.width_bits:
            raise ValueError(_("{device} no tiene el pin {pin}", device=self.name, pin=pin))

    def drive(self, pin: int, level: int | None) -> None:
        """Maneja el pin desde afuera a `level` (0 o 1), o lo suelta con None."""
        self._check_pin(pin)
        if level is None:
            self.external.pop(pin, None)
            self._rebotes = [cambio for cambio in self._rebotes if cambio[1] != pin]
        else:
            nivel = 1 if level else 0
            if self.bounce_cycles and self.external.get(pin) != nivel:
                self._rebotes = rebote.programar(
                    self._rebotes, self.clock.cycles, pin, nivel, self.bounce_cycles
                )
            self.external[pin] = nivel
        self._update()

    def next_deadline(self) -> int | None:
        return rebote.proximo(self._rebotes)

    def service(self, cycle: int) -> None:
        hechos, self._rebotes = rebote.vencidos(self._rebotes, cycle)
        for _ciclo, pin, nivel in hechos:
            self.external[pin] = nivel
            self._update()  # uno por uno: cada flanco queda registrado

    def cycle_drive(self, pin: int) -> None:
        """Suelto → alto → bajo → suelto: lo que hace un clic en el pin desde la interfaz."""
        self._check_pin(pin)
        self.drive(pin, SIGUIENTE_MANEJO[self.external.get(pin)])

    def inspect(self) -> dict[str, int]:
        driven = high = 0
        for pin, level in self.external.items():
            driven |= 1 << pin
            high |= level << pin
        return {
            "dir": self.direction,
            "pull": self.pull,
            "pending": self.pending,
            "short": self.short,
            "driven": driven,
            "driven_high": high,
            "level": self.level,
        }

    def can_wake(self) -> bool:
        return bool(self.irq_enable) and self.irq_line is not None

    # ------------------------------------------------------------- registros

    def read(self, reg: int) -> int:
        values = {
            DIR: self.direction,
            OUT: self.out,
            IN: self.level,
            PULL: self.pull,
            IRQ_EN: self.irq_enable,
            EDGE: self.edge,
            PENDING: self.pending,
            SHORT: self.short,
        }
        if reg not in values:
            raise self.fault(reg, N_("registro inexistente"))
        return values[reg]

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == DIR:
            self.direction = merge(self.direction, value, mask) & self._mask
        elif reg == OUT:
            self.out = merge(self.out, value, mask) & self._mask
        elif reg == PULL:
            self.pull = merge(self.pull, value, mask) & self._mask
        elif reg == IRQ_EN:
            self.irq_enable = merge(self.irq_enable, value, mask) & self._mask
        elif reg == EDGE:
            self.edge = merge(self.edge, value, mask) & self._mask
        elif reg == PENDING:
            self.pending &= ~(value & mask)  # write-1-to-clear
        elif reg in (IN, SHORT):
            raise self.fault(reg, N_("IN y SHORT son de sólo lectura"))
        else:
            raise self.fault(reg, N_("registro inexistente"))
        self._update()
