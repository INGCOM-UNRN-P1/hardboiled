"""Árbol de variables: locales del marco elegido y globales del programa.

Conserva qué nodos están expandidos entre suspensiones (por la ruta estable de
cada valor) y resalta los valores que cambiaron desde la suspensión anterior.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from hardboiled.core.events import VariableInfo

LOCALS = "locals"
GLOBALS = "globals"


class VariablesView(Tree[VariableInfo | None]):
    DEFAULT_CSS = """
    VariablesView { height: auto; max-height: 30; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("variables", id=id)
        self.show_root = False
        self.guide_depth = 2
        self._expanded: set[str] = {LOCALS}
        self._previous: dict[str, str] = {}
        self._current: dict[str, str] = {}
        self._locals: tuple[VariableInfo, ...] = ()
        self._globals: tuple[VariableInfo, ...] = ()
        self._locals_label = "Locales"
        self._section_keys: dict[int, str] = {}

    # ----------------------------------------------------------------- datos

    def set_variables(
        self,
        locals_: tuple[VariableInfo, ...],
        globals_: tuple[VariableInfo, ...],
        function: str | None,
    ) -> None:
        """Nueva suspensión: los cambios se comparan contra la anterior."""
        self._previous = self._current
        self._locals, self._globals = locals_, globals_
        self._locals_label = f"Locales de {function}" if function else "Locales"
        self._current = {}
        self._collect(locals_, LOCALS)
        self._collect(globals_, GLOBALS)
        self._rebuild()

    def set_frame_locals(self, locals_: tuple[VariableInfo, ...], label: str) -> None:
        """Locales de otro marco: no cuentan como cambios."""
        self._locals = locals_
        self._locals_label = f"Locales de {label}"
        self._rebuild()

    def _collect(self, variables: tuple[VariableInfo, ...], section: str) -> None:
        for variable in variables:
            self._current[f"{section}:{variable.path}"] = variable.value
            self._collect(variable.children, section)

    # ----------------------------------------------------------------- árbol

    def _rebuild(self) -> None:
        self.clear()
        for key, label, variables in (
            (LOCALS, self._locals_label, self._locals),
            (GLOBALS, "Globales", self._globals),
        ):
            section = self.root.add(
                Text(label, style="bold"), data=None, expand=key in self._expanded
            )
            self._section_keys[id(section)] = key
            if not variables:
                section.add_leaf(Text("(ninguna)", style="dim"))
            for variable in variables:
                self._add(section, variable, key)

    def _add(self, parent: TreeNode[VariableInfo | None], variable: VariableInfo, key: str) -> None:
        label = Text(variable.name, style="bold cyan")
        label.append(f": {variable.type_name}", style="dim")
        changed = self._previous and self._previous.get(f"{key}:{variable.path}") not in (
            None,
            variable.value,
        )
        label.append(" = ")
        label.append(variable.value, style="bold yellow" if changed else "")
        if variable.children:
            node = parent.add(
                label, data=variable, expand=f"{key}:{variable.path}" in self._expanded
            )
            self._section_keys[id(node)] = key
            for child in variable.children:
                self._add(node, child, key)
        else:
            parent.add_leaf(label, data=variable)

    def clear(self) -> VariablesView:
        super().clear()
        self._section_keys = {}
        return self

    def _node_key(self, node: TreeNode[VariableInfo | None]) -> str | None:
        section = self._section_keys.get(id(node))
        if section is None:
            return None
        return section if node.data is None else f"{section}:{node.data.path}"

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[VariableInfo | None]) -> None:
        key = self._node_key(event.node)
        if key is not None:
            self._expanded.add(key)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[VariableInfo | None]) -> None:
        key = self._node_key(event.node)
        if key is not None:
            self._expanded.discard(key)
