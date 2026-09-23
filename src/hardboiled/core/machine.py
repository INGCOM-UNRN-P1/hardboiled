"""Ensamblado de la placa: CPU + bus MMIO + periféricos + PIC + depurador."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hardboiled.config import BoardConfig
from hardboiled.core.cpu import Cpu, CpuSnapshot
from hardboiled.core.debugger import Debugger
from hardboiled.core.dwarf import LineTable
from hardboiled.core.elf import ElfImage
from hardboiled.core.events import PeripheralInfo
from hardboiled.core.pic import InterruptController
from hardboiled.core.unwind import CallFrameTable
from hardboiled.core.variables import VariableTable
from hardboiled.hardware import MmioBus, Peripheral, SwitchBank, build_peripheral
from hardboiled.hardware.bus import EventSink


@dataclass(frozen=True)
class MachineSnapshot:
    cpu: CpuSnapshot
    devices: dict[str, dict[str, Any]]


class Machine:
    def __init__(
        self,
        image: ElfImage,
        lines: LineTable,
        board: BoardConfig,
        cfi: CallFrameTable | None = None,
        variables: VariableTable | None = None,
    ) -> None:
        self.image = image
        self.lines = lines
        self.board = board
        self.bus = MmioBus(board.memory.mmio_size)
        self.pic = InterruptController(offset=board.pic.offset)
        self.bus.attach(self.pic)
        for cfg in board.peripherals:
            self.bus.attach(
                build_peripheral(
                    cfg.type, cfg.name, cfg.offset, cfg.width_bits, cfg.irq_line, self.pic.raise_irq
                )
            )
        self.cpu = Cpu(
            board.memory,
            self.bus,
            self.pic,
            board.board.max_instructions,
            board.board.clock_hz,
        )
        self.cpu.load(image)
        self.debugger = Debugger(self.cpu, image, lines, cfi, variables)

    @classmethod
    def from_elf(cls, elf_path: str | Path, board: BoardConfig | None = None) -> Machine:
        return cls(
            ElfImage.load(elf_path),
            LineTable.from_elf(elf_path),
            board or BoardConfig(),
            CallFrameTable.from_elf(elf_path),
            VariableTable.from_elf(elf_path),
        )

    @property
    def peripherals(self) -> tuple[Peripheral, ...]:
        return tuple(dev for dev in self.bus.devices if dev is not self.pic)

    def peripheral_info(self) -> tuple[PeripheralInfo, ...]:
        return tuple(
            PeripheralInfo(dev.name, dev.kind, dev.offset, dev.width_bits)
            for dev in self.peripherals
        )

    def switches(self) -> SwitchBank | None:
        for dev in self.peripherals:
            if isinstance(dev, SwitchBank):
                return dev
        return None

    def set_event_sink(self, sink: EventSink) -> None:
        self.bus.set_event_sink(sink)

    def reset(self) -> None:
        self.cpu.reset()

    def snapshot(self) -> MachineSnapshot:
        """Instantánea completa: CPU, memoria y estado de cada periférico (incluido el PIC)."""
        return MachineSnapshot(
            self.cpu.snapshot(), {dev.name: dev.snapshot() for dev in self.bus.devices}
        )

    def restore(self, snap: MachineSnapshot) -> None:
        for dev in self.bus.devices:
            state = snap.devices.get(dev.name)
            if state is not None:
                dev.restore(state)
        self.cpu.restore(snap.cpu)
