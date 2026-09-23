/*
 * {name} — programa para la placa hardboiled (RV32I).
 *
 *   make run        compila y abre el depurador
 *   make headless   compila y ejecuta sin interfaz
 */
#include "hardboiled.h"

int main(void)
{
    uart_puts("Hola desde {name}!\n");
    led_set(0x01);
    return 0;
}
