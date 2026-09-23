"""Genera el SDK (hardboiled.h) y el linker script a partir de una placa.

Así los offsets del SDK nunca quedan desincronizados de `board.toml`: el
header empaquetado es exactamente la salida de este generador para la placa
por defecto (un test lo verifica), y `hardboiled build` genera uno propio
cuando el proyecto usa otra placa.

El primer periférico de cada tipo recibe los nombres "clásicos" del SDK
(LEDS/led_set, SWITCHES/switch_get, UART_TX/uart_putc, TIMER_CTRL/timer_start…);
los siguientes usan su nombre de board.toml (BEDS/beds_set, UART1_TX/uart1_putc).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from hardboiled.config import BoardConfig, PeripheralConfig
from hardboiled.core.pic import IRQ_LINES
from hardboiled.toolchain import RuntimeFiles

# Prefijos de macro y de función del primer periférico de cada tipo.
CLASSIC = {
    "gpio_out": ("LEDS", "led"),
    "gpio_in": ("SWITCHES", "switch"),
    "uart": ("UART", "uart"),
    "timer": ("TIMER", "timer"),
    "gpio_irq": ("BUTTONS", "button"),
    "sevenseg": ("SEG", "seg"),
}


def _identifier(name: str) -> str:
    return re.sub(r"\W", "_", name)


@dataclass(frozen=True)
class Naming:
    macro: str  # "LEDS", "UART1"
    function: str  # "led", "uart1"


def _names(board: BoardConfig) -> dict[str, Naming]:
    seen: set[str] = set()
    names: dict[str, Naming] = {}
    for peripheral in board.peripherals:
        if peripheral.type not in seen:
            seen.add(peripheral.type)
            macro, function = CLASSIC[peripheral.type]
        else:
            macro, function = _identifier(peripheral.name).upper(), _identifier(peripheral.name)
        names[peripheral.name] = Naming(macro, function)
    return names


# --------------------------------------------------------------- registros


def _registers(p: PeripheralConfig, n: Naming) -> list[tuple[str, int, str]]:
    """(macro, offset, descripción) de cada registro."""
    if p.type == "gpio_out":
        return [(n.macro, p.offset, f"escritura/lectura: un bit por LED ({p.width_bits})")]
    if p.type == "gpio_in":
        return [(n.macro, p.offset, f"sólo lectura: un bit por interruptor ({p.width_bits})")]
    if p.type == "sevenseg":
        registers = [(f"{n.macro}_DIGITS", p.offset, f"segmentos de los dígitos 0-3 ({p.digits})")]
        if p.digits > 4:
            registers.append((f"{n.macro}_DIGITS_HI", p.offset + 4, "segmentos de los dígitos 4-7"))
        return registers
    if p.type == "gpio_irq":
        return [
            (f"{n.macro}_STATE", p.offset, f"sólo lectura: botones presionados ({p.width_bits})"),
            (f"{n.macro}_IRQ_EN", p.offset + 4, "máscara de botones que piden la IRQ"),
            (f"{n.macro}_EDGE", p.offset + 8, "por botón: 0 = al presionar, 1 = al soltar"),
            (f"{n.macro}_PENDING", p.offset + 12, "flancos detectados (escribir 1 limpia)"),
        ]
    if p.type == "uart":
        return [
            (f"{n.macro}_TX", p.offset, "escritura: byte a transmitir"),
            (f"{n.macro}_STATUS", p.offset + 4, "bit 0 = listo para transmitir, bit 1 = hay dato"),
            (f"{n.macro}_RX", p.offset + 8, "lectura: siguiente byte recibido"),
            (f"{n.macro}_CTRL", p.offset + 12, "bit 0 = IRQ mientras haya bytes recibidos"),
        ]
    return [
        (f"{n.macro}_CTRL", p.offset, "bit 0 = habilitado, bit 1 = genera IRQ"),
        (f"{n.macro}_RELOAD", p.offset + 4, "período en ciclos (divisor)"),
        (f"{n.macro}_COUNT", p.offset + 8, "ciclos restantes hasta el próximo vencimiento"),
        (f"{n.macro}_STATUS", p.offset + 12, "bit 0 = venció (escribir 1 para limpiar)"),
    ]


def _pic_registers(board: BoardConfig) -> list[tuple[str, int, str]]:
    base = board.pic.offset
    return [
        ("PIC_ENABLE", base, "máscara de IRQs habilitadas"),
        ("PIC_PENDING", base + 4, "IRQs pendientes (escribir 1 para limpiar)"),
        ("PIC_GLOBAL", base + 8, "bit 0 = interrupciones habilitadas globalmente"),
    ]


# ----------------------------------------------------------------- helpers


def _helpers(p: PeripheralConfig, n: Naming) -> str:
    f, m = n.function, n.macro
    if p.type == "gpio_out":
        return f"""\
