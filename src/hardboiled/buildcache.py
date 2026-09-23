"""Caché de compilaciones para `hardboiled run archivo.c`.

La clave combina todo lo que puede cambiar el binario: contenido de los
fuentes y de los encabezados de sus directorios (y de los -I), opciones,
compilador, runtime y versión de hardboiled. Si nada cambió se reutiliza el
ELF sin volver a compilar.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from hardboiled import __version__, paths
from hardboiled.toolchain import BuildOptions, Compiler, build

SOURCE_SUFFIXES = (".c", ".h", ".s", ".S", ".inc")
KEEP_BUILDS = 20


@dataclass(frozen=True)
class CachedBuild:
    elf: Path
    reused: bool
    diagnostics: str


def _hash_file(digest: hashlib._Hash, path: Path) -> None:
    digest.update(str(path).encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")


def dependencies(sources: Sequence[Path], include_dirs: Iterable[Path]) -> list[Path]:
    """Fuentes más los encabezados que plausiblemente incluyen."""
    found = {source.resolve() for source in sources}
    for directory in {s.resolve().parent for s in sources} | {d.resolve() for d in include_dirs}:
        if directory.is_dir():
            found.update(p for p in directory.iterdir() if p.suffix in SOURCE_SUFFIXES)
    return sorted(p for p in found if p.is_file())


def cache_key(sources: Sequence[Path], options: BuildOptions, compiler: Compiler) -> str:
    digest = hashlib.sha256()
    digest.update(f"{__version__}\0{compiler.kind}\0{compiler.command}\0".encode())
    digest.update(repr(options).encode())
    runtime = options.runtime
    for path in (runtime.crt0, runtime.linker_script, *sorted(runtime.include_dir.iterdir())):
        _hash_file(digest, path)
    for path in dependencies(sources, options.include_dirs):
        _hash_file(digest, path)
    return digest.hexdigest()[:20]


def _prune(root: Path, keep: int = KEEP_BUILDS) -> None:
    builds = sorted(
        (d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True
    )
    for stale in builds[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def build_cached(
    sources: Sequence[Path], options: BuildOptions, compiler: Compiler, root: Path | None = None
) -> CachedBuild:
    root = root or paths.cache_dir() / "builds"
    sources = [Path(s).resolve() for s in sources]
    directory = root / cache_key(sources, options, compiler)
    elf = directory / f"{sources[0].stem}.elf"
    if elf.is_file():
        elf.touch()  # marca de uso reciente para la limpieza
        return CachedBuild(elf, reused=True, diagnostics="")
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / f"{sources[0].stem}.partial.elf"
    result = build(sources, partial, options, compiler)
    partial.replace(elf)
    _prune(root)
    return CachedBuild(elf, reused=False, diagnostics=result.diagnostics)
