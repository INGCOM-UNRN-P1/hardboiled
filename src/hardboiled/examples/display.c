/*
 * display.c — Un contador en el display de 7 segmentos.
 *
 * El timer interrumpe periódicamente; la ISR suma y main() muestra la cuenta
 * en decimal. Al llegar a 20 muestra BEEF en hexadecimal y termina.
 *
 * Probá:  hardboiled demo display
 *         seg_set_digit() dibuja segmentos sueltos (bits a-g y el punto).
 */
#include "hardboiled.h"

static volatile uint32_t cuenta;

static void on_tick(void)
{
    cuenta++;
}

int main(void)
{
    attach_irq(IRQ_TIMER0, on_tick);
    timer_start(50000, 1);
    interrupts_enable();

    uint32_t mostrada = 0xFFFFFFFFu;
    while (cuenta < 20) {
        wait_for_interrupt();
        if (cuenta != mostrada) {
            mostrada = cuenta;
            seg_show_dec(mostrada);
        }
    }
    timer_stop();
    seg_show_hex(0xBEEFu);
    seg_set_digit(0, (uint8_t)(seg_pattern(0xF) | 0x80u)); /* F con punto */
    return (int)cuenta;
}
