/*
 * demo.c — Demo interactiva: LEDs, switches, UART e interrupciones juntos.
 *
 * El LED 7 parpadea con la interrupción del timer, los LEDs 0-3 copian los
 * switches y la UART informa cada tick.
 *
 * Probá:  hardboiled demo
 */
#include "hardboiled.h"

static volatile uint32_t ticks;

static void on_tick(void)
{
    ticks++;
    led_toggle(7);
}

static void mirror_switches(void)
{
    uint32_t switches = switch_get();
    led_set((led_get() & 0x80u) | switches);
}

int main(void)
{
    uart_puts("hardboiled demo: mové los switches!\n");
    attach_irq(IRQ_TIMER0, on_tick);
    timer_start(250000, 1);
    interrupts_enable();

    uint32_t last = 0;
    for (;;) {
        wait_for_interrupt();
        mirror_switches();
        if (ticks != last) {
            last = ticks;
            uart_puts("tick ");
            uart_puthex(last);
            uart_putc('\n');
        }
    }
}
