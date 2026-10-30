/* Lee los tres ejes enviados por Cyberdeck. Inspeccioná ejes[] en la TUI. */
#include "hardboiled.h"

volatile unsigned int ejes[3];

int main(void)
{
    for (;;) {
        for (unsigned int canal = 0; canal < 3; canal++) {
            ejes[canal] = adc_read(canal);
        }
    }
}
