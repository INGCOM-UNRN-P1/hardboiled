# Lección 1 — Encender LEDs

La placa tiene 8 LEDs conectados a un registro de E/S mapeado en memoria
(MMIO): el registro `LEDS`, en la dirección `0x4000_0000`. Cada bit enciende
un LED: el bit 0 es el de la derecha y el bit 7, el de la izquierda. Escribir
en el registro es escribir en una dirección de memoria, y `hardboiled.h` lo
envuelve en funciones:

```c
led_set(0x0F);     // enciende los LEDs 0 a 3 y apaga los demás
led_on(5);         // enciende sólo el LED 5
led_off(0);        // apaga sólo el LED 0
```

## Consigna

Encendé los LEDs 0, 2, 5 y 7, y sólo esos (el patrón `0b10100101`), y devolvé
0 desde `main()`.

## Para probar

```bash
hardboiled run main.c             # TUI: F10 avanza línea por línea
hardboiled tutorial check 1       # corre los casos de prueba de la lección
```

## Pistas

- En la TUI, mirá la fila `leds` del panel Placa mientras avanzás con F10.
- `0b10100101` se lee de izquierda (LED 7) a derecha (LED 0). En hexadecimal
  es `0xA5`.
- Con `led_on()` hacen falta cuatro llamadas. Con `led_set()`, una.
