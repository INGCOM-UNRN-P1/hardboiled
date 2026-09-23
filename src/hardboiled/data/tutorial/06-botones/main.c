/* Lección 6 — Botones con interrupción. La consigna está en leccion.md. */
#include "hardboiled.h"

static volatile uint32_t pulsaciones[3];
static volatile int terminar;

void on_boton(void)
{
    /* TODO: averiguá qué botones se apretaron, limpiá sus flancos y contalos.
     * El botón 3 pide terminar. */
}

int main(void)
{
    /* TODO: registrá la ISR y habilitá la IRQ de los botones. Dormí hasta que
     * se apriete el botón 3, mostrando el total en los LEDs. */

    uint32_t total = pulsaciones[0] + pulsaciones[1] + pulsaciones[2];
    for (unsigned int i = 0; i < 3; i++) {
        uart_puts(i == 0 ? "b0=" : i == 1 ? " b1=" : " b2=");
        uart_putc((char)('0' + pulsaciones[i]));
    }
    uart_putc('\n');
    return (int)total;
}
