# Lección 4 — El timer, por sondeo

El timer cuenta ciclos de la CPU. Cada `RELOAD` ciclos "vence": marca un bit
en su registro `STATUS` y vuelve a empezar. Sin interrupciones, el programa
tiene que preguntar (sondear) si ya venció:

```c
timer_start(50000, 0);            // vence cada 50 000 ciclos, sin IRQ
while (!timer_expired()) { }      // espera activa
timer_clear();                    // baja la marca para el próximo vencimiento
timer_stop();
```

## Consigna

Hacé parpadear el LED 0 cinco veces, es decir, 10 cambios de estado, uno por
cada vencimiento de un timer de 50 000 ciclos. En cada cambio imprimí `*`, y
al final un fin de línea. Detené el timer, dejá el LED apagado y devolvé la
cantidad de cambios (10).

## Para probar

```bash
hardboiled run main.c             # con + y - cambiás la velocidad del reloj
hardboiled tutorial check 4
```

## Pistas

- Si no limpiás la marca con `timer_clear()`, `timer_expired()` sigue en 1 y
  el LED cambia sin esperar.
- `led_toggle(0)` alterna el LED 0.
- Con la tecla `h` de la TUI vas a ver que casi todas las instrucciones se
  gastan en la espera activa. En la próxima lección las interrupciones lo
  resuelven.
