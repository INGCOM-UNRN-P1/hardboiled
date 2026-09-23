/* Lección 2 — Leer los switches. La consigna está en leccion.md. */
#include "hardboiled.h"

int main(void)
{
    uint32_t switches = switch_get();

    /* TODO: LEDs 0-3 = switches; LEDs 4-7 = su complemento. */

    int encendidos = 0;
    /* TODO: contá los switches encendidos. */

    return encendidos;
}
