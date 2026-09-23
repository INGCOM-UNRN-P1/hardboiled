/*
 * leds.c — Contador binario en los LEDs, esperando al timer por encuesta.
 *
 * El timer vence cada 100 000 ciclos; el programa espera activamente a que
 * venza (polling), limpia el aviso y suma uno. Termina al llegar a 15.
 *
 * Probá:  hardboiled run leds.c   (con clock_hz de la placa se ve contar)
 */
#include "hardboiled.h"

int main(void)
{
    uint32_t count = 0;
    timer_start(100000, 0); /* sin interrupción: lo consultamos nosotros */
    while (count < 15) {
        while (!timer_expired()) {
            /* espera activa */
        }
        timer_clear();
        count++;
        led_set(count);
    }
    timer_stop();
    return (int)count;
}
