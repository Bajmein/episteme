# Instrucciones para agentes

`episteme` es un servidor MCP en Python que sirve un vault Markdown compatible con Obsidian (documentación y memoria de proyectos). El detalle está en `CLAUDE.md`, `.claude/rules/` y `docs/`; esto es solo lo que aplica a cualquier agente.

## Comandos

```sh
uv sync
uv run ruff check
uv run ty check
uv run pytest
uv run bandit -c pyproject.toml -r src scripts plugin plugin-docs -q
uv run vulture
uv run deptry .
uv run zizmor .github/workflows
```

Dependencias solo con `uv` (`uv add`), nunca `pip install`.

## Estructura de `src/episteme/`

- `server.py`: instrucciones, formato de errores y `build_server`.
- `tools/`: los 9 tools MCP (`search`, `read`, `remember`, `revise`, `review`, `context`, `session`, `plan` y `docs`, este solo con zonas docs; `reading`, `memories`, `hooks`, `docs`, `session` y `plans`; `args.py` guarda las anotaciones compartidas); cada módulo define `register(server, engine…)`.
- `memory/`, `index/`, `docs/`, `session/` y `plans/`: paquetes cuyo `__init__.py` reexporta lo que se usa desde fuera.
- `vault.py`, `engine.py`, `activity.py`, `prompting.py`, `backup.py`, `maintenance.py`, `hookmode.py`: vault, motor, registro de actividad, inyección por mensaje, copias, mantención y modo hook. `worktree.py`: resolver `project_dir` y comparar el worktree de estados y planes.

`plugin/` es el plugin de Claude Code (y de agy y Copilot CLI): skills, el agente `extractor` y la regla `plugin/rules/AGENTS.md`. `plugin-docs/` es el plugin opcional `episteme-docs` (la skill `/episteme-docs:docs` y su `docs_check.py`). Ninguno trae el servidor.

## Reglas

- La interfaz es solo tools MCP: no hay CLI para el agente. El alcance es cerrado: fuera de `memory/`, los tools solo escriben en zonas con un tool propio (`docs` con `docs(action="write")`, `sesiones` con `session` y `planes` con `plan`); no hay tools para mover, renombrar ni borrar notas, ni sync, web, HTTP o embeddings.
- `tests/fixtures/` no se modifica: los tests copian el vault a `tmp_path` antes de escribir.
- Portabilidad a Windows: rutas con `pathlib` u `os.path`, lecturas con `encoding="utf-8"` y escrituras con `newline=""`.
- Un cambio que note quien usa episteme se anota en `CHANGELOG.md`, en «Sin publicar».
- Si cambia un tool que nombran las skills, revisa sus `SKILL.md` (también `plugin-docs/skills/docs/SKILL.md`), `plugin/agents/extractor.md` y `plugin/rules/AGENTS.md`.
- Commits y código en inglés, con Conventional Commits; `README.md` y `docs/` en español; `README.en.md` es la traducción del `README.md` y se actualiza en el mismo PR.
