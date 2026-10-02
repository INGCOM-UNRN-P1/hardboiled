"""El MANUAL (y su copia en docs/) no se aparta de la placa, del SDK ni de la CLI.

El manual anterior describía un mapa MMIO, un board.toml, funciones del SDK, opciones y un
formato de suites que no existían (N-HARDBOILED-05): estos tests lo comparan con lo que genera
el código.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shlex
from pathlib import Path

import pytest

from hardboiled import resources, sdk
from hardboiled.cli import build_parser, main
from hardboiled.config import load_board
from hardboiled.core.hints import HINTS

ROOT = Path(__file__).parents[1]
MANUAL = (ROOT / "MANUAL.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

needs_zig = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)


PALABRAS_DE_C = {"if", "while", "for", "return", "main"}


def _bloques(texto: str, lenguaje: str) -> list[str]:
    return re.findall(rf"```{lenguaje}\n(.*?)```", texto, re.S)


def _registros_de_la_placa() -> set[tuple[int, str]]:
    placa = load_board(resources.default_board_path())
    nombres = sdk._names(placa)
    registros = [r for p in placa.peripherals for r in sdk._registers(p, nombres[p.name])]
    registros += sdk._pic_registers(placa)
    return {(offset, macro) for macro, offset, _ in registros}


def _registros_documentados(texto: str) -> set[tuple[int, str]]:
    filas = re.findall(r"^\| `(0x[0-9A-F]{3})` \| `([A-Z_]+)` \|", texto, re.M)
    return {(int(offset, 16), macro) for offset, macro in filas}


@pytest.mark.parametrize("texto", [MANUAL, README], ids=["MANUAL", "README"])
def test_el_mapa_de_registros_es_el_de_la_placa(texto: str) -> None:
    assert _registros_documentados(texto) == _registros_de_la_placa()


def test_las_funciones_citadas_existen_en_el_sdk() -> None:
    cabecera = sdk.generate_header(load_board(resources.default_board_path()))
    declaradas = set(re.findall(r"\b([a-z_][a-z0-9_]*)\(", cabecera))
    for bloque in _bloques(MANUAL, "c"):
        propias = set(re.findall(r"\b(?:void|int)\s+([a-z_][a-z0-9_]*)\(", bloque))
        citadas = set(re.findall(r"\b([a-z_][a-z0-9_]*)\(", bloque)) - PALABRAS_DE_C
        assert citadas - propias - declaradas == set()
    for macro in re.findall(r"\b(IRQ_[A-Z0-9_]+)\b", MANUAL):
        assert re.search(rf"#define {macro}\b", cabecera), macro


def test_las_trampas_y_avisos_son_los_de_explain() -> None:
    seccion = MANUAL.split("## 7.")[1].split("## 8.")[0]
    trampas = set(re.findall(r"^\| `([a-z0-9-]+)` \| ", seccion, re.M))
    avisos = {"div0", "uninit", "limit"}
    assert trampas | avisos == set(HINTS)
    for aviso in avisos:
        assert f"`{aviso}`" in MANUAL


def _subcomandos(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for accion in parser._actions:
        if isinstance(accion, argparse._SubParsersAction):
            return dict(accion.choices)
    return {}


def _opciones(parser: argparse.ArgumentParser) -> set[str]:
    opciones = set(parser._option_string_actions)
    for sub in _subcomandos(parser).values():
        opciones |= _opciones(sub)
    return opciones


def _comandos_citados() -> list[str]:
    lineas = [linea for bloque in _bloques(MANUAL, "bash") for linea in bloque.splitlines()]
    lineas += re.findall(r"`(hardboiled [^`]+)`", MANUAL)
    lineas = [linea.split("#")[0].strip() for linea in lineas]
    return [linea for linea in lineas if linea.startswith("hardboiled ")]


def test_los_comandos_y_opciones_citados_existen() -> None:
    subcomandos = _subcomandos(build_parser())
    comandos = _comandos_citados()
    assert len(comandos) > 20
    for comando in comandos:
        palabras = shlex.split(comando)
        assert palabras[1] in subcomandos, comando
        opciones = _opciones(subcomandos[palabras[1]])
        for palabra in palabras[2:]:
            if palabra.startswith("--"):
                assert palabra.split("=")[0] in opciones, comando
            elif palabra.startswith("-") and palabra != "-":
                assert palabra[:2] in opciones, comando  # -O1: opción corta con el valor pegado


def test_el_board_toml_del_manual_es_valido(tmp_path: Path) -> None:
    (bloque,) = [b for b in _bloques(MANUAL, "toml") if "[board]" in b]
    (tmp_path / "board.toml").write_text(bloque, encoding="utf-8")
    load_board(tmp_path / "board.toml")


@needs_zig
def test_el_ejemplo_del_manual_compila_y_termina(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDBOILED_CC", "zig")
    (ejemplo,) = [b for b in _bloques(MANUAL, "c") if "int main(void)" in b]
    (tmp_path / "ejemplo.c").write_text(ejemplo, encoding="utf-8")
    argumentos = ["run", str(tmp_path / "ejemplo.c"), "--headless", "--max-instructions", "5000000"]
    codigo = main(argumentos)
    assert codigo == 0
    assert "Iniciando..." in capsys.readouterr().out


def test_la_copia_de_docs_es_el_manual() -> None:
    copia = (ROOT / "docs" / "manual_de_uso.md").read_text(encoding="utf-8")
    assert copia == MANUAL.replace("](README.md)", "](../README.md)")
