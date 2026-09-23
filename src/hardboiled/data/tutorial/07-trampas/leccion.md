# Lección 7 — Cazar errores con el depurador

Este programa tiene **tres errores** clásicos de C. Cuando la placa real hace
algo raro no hay mensajes, pero hardboiled detiene el programa en el lugar
exacto de la *trampa* y explica qué pasó.

El programa debería imprimir:

```
maximo: 42
suma: 116
99: no está
```

## Consigna

Encontrá y corregí los tres errores. No cambies qué imprime el programa, sólo
cómo lo calcula.

## Para probar

```bash
hardboiled run main.c             # F5 corre hasta la trampa
hardboiled tutorial check 7
```

## Pistas

- Cuando aparece la pantalla de la trampa, la **pila de llamadas** muestra
  cómo se llegó ahí. Una lista larguísima de la misma función es una
  recursión que no termina (`hardboiled explain stack-overflow`).
- Un puntero que vale 0 no apunta a nada (`hardboiled explain null-pointer`).
- Si un resultado da raro, poné un breakpoint (F9) en el bucle y mirá las
  variables en cada vuelta. ¿Cuántas vueltas da? ¿Cuántos elementos tiene el
  arreglo?
- Un watchpoint (`w`) sobre una variable detiene el programa cada vez que
  cambia.
