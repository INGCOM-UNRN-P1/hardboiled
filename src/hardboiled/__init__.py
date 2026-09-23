"""hardboiled: emulador pedagógico RV32I bare-metal con depurador de código C."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hardboiled")
except PackageNotFoundError:  # pragma: no cover - ejecución desde el árbol de fuentes
    __version__ = "0.0.0"
