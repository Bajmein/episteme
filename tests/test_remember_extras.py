"""remember: keywords, cross-scope similar, new_tags and link_candidates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import mcp_client

pytestmark = pytest.mark.anyio

BODY = "Usamos zorbfoo para sincronizar los catalogos de productos con el almacen central."


def hook_text(raw: str) -> str:
    """Text a hook call delivers: the plain string or the additionalContext of the JSON envelope."""
    if raw.startswith("{"):
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    return raw


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


async def test_keywords_order_and_search(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok(
            "remember", type="insight", title="Campana de marketing", body="Nada especial aqui.",
            tags=["a/b"], files=["x.py"], keywords=["  zorbmkt ", "marketing"],
        )  # fmt: skip
        fm = _fm(vault / res["path"])
        keys = list(fm)
        assert keys.index("keywords") == keys.index("tags") + 1
        assert fm["keywords"] == ["zorbmkt", "marketing"]
        found = await c.ok("search", query="zorbmkt")
        assert [r["path"] for r in found["results"]] == [res["path"]]


async def test_revise_set_keywords_makes_findable(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("remember", type="insight", title="Otra nota", body="Contenido neutro.")
        assert (await c.ok("search", query="zorbsyn"))["total"] == 0
        await c.ok("revise", note=res["path"], action="set", fields={"keywords": ["zorbsyn"]})
        assert (await c.ok("search", query="zorbsyn"))["total"] == 1
        err = await c.error("revise", note=res["path"], action="set", fields={"keywords": "x"})
        assert "keywords" in err


async def test_keywords_validation(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        for bad in (["x" * 61], [str(i) for i in range(13)], [" "]):
            err = await c.error(
                "remember", type="insight", title="Mala", body="Cuerpo.", keywords=bad
            )
            assert err.startswith("invalid_schema") and "keywords" in err


async def test_similar_across_type_and_project(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        first = await c.ok("remember", type="insight", title="Sincronizar catalogos", body=BODY)
        other = await c.ok("remember", type="lesson", title="Sincronizar catalogos", body=BODY)
        assert other["created"] is True
        top = other["similar"][0]
        assert top["path"] == first["path"]
        assert top["type"] == "insight" and top["project"] == "fabrik"
        shared = await c.ok(
            "remember", type="insight", title="Sincronizar catalogos", body=BODY, project="_shared"
        )
        assert shared["created"] is True
        assert {s["project"] for s in shared["similar"]} == {"fabrik"}
        dup = await c.ok("remember", type="insight", title="Sincronizar catalogos", body=BODY)
        assert dup["created"] is False
        assert dup["similar"][0]["path"] == first["path"]
        assert {s["path"] for s in dup["similar"]} >= {other["path"], shared["path"]}


async def test_new_tags_and_link_candidates(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        a = await c.ok(
            "remember", type="insight", title="Primera", body="Uno distinto.",
            tags=["tema/pricing", "pieza/qq"], files=["src/a.py"],
        )  # fmt: skip
        assert a["new_tags"][0]["tag"] == "tema/pricing"
        b = await c.ok(
            "remember", type="insight", title="Segunda", body="Dos diferente totalmente.",
            tags=["tema/pricin", "pieza/qq", "tema/pricing"], files=["src/a.py"],
        )  # fmt: skip
        assert b["new_tags"] == [{"tag": "tema/pricin", "similar": ["tema/pricing"]}]
        assert b["link_candidates"][0]["path"] == a["path"]
        assert "src/a.py" in b["link_candidates"][0]["reason"]
        c3 = await c.ok(
            "remember", type="insight", title="Tercera", body="Tres otra cosa.",
            tags=["tema/pricing", "pieza/qq"], related=[a["path"]],
        )  # fmt: skip
        assert [x["path"] for x in c3["link_candidates"]] == [b["path"]]
        assert "tema/pricing" in c3["link_candidates"][0]["reason"]
        assert "new_tags" not in c3
        plain = await c.ok("remember", type="insight", title="Cuarta", body="Cuatro sin nada.")
        assert "new_tags" not in plain and "link_candidates" not in plain


async def test_keywords_hint(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        bare = await c.ok("remember", type="insight", title="Sin claves", body="Uno solo.")
        assert bare["keywords_hint"].startswith("No keywords.")
        dry = await c.ok(
            "remember", type="insight", title="Seco", body="Otro distinto.", dry_run=True
        )
        assert "keywords_hint" in dry
        full = await c.ok(
            "remember", type="insight", title="Con claves", body="Dos diferente.",
            keywords=["sinonimo"],
        )  # fmt: skip
        assert "keywords_hint" not in full
        rem = await c.ok(
            "remember", type="reminder", title="Aviso", body="Recordar esto.", due="2026-12-01"
        )
        assert "keywords_hint" not in rem
        ses = await c.ok("remember", type="session", title="Jornada", body="Resumen del dia.")
        assert "keywords_hint" not in ses


async def test_links_hint(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        bare = await c.ok("remember", type="insight", title="Suelta", body="Nada enlazado.")
        assert bare["links_hint"].startswith("No links.")
        linked = await c.ok(
            "remember", type="insight", title="Con related", body="Otra cosa aparte.",
            related=[bare["path"]],
        )  # fmt: skip
        assert "links_hint" not in linked
        name = bare["path"].rsplit("/", 1)[-1].removesuffix(".md")
        body = await c.ok(
            "remember", type="insight", title="Con wikilink", body=f"Sigue a [[{name}]] aqui."
        )
        assert "links_hint" not in body
        rem = await c.ok(
            "remember", type="reminder", title="Aviso suelto", body="Recordar.", due="2026-12-01"
        )
        assert "links_hint" not in rem


async def test_remember_rejects_a_body_over_100000_characters(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        err = await c.error("remember", type="insight", title="Enorme", body="x " * 50_001)

        assert err.startswith("invalid_argument") and "100000" in err
        ok = await c.ok("remember", type="insight", title="Justo", body="y" * 100_000)
        assert ok["created"]


async def test_remember_link_writes_candidates_into_related(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        a = await c.ok(
            "remember", type="insight", title="Primera", body="Uno distinto.",
            tags=["tema/pricing", "pieza/qq"], files=["src/a.py"],
        )  # fmt: skip
        b = await c.ok(
            "remember", type="insight", title="Segunda", body="Dos diferente totalmente.",
            tags=["tema/pricing", "pieza/qq"], link=True,
        )  # fmt: skip
        plain = await c.ok(
            "remember", type="insight", title="Tercera", body="Tres otra cosa.",
            tags=["tema/pricing", "pieza/qq"],
        )  # fmt: skip
        lonely = await c.ok(
            "remember", type="insight", title="Cuarta", body="Cuatro sin nada.", link=True
        )

    assert b["linked"] == [a["path"]]
    assert a["path"] not in [x["path"] for x in b.get("link_candidates", [])]
    assert "[[" in "".join(_fm(vault / b["path"])["related"])
    assert "linked" not in plain and "related" not in _fm(vault / plain["path"])
    assert lonely["linked"] == []
    assert "related" not in _fm(vault / lonely["path"])
    assert "related" not in _fm(vault / a["path"])


async def test_remember_link_rejects_a_non_boolean(vault: Path) -> None:
    async with mcp_client(vault) as c:
        failed, _ = await c.call("remember", type="insight", title="X", body="Y.", link="maybe")

    assert failed
