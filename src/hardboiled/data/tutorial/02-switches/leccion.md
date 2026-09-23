# Lección 2 — Leer los switches

Los 4 switches son la entrada más simple: el registro `SWITCHES` (sólo
lectura) tiene un bit por switch, 1 si está encendido. `switch_get()` lee los
cuatro juntos y `switch_read(i)` sólo el `i` (0 o 1).

Para trabajar con bits vas a necesitar los operadores de C `&` (y), `|` (o),
`~` (complemento) y `<<` (desplazamiento).

## Consigna

1. Mostrá en los LEDs 0 a 3 el estado de los switches.
2. Mostrá en los LEDs 4 a 7 el complemento: encendido donde el switch está
   apagado.
3. Devolvé cuántos switches están encendidos.

Por ejemplo, con los switches en `0b1010` los LEDs quedan en `0b0101_1010` y
`main()` devuelve 2.

## Para probar

```bash
hardboiled run main.c --switches 0b1010
hardboiled tutorial check 2
```

En la TUI, las teclas 0 a 3 (o un click) cambian los switches.

## Pistas

- `~s` invierte los 32 bits: quedate sólo con los 4 de abajo usando `& 0xF`.
- Para llevar 4 bits a los LEDs 4 a 7, desplazalos: `x << 4`.
- Contar bits encendidos: un `for` de 0 a 3 con `switch_read(i)`.
