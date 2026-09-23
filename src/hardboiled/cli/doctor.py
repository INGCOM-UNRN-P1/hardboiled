"""`hardboiled doctor`: diagnóstico del entorno."""

from __future__ import annotations

import argparse

from hardboiled.cli.build import compiler_preference
from hardboiled.cli.common import Subparsers
from hardboiled.doctor import Status, run_checks

SYMBOLS = {Status.OK: "✔", Status.WARN: "⚠", Status.ERROR: "✘"}


def register(sub: Subparsers) -> None:
    parser = sub.add_parser(
        "doctor", help="verifica Python, emulador, runtime, compilador y terminal"
    )
    parser.add_argument("--cc", help="compilador a verificar (como en build)")
    parser.add_argument("--no-build", action="store_true", help="no compilar el programa de prueba")
    parser.set_defaults(func=cmd_doctor)


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = run_checks(compiler_preference(args), build=not args.no_build)
    width = max(len(check.name) for check in checks)
    for check in checks:
        print(f"{SYMBOLS[check.status]} {check.name:<{width}}  {check.detail}")
    errors = sum(check.status is Status.ERROR for check in checks)
    warnings = sum(check.status is Status.WARN for check in checks)
    print(f"\n{errors} error(es), {warnings} aviso(s)")
    return 1 if errors else 0
