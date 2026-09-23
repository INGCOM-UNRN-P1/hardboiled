"""Bus MMIO, periféricos, PIC, interrupciones y esquema de la placa."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hardboiled.config import BoardConfig, load_board
from hardboiled.core.cpu import StopReason
from hardboiled.core.events import Event, EvtHardwareUpdated, EvtUartOutput
from hardboiled.core.pic import InterruptController
from hardboiled.hardware import LedBar, MmioBus, MmioFault, SwitchBank, Timer, Uart
from tests.conftest import MachineFactory, line_of

ROOT = Path(__file__).parents[1]

# ------------------------------------------------------------------ bus


def make_bus() -> tuple[MmioBus, list[Event]]:
    bus = MmioBus(0x1000)
    events: list[Event] = []
    bus.set_event_sink(events.append)
    bus.attach(LedBar("leds", 0x00, 8))
    bus.attach(SwitchBank("switches", 0x04, 4))
    bus.attach(Uart("uart0", 0x10))
    return bus, events


def test_bus_word_and_subword_access() -> None:
    bus, events = make_bus()
    bus.write(0x00, 4, 0x1234_5681)
    assert bus.read(0x00, 4) == 0x81  # sólo 8 LEDs
    bus.write(0x00, 1, 0x0F)
    assert bus.read(0x00, 1) == 0x0F
    assert bus.read(0x00, 2) == 0x0F
    assert [e.value for e in events if isinstance(e, EvtHardwareUpdated)] == [0x81, 0x0F]


def test_bus_rejects_unmapped_and_misaligned() -> None:
    bus, _ = make_bus()
    with pytest.raises(MmioFault, match="ningún periférico"):
        bus.read(0x800, 4)
    with pytest.raises(MmioFault, match="desalineado"):
        bus.read(0x02, 4)


def test_bus_rejects_overlapping_devices() -> None:
    bus, _ = make_bus()
    with pytest.raises(ValueError, match="superpone"):
        bus.attach(Timer("timer0", 0x0C))


def test_led_emits_only_on_change() -> None:
    bus, events = make_bus()
    bus.write(0x00, 4, 5)
    bus.write(0x00, 4, 5)
    assert events == [EvtHardwareUpdated("leds", 0, 5)]


def test_switches_are_read_only() -> None:
    bus, events = make_bus()
    switches = bus.device("switches")
    assert isinstance(switches, SwitchBank)
    switches.toggle(2)
    assert bus.read(0x04, 4) == 0b0100
    assert events[-1] == EvtHardwareUpdated("switches", 0, 0b0100)
    with pytest.raises(MmioFault, match="sólo lectura"):
        bus.write(0x04, 4, 1)
    with pytest.raises(ValueError):
        switches.toggle(4)


def test_uart_transmits_bytes() -> None:
    bus, events = make_bus()
    assert bus.read(0x14, 4) & 1  # TX listo
    for char in b"ok":
        bus.write(0x10, 1, char)
    assert [e.char_code for e in events if isinstance(e, EvtUartOutput)] == list(b"ok")


# ---------------------------------------------------------- timer + PIC


def test_timer_raises_periodic_irq() -> None:
    raised: list[int] = []
    timer = Timer("timer0", 0x20, irq_line=2, raise_irq=raised.append)
    timer.write(0x4, 100, 0xFFFF_FFFF)  # RELOAD
    timer.write(0x0, 0b11, 0xFFFF_FFFF)  # ENABLE | IRQ
    assert timer.next_deadline() == 100
    timer.clock.cycles = 40
    assert timer.read(0x8) == 60  # COUNT
    timer.service(250)
    assert raised == [2]
    assert timer.expirations == 2
    assert timer.next_deadline() == 300
    assert timer.read(0xC) == 1
    timer.write(0xC, 1, 0xFFFF_FFFF)  # write-1-to-clear
    assert timer.read(0xC) == 0
    timer.write(0x0, 0, 0xFFFF_FFFF)
    assert timer.next_deadline() is None


def test_pic_masks_and_priorities() -> None:
    pic = InterruptController()
    pic.raise_irq(3)
    pic.raise_irq(1)
    assert not pic.ready  # nada habilitado
    pic.write(0x0, 0b1010, 0xFF)  # ENABLE
    assert not pic.ready  # falta el habilitador global
    pic.write(0x8, 1, 0xFF)
    assert pic.ready
    assert pic.next_irq() == 1  # la línea más baja tiene prioridad
    pic.acknowledge(1)
    assert pic.in_isr and not pic.ready  # sin anidamiento
    pic.complete()
    assert pic.ready and pic.next_irq() == 3
    pic.write(0x4, 0b1000, 0xFF)  # limpiar PENDING
    assert not pic.ready


# ---------------------------------------------------------- integración


def test_firmware_drives_peripherals(make_machine: MachineFactory) -> None:
    machine, events = make_machine("mmio", switches=0b0101)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED
    assert stop.exit_code == 3 + 100 * 5  # 3 ticks del timer + switches

    uart = bytes(e.char_code for e in events if isinstance(e, EvtUartOutput))
    assert uart == b"hola\n0x00000005\n"

    leds = [
        e.value for e in events if isinstance(e, EvtHardwareUpdated) and e.device_name == "leds"
    ]
    # led_set(0x0F), escritura de 8 bits 0x35 y tres toggles del LED 7 desde la ISR.
    assert leds == [0x0F, 0x35, 0xB5, 0x35, 0xB5]
    timer = machine.bus.device("timer0")
    assert isinstance(timer, Timer) and timer.expirations >= 3


def test_breakpoint_inside_isr(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("mmio")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
    stop = debugger.continue_()
    assert stop.reason is StopReason.BREAK
    assert debugger.function() == "on_timer"
    assert machine.pic.in_isr and machine.pic.active_line == 0
    # Stepping dentro de la ISR y salida por mret de vuelta a main.
    for _ in range(10):
        debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
        debugger.step_over()
        debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
        if not machine.pic.in_isr:
            break
    assert not machine.pic.in_isr
    # Se vuelve al punto interrumpido: el bucle de main o el wfi dentro de wait_for_interrupt().
    assert debugger.function() in {"main", "wait_for_interrupt"}


def test_isr_preserves_interrupted_context(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("mmio")
    debugger = machine.debugger
    cpu = machine.cpu
    debugger.toggle_line_breakpoint(line_of("mmio.c", "wait_loop"), "mmio.c")
    debugger.continue_()
    ticks = machine.image.symbol_address("ticks")
    assert ticks is not None
    before = cpu.registers()
    ticks_before = cpu.read_memory(ticks, 4)

    # Forzar una IRQ antes de la próxima instrucción y volver al mismo PC.
    machine.pic.raise_irq(0)
    stop = debugger.run_to(before["pc"])
    assert stop.reason is StopReason.BREAK
    assert cpu.read_memory(ticks, 4) != ticks_before  # la ISR se ejecutó
    assert cpu.registers() == before  # ...y el contexto quedó intacto
    assert not machine.pic.in_isr


def test_step_over_is_not_hijacked_by_interrupts(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("mmio")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("mmio.c", "wait_loop"), "mmio.c")
    debugger.continue_()
    debugger.toggle_line_breakpoint(line_of("mmio.c", "wait_loop"), "mmio.c")
    return_line = line_of("mmio.c", "mmio_return")
    visited: list[int] = []
    # Tres vueltas del while (una por tick del timer) y salida del bucle: nunca dentro de la ISR.
    while len(visited) < 20 and (not visited or visited[-1] < return_line):
        assert debugger.step_over().reason is StopReason.BREAK
        assert debugger.function() == "main"
        assert not machine.pic.in_isr
        location = debugger.location()
        assert location is not None
        visited.append(location.line)
    assert visited[-1] == return_line
    assert visited.count(line_of("mmio.c", "wait_loop") + 1) == 3  # un wfi por tick
    assert machine.pic.read(0x8) == 0  # se ejecutó interrupts_disable()


# ---------------------------------------------------------------- placa


def test_default_board_toml_is_valid() -> None:
    board = load_board(ROOT / "board.toml")
    assert board.board.name == "lab-rv32-basics"
    assert board.board.max_instructions == 5_000_000
    assert board.memory.mmio_base == 0x4000_0000
    assert [p.name for p in board.peripherals] == ["leds", "switches", "uart0", "timer0"]
    assert board.peripherals[3].irq_line == 0


def test_board_rejects_overlapping_peripherals() -> None:
    with pytest.raises(ValidationError, match="se superponen"):
        BoardConfig.model_validate(
            {
                "peripherals": [
                    {"name": "a", "type": "timer", "offset": "0x20"},
                    {"name": "b", "type": "uart", "offset": "0x28"},
                ]
            }
        )


def test_board_rejects_irq_on_non_timer_and_bad_memory() -> None:
    with pytest.raises(ValidationError, match="sólo generan interrupciones"):
        BoardConfig.model_validate(
            {"peripherals": [{"name": "l", "type": "gpio_out", "offset": 0, "irq_line": 1}]}
        )
    with pytest.raises(ValidationError, match="puntero"):
        BoardConfig.model_validate({"memory": {"flash_base": "0x0"}})
    with pytest.raises(ValidationError, match="entero inválido"):
        BoardConfig.model_validate({"memory": {"sram_base": "cero"}})
