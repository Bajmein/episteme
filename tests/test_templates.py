"""Body templates per memory type: missing_sections and the template_hint of remember."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import mcp_client

from episteme.memory import TEMPLATES, missing_sections, template_hint
from episteme.memory.schema import TYPES

FILLER = "Detalle con los archivos y comandos que hacen falta para entenderlo despues. " * 5


def test_every_memory_type_has_a_template() -> None:
    assert set(TEMPLATES) == set(TYPES)


@pytest.mark.parametrize("type", sorted(TEMPLATES))
def test_skeleton_has_every_section_of_its_type(type: str) -> None:
    template = TEMPLATES[type]

    assert missing_sections(type, template.skeleton) == []
    assert template.skeleton.strip()


def test_session_template_lists_its_sections_in_order() -> None:
    assert TEMPLATES["session"].sections == (
        "Objetivo",
        "Hecho (con evidencia)",
        "En curso",
        "Lo que no funcionó",
        "Siguiente paso",
        "Pendiente",
        "Decisiones cerradas",
        "Restricciones y preferencias",
        "Archivos",
    )
    assert "| ruta | estado | nota |" in TEMPLATES["session"].skeleton


def test_missing_sections_lists_the_absent_ones_in_template_order() -> None:
    body = "## Decisión\n\nUsar X.\n\n## Contexto\n\nAlgo."

    assert missing_sections("decision", body) == ["Descartado", "Consecuencias"]


@pytest.mark.parametrize(
    "heading",
    [
        "## Situacion",
        "## SITUACIÓN",
        "##   situación  ",
        "## Situación (del lunes)",
        "## Situación: despliegue",
        "## ¿Situación?",
    ],
)
def test_missing_sections_ignores_case_accents_and_extra_text(heading: str) -> None:
    body = f"{heading}\n\nx\n\n## Qué pasó\n\ny\n\n## Leccion aprendida\n\nz"

    assert missing_sections("lesson", body) == []


def test_missing_sections_accepts_the_name_without_its_parenthesised_note() -> None:
    body = "\n\n".join(f"## {name.split(' (')[0]}" for name in TEMPLATES["session"].sections)

    assert missing_sections("session", body) == []


@pytest.mark.parametrize(
    "body",
    [
        "# Situación\n\n### Qué pasó\n\n#### Lección",
        "Situación, qué pasó y lección en un solo párrafo.",
        "## Situaciones\n\n## Qué pasó\n\n## Lección",
        "```md\n## Situación\n```\n\n## Qué pasó\n\n## Lección",
    ],
)
def test_missing_sections_needs_a_whole_level_two_heading_outside_code(body: str) -> None:
    assert "Situación" in missing_sections("lesson", body)


@pytest.mark.parametrize("type", ["preference", "reminder", "unknown"])
def test_missing_sections_is_empty_for_types_without_sections(type: str) -> None:
    assert missing_sections(type, FILLER) == []


def test_template_hint_names_the_sections_and_the_template_call() -> None:
    hint = template_hint("error", "## Síntoma\n\n" + FILLER)

    assert hint == (
        "Body lacks the error template sections: Causa, Solución, Comprobación. "
        'Template: session(action="template", type="error").'
    )


@pytest.mark.parametrize(
    "type,body",
    [
        ("error", "Un cuerpo corto sin secciones."),
        ("error", "## Síntoma\n\n## Causa\n\n## Solución\n\n## Comprobación\n\n" + FILLER),
        ("reminder", FILLER),
    ],
)
def test_template_hint_is_none_when_short_complete_or_without_sections(
    type: str, body: str
) -> None:
    assert template_hint(type, body) is None


@pytest.mark.anyio
async def test_remember_hints_the_template_and_still_saves(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("remember", type="decision", title="Formato largo", body=FILLER)

        assert res["created"] is True
        assert (vault / res["path"]).exists()
        assert res["template_hint"].startswith(
            "Body lacks the decision template sections: Contexto, Decisión, Descartado, "
        )


@pytest.mark.anyio
async def test_remember_has_no_template_hint_when_short_complete_or_reminder(
    vault: Path,
) -> None:
    complete = "\n\n".join(
        f"## {name}\n\n{FILLER}" for name in TEMPLATES["constraint"].sections
    )
    async with mcp_client(vault, today="2026-10-22") as c:
        short = await c.ok("remember", type="lesson", title="Corta", body="Uno solo.")
        full = await c.ok("remember", type="constraint", title="Completa", body=complete)
        rem = await c.ok(
            "remember", type="reminder", title="Aviso largo", body=FILLER, due="2026-12-01"
        )

        assert "template_hint" not in short
        assert "template_hint" not in full
        assert "template_hint" not in rem
