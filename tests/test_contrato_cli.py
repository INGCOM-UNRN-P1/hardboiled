"""Contrato de línea de comandos (LINEAMIENTOS §3.2, N-ECO-04): -h, -v/--version y doctor --json."""

from __future__ import annotations

import json
import re

import pytest

from hardboiled.cli import main


@pytest.mark.parametrize("opcion", ["-h", "--help", "-v", "--version"])
def test_ayuda_y_version(capsys: pytest.CaptureFixture[str], opcion: str) -> None:
    with pytest.raises(SystemExit) as salida:
        main([opcion])
    assert salida.value.code == 0
    assert capsys.readouterr().out.strip()


def test_doctor_json_con_sobre_comun(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = main(["doctor", "--json", "--no-build"])
    datos = json.loads(capsys.readouterr().out)
    assert datos["schema_version"] == "1.0.0"
    assert datos["herramienta"] == "hardboiled"
    assert codigo == (0 if datos["ok"] else 1)
    assert {"checks", "errors", "warnings"} <= set(datos)  # compatibilidad


def test_la_ayuda_esta_en_espanol(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    ayuda = capsys.readouterr().out
    assert ayuda.startswith("uso: hardboiled") and "muestra esta ayuda y sale" in ayuda


@pytest.mark.parametrize(
    ("argumentos", "mensaje"),
    [
        # Según la versión de Python, argparse cita las opciones ('new') o no (new).
        (["nada"], r"'nada' no es ninguna de estas opciones: '?new'?, "),
        (["new"], r"faltan los argumentos obligatorios: path"),
        (["run", "--board"], r"argumento --board: necesita un valor"),
    ],
)
def test_errores_de_uso_en_espanol(
    capsys: pytest.CaptureFixture[str], argumentos: list[str], mensaje: str
) -> None:
    with pytest.raises(SystemExit) as salida:
        main(argumentos)
    assert salida.value.code == 2
    error = capsys.readouterr().err
    assert "uso: hardboiled" in error and re.search(mensaje, error), error
