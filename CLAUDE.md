# CLAUDE.md

Guía para Claude Code en este repo. Está pensada para ejecutarse en una sesión de **Claude Code cloud** que solo tiene este repo.

## Qué es

`episteme-mcp` es un servidor MCP en Python que sirve un vault Markdown compatible con Obsidian (documentación y memoria de proyectos). **El plan completo está en `PLAN.md` y manda sobre cualquier otra suposición.** Léelo entero antes de escribir código.

## Lo que hay y lo que no

- Solo este repo. No hay acceso a fabrik, al vault real `episteme`, a OMEGA ni a nada de la máquina de la persona. Lo que haga falta de ellos ya está en `PLAN.md` o en `tests/fixtures/`.
- `tests/fixtures/vault/` es el vault de prueba: `docs/` es una copia real, y `memory/` y `episteme.toml` son sintéticos. **No se modifica**: los tests lo copian a `tmp_path` antes de escribir.
- `tests/fixtures/project/` hace de `project_dir` para `checkpoint`, y `tests/fixtures/omega-export/` sirve para probar `scripts/migrate_omega.py`.

## Cómo se trabaja

- Dependencias con `uv` (`uv sync`, `uv add`). Nada de `pip install` suelto.
- Antes de cada commit: `uv run ruff check` y `uv run pytest` en verde.
- SDK de MCP 2.x: la clase es `MCPServer` (antes `FastMCP`). `instructions=` se pasa siempre por keyword y los tools de solo lectura llevan `ToolAnnotations(read_only_hint=True)`. Ante la duda, consulta la documentación actual del SDK en lugar de fiarte de la memoria.
- La interfaz es **solo tools MCP**: no hay CLI para el agente. El único script es `scripts/migrate_omega.py`, que la persona corre una vez en local.
- Todo el trabajo va en la rama `feat/initial-implementation`, con commits pequeños por fase. Al terminar, se abre una PR contra `main`. No se mergea, no se crean tags (el proxy los rechaza) y no se borran ramas.

## Convenciones

- Código, identificadores y commits en inglés, con Conventional Commits (`feat: …`, `test: …`, `ci: …`).
- Docstrings y descripciones de tools en inglés, que es lo que lee el modelo. `README.md`, en español.
- Los mensajes de error de los tools dicen qué falló y qué hacer, por ejemplo: «ambiguous note name "best-practices": candidates are …».
- Si algo del plan resulta imposible o contradictorio, se apunta en la PR en una sección «Desvíos del plan» con el motivo. No se decide en silencio.
