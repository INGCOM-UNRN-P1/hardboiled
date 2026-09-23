#include "hardboiled.h"

static volatile uint32_t pulsaciones[3];
static volatile int terminar;

void on_boton(void)
{
    uint32_t flancos = buttons_pending();
    buttons_clear(flancos);
    for (unsigned int i = 0; i < 3; i++) {
        if (flancos & (1u << i)) {
            pulsaciones[i]++;
        }
    }
    if (flancos & (1u << 3)) {
        terminar = 1;
    }
}

int main(void)
{
    attach_irq(IRQ_BUTTONS, on_boton);
    button_irq_enable(0xFu);
    interrupts_enable();
    while (!terminar) {
        wait_for_interrupt();
        led_set(pulsaciones[0] + pulsaciones[1] + pulsaciones[2]);
    }
    interrupts_disable();
    uint32_t total = pulsaciones[0] + pulsaciones[1] + pulsaciones[2];
    for (unsigned int i = 0; i < 3; i++) {
        uart_puts(i == 0 ? "b0=" : i == 1 ? " b1=" : " b2=");
        uart_putc((char)('0' + pulsaciones[i]));
    }
    uart_putc('\n');
    return (int)total;
}
