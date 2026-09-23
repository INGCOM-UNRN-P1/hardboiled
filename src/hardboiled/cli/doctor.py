"""`hardboiled doctor`: diagnóstico del entorno."""

from __future__ import annotations

import argparse

from hardboiled.cli.build import compiler_preference
from hardboiled.cli.common import Subparsers, print_json
from hardboiled.doctor import Status, run_checks

SYMBOLS = {Status.OK: "✔", Status.WARN: "⚠", Status.ERROR: "✘"}


def register(sub: Subparsers) -> None:
    parser = sub.add_parser(
        "doctor", help="verifica Python, emulador, runtime, compilador y terminal"
    )
    parser.add_argument("--cc", help="compilador a verificar (como en build)")
    parser.add_argument("--no-build", action="store_true", help="no compilar el programa de prueba")
    parser.add_argument("--json", action="store_true", help="resultado en JSON")
    parser.set_defaults(func=cmd_doctor)


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = run_checks(compiler_preference(args), build=not args.no_build)
    errors = sum(check.status is Status.ERROR for check in checks)
    warnings = sum(check.status is Status.WARN for check in checks)
    if args.json:
        print_json(
            {
                "checks": [
                    {"name": c.name, "status": c.status.name.lower(), "detail": c.detail}
                    for c in checks
                ],
                "errors": errors,
                "warnings": warnings,
            }
        )
        return 1 if errors else 0
    width = max(len(check.name) for check in checks)
    for check in checks:
        print(f"{SYMBOLS[check.status]} {check.name:<{width}}  {check.detail}")
    print(f"\n{errors} error(es), {warnings} aviso(s)")
    return 1 if errors else 0
