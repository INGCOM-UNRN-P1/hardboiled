/* hardboiled.ld — Linker script para la placa virtual hardboiled (RV32I).
 *
 * Mapa de memoria (ver board.toml):
 *   0x0000_0000 - 0x0000_FFFF  zona de trampa (punteros nulos)
 *   0x0001_0000 - 0x0001_FFFF  Flash: vectores, crt0, .text, .rodata, imagen de .data
 *   0x2000_0000 - 0x2000_FFFF  SRAM: .data, .bss, heap y pila (crece desde 0x2001_0000)
 *   0x4000_0000 - 0x4000_0FFF  MMIO (periféricos)
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00010000, LENGTH = 64K
    SRAM  (rw)  : ORIGIN = 0x20000000, LENGTH = 64K
}

__stack_top = ORIGIN(SRAM) + LENGTH(SRAM);

SECTIONS
{
    .text : ALIGN(4)
    {
        KEEP(*(.text.init))
        KEEP(*(.text.vectors))
        *(.text .text.*)
    } > FLASH

    .rodata : ALIGN(4)
    {
        *(.srodata .srodata.*)
        *(.rodata .rodata.*)
        . = ALIGN(4);
    } > FLASH

    .data : ALIGN(4)
    {
        __data_start = .;
        *(.sdata .sdata.*)
        *(.data .data.*)
        . = ALIGN(4);
        __data_end = .;
    } > SRAM AT > FLASH
    __data_load = LOADADDR(.data);

    .bss (NOLOAD) : ALIGN(4)
    {
        __bss_start = .;
        *(.sbss .sbss.*)
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > SRAM

    __global_pointer$ = __data_start + 0x800;
    _end = .;
    __heap_start = .;

    /DISCARD/ : { *(.eh_frame .eh_frame_hdr .note .note.*) }
}
