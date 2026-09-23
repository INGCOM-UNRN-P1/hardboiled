# Lección 6 — Botones con interrupción

Los 4 botones pulsadores piden la IRQ `IRQ_BUTTONS` al apretarse. Como
comparten una sola línea, la ISR tiene que averiguar cuáles fueron mirando los
flancos pendientes, y limpiarlos:

```c
uint32_t flancos = buttons_pending();   // un bit por botón apretado
buttons_clear(flancos);                 // si no se limpian, la IRQ sigue pedida
button_irq_enable(0xF);                 // qué botones piden la IRQ
```

## Consigna

Contá las pulsaciones de los botones 0, 1 y 2 en la ISR, y mostrá el total en
los LEDs. El botón 3 termina el programa: imprimí `b0=N b1=N b2=N` (con un
fin de línea) y devolvé el total de pulsaciones de los botones 0 a 2. Mientras
espera, `main()` duerme con `wait_for_interrupt()`.

## Para probar

```bash
hardboiled run main.c             # click en los botones ▣ del panel Placa
hardboiled tutorial check 6
```

Los casos de prueba aprietan botones en ciclos dados con un guion
(`--script`). Mirá `casos.toml` para ver cuáles.

## Pistas

- Pueden llegar varios flancos juntos (dos botones en el mismo instante): mirá
  todos los bits, no sólo el primero.
- Cualquier variable que modifique la ISR y lea `main()`, `volatile`.
