"""Tutorial guiado: lecciones progresivas con casos de prueba.

Cada lección es un directorio empaquetado en `data/tutorial/NN-tema/` con:
- `leccion.md`: explicación, consigna, cómo probar y pistas;
- `main.c`: el punto de partida, con TODOs;
- `casos.toml`: la suite con la que `hardboiled tutorial check` corrige.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hardboiled import resources

LESSON_FILES = ("leccion.md", "main.c")


class LessonError(Exception):
    pass


@dataclass(frozen=True)
class Lesson:
    number: int
    slug: str  # "leds"
    path: Path

    @property
    def title(self) -> str:
        """Lo que sigue a la raya en el título de leccion.md ("Encender LEDs")."""
        first = self.text.splitlines()[0].lstrip("# ")
        return first.split("—", 1)[1].strip() if "—" in first else first

    @property
    def text(self) -> str:
        return (self.path / "leccion.md").read_text(encoding="utf-8")

    @property
    def suite(self) -> Path:
        return self.path / "casos.toml"

    @property
    def default_dir(self) -> str:
        return f"leccion-{self.number:02d}-{self.slug}"


def tutorial_dir() -> Path:
    return resources.package_dir() / "data" / "tutorial"


def lessons() -> list[Lesson]:
    found = []
    for path in sorted(tutorial_dir().iterdir()):
        number, _, slug = path.name.partition("-")
        if path.is_dir() and number.isdigit():
            found.append(Lesson(int(number), slug, path))
    return found


def find_lesson(key: str) -> Lesson:
    """Por número (`3`, `03`) o por tema (`uart`)."""
    for lesson in lessons():
        if (key.isdigit() and int(key) == lesson.number) or key == lesson.slug:
            return lesson
    available = ", ".join(f"{lesson.number} ({lesson.slug})" for lesson in lessons())
    raise LessonError(f"no existe la lección {key!r}; disponibles: {available}")
