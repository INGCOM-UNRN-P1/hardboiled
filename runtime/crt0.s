# crt0.s — Código de arranque de hardboiled (RV32I bare-metal).
#
# 1. Inicializa gp y sp (sp = __stack_top = 0x20010000).
# 2. Copia .data desde Flash (LMA) a SRAM (VMA).
# 3. Pone en cero .bss.
# 4. Llama a main() y, al volver, detiene la CPU con `ebreak` (a0 = código de salida).
#
# También define la tabla de vectores de interrupción. El emulador, al atender
# la IRQ n, guarda el contexto en la pila y salta a __vector_table[n]; cada
# entrada busca el handler registrado con attach_irq() y termina con `mret`,
# que el emulador intercepta para restaurar el contexto.

    .equ HB_IRQ_LINES, 8

    .section .text.init, "ax"
    .globl _start
_start:
    .option push
    .option norelax
    la      gp, __global_pointer$
    .option pop
    la      sp, __stack_top

    # Copia de .data (Flash -> SRAM)
    la      t0, __data_load
    la      t1, __data_start
    la      t2, __data_end
1:  bgeu    t1, t2, 2f
    lw      t3, 0(t0)
    sw      t3, 0(t1)
    addi    t0, t0, 4
    addi    t1, t1, 4
    j       1b

    # Limpieza de .bss
2:  la      t1, __bss_start
    la      t2, __bss_end
3:  bgeu    t1, t2, 4f
    sw      zero, 0(t1)
    addi    t1, t1, 4
    j       3b

4:  call    main

    .globl _exit
_exit:
    ebreak
    j       _exit

# ---------------------------------------------------------------------------
# Tabla de vectores e entradas de interrupción
# ---------------------------------------------------------------------------
    .section .text.vectors, "ax"
    .balign 4
    .globl __vector_table
__vector_table:
    .word   __irq_entry0
    .word   __irq_entry1
    .word   __irq_entry2
    .word   __irq_entry3
    .word   __irq_entry4
    .word   __irq_entry5
    .word   __irq_entry6
    .word   __irq_entry7

__irq_entry0: li t0, 0
    j       __irq_dispatch
__irq_entry1: li t0, 1
    j       __irq_dispatch
__irq_entry2: li t0, 2
    j       __irq_dispatch
__irq_entry3: li t0, 3
    j       __irq_dispatch
__irq_entry4: li t0, 4
    j       __irq_dispatch
__irq_entry5: li t0, 5
    j       __irq_dispatch
__irq_entry6: li t0, 6
    j       __irq_dispatch
__irq_entry7: li t0, 7
    j       __irq_dispatch

# El emulador ya salvó ra, t0-t6 y a0-a7: se pueden usar libremente.
__irq_dispatch:
    la      t1, __irq_handlers
    slli    t0, t0, 2
    add     t1, t1, t0
    lw      t1, 0(t1)
    beqz    t1, 1f
    jalr    t1
1:  mret

# Handlers registrados por attach_irq() (se ponen en cero junto con .bss).
    .section .bss.irq_handlers, "aw", @nobits
    .balign 4
    .globl __irq_handlers
__irq_handlers:
    .space  4 * HB_IRQ_LINES
