/*
 * hardboiled_test.h — aserciones para probar firmware sobre los registros de E/S.
 *
 * Las pruebas corren en la placa emulada: cada aserción lee los registros mapeados en
 * memoria (MMIO) y, si falla, informa por la UART el archivo, la línea, la expresión y
 * los valores. Al final, `return hb_test_fin();` imprime el resumen y sale con 0 si todo
 * pasó o con 1 si algo falló, así que `hardboiled test` (o `hardboiled run --headless`)
 * lo puede evaluar en el CI sin mirar la pantalla.
 *
 *     #include "hardboiled.h"
 *     #include "hardboiled_test.h"
 *
 *     HB_TEST(configura_el_timer)
 *     {
 *         timer_start(1000, 1);
 *         HB_ASSERT_REG_EQ(TIMER_RELOAD, 1000);
 *         HB_ASSERT_BITS_SET(TIMER_CTRL, TIMER_CTRL_ENABLE | TIMER_CTRL_IRQ);
 *     }
 *
 *     int main(void)
 *     {
 *         HB_RUN(configura_el_timer);
 *         return hb_test_fin();
 *     }
 *
 * Los ciclos se miden con hb_cycles(), el reloj del emulador: la misma prueba da siempre
 * el mismo resultado. Un estímulo externo (un botón, un byte por la UART) llega desde el
 * guion del caso de prueba (`[[case.at]]` en casos.toml) en un ciclo fijo.
 *
 * Una aserción que falla termina la prueba en curso (hace `return`): usalas sólo dentro
 * de una función HB_TEST.
 */
#ifndef HARDBOILED_TEST_H
#define HARDBOILED_TEST_H

#include "hardboiled.h"

static unsigned int hb_test_pruebas;
static unsigned int hb_test_falladas;
static int hb_test_fallo_actual;

static inline void hb_test_dec(uint32_t n)
{
    char cifras[10];
    int i = 0;
    do {
        uint32_t resto = 0;
        uint32_t cociente = 0;
        /* división por 10 sin la biblioteca de C (RV32I no tiene instrucción de división) */
        for (int bit = 31; bit >= 0; bit--) {
            resto = (resto << 1) | ((n >> bit) & 1u);
            if (resto >= 10u) {
                resto -= 10u;
                cociente |= 1u << bit;
            }
        }
        cifras[i++] = (char)('0' + resto);
        n = cociente;
    } while (n != 0u && i < 10);
    while (i > 0) {
        uart_putc(cifras[--i]);
    }
}

static inline void hb_test_fallar(const char *archivo, int linea, const char *expresion,
                                  int con_valores, uint32_t obtenido, uint32_t esperado)
{
    hb_test_fallo_actual = 1;
    for (const char *c = archivo; *c != '\0'; c++) {
        if (*c == '/' || *c == '\\') {
            archivo = c + 1; /* sólo el nombre: la ruta completa no aporta */
        }
    }
    uart_puts("  FALLA ");
    uart_puts(archivo);
    uart_putc(':');
    hb_test_dec((uint32_t)linea);
    uart_puts(": ");
    uart_puts(expresion);
    if (con_valores) {
        uart_puts(" (obtenido ");
        uart_puthex(obtenido);
        uart_puts(", esperado ");
        uart_puthex(esperado);
        uart_putc(')');
    }
    uart_putc('\n');
}

static inline void hb_test_correr(const char *nombre, void (*prueba)(void))
{
    hb_test_fallo_actual = 0;
    hb_test_pruebas++;
    prueba();
    if (hb_test_fallo_actual) {
        hb_test_falladas++;
        uart_puts("[FALLA] ");
    } else {
        uart_puts("[ ok  ] ");
    }
    uart_puts(nombre);
    uart_putc('\n');
}

/* Resumen («N pruebas, M fallas») y código de salida: 0 si todo pasó. */
static inline int hb_test_fin(void)
{
    hb_test_dec(hb_test_pruebas);
    uart_puts(" pruebas, ");
    hb_test_dec(hb_test_falladas);
    uart_puts(hb_test_falladas == 1u ? " falla\n" : " fallas\n");
    return hb_test_falladas == 0u ? 0 : 1;
}

#define HB_TEST(nombre) static void nombre(void)
#define HB_RUN(nombre) hb_test_correr(#nombre, nombre)

/* ------------------------------------------------------------ Aserciones --- */

