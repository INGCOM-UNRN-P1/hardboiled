#include "hardboiled.h"

int main(void)
{
    char nombre[32];
    uart_puts("¿Cómo te llamás?\n");
    int largo = uart_gets(nombre, (int)sizeof nombre);
    uart_puts("Hola, ");
    uart_puts(largo > 0 ? nombre : "desconocido");
    uart_puts("!\n");
    return largo;
}
