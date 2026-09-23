"""Vigila el programa en la TUI: si se recompila (o cambian sus fuentes), se recarga.

- Con un ELF, se vigila el archivo: lo recompila el alumno (make, gcc, build).
- Con fuentes, se vigilan ellos y los encabezados de sus directorios; al
  cambiar, se recompila con las mismas opciones (y la caché de compilación).

Para no leer un archivo a medio escribir, un cambio cuenta recién cuando dos
consultas seguidas ven lo mismo.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from hardboiled.buildcache import dependencies

Fingerprint = tuple[tuple[str, int, int], ...]


class WatchError(Exception):
    """No se pudo obtener el programa nuevo (p. ej. un error de compilación)."""


class ProgramWatcher:
    def __init__(
        self,
        files: Callable[[], Sequence[Path]],
        rebuild: Callable[[], Path],
        builds: bool,
    ) -> None:
        self._files = files
        self._rebuild = rebuild
        self.builds = builds  # True: hay que compilar (se vigilan fuentes)
        self._seen = self._fingerprint()
        self._pending: Fingerprint | None = None

    @classmethod
    def for_elf(cls, elf: Path) -> ProgramWatcher:
        elf = elf.resolve()
        return cls(lambda: [elf], lambda: elf, builds=False)

    @classmethod
    def for_sources(
        cls,
        sources: Sequence[Path],
        include_dirs: Sequence[Path],
        rebuild: Callable[[], Path],
    ) -> ProgramWatcher:
        sources = [Path(source).resolve() for source in sources]
        return cls(lambda: dependencies(sources, include_dirs), rebuild, builds=True)

    def _fingerprint(self) -> Fingerprint:
        stamps = []
        for path in self._files():
            try:
                info = path.stat()
            except OSError:
                continue  # borrado o renombrado a mitad de un guardado
            stamps.append((str(path), info.st_mtime_ns, info.st_size))
        return tuple(stamps)

    def changed(self) -> bool:
        """¿Cambió algo desde la última recarga (y ya dejó de cambiar)?"""
        current = self._fingerprint()
        if current == self._seen:
            self._pending = None
            return False
        if current != self._pending:
            self._pending = current  # se confirma en la próxima consulta
            return False
        self._seen = current
        self._pending = None
        return True

    def rebuild(self) -> Path:
        """El ELF a cargar (recompilado si hace falta). WatchError si falla."""
        return self._rebuild()
