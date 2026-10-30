/*
 * teclado_matricial.c — Lectura de teclado matricial 4x4 externo mediante barrido de filas.
 *
 * Registros MMIO del periférico externo (base 0x40000050):
 *   +0x00: FILAS (R/W)
 *   +0x04: COLUMNAS (R)
 */

#include <stdint.h>
#include <stdbool.h>

#define MMIO_BASE        0x40000000
#define KEYPAD_OFFSET    0x50

#define KEYPAD_FILAS     (*(volatile uint32_t *)(MMIO_BASE + KEYPAD_OFFSET + 0x00))
#define KEYPAD_COLUMNAS  (*(volatile uint32_t *)(MMIO_BASE + KEYPAD_OFFSET + 0x04))

#define UART_TX          (*(volatile uint32_t *)(MMIO_BASE + 0x10))

static const char MAPA_TECLAS[4][4] = {
    {'1', '2', '3', 'A'},
    {'4', '5', '6', 'B'},
    {'7', '8', '9', 'C'},
    {'*', '0', '#', 'D'}
};

static void uart_putc(char c)
{
    UART_TX = (uint32_t)c;
}

static void uart_puts(const char *s)
{
    while (*s) {
        uart_putc(*s++);
    }
}

int main(void)
{
    uart_puts("Iniciando escaneo de teclado matricial externo...\n");

    /* Barrido de 4 filas */
    for (int f = 0; f < 4; f++) {
        KEYPAD_FILAS = (1u << f);
        uint32_t cols = KEYPAD_COLUMNAS;

        for (int c = 0; c < 4; c++) {
            if (cols & (1u << c)) {
                uart_puts("Tecla detectada: ");
                uart_putc(MAPA_TECLAS[f][c]);
                uart_putc('\n');
            }
        }
    }

    uart_puts("Fin de escaneo.\n");
    return 0;
}