static inline void {f}_set(uint32_t mask) {{ {m} = mask; }}
static inline uint32_t {f}_get(void) {{ return {m}; }}
static inline void {f}_on(unsigned int index) {{ {m} = {m} | (1u << index); }}
static inline void {f}_off(unsigned int index) {{ {m} = {m} & ~(1u << index); }}
static inline void {f}_toggle(unsigned int index) {{ {m} = {m} ^ (1u << index); }}
"""
    if p.type == "gpio_in":
        return f"""\
static inline uint32_t {f}_get(void) {{ return {m}; }}
static inline int {f}_read(unsigned int index) {{ return (int)(({m} >> index) & 1u); }}
"""
    if p.type == "sevenseg":
        return f"""\
#define {m}_COUNT {p.digits}

/* Segmentos (a-g en los bits 0-6, punto en el 7) que dibujan la cifra hexadecimal `digit`. */
static inline uint8_t {f}_pattern(unsigned int digit)
{{
    static const uint8_t font[16] = {{
        0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
        0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71,
    }};
    return font[digit & 0xFu];
}}

/* Enciende los segmentos `segments` del dígito `index` (0 = el de la derecha). */
static inline void {f}_set_digit(unsigned int index, uint8_t segments)
{{
    volatile uint8_t *digits = (volatile uint8_t *)&{m}_DIGITS;
    digits[index] = segments;
}}

/* Muestra `value` en hexadecimal (los dígitos que entren). */
static inline void {f}_show_hex(uint32_t value)
{{
    for (unsigned int i = 0; i < {m}_COUNT; i++) {{
        {f}_set_digit(i, {f}_pattern(value >> (4 * i)));
    }}
}}

/* Muestra `value` en decimal, sin ceros a la izquierda. */
static inline void {f}_show_dec(uint32_t value)
{{
    for (unsigned int i = 0; i < {m}_COUNT; i++) {{
        int blank = value == 0 && i > 0;
        {f}_set_digit(i, blank ? 0 : {f}_pattern(value % 10u));
        value /= 10u;
    }}
}}

static inline void {f}_clear(void) {{ {m}_DIGITS = 0; }}
"""
    if p.type == "gpio_irq":
        return f"""\
static inline uint32_t {f}s_get(void) {{ return {m}_STATE; }}
static inline int {f}_read(unsigned int index) {{ return (int)(({m}_STATE >> index) & 1u); }}

/* Pide la IRQ cuando se presionan los botones de `mask` (flanco de subida). */
static inline void {f}_irq_enable(uint32_t mask) {{ {m}_IRQ_EN = {m}_IRQ_EN | mask; }}
static inline void {f}_irq_disable(uint32_t mask) {{ {m}_IRQ_EN = {m}_IRQ_EN & ~mask; }}

/* Flancos detectados desde la última limpieza (un bit por botón). */
static inline uint32_t {f}s_pending(void) {{ return {m}_PENDING; }}
static inline void {f}s_clear(uint32_t mask) {{ {m}_PENDING = mask; }}
"""
    if p.type == "uart":
        return f"""\
static inline void {f}_putc(char c)
{{
    while (({m}_STATUS & UART_STATUS_READY) == 0) {{
    }}
    {m}_TX = (uint32_t)(unsigned char)c;
}}

static inline void {f}_puts(const char *text)
{{
    while (*text != '\\0') {{
        {f}_putc(*text);
        text++;
    }}
}}

/* ¿Llegó algún byte por la UART? */
static inline int {f}_available(void) {{ return ({m}_STATUS & UART_STATUS_RX) != 0; }}

/* Espera (activamente) el siguiente byte recibido. */
static inline char {f}_getc(void)
{{
    while (!{f}_available()) {{
    }}
    return (char){m}_RX;
}}