#define HB_ASSERT(condicion)                                                   \
    do {                                                                       \
        if (!(condicion)) {                                                    \
            hb_test_fallar(__FILE__, __LINE__, #condicion, 0, 0u, 0u);         \
            return;                                                            \
        }                                                                      \
    } while (0)

/* Compara y, si difiere, informa `texto` (la expresión como la escribió la prueba: los
 * nombres de los registros, no su dirección expandida). */
#define HB_ASSERT_EQ_TEXTO(obtenido, esperado, texto)                          \
    do {                                                                       \
        uint32_t hb_o_ = (uint32_t)(obtenido);                                 \
        uint32_t hb_e_ = (uint32_t)(esperado);                                 \
        if (hb_o_ != hb_e_) {                                                  \
            hb_test_fallar(__FILE__, __LINE__, texto, 1, hb_o_, hb_e_);        \
            return;                                                            \
        }                                                                      \
    } while (0)

#define HB_ASSERT_EQ(obtenido, esperado)                                       \
    HB_ASSERT_EQ_TEXTO(obtenido, esperado, #obtenido " == " #esperado)

/* El registro vale exactamente `valor`. */
#define HB_ASSERT_REG_EQ(reg, valor) HB_ASSERT_EQ_TEXTO((reg), (valor), #reg " == " #valor)

/* Los bits de `mascara` están en 1 (los demás no importan). */
#define HB_ASSERT_BITS_SET(reg, mascara)                                       \
    HB_ASSERT_EQ_TEXTO((reg) & (mascara), (mascara), #reg ": bits " #mascara " en 1")

/* Los bits de `mascara` están en 0. */
#define HB_ASSERT_BITS_CLEAR(reg, mascara)                                     \
    HB_ASSERT_EQ_TEXTO((reg) & (mascara), 0u, #reg ": bits " #mascara " en 0")

/* El campo `mascara` del registro vale `valor` (ya desplazado a la posición del campo). */
#define HB_ASSERT_FIELD(reg, mascara, valor)                                   \
    HB_ASSERT_EQ_TEXTO((reg) & (mascara), (valor), #reg ": campo " #mascara " == " #valor)

/* ------------------------------------------------- GPIO e interrupciones --- */

/* El pin tiene el pull-up activado (registro <PUERTO>_PULL de un gpio_port). */
#define HB_ASSERT_PULLUP(reg_pull, pin)                                        \
    HB_ASSERT_EQ_TEXTO((reg_pull) & (1u << (pin)), 1u << (pin), "pull-up del pin " #pin " en " #reg_pull)
#define HB_ASSERT_NO_PULLUP(reg_pull, pin)                                     \
    HB_ASSERT_EQ_TEXTO((reg_pull) & (1u << (pin)), 0u, "sin pull-up el pin " #pin " en " #reg_pull)

/* La línea de IRQ está habilitada en el PIC / tiene una solicitud pendiente. */
#define HB_ASSERT_IRQ_ENABLED(linea)                                           \
    HB_ASSERT_EQ_TEXTO(PIC_ENABLE & (1u << (linea)), 1u << (linea), "IRQ " #linea " habilitada en PIC_ENABLE")
#define HB_ASSERT_IRQ_PENDING(linea)                                           \
    HB_ASSERT_EQ_TEXTO(PIC_PENDING & (1u << (linea)), 1u << (linea), "IRQ " #linea " pendiente")
#define HB_ASSERT_IRQ_NOT_PENDING(linea)                                       \
    HB_ASSERT_EQ_TEXTO(PIC_PENDING & (1u << (linea)), 0u, "IRQ " #linea " sin solicitud pendiente")

/* Las interrupciones están habilitadas globalmente. */
#define HB_ASSERT_INTERRUPTS_ON() HB_ASSERT_EQ_TEXTO(PIC_GLOBAL & 1u, 1u, "interrupciones habilitadas (PIC_GLOBAL)")

/* ------------------------------------------------------- Ciclos de reloj --- */

/* `sentencia` tarda como mucho `max_ciclos` ciclos. */
#define HB_ASSERT_CYCLES_AT_MOST(sentencia, max_ciclos)                        \
    do {                                                                       \
        uint64_t hb_c0_ = hb_cycles();                                         \
        sentencia;                                                             \
        uint32_t hb_d_ = (uint32_t)(hb_cycles() - hb_c0_);                     \
        if (hb_d_ > (uint32_t)(max_ciclos)) {                                  \
            hb_test_fallar(__FILE__, __LINE__, "ciclos de " #sentencia " <= "  \
                           #max_ciclos, 1, hb_d_, (uint32_t)(max_ciclos));      \
            return;                                                            \
        }                                                                      \
    } while (0)

/* Espera (activamente) hasta que `condicion` se cumpla; falla si pasan más de
 * `max_ciclos` ciclos. Sirve para esperar una interrupción o un estímulo del guion. */
#define HB_ESPERAR(condicion, max_ciclos)                                      \
    do {                                                                       \
        uint64_t hb_c0_ = hb_cycles();                                         \
        while (!(condicion)) {                                                 \
            if (hb_cycles() - hb_c0_ > (uint64_t)(max_ciclos)) {               \
                hb_test_fallar(__FILE__, __LINE__, "se esperaba " #condicion   \
                               " en " #max_ciclos " ciclos", 0, 0u, 0u);       \
                return;                                                        \
            }                                                                  \
        }                                                                      \
    } while (0)

#endif /* HARDBOILED_TEST_H */
