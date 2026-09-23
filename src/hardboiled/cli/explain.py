"""`hardboiled explain`: la guía de cada trampa o aviso."""

from __future__ import annotations

import argparse

from hardboiled.cli.common import CliError, Subparsers
from hardboiled.core.hints import HINTS, explain


def register(sub: Subparsers) -> None:
    parser = sub.add_parser("explain", help="explica una trampa o un aviso (sin tipo: la lista)")
    parser.add_argument("kind", nargs="?", help="tipo, p. ej. null-pointer o stack-overflow")
    parser.set_defaults(func=cmd_explain)


def cmd_explain(args: argparse.Namespace) -> int:
    if args.kind is None:
        print("Tipos de trampa y aviso (hardboiled explain TIPO):")
        width = max(len(kind) for kind in HINTS)
        for kind, hint in HINTS.items():
            print(f"  {kind:<{width}}  {hint}")
        return 0
    text = explain(args.kind)
    if text is None:
        raise CliError(f"no hay explicación para {args.kind!r}; tipos: {', '.join(HINTS)}")
    print(text)
    return 0
