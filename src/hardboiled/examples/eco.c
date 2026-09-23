/*
 * eco.c — Lee líneas por la UART y las devuelve en mayúsculas.
 *
 * La interrupción de la UART avisa cuando llega un byte; main() duerme con wfi
 * mientras tanto. Cuando la ISR completa una línea deshabilita la interrupción
 * de recepción (los bytes siguientes esperan en la UART) y main() la vuelve a
 * habilitar después de procesarla. Escribí "fin" para terminar.
 *
 * Probá:  hardboiled demo eco           (escribí en el campo bajo la consola)
 *         printf 'hola\nfin\n' | hardboiled demo eco --headless --uart-input -
 */
#include "hardboiled.h"

static volatile int linea_lista;
static char linea[64];
static int largo;

static void on_uart(void)
{
    while (uart_available()) {
        char c = (char)UART_RX;
        if (c == '\n' || c == '\r') {
            linea[largo] = '\0';
            linea_lista = 1;
            uart_rx_irq(0); /* el resto espera en la UART hasta procesar esta línea */
            return;
        }
        if (largo < (int)sizeof(linea) - 1) {
            linea[largo++] = c;
        }
    }
}

static int es_fin(const char *texto)
{
    return texto[0] == 'f' && texto[1] == 'i' && texto[2] == 'n' && texto[3] == '\0';
}

int main(void)
{
    attach_irq(IRQ_UART0, on_uart);
    uart_rx_irq(1);
    interrupts_enable();
    uart_puts("eco: escribí una línea (\"fin\" termina)\n");
    for (;;) {
        while (!linea_lista) {
            wait_for_interrupt();
        }
        if (es_fin(linea)) {
            break;
        }
        for (int i = 0; linea[i] != '\0'; i++) {
            char c = linea[i];
            uart_putc(c >= 'a' && c <= 'z' ? (char)(c - 'a' + 'A') : c);
        }
        uart_putc('\n');
        largo = 0;
        linea_lista = 0;
        uart_rx_irq(1); /* lista para la línea siguiente */
    }
    uart_puts("chau\n");
    return 0;
}
