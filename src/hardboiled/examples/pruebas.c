/*
 * pruebas.c — Pruebas unitarias de firmware con hardboiled_test.h.
 *
 * Cada HB_TEST verifica lo que el programa dejó en los registros de E/S: la
 * configuración del timer, que la interrupción del botón esté habilitada y que
 * la rutina de interrupción encienda el LED, y cuántos ciclos tarda una función.
 * El botón 0 lo aprieta el guion de la prueba en un ciclo fijo, así que el
 * resultado es siempre el mismo.
 *
 * Probá:  hardboiled test pruebas.c --press 0@20000 --expect-exit 0
 *         (o hardboiled run pruebas.c y apretá el botón 0 con Alt+0)
 */
#include "hardboiled.h"
#include "hardboiled_test.h"

static volatile uint32_t pulsaciones; /* volatile: la modifica la interrupción */

static void on_button(void)
{
    buttons_clear(1u);
    pulsaciones++;
    led_on(3);
}

static uint32_t sumar_hasta(uint32_t n)
{
    uint32_t total = 0;
    for (uint32_t i = 1; i <= n; i++) {
        total += i;
    }
    return total;
}

HB_TEST(configura_el_timer)
{
    timer_start(1000, 0);
    HB_ASSERT_REG_EQ(TIMER_RELOAD, 1000);
    HB_ASSERT_BITS_SET(TIMER_CTRL, TIMER_CTRL_ENABLE);
    HB_ASSERT_BITS_CLEAR(TIMER_CTRL, TIMER_CTRL_IRQ);
    timer_stop();
}

HB_TEST(habilita_la_interrupcion_del_boton)
{
    attach_irq(IRQ_BUTTONS, on_button);
    button_irq_enable(1u);
    interrupts_enable();
    HB_ASSERT_IRQ_ENABLED(IRQ_BUTTONS);
    HB_ASSERT_BITS_SET(BUTTONS_IRQ_EN, 1u);
    HB_ASSERT_INTERRUPTS_ON();
}

HB_TEST(el_boton_enciende_el_led)
{
    led_set(0);
    HB_ESPERAR(pulsaciones > 0u, 200000);
    HB_ASSERT_BITS_SET(LEDS, 1u << 3);
    HB_ASSERT_EQ(pulsaciones, 1);
}

HB_TEST(sumar_hasta_es_rapida)
{
    uint32_t total = 0;
    HB_ASSERT_CYCLES_AT_MOST(total = sumar_hasta(10), 400);
    HB_ASSERT_EQ(total, 55);
}

int main(void)
{
    HB_RUN(configura_el_timer);
    HB_RUN(habilita_la_interrupcion_del_boton);
    HB_RUN(el_boton_enciende_el_led);
    HB_RUN(sumar_hasta_es_rapida);
    return hb_test_fin();
}
