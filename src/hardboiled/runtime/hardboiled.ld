/* hardboiled.ld — Linker script para la placa 'lab-rv32-basics' (RV32I).
 * Generado a partir de board.toml con `hardboiled gen-header --linker-script`.
 *
 * Mapa de memoria:
 *   0x0000_0000 - 0x0000_FFFF  zona de trampa (punteros nulos)
 *   0x00010000 (64 KB)  Flash: vectores, crt0, .text, .rodata, .data
 *   0x20000000 (64 KB)  SRAM: .data, .bss, heap y pila (desde el final)
 *   0x40000000 (4 KB)  MMIO (periféricos)
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
