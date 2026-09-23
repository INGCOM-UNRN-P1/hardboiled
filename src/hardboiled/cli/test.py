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


def case_from_args(args: argparse.Namespace) -> Case:
    uart = read_uart_input(args.uart_input).decode("utf-8", "replace") if args.uart_input else None
    return Case(
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
    )
    if args.suite and any(value is not None for value in single):
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
        detail = f"código {result.exit_code}" if result.outcome == "exited" else result.outcome
        print(f"{mark} {result.name} ({detail}, {result.instructions:,} instrucciones)")
        for failure in result.failures:
            print("      " + failure.replace("\n", "\n      "))
    passed = sum(result.passed for result in results)
    print(f"\n{passed}/{len(results)} casos correctos")
    return 0 if passed == len(results) else EXIT_FAILED
