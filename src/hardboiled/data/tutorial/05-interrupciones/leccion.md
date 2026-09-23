# Lección 5 — Interrupciones

En lugar de sondear, el timer puede **interrumpir** a la CPU: cuando vence,
la CPU guarda lo que estaba haciendo, ejecuta una función tuya (la *rutina de
interrupción*, ISR) y después sigue donde estaba.

```c
static volatile int ticks;

void on_tick(void) { ticks++; }              // la ISR: corta y sin esperas

attach_irq(IRQ_TIMER0, on_tick);             // registra la ISR y habilita la línea
timer_start(20000, 1);                       // el 1: el timer pide su IRQ
interrupts_enable();                         // habilitador global
wait_for_interrupt();                        // duerme hasta la próxima IRQ
```

## Consigna

Contá los vencimientos del timer (cada 20 000 ciclos) en una ISR. `main()`
duerme con `wait_for_interrupt()` hasta que haya 8 ticks y, cada vez que se
despierta, muestra la cuenta en el display (`seg_show_dec`). Al llegar a 8,
detené el timer, deshabilitá las interrupciones, imprimí `ticks: 8` (con un
fin de línea) y devolvé la cuenta.

## Para probar

```bash
hardboiled run main.c             # poné un breakpoint (F9) dentro de on_tick
hardboiled tutorial check 5
```

## Pistas

- Una variable que cambia en la ISR y se lee en `main()` tiene que ser
  `volatile`: sin eso, el compilador optimizado puede no volver a leerla.
- Si `main()` duerme sin habilitar las interrupciones, la CPU no se despierta
  nunca y hardboiled lo informa como *deadlock* (`hardboiled explain
  wfi-deadlock`).
- Para imprimir un dígito: `uart_putc('0' + n)`.