/* Lee hasta fin de línea o `size - 1` bytes; devuelve la cantidad leída. */
static inline int {f}_gets(char *buffer, int size)
{{
    int count = 0;
    while (count < size - 1) {{
        char c = {f}_getc();
        if (c == '\\n' || c == '\\r') {{
            break;
        }}
        buffer[count++] = c;
    }}
    buffer[count] = '\\0';
    return count;
}}

/* Pide (o deja de pedir) la IRQ de la UART mientras haya bytes recibidos. */
static inline void {f}_rx_irq(int enabled) {{ {m}_CTRL = enabled ? 1u : 0u; }}

/* Imprime un entero sin signo en hexadecimal (sin usar división). */
static inline void {f}_puthex(uint32_t value)
{{
    static const char digits[] = "0123456789abcdef";
    {f}_puts("0x");
    for (int shift = 28; shift >= 0; shift -= 4) {{
        {f}_putc(digits[(value >> shift) & 0xFu]);
    }}
}}
"""
    return f"""\
static inline void {f}_start(uint32_t period_cycles, int with_irq)
{{
    {m}_RELOAD = period_cycles;
    {m}_CTRL = TIMER_CTRL_ENABLE | (with_irq ? TIMER_CTRL_IRQ : 0u);
}}

static inline void {f}_stop(void) {{ {m}_CTRL = 0; }}
static inline int {f}_expired(void) {{ return (int)({m}_STATUS & 1u); }}
static inline void {f}_clear(void) {{ {m}_STATUS = 1u; }}
"""


SECTION_TITLES = {
    "gpio_irq": "Botones",
    "sevenseg": "Display de 7 segmentos",
    "gpio_out": "LEDs",
    "gpio_in": "Switches",
    "uart": "UART",
    "timer": "Timer",
}


def _grouped(address: int) -> str:
    """0x40000000 -> 0x4000_0000."""
    return f"0x{address >> 16:04X}_{address & 0xFFFF:04X}"


def _section(title: str) -> str:
    return f"/* {'-' * (70 - len(title))} {title} --- */"


# ------------------------------------------------------------------ header


def generate_header(board: BoardConfig) -> str:
    names = _names(board)
    registers: list[tuple[str, int, str]] = []
    for peripheral in board.peripherals:
        registers += _registers(peripheral, names[peripheral.name])
    registers += _pic_registers(board)
    width = max(len(macro) for macro, _, _ in registers)
    kinds = {p.type for p in board.peripherals}

    doc = [
        "/*",
        " * hardboiled.h — SDK pedagógico para la placa virtual hardboiled (RV32I).",
        " *",
        f" * Generado a partir de la placa '{board.board.name}' con `hardboiled gen-header`.",
        " * Encapsula los registros de E/S mapeados en memoria (MMIO) y ofrece",
        " * funciones simples para los periféricos y las interrupciones.",
        " *",
        f" * Mapa MMIO (base {_grouped(board.memory.mmio_base)}):",
    ]
    doc += [f" *   0x{offset:03X}  {macro:<{width}} {text}" for macro, offset, text in registers]
    doc.append(" */")

    out = [*doc, "#ifndef HARDBOILED_H", "#define HARDBOILED_H", "", "#include <stdint.h>", ""]
    out += [
        f"#define HB_MMIO_BASE 0x{board.memory.mmio_base:08X}u",
        "#define HB_REG(offset) (*(volatile uint32_t *)(HB_MMIO_BASE + (offset)))",
        "",
    ]
    out += [f"#define {macro:<{width}} HB_REG(0x{offset:03X})" for macro, offset, _ in registers]
    out.append("")
    if "timer" in kinds:
        out += ["#define TIMER_CTRL_ENABLE (1u << 0)", "#define TIMER_CTRL_IRQ    (1u << 1)"]
    if "uart" in kinds:
        out += ["#define UART_STATUS_READY (1u << 0)", "#define UART_STATUS_RX    (1u << 1)"]
    out += ["", f"#define HB_IRQ_LINES {IRQ_LINES}"]
    for peripheral in board.peripherals:
        if peripheral.irq_line is not None:
            out.append(f"#define IRQ_{_identifier(peripheral.name).upper()} {peripheral.irq_line}")
    out += [
        "",
        "typedef void (*irq_handler_t)(void);",
        "",
        "/* Tabla de handlers definida en crt0.s. */",
        "extern volatile irq_handler_t __irq_handlers[HB_IRQ_LINES];",
        "",
    ]
    for peripheral in board.peripherals:
        naming = names[peripheral.name]
        title = SECTION_TITLES[peripheral.type]
        if naming.macro != CLASSIC[peripheral.type][0]:
            title = f"{title} ({peripheral.name})"
        out += [_section(title), "", _helpers(peripheral, naming)]
    out += [
        _section("Interrupciones"),
        "",
        """\
