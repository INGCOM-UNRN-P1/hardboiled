/* Solución de referencia de la lección 7. */
#include "hardboiled.h"

#define CANTIDAD 8

static int datos[CANTIDAD] = {4, 8, 15, 16, 23, 42, 7, 1};
static int limite = 100;

static void imprimir(int n)
{
    char cifras[12];
    int i = 0;
    if (n == 0) {
        uart_putc('0');
        return;
    }
    while (n > 0) {
        cifras[i++] = (char)('0' + n % 10);
        n /= 10;
    }
    while (i > 0) {
        uart_putc(cifras[--i]);
    }
}

/* El mayor de los primeros n elementos. */
static int maximo(const int *v, int n)
{
    int mayor = v[0];
    for (int i = 1; i < n; i++) {
        if (v[i] > mayor) {
            mayor = v[i];
        }
    }
    return mayor;
}

/* La suma de los primeros n elementos. */
static int suma(const int *v, int n)
{
    if (n == 0) {
        return 0;
    }
    return v[n - 1] + suma(v, n - 1);
}

/* Un puntero al primer elemento igual a x, o NULL si no está. */
static int *buscar(int *v, int n, int x)
{
    for (int i = 0; i < n; i++) {
        if (v[i] == x) {
            return &v[i];
        }
    }
    return 0;
}

int main(void)
{
    uart_puts("maximo: ");
    imprimir(maximo(datos, CANTIDAD));
    uart_puts("\nsuma: ");
    imprimir(suma(datos, CANTIDAD));
    uart_puts("\n");

    int *encontrado = buscar(datos, CANTIDAD, 99);
    imprimir(99);
    if (encontrado != 0) {
        uart_puts(": está\n");
    } else {
        uart_puts(": no está\n");
    }
    return limite - 100;
}
