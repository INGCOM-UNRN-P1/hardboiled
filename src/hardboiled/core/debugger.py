"""Control de flujo a nivel de código fuente: breakpoints, Step Into, Step Over y Continue.

Cada operación se traduce en una condición `stop_check(pc)` que la CPU evalúa
antes de ejecutar cada instrucción. Los pasos no se detienen dentro de una
rutina de interrupción que empezó durante el paso (salvo breakpoints), de modo
que una IRQ asíncrona no "secuestra" el step del usuario.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from hardboiled.core.cpu import Cpu, StopInfo, StopReason
from hardboiled.core.disasm import Instruction, decode, disassemble
from hardboiled.core.dwarf import LineTable, SourceLocation
from hardboiled.core.elf import ElfImage
from hardboiled.core.events import VariableInfo
from hardboiled.core.expressions import Evaluator, ExpressionError, tokenize
from hardboiled.core.unwind import CallFrameTable, Frame, Unwinder
from hardboiled.core.variables import CType, Formatter, FrameContext, Storage, VariableTable


class DebuggerError(Exception):
    pass


@dataclass
class BreakpointCondition:
    """Condición C y/o cantidad de pasadas de un breakpoint."""

    expression: str | None = None
    hit_target: int | None = None  # detener recién en la pasada N (y las siguientes)
    hits: int = 0

    def describe(self) -> str:
        parts = []
        if self.expression:
            parts.append(f"si {self.expression}")
        if self.hit_target:
            parts.append(f"desde la pasada {self.hit_target}")
        return ", ".join(parts)


@dataclass
class Watchpoint:
    watch_id: int
    expression: str
    address: int
    ctype: CType
    # Marco dueño si la expresión usa locales: al terminar esa función se elimina.
    scope_cfa: int | None = None
    scope_function: str | None = None


class Debugger:
    def __init__(
        self,
        cpu: Cpu,
        image: ElfImage,
        lines: LineTable,
        cfi: CallFrameTable | None = None,
        variables: VariableTable | None = None,
    ) -> None:
        self.cpu = cpu
        self.image = image
        self.lines = lines
        self.unwinder = Unwinder(image, lines, cfi or CallFrameTable.empty())
        self.variables = variables or VariableTable.empty()
        self.formatter = Formatter(self._read_for_display, self.describe_address)
        self._watches: dict[int, Watchpoint] = {}
        self._line_breakpoints: dict[tuple[str, int], int] = {}
        self._address_breakpoints: set[int] = set()
        self._conditions: dict[int, BreakpointCondition] = {}
        self._breakpoint_note: str | None = None
        # Conjunto vivo: se consulta en cada instrucción y puede cambiar durante un Continue.
        self._active: set[int] = set()

    # ------------------------------------------------------------ breakpoints

    @property
    def line_breakpoints(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._line_breakpoints)

    @property
    def line_breakpoint_addresses(self) -> dict[tuple[str, int], int]:
        return dict(self._line_breakpoints)

    @property
    def address_breakpoints(self) -> frozenset[int]:
        return frozenset(self._address_breakpoints)

    def is_breakpoint(self, pc: int | None = None) -> bool:
        return (self.cpu.pc if pc is None else pc) in self._active

    def _rebuild(self) -> None:
        self._active.clear()
        self._active.update(self._line_breakpoints.values())
        self._active.update(self._address_breakpoints)

    def toggle_line_breakpoint(self, line: int, source_file: str | None = None) -> bool:
        """Pone o quita un breakpoint. Devuelve True si quedó puesto."""
        file, effective_line, address = self.resolve_line(line, source_file)
        key = (file, effective_line)
        if key in self._line_breakpoints:
            self._conditions.pop(self._line_breakpoints.pop(key), None)
            placed = False
        else:
            self._line_breakpoints[key] = address
            placed = True
        self._rebuild()
        return placed

    @property
    def conditions(self) -> dict[int, BreakpointCondition]:
        return dict(self._conditions)

    def set_condition(
        self,
        line: int,
        source_file: str | None = None,
        expression: str | None = None,
        hit_target: int | None = None,
    ) -> BreakpointCondition | None:
        """Pone (o crea) un breakpoint condicional en una línea; sin condición la quita.

        La expresión se valida ahora en el marco actual sólo si es sintácticamente
        inválida; que use variables todavía no visibles es válido.
        """
        file, effective, address = self.resolve_line(line, source_file)
        expression = (expression or "").strip() or None
        if expression is not None:
            try:
                tokenize(expression)
            except ExpressionError as exc:
                raise DebuggerError(f"condición inválida: {exc}") from exc
        if hit_target is not None and hit_target < 1:
            raise DebuggerError("la cantidad de pasadas debe ser 1 o más")
        self._line_breakpoints[(file, effective)] = address
        self._rebuild()
        if expression is None and hit_target is None:
            self._conditions.pop(address, None)
            return None
        condition = BreakpointCondition(expression, hit_target)
        self._conditions[address] = condition
        return condition

    def _breakpoint_fires(self, pc: int) -> bool:
        """Se evalúa en el hook de la CPU al llegar a un breakpoint."""
        condition = self._conditions.get(pc)
        if condition is None:
            self._breakpoint_note = None
            return True
        if condition.expression is not None:
            try:
                if not self.evaluator().integer(condition.expression):
                    return False
            except ExpressionError as exc:
                self._breakpoint_note = f"no se pudo evaluar la condición: {exc}"
                return True
        condition.hits += 1
        if condition.hit_target is not None and condition.hits < condition.hit_target:
            return False
        detail = [f"{condition.expression} es verdadera"] if condition.expression else []
        detail.append(f"pasada {condition.hits}")
        self._breakpoint_note = "breakpoint condicional: " + ", ".join(detail)
        return True

    def resolve_line(self, line: int, source_file: str | None = None) -> tuple[str, int, int]:
        """(archivo, línea efectiva, dirección) de una línea, o la siguiente con código."""
        file = self._resolve_file(source_file)
        resolved = self.lines.address_for_line(file, line)
        if resolved is None:
            raise DebuggerError(f"no hay código ejecutable en {file}:{line} ni después")
        return file, resolved[0], resolved[1]

    def toggle_address_breakpoint(self, address: int) -> bool:
        if address in self._address_breakpoints:
            self._address_breakpoints.discard(address)
            self._conditions.pop(address, None)
            placed = False
        else:
            self._address_breakpoints.add(address)
            placed = True
        self._rebuild()
        return placed

    def _resolve_file(self, source_file: str | None) -> str:
        if source_file is None:
            current = self.location()
            if current is not None:
                return current.file
            if len(self.lines.user_files) == 1:
                return self.lines.user_files[0]
            raise DebuggerError("indicá el archivo fuente del breakpoint")
        resolved = self.lines.resolve_file(source_file)
        if resolved is None:
            raise DebuggerError(f"el binario no tiene información de líneas de {source_file}")
        return resolved

    # ---------------------------------------------------------------- estado

    def location(self, pc: int | None = None) -> SourceLocation | None:
        return self.lines.lookup(self.cpu.pc if pc is None else pc)

    def function(self, pc: int | None = None) -> str | None:
        return self.image.function_at(self.cpu.pc if pc is None else pc)

    def backtrace(self) -> list[Frame]:
        """Pila de llamadas: el marco 0 es la función en curso."""
        return self.unwinder.unwind(self.cpu)

    # ---------------------------------------------------------- desensamblado

    def instruction_at(self, pc: int) -> Instruction | None:
        data = self.cpu.read_memory(pc, 4) or self.cpu.read_memory(pc, 2)
        return decode(pc, data, self.image.describe) if data else None

    def disassemble_around(self, pc: int | None = None, limit: int = 400) -> list[Instruction]:
        """La función que contiene `pc` completa o, sin función, desde la etiqueta previa."""
        pc = self.cpu.pc if pc is None else pc
        read = self.cpu.read_memory
        function = self.image.function_at(pc)
        if function is not None:
            symbol = self.image.symbols[function]
            start, end = symbol.address, symbol.address + symbol.size
        else:
            label = self.image.nearest_symbol(pc)
            start = pc - label[1] if label is not None and label[1] < 0x400 else pc
            end = pc + 64
        if (end - start) // 2 > limit:  # funciones enormes: una ventana alrededor del PC
            start = max(start, pc - limit)
            end = min(end, pc + limit)
        instructions = disassemble(read, start, end, self.image.describe, limit)
        if pc not in {i.address for i in instructions}:
            # Arrancó a mitad de una instrucción (datos en .text): se desensambla desde el PC.
            instructions = disassemble(read, pc, pc + 64, self.image.describe, limit)
        return instructions

    # ------------------------------------------------------------- variables

    def _read_for_display(self, address: int, size: int) -> bytes | None:
        return self.cpu.read_memory(address, size)

    def frame_context(self, frame: Frame | None = None) -> FrameContext:
        """Contexto para evaluar ubicaciones: el marco 0 ve todos los registros."""
        if frame is None or frame.index == 0:
            regs = {index: self.cpu.read_register(index) for index in range(32)}
            cfa = frame.cfa if frame is not None else self.unwinder.current_cfa(self.cpu)
            return FrameContext(self.cpu.pc, cfa, regs)
        return FrameContext(frame.site, frame.cfa, dict(frame.regs))

    def locals_of(self, frame: Frame | None = None) -> tuple[VariableInfo, ...]:
        context = self.frame_context(frame)
        return tuple(
            self.formatter.variable(
                decl.name, decl.ctype, self.variables.storage(decl, context), context.regs
            )
            for decl in self.variables.locals_at(context.pc)
        )

    def global_variables(self) -> tuple[VariableInfo, ...]:
        return tuple(
            self.formatter.variable(decl.name, decl.ctype, self.variables.storage(decl, None), {})
            for decl in self.variables.globals
        )

    def describe_address(self, address: int) -> str | None:
        """Nombre de lo que hay en una dirección: función, variable global o elemento."""
        if self.image.function_at(address) is not None:
            return self.image.describe(address)
        for decl in self.variables.globals:
            storage = self.variables.storage(decl, None)
            if storage is None or storage.address is None:
                continue
            offset = address - storage.address
            if 0 <= offset < max(decl.ctype.size, 1):
                if offset == 0:
                    return decl.name
                element = decl.ctype.target
                if decl.ctype.kind == "array" and element is not None and element.size:
                    index, rest = divmod(offset, element.size)
                    return f"{decl.name}[{index}]" + (f"+{rest}" if rest else "")
                return f"{decl.name}+{offset}"
        return None

    # ----------------------------------------------------------- watchpoints

    @property
    def watchpoints(self) -> tuple[Watchpoint, ...]:
        return tuple(self._watches.values())

    def evaluator(self, frame: Frame | None = None) -> Evaluator:
        context = self.frame_context(frame)
        return Evaluator(self.variables, self.cpu.read_memory, context, context.pc)

    def evaluate(self, expression: str) -> str:
        """Valor de una expresión C en el marco actual, formateado."""
        try:
            evaluator = self.evaluator()
            value = evaluator.evaluate(expression)
            if value.address is not None:
                return self.formatter.variable(
                    expression, value.ctype, Storage(value.address), {}
                ).value
            return str(evaluator.load(value))
        except ExpressionError as exc:
            raise DebuggerError(str(exc)) from exc

    def add_watchpoint(self, expression: str) -> Watchpoint:
        expression = expression.strip()
        try:
            evaluator = self.evaluator()
            value = evaluator.evaluate(expression)
        except ExpressionError as exc:
            raise DebuggerError(str(exc)) from exc
        if value.address is None:
            raise DebuggerError(
                f"{expression!r} no es una variable en memoria: no se puede vigilar"
            )
        size = value.ctype.size
        if size <= 0:
            raise DebuggerError(f"{expression!r} no tiene tamaño conocido")
        try:
            watch_id = self.cpu.add_watch(value.address, size)
        except ValueError as exc:
            raise DebuggerError(f"{expression}: {exc}") from exc
        scope_cfa = scope_function = None
        if evaluator.used_locals:
            frames = self.backtrace()
            if frames:
                scope_cfa, scope_function = frames[0].cfa, frames[0].function
        watch = Watchpoint(
            watch_id, expression, value.address, value.ctype, scope_cfa, scope_function
        )
        self._watches[watch_id] = watch
        return watch

    def remove_watchpoint(self, expression: str) -> bool:
        for watch in list(self._watches.values()):
            if watch.expression == expression.strip():
                self.cpu.remove_watch(watch.watch_id)
                del self._watches[watch.watch_id]
                return True
        return False

    def toggle_watchpoint(self, expression: str) -> bool:
        """Pone o quita un watchpoint. Devuelve True si quedó puesto."""
        if self.remove_watchpoint(expression):
            return False
        self.add_watchpoint(expression)
        return True

    def _prune_watchpoints(self) -> list[str]:
        """Quita los watchpoints de locales cuya función ya terminó."""
        scoped = [w for w in self._watches.values() if w.scope_cfa is not None]
        if not scoped:
            return []
        alive = {(frame.cfa, frame.function) for frame in self.backtrace()}
        removed = []
        for watch in scoped:
            if (watch.scope_cfa, watch.scope_function) not in alive:
                self.cpu.remove_watch(watch.watch_id)
                del self._watches[watch.watch_id]
                removed.append(watch.expression)
        return removed

    def _describe_watch_hit(self, stop: StopInfo) -> StopInfo:
        hit = stop.watch
        if hit is None:
            return stop
        watch = self._watches.get(hit.watch_id)
        if watch is None:
            return stop
        ctype = watch.ctype
        if ctype.kind in ("base", "pointer", "enum") and ctype.size <= 8:
            change = (
                f"{self.formatter.scalar(ctype, hit.old)} → {self.formatter.scalar(ctype, hit.new)}"
            )
        else:
            change = "cambió su contenido"
        location = self.lines.lookup(hit.pc)
        where = (
            f" (escrito en {location.file.rsplit('/', 1)[-1]}:{location.line})" if location else ""
        )
        return replace(stop, message=f"watchpoint {watch.expression}: {change}{where}")

    # ------------------------------------------------------------- ejecución

    def _run(self, predicate: Callable[[int], bool]) -> StopInfo:
        stop = self._run_raw(predicate)
        stop = self._describe_watch_hit(stop)
        if self._breakpoint_note and stop.reason is StopReason.BREAK and not stop.message:
            stop = replace(stop, message=self._breakpoint_note)
        removed = self._prune_watchpoints()
        if removed and stop.reason is StopReason.BREAK:
            note = "watchpoint eliminado al salir de su función: " + ", ".join(removed)
            stop = replace(stop, message=f"{stop.message}; {note}" if stop.message else note)
        return stop

    def _run_raw(self, predicate: Callable[[int], bool]) -> StopInfo:
        breakpoints = self._active
        cpu = self.cpu
        start_pc = cpu.pc
        start_count = cpu.instructions

        def check(pc: int) -> bool:
            # No volver a detenerse en el breakpoint desde el que se reanuda: la
            # primera instrucción se evalúa (Step Over detecta llamadas) pero no
            # detiene. Se decide por el contador y no por el PC para que un
            # `j .` (salto a sí mismo) no quede eximido para siempre.
            if pc == start_pc and cpu.instructions == start_count:
                predicate(pc)
                return False
            return (pc in breakpoints and self._breakpoint_fires(pc)) or predicate(pc)

        self._breakpoint_note = None
        self.cpu.stop_check = check
        try:
            return self.cpu.run()
        finally:
            self.cpu.stop_check = None

    def continue_(self) -> StopInfo:
        return self._run(lambda pc: False)

    def run_to(self, address: int) -> StopInfo:
        return self._run(lambda pc: pc == address)

    def run_to_line(self, line: int, source_file: str | None = None) -> StopInfo:
        """Ejecuta hasta la línea indicada (o la siguiente con código) sin dejar breakpoint.

        Los breakpoints del camino detienen antes, como en cualquier Continue.
        """
        return self.run_to(self.resolve_line(line, source_file)[2])

    def run_to_main(self) -> StopInfo | None:
        """Ejecuta el arranque (crt0) y se detiene en la primera línea del cuerpo de main()."""
        main = self.image.symbol_address("main")
        if main is None:
            return None
        stop = self.run_to(main)
        if stop.reason is StopReason.BREAK and self.location() is not None:
            stop = self.step_into()  # saltea el prólogo (la línea de la llave de apertura)
        return stop

    def step_instruction(self) -> StopInfo:
        """Ejecuta exactamente una instrucción de máquina (si llega una IRQ, se entra a ella)."""
        cpu = self.cpu
        start = cpu.instructions
        return self._run(lambda pc: cpu.instructions > start)

    def step_into(self) -> StopInfo:
        """Ejecuta hasta llegar a otra línea de C (entrando en las funciones llamadas)."""
        pic = self.cpu.pic
        lookup = self.lines.lookup
        start = self.location()
        started_in_isr = pic.in_isr

        def reached_new_line(pc: int) -> bool:
            if pic.in_isr and not started_in_isr:
                return False
            location = lookup(pc)
            return location is not None and location != start

        return self._run(reached_new_line)

    def step_out(self) -> StopInfo:
        """Ejecuta hasta volver a la función llamadora (como `finish` de gdb).

        Se detiene en la dirección de retorno cuando sp vuelve al CFA del marco
        actual, así una llamada recursiva a la misma función no lo confunde.
        Dentro de una rutina de interrupción, sale hasta el código interrumpido.
        """
        frames = self.backtrace()
        if len(frames) < 2 or frames[0].cfa is None:
            raise DebuggerError("no hay una función llamadora a la que volver")
        cpu = self.cpu
        function = frames[0].function or self.image.describe(frames[0].pc)
        if frames[1].irq_line is not None:
            pic = cpu.pic
            stop = self._run(lambda pc: not pic.in_isr)
            return self._with_message(stop, f"fin de la interrupción ({function})")
        return_pc, cfa = frames[1].pc, frames[0].cfa
        stop = self._run(lambda pc: pc == return_pc and cpu.sp >= cfa)
        if stop.reason is StopReason.BREAK and cpu.pc == return_pc:
            value = cpu.read_register(10)
            signed = value - (1 << 32) if value & 0x8000_0000 else value
            return self._with_message(stop, f"{function} devolvió a0 = {signed} (0x{value:x})")
        return stop

    @staticmethod
    def _with_message(stop: StopInfo, message: str) -> StopInfo:
        if stop.reason is not StopReason.BREAK:
            return stop
        return replace(stop, message=message)

    def step_over(self) -> StopInfo:
        """Como Step Into, pero las llamadas (jal/jalr a ra) se ejecutan completas.

        Ante una llamada se arma un breakpoint efímero en PC + 4, que sólo se
        considera alcanzado si sp volvió a su valor previo (así una llamada
        recursiva no lo dispara antes de tiempo).
        """
        cpu = self.cpu
        pic = cpu.pic
        lookup = self.lines.lookup
        call_sites = cpu.call_sites
        start = self.location()
        started_in_isr = pic.in_isr
        return_to: tuple[int, int] | None = None

        def reached_new_line(pc: int) -> bool:
            nonlocal return_to
            if pic.in_isr and not started_in_isr:
                return False
            if return_to is not None:
                if pc != return_to[0] or cpu.sp < return_to[1]:
                    return False
                return_to = None
            location = lookup(pc)
            if location is not None and location != start:
                return True
            if pc in call_sites:
                return_to = (pc + 4, cpu.sp)
            return False

        return self._run(reached_new_line)
