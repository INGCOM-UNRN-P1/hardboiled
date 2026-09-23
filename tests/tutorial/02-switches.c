#include "hardboiled.h"

int main(void)
{
    uint32_t switches = switch_get() & 0xFu;
    led_set(switches | ((~switches & 0xFu) << 4));
    int encendidos = 0;
    for (unsigned int i = 0; i < 4; i++) {
        encendidos += switch_read(i);
    }
    return encendidos;
}
