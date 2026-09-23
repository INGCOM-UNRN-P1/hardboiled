/*
 * switches.c — Los LEDs copian el estado de los switches.
 *
 * Leer SWITCHES es una lectura de un registro MMIO: cada vuelta del bucle
 * consulta el hardware. Termina cuando los cuatro switches están encendidos.
 *
 * Probá:  hardboiled run switches.c        (y tocá los switches con 0-3)
 *         hardboiled run switches.c --headless --switches 0b1111
 */
#include "hardboiled.h"

int main(void)
{
    uint32_t state;
    do {
        state = switch_get();
        led_set(state);
    } while (state != 0xFu);
    uart_puts("todos encendidos\n");
    return 0;
}
