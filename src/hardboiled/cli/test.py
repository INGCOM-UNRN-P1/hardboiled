"""`hardboiled test`: ejecuta casos con salida esperada (corrección automática)."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from hardboiled.cli.build import add_build_options
from hardboiled.cli.common import (
    CliError,
    Subparsers,
    board_from,
    load_machine,
    parse_int,
    print_json,
)
from hardboiled.cli.run import read_uart_input, resolve_program
from hardboiled.grading import Case, CaseResult, Grader, SuiteError, load_suite
from hardboiled.script import Step

EXIT_FAILED = 1


def register(sub: Subparsers) -> None:
    parser = sub.add_parser(
        "test",
        help="ejecuta el programa con entradas dadas y compara la salida esperada",
        description=(
            "Corre el programa sin interfaz y verifica la salida por la UART, el código "
            "de salida o la trampa esperada. Un caso se arma con las opciones; varios, "
            "con --suite casos.toml. Termina con 0 si todos pasan y 1 si alguno falla."
        ),
    )
    parser.add_argument("program", nargs="+", help="un ELF, o fuentes .c/.s que se compilan")
    parser.add_argument("--suite", metavar="ARCHIVO", help="TOML con varios casos [[case]]")
    parser.add_argument("--board", help="board.toml (por defecto ./board.toml si existe)")
    parser.add_argument("--switches", type=parse_int, help="estado de los switches")
    parser.add_argument("--uart-input", metavar="ARCHIVO", help="bytes que llegan por la UART")
    parser.add_argument("--script", metavar="ARCHIVO", help="guion TOML de estímulos")
    parser.add_argument(
        "--press",
        metavar="BOTÓN@MOMENTO",
        action="append",
        default=[],
        help="aprieta un botón en un ciclo (0@20000) o en un momento (0@5ms); repetible",
    )
    parser.add_argument(
        "--hasta",
        metavar="MOMENTO",
        help="corre hasta ese ciclo (o 50ms) y juzga ahí: para firmware que no termina",
    )
    parser.add_argument("--max-instructions", type=parse_int, help="cuota de instrucciones")
    parser.add_argument("--expect-uart", metavar="ARCHIVO", help="salida exacta esperada")
    parser.add_argument("--expect-exit", type=int, help="código de salida esperado")
    parser.add_argument(
        "--expect-trap", metavar="TIPO", help="trampa esperada (p. ej. null-pointer, o *)"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="sólo el resumen")
    parser.add_argument("--json", action="store_true", help="resultados en JSON")
    add_build_options(parser)
    parser.set_defaults(func=cmd_test)


def parse_momento(texto: str) -> tuple[int | None, float | None]:
    """`20000` (ciclos) o `5ms` → (20000, None) o (None, 5.0)."""
    texto = texto.strip().lower()
    try:
        if texto.endswith("ms"):
            return None, float(texto[:-2])
        return parse_int(texto), None
    except (ValueError, argparse.ArgumentTypeError) as exc:
        raise CliError(
            f"momento inválido: {texto!r} (un número de ciclos o algo como 5ms)"
        ) from exc


def steps_from_press(valores: list[str]) -> list[Step]:
    pasos = []
    for valor in valores:
        boton, sep, momento = valor.partition("@")
        if not sep or not boton.strip().isdigit():
            raise CliError(
                f"--press {valor!r}: se espera BOTÓN@MOMENTO, por ejemplo 0@20000 o 1@5ms"
            )
        ciclo, ms = parse_momento(momento)
        pasos.append(Step(press=[int(boton)], cycle=ciclo, ms=ms))
    return pasos


def case_from_args(args: argparse.Namespace) -> Case:
    uart = read_uart_input(args.uart_input).decode("utf-8", "replace") if args.uart_input else None
    hasta_ciclo, hasta_ms = parse_momento(args.hasta) if args.hasta else (None, None)
    if args.press and args.script:
        raise CliError("--press y --script se excluyen: agregá la pulsación al guion")
    return Case(
        at=steps_from_press(args.press),
        until_cycle=hasta_ciclo,
        until_ms=hasta_ms,
        name=Path(args.program[0]).name,
        switches=args.switches,
        uart_input=uart,
        script=Path(args.script) if args.script else None,
        max_instructions=args.max_instructions,
        expect_uart_file=Path(args.expect_uart) if args.expect_uart else None,
        expect_exit=args.expect_exit,
        expect_trap=args.expect_trap,
    )


def run_cases(args: argparse.Namespace) -> list[CaseResult]:
    single = (
        args.switches,
        args.uart_input,
        args.script,
        args.expect_uart,
        args.expect_exit,
        args.expect_trap,
        args.hasta,
    )
    if args.suite and (any(value is not None for value in single) or args.press):
        raise CliError("con --suite, las entradas y lo esperado se indican en cada caso")
    try:
        cases = load_suite(args.suite) if args.suite else [case_from_args(args)]
    except SuiteError as exc:
        raise CliError(str(exc)) from exc
    board = board_from(args.board)
    if args.suite and args.max_instructions is not None:
        cases = [
            c
            if c.max_instructions
            else c.model_copy(update={"max_instructions": args.max_instructions})
            for c in cases
        ]
    machine = load_machine(resolve_program(args), board)
    grader = Grader(machine, board.board.clock_hz)
    try:
        return [grader.run(case) for case in cases]
    except SuiteError as exc:
        raise CliError(str(exc)) from exc


def cmd_test(args: argparse.Namespace) -> int:
    results = run_cases(args)
    passed = sum(result.passed for result in results)
    status = 0 if passed == len(results) else EXIT_FAILED
    if args.json:
        print_json({"passed": passed, "total": len(results), "cases": [asdict(r) for r in results]})
        return status
    return print_results(results, args.quiet)


def print_results(results: list[CaseResult], quiet: bool = False) -> int:
    """Informe de los casos para la terminal. Devuelve el código de salida."""
    for result in results:
        if result.passed and quiet:
            continue
        mark = "ok   " if result.passed else "FALLA"
        detail = (
            f"código {result.exit_code}"
            if result.outcome == "exited"
            else f"hasta el ciclo {result.cycles:,}"
            if result.outcome == "until"
            else result.outcome
        )
        if result.checks:
            detail += f", {result.checks} controles"
        print(f"{mark} {result.name} ({detail}, {result.instructions:,} instrucciones)")
        for failure in result.failures:
            print("      " + failure.replace("\n", "\n      "))
    passed = sum(result.passed for result in results)
    print(f"\n{passed}/{len(results)} casos correctos")
    return 0 if passed == len(results) else EXIT_FAILED
