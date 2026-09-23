/* Cada valor de los switches selecciona un error distinto. */
#include "hardboiled.h"

int deep(int n)
{
    volatile int buffer[16];
    buffer[0] = n;
    return deep(n + 1) + buffer[0];
}

uint32_t not_code[4] = {0x00000013u, 0x00000013u, 0x00000013u, 0x00008067u};

int main(void)
{
    switch (switch_get()) {
    case 1: /* puntero nulo */
        return *(volatile int *)0;
    case 2: /* escritura en Flash */
        *(volatile uint32_t *)0x00010000u = 1;
        return 0;
    case 3: /* stack overflow */
        return deep(0);
    case 4: /* bucle infinito */
        for (;;) {
        }
    case 5: /* registro MMIO inexistente */
        HB_REG(0x100) = 1;
        return 0;
    case 6: /* escritura en registro de sólo lectura */
        SWITCHES = 1;
        return 0;
    case 7: /* memoria no mapeada */
        return *(volatile int *)0x30000000u;
    case 8: /* wfi sin interrupciones habilitadas */
        wait_for_interrupt();
        return 0;
    case 9: /* ejecutar datos de la SRAM */
        return ((int (*)(void))(uintptr_t)not_code)();
    case 10: { /* acceso desalineado: la dirección se calcula en ejecución */
        uintptr_t address = (uintptr_t)&not_code[0] + (switch_get() - 9); /* +1 */
        return *(volatile int *)address;
    }
    case 11: { /* división por cero: RISC-V no la atrapa */
        volatile int dividendo = 10;
        int divisor = (int)switch_get() - 11;
        return dividendo / divisor; /* @div0 */
    }
    default:
        return 0;
    }
}
