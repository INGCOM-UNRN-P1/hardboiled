/*
 * botones.c — Cuenta pulsaciones de botones con una interrupción.
 *
 * Cada vez que se presiona un botón, el hardware pide la IRQ de los botones;
 * la ISR averigua cuál fue mirando los flancos pendientes, los limpia y suma.
 * Los LEDs muestran la cuenta. Termina a las 5 pulsaciones.
 *
 * Probá:  hardboiled demo botones    (y hacé click en los botones ▣)
 */
#include "hardboiled.h"

static volatile uint32_t pulsaciones;
static volatile uint32_t ultimo;

static void on_boton(void)
{
    uint32_t flancos = buttons_pending();
    buttons_clear(flancos); /* sin limpiar, la IRQ seguiría pedida */
    for (unsigned int i = 0; i < 4; i++) {
        if (flancos & (1u << i)) {
            pulsaciones++;
            ultimo = i;
        }
    }
    led_set(pulsaciones);
}

int main(void)
{
    attach_irq(IRQ_BUTTONS, on_boton);
    button_irq_enable(0xFu);
    interrupts_enable();
    uart_puts("apretá botones (5 para terminar)\n");
    uint32_t vistas = 0;
    while (pulsaciones < 5) {
        wait_for_interrupt();
        /* Pueden haber llegado varias pulsaciones mientras dormíamos. */
        while (vistas < pulsaciones) {
            vistas++;
            uart_puts("pulsación ");
            uart_putc((char)('0' + vistas));
            uart_puts(" (último botón: ");
            uart_putc((char)('0' + ultimo));
            uart_puts(")\n");
        }
    }
    return (int)pulsaciones;
}
