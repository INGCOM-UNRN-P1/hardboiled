# Lección 3 — Hablar por la UART

La UART es el puerto serie de la placa: lo que el programa transmite aparece
en la consola, y lo que se escribe en la consola llega al programa.

```c
uart_puts("texto\n");             // transmite una cadena
uart_putc('x');                   // transmite un carácter
int n = uart_gets(buffer, 32);    // espera una línea; devuelve cuántos caracteres leyó
```

`uart_gets` no guarda el fin de línea y termina la cadena con `'\0'`.

## Consigna

1. Preguntá `¿Cómo te llamás?` (con un fin de línea).
2. Leé el nombre con `uart_gets`.
3. Respondé `Hola, <nombre>!` (con un fin de línea). Si la línea llegó vacía,
   respondé `Hola, desconocido!`.
4. Devolvé la cantidad de caracteres del nombre.

## Para probar

```bash
hardboiled run main.c                              # escribí en el campo de la consola
printf 'Ada\n' | hardboiled run main.c --headless --uart-input -
hardboiled tutorial check 3
```

## Pistas

- El buffer tiene que tener lugar para el `'\0'` final.
- `uart_gets` ya devuelve la longitud: no hace falta `strlen`.
