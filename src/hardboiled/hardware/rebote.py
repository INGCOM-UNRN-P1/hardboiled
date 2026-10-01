"""Rebote de contactos (qol.md #74): al cambiar, la señal oscila antes de estabilizarse.

Un botón o un switch real no pasa de 0 a 1 limpio: el contacto rebota unos microsegundos.
Con `bounce_cycles` en `board.toml`, cada cambio de una entrada (switches, botones o un pin
del GPIO manejado desde afuera) llega al nivel nuevo, vuelve al anterior, llega otra vez,
vuelve y recién ahí se queda: tres flancos hacia el nivel nuevo. Aparece el bug clásico de
«apreté una vez y contó tres» y el antirrebote por software deja de ser teoría.

Los cambios pendientes se guardan como una lista de tuplas (ciclo, pin, nivel) en el
periférico, para que el instantáneo del paso atrás la copie como al resto de su estado.
"""

from __future__ import annotations

# Momentos de cada cambio dentro de la ventana de rebote (fracción de bounce_cycles) y si el nivel
# es el nuevo (True) o el anterior (False). El primer contacto, en el ciclo del estímulo, ya es el
# nuevo; el último, al final de la ventana, lo deja estable.
PATRON = ((0.15, False), (0.35, True), (0.6, False), (1.0, True))

Pendientes = list[tuple[int, int, int]]  # (ciclo, pin, nivel)


def programar(pendientes: Pendientes, ahora: int, pin: int, nivel: int, ciclos: int) -> Pendientes:
    """Los cambios pendientes con el rebote de `pin` hacia `nivel` desde el ciclo `ahora`.

    Un cambio nuevo en el mismo pin reemplaza al rebote que estuviera en curso.
    """
    nuevos = [cambio for cambio in pendientes if cambio[1] != pin]
    anterior = 1 - nivel
    for fraccion, es_nuevo in PATRON:
        momento = ahora + max(1, round(ciclos * fraccion))
        nuevos.append((momento, pin, nivel if es_nuevo else anterior))
    return sorted(nuevos)


def proximo(pendientes: Pendientes) -> int | None:
    return pendientes[0][0] if pendientes else None


def vencidos(pendientes: Pendientes, ciclo: int) -> tuple[list[tuple[int, int, int]], Pendientes]:
    """(cambios con ciclo <= `ciclo`, en orden; los que quedan)."""
    corte = 0
    while corte < len(pendientes) and pendientes[corte][0] <= ciclo:
        corte += 1
    return pendientes[:corte], pendientes[corte:]


def finales(pendientes: Pendientes) -> dict[int, int]:
    """Nivel en que queda cada pin cuando termine su rebote (para un reset a mitad de camino)."""
    return {pin: nivel for _, pin, nivel in pendientes}
