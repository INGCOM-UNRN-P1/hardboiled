#include "hardboiled.h"

#define PERIODO 50000u
#define CAMBIOS 10

int main(void)
{
    int cambios = 0;
    timer_start(PERIODO, 0);
    while (cambios < CAMBIOS) {
        while (!timer_expired()) {
        }
        timer_clear();
        led_toggle(0);
        uart_putc('*');
        cambios++;
    }
    timer_stop();
    uart_putc('\n');
    return cambios;
}
