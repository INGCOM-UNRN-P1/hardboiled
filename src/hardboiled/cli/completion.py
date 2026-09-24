"""`hardboiled completion`: scripts de autocompletado para bash, zsh y fish.

Se generan recorriendo el parser de argparse, así cualquier subcomando u
opción nueva queda incluida sin mantener listas a mano.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from hardboiled import resources
from hardboiled.cli.common import Subparsers

FILE_PATTERN = "c|s|S|h|elf|toml"
# Subcomandos (o subacciones) cuyo argumento es el nombre de un ejemplo.
EXAMPLE_COMMANDS = ("demo", "show", "copy")


@dataclass
class CommandSpec:
    name: str
    help: str
    options: list[str] = field(default_factory=list)
    children: dict[str, CommandSpec] = field(default_factory=dict)


def _spec(name: str, parser: argparse.ArgumentParser, help_text: str = "") -> CommandSpec:
    spec = CommandSpec(name, help_text)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
            for child_name, child in action.choices.items():
                spec.children[child_name] = _spec(child_name, child, helps.get(child_name, ""))
        else:
            spec.options.extend(o for o in action.option_strings if o.startswith("--"))
    return spec


def build_spec() -> CommandSpec:
    from hardboiled.cli import build_parser

    return _spec("hardboiled", build_parser())


def bash_script(spec: CommandSpec) -> str:
    examples = " ".join(resources.example_names())
    cases = []
    for name, command in spec.children.items():
        children = " ".join(command.children)
        options = " ".join(command.options)
        nested = []
        for child_name, child in command.children.items():
            nested.append(f'                {child_name}) opts="{" ".join(child.options)}" ;;')
        nested_case = "\n".join(nested)
        cases.append(
            f"""        {name})
            opts="{options}"
            subs="{children}"
            if [[ -n "$sub2" ]]; then
                case "$sub2" in
{nested_case}
                esac
                subs=""
            fi ;;"""
        )
    joined_cases = "\n".join(cases)
    top = " ".join(spec.children)
    # `case` admite alternativas sin extglob: "demo …", "examples show", etc.
    example_patterns = "|".join(
        pattern for name in EXAMPLE_COMMANDS for pattern in (f'"{name} "*', f'*" {name}"')
    )
    return f"""# Autocompletado de hardboiled para bash (también el 3.2 de macOS).
# Instalar:  hardboiled completion bash > ~/.local/share/bash-completion/completions/hardboiled
# extglob (para el patrón de archivos de compgen -X) tiene que estar activo antes
# de leer la función: bash 3.2 no lo activa solo.
shopt -s extglob
_hardboiled() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}"
    local sub="" sub2="" opts="" subs="" word i
    for ((i = 1; i < COMP_CWORD; i++)); do
        word="${{COMP_WORDS[i]}}"
        [[ "$word" == -* ]] && continue
        if [[ -z "$sub" ]]; then sub="$word"; elif [[ -z "$sub2" ]]; then sub2="$word"; fi
    done
    if [[ -z "$sub" ]]; then
        COMPREPLY=($(compgen -W "{top} --help --version" -- "$cur"))
        return
    fi
    case "$sub" in
{joined_cases}
    esac
    if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "$opts" -- "$cur"))
    elif [[ -n "$subs" ]]; then
        COMPREPLY=($(compgen -W "$subs" -- "$cur"))
    else
        case "$sub $sub2" in
            {example_patterns})
                COMPREPLY=($(compgen -W "{examples}" -- "$cur")) ;;
            *)
                COMPREPLY=($(compgen -f -X '!*.@({FILE_PATTERN})' -- "$cur")
                           $(compgen -d -- "$cur")) ;;
        esac
    fi
}}
complete -o filenames -F _hardboiled hardboiled
"""


def zsh_script(spec: CommandSpec) -> str:
    return (
        "# Autocompletado de hardboiled para zsh (reutiliza el de bash).\n"
        "# Instalar:  hardboiled completion zsh > ~/.zfunc/_hardboiled.zsh y cargarlo desde\n"
        "# ~/.zshrc con: source ~/.zfunc/_hardboiled.zsh\n"
        "autoload -U +X bashcompinit && bashcompinit\n" + bash_script(spec)
    )


def _fish_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def fish_script(spec: CommandSpec) -> str:
    lines = [
        "# Autocompletado de hardboiled para fish.",
        "# Instalar:  hardboiled completion fish > ~/.config/fish/completions/hardboiled.fish",
        "complete -c hardboiled -f",
    ]
    top = " ".join(spec.children)
    for name, command in spec.children.items():
        lines.append(
            f"complete -c hardboiled -n 'not __fish_seen_subcommand_from {top}' "
            f"-a {name} -d '{_fish_escape(command.help)}'"
        )
        for option in command.options:
            lines.append(
                f"complete -c hardboiled -n '__fish_seen_subcommand_from {name}' "
                f"-l {option.removeprefix('--')}"
            )
        children = " ".join(command.children)
        for child_name, child in command.children.items():
            lines.append(
                f"complete -c hardboiled -n '__fish_seen_subcommand_from {name}; "
                f"and not __fish_seen_subcommand_from {children}' "
                f"-a {child_name} -d '{_fish_escape(child.help)}'"
            )
    examples = " ".join(resources.example_names())
    lines.append(
        "complete -c hardboiled -n '__fish_seen_subcommand_from "
        f"{' '.join(EXAMPLE_COMMANDS)}' -a '{examples}'"
    )
    for file_command in ("run", "build", "info", "validate"):
        lines.append(
            f"complete -c hardboiled -n '__fish_seen_subcommand_from {file_command}' "
            "-a '(__fish_complete_suffix .c .s .h .elf .toml)'"
        )
    return "\n".join(lines) + "\n"


GENERATORS = {"bash": bash_script, "zsh": zsh_script, "fish": fish_script}


def register(sub: Subparsers) -> None:
    parser = sub.add_parser("completion", help="imprime el script de autocompletado de la shell")
    parser.add_argument("shell", choices=sorted(GENERATORS))
    parser.set_defaults(func=cmd_completion)


def cmd_completion(args: argparse.Namespace) -> int:
    print(GENERATORS[args.shell](build_spec()), end="")
    return 0
