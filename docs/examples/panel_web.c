/* Panel web: barrido 4x4, texto y glifo CGRAM en LCD, tres canales PWM. */
#define REG(offset) (*(volatile unsigned int *)(0x40000000u + (offset)))
#define FILAS REG(0x50)
#define COLUMNAS REG(0x54)
#define LCD_COMANDO REG(0x60)
#define LCD_DATO REG(0x64)
#define PERIODO REG(0x70)
#define ROJO REG(0x74)
#define VERDE REG(0x78)
#define AZUL REG(0x7c)

static void texto(const char *cadena)
{
    while (*cadena != '\0') {
        LCD_DATO = (unsigned char)*cadena;
        cadena++;
    }
}

int main(void)
{
    const char teclas[4][4] = {
        {'1', '2', '3', 'A'}, {'4', '5', '6', 'B'},
        {'7', '8', '9', 'C'}, {'*', '0', '#', 'D'}
    };
    const unsigned int sonrisa[8] = {0, 10, 10, 0, 17, 14, 0, 0};
    char anterior = '\0';
    LCD_COMANDO = 0x38;
    LCD_COMANDO = 0x01;
    LCD_COMANDO = 0x06;
    LCD_COMANDO = 0x0e;
    LCD_COMANDO = 0x40;
    for (unsigned int i = 0; i < 8; i++) {
        LCD_DATO = sonrisa[i];
    }
    LCD_COMANDO = 0x80;
    texto("Hola hardboiled");
    LCD_DATO = 0;
    LCD_COMANDO = 0xc0;
    texto("Tecla: -");
    PERIODO = 1000;
    VERDE = 500;
    AZUL = 750;
    for (;;) {
        char actual = '-';
        for (unsigned int fila = 0; fila < 4; fila++) {
            FILAS = 1u << fila;
            unsigned int columnas = COLUMNAS;
            for (unsigned int col = 0; col < 4; col++) {
                if ((columnas & (1u << col)) != 0) {
                    actual = teclas[fila][col];
                }
            }
        }
        if (actual != anterior) {
            LCD_COMANDO = 0xc7;
            LCD_DATO = (unsigned char)actual;
            ROJO = actual == '-' ? 250 : 1000;
            anterior = actual;
        }
    }
}
