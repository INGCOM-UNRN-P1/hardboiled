/*
 * hardboiled.h — SDK pedagógico para la placa virtual hardboiled (RV32I).
 *
 * Generado a partir de la placa 'lab-rv32-basics' con `hardboiled gen-header`.
 * Encapsula los registros de E/S mapeados en memoria (MMIO) y ofrece
 * funciones simples para los periféricos y las interrupciones.
 *
 * Mapa MMIO (base 0x4000_0000):
 *   0x000  LEDS         escritura/lectura: un bit por LED (8)
 *   0x004  SWITCHES     sólo lectura: un bit por interruptor (4)
 *   0x010  UART_TX      escritura: byte a transmitir
 *   0x014  UART_STATUS  lectura: bit 0 = listo para transmitir
 *   0x020  TIMER_CTRL   bit 0 = habilitado, bit 1 = genera IRQ
 *   0x024  TIMER_RELOAD período en ciclos (divisor)
 *   0x028  TIMER_COUNT  ciclos restantes hasta el próximo vencimiento
 *   0x02C  TIMER_STATUS bit 0 = venció (escribir 1 para limpiar)
 *   0xF00  PIC_ENABLE   máscara de IRQs habilitadas
 *   0xF04  PIC_PENDING  IRQs pendientes (escribir 1 para limpiar)
 *   0xF08  PIC_GLOBAL   bit 0 = interrupciones habilitadas globalmente
 */
#ifndef HARDBOILED_H
#define HARDBOILED_H

#include <stdint.h>

#define HB_MMIO_BASE 0x40000000u
#define HB_REG(offset) (*(volatile uint32_t *)(HB_MMIO_BASE + (offset)))

#define LEDS         HB_REG(0x000)
#define SWITCHES     HB_REG(0x004)
#define UART_TX      HB_REG(0x010)
#define UART_STATUS  HB_REG(0x014)
#define TIMER_CTRL   HB_REG(0x020)
#define TIMER_RELOAD HB_REG(0x024)
#define TIMER_COUNT  HB_REG(0x028)
#define TIMER_STATUS HB_REG(0x02C)
#define PIC_ENABLE   HB_REG(0xF00)
#define PIC_PENDING  HB_REG(0xF04)
#define PIC_GLOBAL   HB_REG(0xF08)

#define TIMER_CTRL_ENABLE (1u << 0)
#define TIMER_CTRL_IRQ    (1u << 1)
#define UART_STATUS_READY (1u << 0)

#define HB_IRQ_LINES 8
#define IRQ_TIMER0 0

typedef void (*irq_handler_t)(void);

/* Tabla de handlers definida en crt0.s. */
extern volatile irq_handler_t __irq_handlers[HB_IRQ_LINES];

/* ------------------------------------------------------------------ LEDs --- */

static inline void led_set(uint32_t mask) { LEDS = mask; }
static inline uint32_t led_get(void) { return LEDS; }
static inline void led_on(unsigned int index) { LEDS = LEDS | (1u << index); }
static inline void led_off(unsigned int index) { LEDS = LEDS & ~(1u << index); }
static inline void led_toggle(unsigned int index) { LEDS = LEDS ^ (1u << index); }

/* -------------------------------------------------------------- Switches --- */

static inline uint32_t switch_get(void) { return SWITCHES; }
static inline int switch_read(unsigned int index) { return (int)((SWITCHES >> index) & 1u); }

/* ------------------------------------------------------------------ UART --- */

static inline void uart_putc(char c)
{
    while ((UART_STATUS & UART_STATUS_READY) == 0) {
    }
    UART_TX = (uint32_t)(unsigned char)c;
}

static inline void uart_puts(const char *text)
{
    while (*text != '\0') {
        uart_putc(*text);
        text++;
    }
}

/* Imprime un entero sin signo en hexadecimal (sin usar división). */
static inline void uart_puthex(uint32_t value)
{
    static const char digits[] = "0123456789abcdef";
    uart_puts("0x");
    for (int shift = 28; shift >= 0; shift -= 4) {
        uart_putc(digits[(value >> shift) & 0xFu]);
    }
}

/* ----------------------------------------------------------------- Timer --- */

static inline void timer_start(uint32_t period_cycles, int with_irq)
{
    TIMER_RELOAD = period_cycles;
    TIMER_CTRL = TIMER_CTRL_ENABLE | (with_irq ? TIMER_CTRL_IRQ : 0u);
}

static inline void timer_stop(void) { TIMER_CTRL = 0; }
static inline int timer_expired(void) { return (int)(TIMER_STATUS & 1u); }
static inline void timer_clear(void) { TIMER_STATUS = 1u; }

/* -------------------------------------------------------- Interrupciones --- */

static inline void attach_irq(unsigned int line, irq_handler_t handler)
{
    __irq_handlers[line] = handler;
    PIC_ENABLE = PIC_ENABLE | (1u << line);
}

static inline void detach_irq(unsigned int line)
{
    PIC_ENABLE = PIC_ENABLE & ~(1u << line);
    __irq_handlers[line] = 0;
}

static inline void interrupts_enable(void) { PIC_GLOBAL = 1u; }
static inline void interrupts_disable(void) { PIC_GLOBAL = 0u; }

/* Duerme la CPU hasta que llegue una interrupción habilitada. */
static inline void wait_for_interrupt(void) { __asm__ volatile("wfi"); }

#endif /* HARDBOILED_H */