static inline void attach_irq(unsigned int line, irq_handler_t handler)
{
    __irq_handlers[line] = handler;
    PIC_ENABLE = PIC_ENABLE | (1u << line);
}

static inline void detach_irq(unsigned int line)
{
    PIC_ENABLE = PIC_ENABLE & ~(1u << line);
    __irq_handlers[line] = 0;
}

static inline void interrupts_enable(void) { PIC_GLOBAL = 1u; }
static inline void interrupts_disable(void) { PIC_GLOBAL = 0u; }

/* Duerme la CPU hasta que llegue una interrupción habilitada. */
static inline void wait_for_interrupt(void) { __asm__ volatile("wfi"); }
""",
        "#endif /* HARDBOILED_H */",
        "",
    ]
    return "\n".join(out)


# ----------------------------------------------------------- linker script


def generate_linker_script(board: BoardConfig) -> str:
    mem = board.memory
    return f"""\
/* hardboiled.ld — Linker script para la placa '{board.board.name}' (RV32I).
 * Generado a partir de board.toml con `hardboiled gen-header --linker-script`.
 *
 * Mapa de memoria:
 *   0x0000_0000 - 0x0000_FFFF  zona de trampa (punteros nulos)
 *   0x{mem.flash_base:08X} ({mem.flash_size_kb} KB)  Flash: vectores, crt0, .text, .rodata, .data
 *   0x{mem.sram_base:08X} ({mem.sram_size_kb} KB)  SRAM: .data, .bss, heap y pila (desde el final)
 *   0x{mem.mmio_base:08X} ({mem.mmio_size_kb} KB)  MMIO (periféricos)
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{{
    FLASH (rx)  : ORIGIN = 0x{mem.flash_base:08X}, LENGTH = {mem.flash_size_kb}K
    SRAM  (rw)  : ORIGIN = 0x{mem.sram_base:08X}, LENGTH = {mem.sram_size_kb}K
}}

__stack_top = ORIGIN(SRAM) + LENGTH(SRAM);

SECTIONS
{{
    .text : ALIGN(4)
    {{
        KEEP(*(.text.init))
        KEEP(*(.text.vectors))
        *(.text .text.*)
    }} > FLASH

    .rodata : ALIGN(4)
    {{
        *(.srodata .srodata.*)
        *(.rodata .rodata.*)
        . = ALIGN(4);
    }} > FLASH

    .data : ALIGN(4)
    {{
        __data_start = .;
        *(.sdata .sdata.*)
        *(.data .data.*)
        . = ALIGN(4);
        __data_end = .;
    }} > SRAM AT > FLASH
    __data_load = LOADADDR(.data);

    .bss (NOLOAD) : ALIGN(4)
    {{
        __bss_start = .;
        *(.sbss .sbss.*)
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    }} > SRAM

    __global_pointer$ = __data_start + 0x800;
    _end = .;
    __heap_start = .;

    /DISCARD/ : {{ *(.eh_frame .eh_frame_hdr .note .note.*) }}
}}
"""


def runtime_for(board: BoardConfig, cache_root: Path) -> RuntimeFiles:
    """Runtime (include, linker script, crt0) para `board`.

    Si la placa genera exactamente el SDK empaquetado se usa el empaquetado; si
    no, se generan header y linker script en la caché (por contenido).
    """
    header = generate_header(board)
    linker = generate_linker_script(board)
    packaged = RuntimeFiles.packaged()
    if header == packaged.include_dir.joinpath("hardboiled.h").read_text(
        encoding="utf-8"
    ) and linker == packaged.linker_script.read_text(encoding="utf-8"):
        return packaged
    digest = hashlib.sha256((header + linker).encode()).hexdigest()[:16]
    directory = cache_root / "sdk" / digest
    (directory / "include").mkdir(parents=True, exist_ok=True)
    (directory / "include" / "hardboiled.h").write_text(header, encoding="utf-8")
    (directory / "hardboiled.ld").write_text(linker, encoding="utf-8")
    return RuntimeFiles(directory / "include", directory / "hardboiled.ld", packaged.crt0)
