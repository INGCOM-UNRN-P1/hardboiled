"""`hardboiled tutorial`: lecciones guiadas que se corrigen solas."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from hardboiled import paths
from hardboiled.buildcache import build_cached
from hardboiled.cli.build import compiler_preference
from hardboiled.cli.common import CliError, Subparsers, load_board_file, load_machine
from hardboiled.cli.test import print_results
from hardboiled.grading import Grader, SuiteError, load_suite
from hardboiled.resources import default_board_path
from hardboiled.sdk import runtime_for
from hardboiled.toolchain import BuildError, BuildOptions, ToolchainError, select_compiler
from hardboiled.tutorial import LESSON_FILES, Lesson, LessonError, find_lesson, lessons


def register(sub: Subparsers) -> None:
    parser = sub.add_parser(
        "tutorial", help="lecciones guiadas: LEDs, switches, UART, timer, ISR, depuración"
    )
    parser.set_defaults(func=cmd_list)
    actions = parser.add_subparsers(dest="tutorial_command")

    show = actions.add_parser("show", help="imprime la explicación y la consigna de una lección")
    show.add_argument("lesson", help="número o tema de la lección")
    show.set_defaults(func=cmd_show)

    start = actions.add_parser("start", help="copia el punto de partida de una lección")
    start.add_argument("lesson", help="número o tema de la lección")
    start.add_argument("--dest", help="directorio (por defecto leccion-NN-tema)")
    start.add_argument("--force", action="store_true", help="sobrescribir archivos existentes")
    start.set_defaults(func=cmd_start)

    check = actions.add_parser("check", help="compila tu solución y corre los casos de prueba")
    check.add_argument("lesson", help="número o tema de la lección")
    check.add_argument("--dir", help="directorio con tu main.c (por defecto leccion-NN-tema o .)")
    check.add_argument("--cc", help="compilador: auto, gcc, zig o una ruta")
    check.add_argument("-q", "--quiet", action="store_true", help="sólo el resumen")
    check.set_defaults(func=cmd_check)


def _lesson(key: str) -> Lesson:
    try:
        return find_lesson(key)
    except LessonError as exc:
        raise CliError(str(exc)) from exc


def cmd_list(_args: argparse.Namespace) -> int:
    print("Lecciones:")
    for lesson in lessons():
        print(f"  {lesson.number}. {lesson.title}  ({lesson.slug})")
    print("\nhardboiled tutorial start 1     copia el punto de partida a leccion-01-leds/")
    print("hardboiled tutorial show 1      explicación y consigna")
    print("hardboiled tutorial check 1     compila tu main.c y corre los casos de prueba")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    print(_lesson(args.lesson).text, end="")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    lesson = _lesson(args.lesson)
    dest = Path(args.dest or lesson.default_dir)
    dest.mkdir(parents=True, exist_ok=True)
    targets = [dest / name for name in (*LESSON_FILES, "casos.toml")]
    existing = [t for t in targets if t.exists()]
    if existing and not args.force:
        listed = ", ".join(str(p) for p in existing)
        raise CliError(f"ya existen {listed} (usá --force para sobrescribir)")
    for target in targets:
        shutil.copyfile(lesson.path / target.name, target)
    print(f"Lección {lesson.number}: {lesson.title}, en {dest}/")
    print(f"  consigna:  {dest / 'leccion.md'}")
    print(f"  probar:    hardboiled run {dest / 'main.c'}")
    check = f"hardboiled tutorial check {lesson.number}"
    print(f"  corregir:  {check}" + (f" --dir {dest}" if args.dest else ""))
    return 0


def _solution_dir(lesson: Lesson, given: str | None) -> Path:
    if given:
        return Path(given)
    default = Path(lesson.default_dir)
    return default if (default / "main.c").is_file() else Path(".")


def cmd_check(args: argparse.Namespace) -> int:
    lesson = _lesson(args.lesson)
    directory = _solution_dir(lesson, args.dir)
    sources = sorted(directory.glob("*.c"))
    if not sources:
        raise CliError(
            f"no hay archivos .c en {directory} "
            f"(¿hiciste `hardboiled tutorial start {lesson.number}`?)"
        )
    # Siempre la placa por defecto: las lecciones están pensadas para ella.
    board = load_board_file(default_board_path())
    options = BuildOptions(runtime=runtime_for(board, paths.cache_dir()), march=board.board.isa)
    try:
        compiler = select_compiler(compiler_preference(args))
        built = build_cached([s.resolve() for s in sources], options, compiler)
    except BuildError as exc:
        raise CliError(f"tu programa no compila:\n{exc.output}") from exc
    except ToolchainError as exc:
        raise CliError(str(exc)) from exc
    print(f"Lección {lesson.number}: {lesson.title} ({', '.join(s.name for s in sources)})\n")
    machine = load_machine(built.elf, board)
    grader = Grader(machine, board.board.clock_hz)
    try:
        results = [grader.run(case) for case in load_suite(lesson.suite)]
    except SuiteError as exc:
        raise CliError(str(exc)) from exc
    status = print_results(results, args.quiet)
    if status == 0:
        following = [other for other in lessons() if other.number == lesson.number + 1]
        if following:
            print(f"¡Muy bien! Seguí con: hardboiled tutorial start {following[0].number}")
        else:
            print("¡Muy bien! Terminaste el tutorial.")
    return status
