#include "hardboiled.h"

#define PERIODO 20000u
#define TICKS 8

static volatile int ticks;

void on_tick(void)
{
    ticks++;
}

int main(void)
{
    attach_irq(IRQ_TIMER0, on_tick);
    timer_start(PERIODO, 1);
    interrupts_enable();
    while (ticks < TICKS) {
        wait_for_interrupt();
        seg_show_dec((uint32_t)ticks);
    }
    timer_stop();
    interrupts_disable();
    uart_puts("ticks: ");
    uart_putc((char)('0' + ticks));
    uart_putc('\n');
    return ticks;
}
