"""Control de flujo a nivel de código fuente: breakpoints, Step Into, Step Over y Continue.

Cada operación se traduce en una condición `stop_check(pc)` que la CPU evalúa
antes de ejecutar cada instrucción. Los pasos no se detienen dentro de una
rutina de interrupción que empezó durante el paso (salvo breakpoints), de modo
que una IRQ asíncrona no "secuestra" el step del usuario.
"""

from __future__ import annotations

from collections.abc import Callable

from hardboiled.core.cpu import Cpu, StopInfo, StopReason
from hardboiled.core.dwarf import LineTable, SourceLocation
from hardboiled.core.elf import ElfImage


class DebuggerError(Exception):
    pass


class Debugger:
    def __init__(self, cpu: Cpu, image: ElfImage, lines: LineTable) -> None:
        self.cpu = cpu
        self.image = image
        self.lines = lines
        self._line_breakpoints: dict[tuple[str, int], int] = {}
        self._address_breakpoints: set[int] = set()
        # Conjunto vivo: se consulta en cada instrucción y puede cambiar durante un Continue.
        self._active: set[int] = set()

    # ------------------------------------------------------------ breakpoints

    @property
    def line_breakpoints(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._line_breakpoints)

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
        file = self._resolve_file(source_file)
        resolved = self.lines.address_for_line(file, line)
        if resolved is None:
            raise DebuggerError(f"no hay código ejecutable en {file}:{line} ni después")
        effective_line, address = resolved
        key = (file, effective_line)
        if key in self._line_breakpoints:
            del self._line_breakpoints[key]
            placed = False
        else:
            self._line_breakpoints[key] = address
            placed = True
        self._rebuild()
        return placed

    def toggle_address_breakpoint(self, address: int) -> bool:
        if address in self._address_breakpoints:
            self._address_breakpoints.discard(address)
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

    # ------------------------------------------------------------- ejecución

    def _run(self, predicate: Callable[[int], bool]) -> StopInfo:
        breakpoints = self._active
        start_pc = self.cpu.pc
        leaving_start = True

        def check(pc: int) -> bool:
            nonlocal leaving_start
            # No volver a detenerse en el breakpoint desde el que se reanuda.
            if leaving_start:
                if pc == start_pc:
                    predicate(pc)
                    return False
                leaving_start = False
            return pc in breakpoints or predicate(pc)

        self.cpu.stop_check = check
        try:
            return self.cpu.run()
        finally:
            self.cpu.stop_check = None

    def continue_(self) -> StopInfo:
        return self._run(lambda pc: False)

    def run_to(self, address: int) -> StopInfo:
        return self._run(lambda pc: pc == address)

    def run_to_main(self) -> StopInfo | None:
        """Ejecuta el arranque (crt0) y se detiene en la primera línea del cuerpo de main()."""
        main = self.image.symbol_address("main")
        if main is None:
            return None
        stop = self.run_to(main)
        if stop.reason is StopReason.BREAK and self.location() is not None:
            stop = self.step_into()  # saltea el prólogo (la línea de la llave de apertura)
        return stop

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
