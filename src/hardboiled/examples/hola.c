/*
 * hola.c — Primer programa: escribe un saludo por la UART y termina.
 *
 * Probá:  hardboiled run hola.c --headless
 *         hardboiled run hola.c            (y avanzá con F10)
 */
#include "hardboiled.h"

int main(void)
{
    uart_puts("Hola, hardboiled!\n");
    return 0; /* el valor de retorno de main() es el código de salida */
}
