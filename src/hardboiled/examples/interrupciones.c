/*
 * interrupciones.c — Un timer que interrumpe a la CPU.
 *
 * on_tick() es una rutina de interrupción: nadie la llama desde main(), la
 * dispara el hardware cada vez que vence el timer. main() duerme con wfi y
 * se despierta en cada interrupción.
 *
 * Probá:  hardboiled run interrupciones.c
 *         poné un breakpoint (F9) en on_tick y mirá la pila al detenerse.
 */
#include "hardboiled.h"

static volatile uint32_t ticks; /* volatile: la modifica la interrupción */

static void on_tick(void)
{
    ticks++;
    led_toggle(0);
}

int main(void)
{
    attach_irq(IRQ_TIMER0, on_tick);
    timer_start(50000, 1);
    interrupts_enable();

    while (ticks < 10) {
        wait_for_interrupt();
    }

    timer_stop();
    interrupts_disable();
    uart_puts("10 interrupciones atendidas\n");
    return (int)ticks;
}
