/*
 * Lazo de hardware: toda la placa trabajando a la vez, estimulada desde el test.
 *
 * - timer0 (IRQ 0) cuenta ticks; el display muestra la cuenta en decimal.
 * - buttons (IRQ 2) cuenta pulsaciones por botón.
 * - uart0 (IRQ 1) guarda lo recibido en un buffer circular; el lazo lo
 *   devuelve en mayúsculas y termina al recibir 'q'.
 * - Los LEDs muestran los switches (bits 0-3) y el total de pulsaciones (4-7).
 *
 * El lazo principal duerme con `wfi` y se despierta con cualquier IRQ.
 */
#include "hardboiled.h"

#define TICK_CYCLES 20000u
#define RX_SIZE 32u

volatile uint32_t ticks;
volatile uint32_t presses[4];
volatile uint32_t total_presses;
volatile uint32_t wakeups;

static volatile char rx_buffer[RX_SIZE];
static volatile uint32_t rx_head;
static volatile uint32_t rx_tail;

void on_timer(void)
{
    timer_clear();
    ticks++; /* @tick */
}

void on_buttons(void)
{
    uint32_t edges = buttons_pending();
    buttons_clear(edges);
    for (unsigned int i = 0; i < 4; i++) {
        if (edges & (1u << i)) {
            presses[i]++;
            total_presses++;
        }
    }
}

void on_uart(void)
{
    while (uart_available()) { /* leer baja el pedido de IRQ */
        rx_buffer[rx_head % RX_SIZE] = uart_getc();
        rx_head++;
    }
}

/* Como seg_show_dec(), pero con un único store: quien mire el display nunca ve
 * una cuenta a medio escribir (p. ej. "0" entre el 9 y el 10). */
static void show_ticks(uint32_t value)
{
    uint32_t digits = 0;
    for (unsigned int i = 0; i < SEG_COUNT; i++) {
        int blank = value == 0 && i > 0;
        digits |= (uint32_t)(blank ? 0 : seg_pattern(value % 10u)) << (8 * i);
        value /= 10u;
    }
    SEG_DIGITS = digits;
}

int main(void)
{
    attach_irq(IRQ_TIMER0, on_timer);
    attach_irq(IRQ_BUTTONS, on_buttons);
    attach_irq(IRQ_UART0, on_uart);
    button_irq_enable(0xFu);
    uart_rx_irq(1);
    timer_start(TICK_CYCLES, 1);
    interrupts_enable();
    uart_puts("listo\n");

    int quit = 0;
    while (!quit) {
        wait_for_interrupt(); /* @sleep */
        wakeups++;
        led_set((switch_get() & 0xFu) | (total_presses & 0xFu) << 4); /* @mirror */
        show_ticks(ticks);
        while (rx_tail != rx_head) {
            char c = rx_buffer[rx_tail % RX_SIZE];
            rx_tail++;
            if (c == 'q') {
                quit = 1;
            } else if (c >= 'a' && c <= 'z') {
                uart_putc((char)(c - 'a' + 'A')); /* @echo */
            } else {
                uart_putc(c);
            }
        }
    }

    timer_stop();
    interrupts_disable();
    uart_puts("fin\n");
    return (int)total_presses; /* @hwloop_return */
}
