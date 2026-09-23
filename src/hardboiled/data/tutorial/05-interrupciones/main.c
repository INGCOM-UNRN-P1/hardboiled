/* Lección 5 — Interrupciones. La consigna está en leccion.md. */
#include "hardboiled.h"

#define PERIODO 20000u
#define TICKS 8

static volatile int ticks;

void on_tick(void)
{
    /* TODO: contá el tick. */
}

int main(void)
{
    /* TODO: registrá la ISR, arrancá el timer con IRQ y habilitá las
     * interrupciones. Después dormí hasta TICKS, mostrando la cuenta. */

    uart_puts("ticks: ");
    uart_putc((char)('0' + ticks));
    uart_putc('\n');
    return ticks;
}
