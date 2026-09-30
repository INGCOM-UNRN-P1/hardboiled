"""Textos de argparse en español (LINEAMIENTOS §4.2, N-ECO-14).

La ayuda de los subcomandos está en español, pero argparse agregaba sus propios
textos en inglés («usage:», «positional arguments», «invalid choice…»).
hardboiled no usa Typer, así que no toma los textos de yutani: argparse busca
cada texto con `_()` y `ngettext()` (gettext) en el momento de usarlo, e
`install()` reemplaza esas dos funciones del módulo por una tabla. Lo que la
tabla no tiene (un texto nuevo de otra versión de Python) queda en inglés en
lugar de fallar.
"""

from __future__ import annotations

import argparse

# Misma redacción que los textos de Typer/Click que traduce yutani.
TEXTS = {
    "usage: ": "uso: ",
    "positional arguments": "argumentos",
    "options": "opciones",
    "subcommands": "subcomandos",
    "show this help message and exit": "muestra esta ayuda y sale",
    "show program's version number and exit": "muestra la versión y sale",
    " (default: %(default)s)": " (por defecto: %(default)s)",
    "argument %(argument_name)s: %(message)s": "argumento %(argument_name)s: %(message)s",
    "the following arguments are required: %s": "faltan los argumentos obligatorios: %s",
    "one of the arguments %s is required": "falta uno de estos argumentos: %s",
    "unrecognized arguments: %s": "argumentos no reconocidos: %s",
    "not allowed with argument %s": "no se puede usar junto con %s",
    "ambiguous option: %(option)s could match %(matches)s": (
        "opción ambigua: %(option)s puede ser %(matches)s"
    ),
    "expected one argument": "necesita un valor",
    "expected at most one argument": "admite como máximo un valor",
    "expected at least one argument": "necesita al menos un valor",
    "ignored explicit argument %r": "no lleva valor: %r",
    "invalid %(type)s value: %(value)r": "valor inválido (%(type)s): %(value)r",
    "invalid choice: %(value)r (choose from %(choices)s)": (
        "%(value)r no es ninguna de estas opciones: %(choices)s"
    ),
    "can't open '%(filename)s': %(error)s": "no se puede abrir '%(filename)s': %(error)s",
    "argument '%(argument_name)s' is deprecated": "el argumento '%(argument_name)s' está obsoleto",
    "option '%(option)s' is deprecated": "la opción '%(option)s' está obsoleta",
    "command '%(parser_name)s' is deprecated": "el comando '%(parser_name)s' está obsoleto",
    "%(prog)s: warning: %(message)s\n": "%(prog)s: aviso: %(message)s\n",
}

PLURALS = {
    ("expected %s argument", "expected %s arguments"): ("necesita %s valor", "necesita %s valores"),
}


def _text(message: str) -> str:
    return TEXTS.get(message, message)


def _plural(singular: str, plural: str, n: int) -> str:
    singular, plural = PLURALS.get((singular, plural), (singular, plural))
    return singular if n == 1 else plural


def install() -> None:
    """Pasa al español la ayuda y los errores de argparse (idempotente)."""
    module = vars(argparse)
    if "_" in module:
        module["_"] = _text
    if "ngettext" in module:
        module["ngettext"] = _plural
