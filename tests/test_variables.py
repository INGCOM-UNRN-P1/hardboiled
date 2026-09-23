"""Inspección de variables con DWARF: tipos, alcance y marcos."""

from __future__ import annotations

from hardboiled.core.events import VariableInfo
from hardboiled.core.machine import Machine
from tests.conftest import MachineFactory, line_of


def by_name(variables: tuple[VariableInfo, ...]) -> dict[str, VariableInfo]:
    return {v.name: v for v in variables}


def stopped_in_medir(make_machine: MachineFactory) -> Machine:
    machine, _ = make_machine("types")
    machine.debugger.toggle_line_breakpoint(line_of("types.c", "medir_loop"), "types.c")
    machine.debugger.continue_()
    return machine


def test_scalar_and_pointer_globals(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("types")
    machine.debugger.run_to_main()
    g = by_name(machine.debugger.global_variables())
    assert (g["corto"].type_name, g["corto"].value) == ("short", "-3")
    assert g["byte_suelto"].value == "65 'A'"
    assert g["bandera"].value == "true"
    assert g["saludo"].type_name == "const char *"
    assert g["saludo"].value.endswith('"hola"')
    assert g["contador_estatico"].value == "9"  # static de archivo


def test_arrays_structs_enums_and_bitfields(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("types")
    machine.debugger.run_to_main()
    g = by_name(machine.debugger.global_variables())
    matriz = g["matriz"]
    assert matriz.type_name == "int [2][3]"
    assert matriz.value == "{{1, 2, 3}, {4, 5, 6}}"
    assert matriz.children[1].children[2].path == "matriz[1][2]"

    fig = by_name(g["triangulo"].children)
    assert fig["nombre"].value == '"tri"'
    assert fig["vertices"].children[1].value == "{x = 4, y = 0}"
    assert fig["color"].value == "VERDE (5)"
    assert (fig["visible"].value, fig["capa"].value) == ("1", "7")
    assert fig["visible"].type_name == "unsigned int : 1"


def test_function_pointer_and_self_reference(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("types")
    debugger = machine.debugger
    debugger.run_to_line(line_of("types.c", "main_call"), "types.c")
    g = by_name(debugger.global_variables())
    assert g["operacion"].type_name == "int (*)(int, int)"
    assert g["operacion"].value.endswith("→ sumar")
    siguiente = by_name(g["triangulo"].children)["siguiente"]
    assert siguiente.type_name == "struct figura *"
    assert siguiente.value.endswith("→ triangulo")


def test_locals_parameters_and_block_scope(make_machine: MachineFactory) -> None:
    machine = stopped_in_medir(make_machine)
    local = by_name(machine.debugger.locals_of())
    assert list(local) == ["f", "escala", "perimetro", "i", "dx"]
    assert local["escala"].value == "2"
    assert local["f"].value.endswith("→ triangulo")
    assert local["i"].value == "0"
    # Fuera del for, `i` y `dx` ya no son visibles.
    machine.debugger.toggle_line_breakpoint(line_of("types.c", "medir_loop"), "types.c")
    machine.debugger.run_to_line(line_of("types.c", "medir_return"), "types.c")
    assert "i" not in by_name(machine.debugger.locals_of())


def test_locals_of_caller_frame(make_machine: MachineFactory) -> None:
    machine = stopped_in_medir(make_machine)
    frames = machine.debugger.backtrace()
    caller = by_name(machine.debugger.locals_of(frames[1]))
    assert caller["origen"].value == "{x = 10, y = -20}"
    assert caller["letra"].value == "122 'z'"


def test_variables_during_prologue_use_cfa(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("types")
    medir = machine.image.symbol_address("medir")
    assert medir is not None
    machine.debugger.toggle_address_breakpoint(medir)
    machine.debugger.continue_()  # prólogo sin ejecutar: s0 es todavía el de main
    frames = machine.debugger.backtrace()
    caller = by_name(machine.debugger.locals_of(frames[1]))
    assert caller["origen"].value == "{x = 10, y = -20}"


def test_program_without_user_debug_info_has_no_variables(
    make_machine: MachineFactory,
) -> None:
    machine, _ = make_machine("basic")
    assert machine.debugger.locals_of() == ()  # en _start (crt0), sin variables


def test_pointers_can_be_dereferenced(make_machine: MachineFactory) -> None:
    machine = stopped_in_medir(make_machine)
    f = by_name(machine.debugger.locals_of())["f"]
    (target,) = f.children
    assert target.name == "*f" and target.type_name == "struct figura"
    assert by_name(target.children)["nombre"].value == '"tri"'
    # Autorreferencia (triangulo.siguiente = &triangulo): la profundidad está acotada.
    node = target
    depth = 0
    while node.children:
        node = next((c for c in node.children if c.name in ("siguiente", "*siguiente")), node)
        if not node.children or depth > 20:
            break
        depth += 1
    assert depth < 20
