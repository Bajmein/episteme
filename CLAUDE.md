# CLAUDE.md

Guía para Claude Code en este repo.

## Qué es

`episteme` es un servidor MCP en Python que sirve un vault Markdown compatible con Obsidian (documentación y memoria de proyectos). El uso, los argumentos, los 10 tools y el bloque de hooks están en `README.md`; el contrato de cada tool, en sus docstrings.

- La interfaz es **solo tools MCP**: no hay CLI para el agente. El único script es `scripts/migrate_omega.py`, que la persona corre una vez en local.
- Alcance cerrado: no hay tools para mover, renombrar, borrar o crear notas fuera de `memory/`, ni sync, web, HTTP o embeddings.
- Los invariantes por módulo están en `.claude/rules/` y se cargan al tocar esos archivos. El porqué de las decisiones está en las memorias de episteme (`search` con `project="episteme"`).

## Cómo se trabaja

- Dependencias con `uv` (`uv sync`, `uv add`). Nada de `pip install` suelto.
- Antes de cada commit: `uv run ruff check` y `uv run pytest` en verde.
- SDK de MCP 2.x: la clase es `MCPServer` (antes `FastMCP`). `instructions=` se pasa siempre por keyword (por posición acaba en `title`). Dependencia fijada: `mcp>=2.3,<3`. Si algo no coincide con lo esperado, manda el código del SDK en `.venv`.
- `tests/fixtures/vault/` es el vault de prueba (`docs/` es una copia real; `memory/` y `episteme.toml` son sintéticos). **No se modifica**: los tests lo copian a `tmp_path` antes de escribir. `tests/fixtures/project/` hace de `project_dir` para `checkpoint` y `tests/fixtures/omega-export/` sirve para `migrate_omega.py`.
- Los tests de integración arrancan el servidor por stdio (`stdio_client` y `ClientSession` del SDK) y llaman a los tools como lo haría Claude Code.
- Las versiones se publican con un tag en local (`git tag vX && git push --tags`) con CI en verde; los proyectos fijan el tag en su config.

## Convenciones

- Código, identificadores y commits en inglés, con Conventional Commits (`feat: …`, `fix: …`, `docs: …`).
- Docstrings y descripciones de tools en inglés, que es lo que lee el modelo. `README.md`, en español.
- Los errores de los tools siguen `<código>: <qué falló>. <qué hacer>`, por ejemplo: `ambiguous: note name "best-practices" matches 2 notes: a.md, b.md. Pass the full path.`
