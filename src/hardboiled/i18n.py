"""Idioma de los mensajes: español (el original) o inglés.

Al estilo gettext, la clave de cada mensaje es el propio texto en español, con
marcadores `{nombre}` para las partes variables:

    _("stack overflow: sp = {sp}", sp=f"0x{sp:08x}")

`N_()` sólo marca un texto (en constantes de módulo) para traducirlo después,
al usarlo, con `_()`. Los catálogos viven en `hardboiled.locale.<idioma>` y un
test verifica que cada texto marcado tenga su traducción con los mismos
marcadores.

El idioma se elige con la variable HARDBOILED_LANG o con `language` en [ui]
de config.toml. Por defecto, español.
"""

from __future__ import annotations

import importlib
import os

LANGUAGES = ("es", "en")
DEFAULT_LANGUAGE = "es"

_language = DEFAULT_LANGUAGE
_catalog: dict[str, str] = {}


def normalize(language: str | None) -> str | None:
    """`en_US.UTF-8` -> `en`; None si no es un idioma disponible."""
    if not language:
        return None
    code = language.strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    return code if code in LANGUAGES else None


def set_language(language: str | None) -> str:
    """Fija el idioma (uno desconocido deja el español). Devuelve el elegido."""
    global _language, _catalog
    _language = normalize(language) or DEFAULT_LANGUAGE
    if _language == DEFAULT_LANGUAGE:
        _catalog = {}
    else:
        module = importlib.import_module(f"hardboiled.locale.{_language}")
        _catalog = module.MESSAGES
    return _language


def language() -> str:
    return _language


def configure(preferred: str | None = None) -> str:
    """HARDBOILED_LANG manda; si no, la preferencia del usuario; si no, español."""
    return set_language(os.environ.get("HARDBOILED_LANG") or preferred)


def _(message: str, /, **values: object) -> str:
    """Traduce `message` al idioma actual y completa sus marcadores."""
    text = _catalog.get(message, message)
    return text.format(**values) if values else text


def N_(message: str) -> str:
    """Marca un texto para traducir más tarde (no lo traduce)."""
    return message


configure()
