"""markdown.py: frontmatter, headings, tags, comments and wikilinks."""

from __future__ import annotations

from episteme.markdown import (
    first_sentence,
    parse,
    parse_wikilink,
    section_text,
    slugify,
)

NOTE = """\
---
title: Demo
tags: [dominio/auth, x]
up: "[[README.index]]"
related:
  - "[[other#Part]]"
---
# Heading one

Text with #inline-tag and a link to [[target|alias]] and `[[not-a-link]]`.

%% nav:start %%
hidden words [[nav-target]]
%% nav:end %%

```python
# not a heading
[[code-link]] #code-tag
```

## Sub section
| a | [[table-target\\|shown]] |
"""


def test_parse_extracts_everything() -> None:
    note = parse(NOTE, "x/demo.md")
    assert note.fm_valid
    assert note.title == "Demo"
    assert [(h.level, h.text) for h in note.headings] == [(1, "Heading one"), (2, "Sub section")]
    assert note.headings[0].line == 8
    assert {"dominio/auth", "dominio", "x", "inline-tag"} <= set(note.tags)
    assert "code-tag" not in note.tags
    targets = {(lk.target, lk.kind) for lk in note.links}
    assert ("README.index", "up") in targets
    assert ("other", "related") in targets
    assert ("target", "body") in targets
    assert ("nav-target", "body") in targets
    assert ("table-target", "body") in targets
    assert not {"not-a-link", "code-link"} & {lk.target for lk in note.links}
    assert "hidden words" not in note.search_text
    assert "Text with" in note.search_text
    assert "title: Demo" not in note.search_text


def test_invalid_frontmatter_is_tolerated() -> None:
    note = parse("---\ndescription: a: b\n---\n# Body title\n\nbody text\n", "a.md")
    assert not note.fm_valid
    assert note.fm_error
    assert note.title == "Body title"
    assert "body text" in note.search_text


def test_impossible_date_is_invalid_not_fatal() -> None:
    note = parse("---\ncreated: 2026-02-30\n---\n# T\n\nbody\n", "a.md")
    assert not note.fm_valid
    assert note.fm_error
    assert "body" in note.search_text


def test_percent_signs_in_inline_code_do_not_open_a_comment() -> None:
    note = parse(
        '# T\n\nUse `printf "%d%%"` here.\n\n## After\n\nlater words\n\n'
        "%% hidden [[nav]] %% shown\n",
        "a.md",
    )
    assert [h.text for h in note.headings] == ["T", "After"]
    assert "later words" in note.search_text
    assert "hidden" not in note.search_text and "shown" in note.search_text
    assert "nav" in {lk.target for lk in note.links}


def test_non_mapping_frontmatter_is_invalid() -> None:
    note = parse("---\n- a\n- b\n---\ntext\n", "a.md")
    assert not note.fm_valid
    assert note.title == "a"


def test_wikilink_syntax() -> None:
    assert parse_wikilink("dest#Head|alias") == ("dest", "Head", None, "alias")
    assert parse_wikilink("dest#^block") == ("dest", None, "block", None)
    assert parse_wikilink("#Local") == ("", "Local", None, None)
    assert parse_wikilink("a/b\\|c") == ("a/b", None, None, "c")


def test_section_and_helpers() -> None:
    note = parse(NOTE, "demo.md")
    section = section_text(note, "heading ONE")
    assert section is not None
    assert section.startswith("# Heading one") and "## Sub section" in section
    sub = section_text(note, "sub section")
    assert sub is not None and sub.startswith("## Sub section")
    assert section_text(note, "missing") is None
    assert first_sentence("# T\n\nFirst one. Second one.") == "First one."
    assert slugify("Serena usa ty 0.0.89 ¡ya!") == "serena-usa-ty-0-0-89-ya"
