/*
 * errores.c — Catálogo de errores que la placa detecta y explica.
 *
 * El valor de los switches elige el error. Con los switches en 0 se imprime
 * el menú.
 *
 * Probá:  hardboiled run errores.c --headless --switches 1
 *         hardboiled run errores.c   (poné los switches y apretá F5)
 */
#include "hardboiled.h"

static int profundidad(int n)
{
    volatile int buffer[16]; /* cada llamada ocupa 64 bytes más de pila */
    buffer[0] = n;
    return profundidad(n + 1) + buffer[0];
}

int main(void)
{
    switch (switch_get()) {
    case 1: { /* puntero nulo */
        volatile int *p = 0;
        return *p;
    }
    case 2: /* escribir en la Flash, que es de sólo lectura */
        *(volatile uint32_t *)0x00010000u = 1;
        return 0;
    case 3: /* recursión sin caso base: la pila se desborda */
        return profundidad(0);
    case 4: /* bucle infinito: se agota la cuota de instrucciones */
        for (;;) {
        }
    case 5: /* dirección sin memoria detrás */
        return *(volatile int *)0x30000000u;
    case 6: /* dormir sin ninguna interrupción que pueda despertarnos */
        wait_for_interrupt();
        return 0;
    default:
        uart_puts("Elegí un error con los switches:\n"
                  "  1 puntero nulo        2 escritura en Flash\n"
                  "  3 stack overflow      4 bucle infinito\n"
                  "  5 memoria inexistente 6 wfi sin interrupciones\n");
        return 0;
    }
}
