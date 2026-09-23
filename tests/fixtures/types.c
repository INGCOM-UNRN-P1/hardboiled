/* Tipos variados para probar la inspección de variables. */
#include "hardboiled.h"

typedef enum { ROJO, VERDE = 5, AZUL } color_t;

struct punto {
    int x;
    int y;
};

struct figura {
    char nombre[8];
    struct punto vertices[3];
    color_t color;
    unsigned int visible : 1;
    unsigned int capa : 4;
    struct figura *siguiente;
};

const char *saludo = "hola";
unsigned char byte_suelto = 'A';
_Bool bandera = 1;
short corto = -3;
int matriz[2][3] = {{1, 2, 3}, {4, 5, 6}};
struct figura triangulo = {"tri", {{0, 0}, {4, 0}, {0, 3}}, VERDE, 1, 7, 0};
static int contador_estatico = 9;
int (*operacion)(int, int);

static int sumar(int a, int b)
{
    return a + b;
}

int medir(struct figura *f, int escala)
{
    int perimetro = 0; /* @medir_first */
    for (int i = 0; i < 3; i++) {
        int dx = f->vertices[(i + 1) % 3].x - f->vertices[i].x; /* @medir_loop */
        perimetro += dx < 0 ? -dx : dx;
    }
    return perimetro * escala; /* @medir_return */
}

int main(void)
{
    struct punto origen = {10, -20};
    char letra = 'z';
    operacion = sumar;
    triangulo.siguiente = &triangulo;
    int resultado = medir(&triangulo, 2); /* @main_call */
    contador_estatico += operacion(origen.x, letra);
    /* Usar todas las globales para que --gc-sections no las elimine. */
    int extra = saludo[0] + byte_suelto + bandera + corto + matriz[1][2];
    return resultado + contador_estatico + extra; /* @main_return */
}
