"""Body templates per memory type: a reference for the format that never refuses a save."""

from __future__ import annotations

import re
from typing import NamedTuple

from episteme.markdown import fold

TEMPLATE_HINT_MIN_CHARS = 300
_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
# "1. ", "2) " or "3 - " before the name; not "2026 objetivos" nor "1.5 Resultados".
_NUMBERING = re.compile(r"\d{1,2}(?:[.)]\s+|\s+-\s+)")
_EMPTY = "Una sección sin contenido lleva «Nada.»; no se quita."


class Template(NamedTuple):
    """Required ``## `` sections of a type and the skeleton that shows how to fill them."""

    sections: tuple[str, ...]
    skeleton: str


def _skeleton(parts: tuple[tuple[str, str], ...], extra: str = "") -> str:
    """``## <Section>`` and an italic line that says what goes there, for each section."""
    blocks = [f"## {name}\n\n_{guide}_\n" for name, guide in parts]
    return f"_{_EMPTY}_\n\n" + "\n".join(blocks) + extra


def _template(parts: tuple[tuple[str, str], ...], extra: str = "") -> Template:
    return Template(tuple(name for name, _ in parts), _skeleton(parts, extra))


_SESSION = (
    ("Objetivo", "Qué se quiere lograr en esta sesión, en una o dos frases."),
    ("Hecho (con evidencia)", "Cada ítem con su evidencia: test, comando o salida."),
    ("En curso", "Lo que quedó a medias y en qué punto."),
    ("Lo que no funcionó", "El enfoque que se probó y el error exacto."),
    (
        "Siguiente paso",
        "Uno solo, con archivo y punto, tan preciso que retomar no exija pensar.",
    ),
    ("Pendiente", "Lo que falta después del siguiente paso."),
    ("Decisiones cerradas", "Qué se decidió y por qué, en una línea cada una."),
    ("Restricciones y preferencias", "Reglas de la persona o del proyecto que valen aquí."),
    ("Archivos", "Tabla con la ruta, su estado y una nota."),
)
_FILES_TABLE = "\n| ruta | estado | nota |\n| --- | --- | --- |\n"

TEMPLATES: dict[str, Template] = {
    "session": _template(_SESSION, _FILES_TABLE),
    "decision": _template(
        (
            ("Contexto", "Qué problema o situación llevó a decidir."),
            ("Decisión", "Qué se decidió, con los archivos, tools o comandos que toca."),
            ("Descartado", "Las alternativas que se dejaron y por qué, en una línea cada una."),
            ("Consecuencias", "Qué cambia a partir de ahora y qué hay que vigilar."),
        )
    ),
    "lesson": _template(
        (
            ("Situación", "Qué se estaba haciendo."),
            ("Qué pasó", "Lo que ocurrió, con el dato concreto."),
            ("Lección", "Qué hacer distinto la próxima vez."),
        )
    ),
    "error": _template(
        (
            ("Síntoma", "El error exacto o lo que se observó."),
            ("Causa", "Por qué ocurría."),
            ("Solución", "Qué lo arregló, con archivos y comandos."),
            ("Comprobación", "Cómo se comprobó que quedó resuelto."),
        )
    ),
    "constraint": _template(
        (
            ("Regla", "Qué se debe o no se debe hacer."),
            ("Por qué", "El motivo, para poder juzgar los casos límite."),
            ("Alcance", "Dónde aplica: proyecto, archivos o situaciones."),
        )
    ),
    "insight": _template(
        (
            ("Hallazgo", "Lo que se descubrió."),
            ("Fuente", "De dónde sale: documento, medición, conversación."),
            ("Implicaciones", "Qué cambia o qué conviene hacer con esto."),
        )
    ),
    "preference": Template(
        (),
        "_Un párrafo: qué prefiere la persona, en qué casos y, si se sabe, por qué._\n",
    ),
    "reminder": Template(
        (),
        "_Un párrafo: qué hay que hacer o recordar y cuándo deja de hacer falta._\n",
    ),
}


def _section_key(name: str) -> str:
    """The folded name without its parenthesised note: ``Hecho (con evidencia)`` -> ``hecho``."""
    return fold(name.split("(", 1)[0]).strip()


def _without_lead(text: str) -> str:
    """``text`` from its first letter or digit on."""
    return text[next((i for i, c in enumerate(text) if c.isalnum()), len(text)) :]


def _heading_key(heading: str) -> str:
    """The folded heading without leading punctuation or numbering: ``¿Qué pasó?`` -> ``que
    paso?``, ``1. Situación`` -> ``situacion``."""
    key = _without_lead(fold(heading).strip())
    numbered = _NUMBERING.match(key)
    return _without_lead(key[numbered.end() :]) if numbered else key


def _heading_matches(heading: str, key: str) -> bool:
    """True when a heading key is the section name, maybe followed by extra text."""
    if not heading.startswith(key):
        return False
    rest = heading[len(key) :]
    return not rest or not rest[0].isalnum()


def missing_sections(type: str, body: str) -> list[str]:
    """Template sections of ``type`` with no ``## <section>`` line in ``body``, in order.

    Case, accents and leading punctuation are ignored, text after the name is accepted
    (``## Hecho`` counts for ``Hecho (con evidencia)``) and headings inside fenced code blocks
    do not count. Types without sections, or unknown, miss nothing.
    """
    template = TEMPLATES.get(type)
    if template is None:
        return []
    text = _FENCE.sub("", body)
    headings = [_heading_key(m.group(1)) for m in _HEADING.finditer(text)]
    keys = {name: _section_key(name) for name in template.sections}
    return [
        name
        for name, key in keys.items()
        if not any(_heading_matches(h, key) for h in headings)
    ]


def template_hint(type: str, body: str) -> str | None:
    """A hint naming the missing sections of a long body, or ``None``. It never refuses."""
    if len(body) < TEMPLATE_HINT_MIN_CHARS:
        return None
    missing = missing_sections(type, body)
    if not missing:
        return None
    return (
        f"Body lacks the {type} template sections: {', '.join(missing)}. "
        f'Template: session(action="template", type="{type}").'
    )
