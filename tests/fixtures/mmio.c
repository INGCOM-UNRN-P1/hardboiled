/* Periféricos: LEDs, switches, UART, timer e interrupciones. */
#include "hardboiled.h"

volatile int ticks = 0;

void on_timer(void)
{
    ticks++; /* @isr_body */
    led_toggle(7);
}

int main(void)
{
    uart_puts("hola\n");
    led_set(0x0F); /* @leds_0f */
    *(volatile uint8_t *)&LEDS = 0x35; /* acceso de 8 bits */

    attach_irq(IRQ_TIMER0, on_timer);
    timer_start(500, 1);
    interrupts_enable();
    while (ticks < 3) { /* @wait_loop */
        wait_for_interrupt();
    }
    timer_stop();
    interrupts_disable();

    uart_puthex(switch_get());
    uart_putc('\n');
    return ticks + 100 * (int)switch_get(); /* @mmio_return */
}
