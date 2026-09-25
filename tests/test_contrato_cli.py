"""Contrato de línea de comandos (LINEAMIENTOS §3.2, N-ECO-04): -h, -v/--version y doctor --json."""

from __future__ import annotations

import json

import pytest

from hardboiled.cli import main


@pytest.mark.parametrize("opcion", ["-h", "--help", "-v", "--version"])
def test_ayuda_y_version(capsys, opcion):
    with pytest.raises(SystemExit) as salida:
        main([opcion])
    assert salida.value.code == 0
    assert capsys.readouterr().out.strip()


def test_doctor_json_con_sobre_comun(capsys):
    codigo = main(["doctor", "--json", "--no-build"])
    datos = json.loads(capsys.readouterr().out)
    assert datos["schema_version"] == "1.0.0"
    assert datos["herramienta"] == "hardboiled"
    assert codigo == (0 if datos["ok"] else 1)
    assert {"checks", "errors", "warnings"} <= set(datos)  # compatibilidad
