# Instrucciones para agentes

`episteme` es un servidor MCP en Python que sirve un vault Markdown compatible con Obsidian (documentación y memoria de proyectos). El detalle está en `CLAUDE.md`, `.claude/rules/` y `docs/`; esto es solo lo que aplica a cualquier agente.

## Comandos

```sh
uv sync
uv run ruff check
uv run ty check
uv run pytest
uv run bandit -c pyproject.toml -r src scripts -q
uv run vulture
uv run deptry .
uv run zizmor .github/workflows
```

Dependencias solo con `uv` (`uv add`), nunca `pip install`.

## Estructura de `src/episteme/`

- `server.py`: instrucciones, formato de errores y `build_server`.
- `tools/`: los tools MCP (`reading`, `memories`, `hooks`); cada módulo define `register(server, engine…)`.
- `memory/` e `index/`: paquetes cuyo `__init__.py` reexporta lo que se usa desde fuera.
- `vault.py`, `engine.py`, `checkpoint.py`, `backup.py`, `maintenance.py`, `hookmode.py`: vault, motor, checkpoint, copias, mantención y modo hook.

## Reglas

- La interfaz es solo tools MCP: no hay CLI para el agente. El alcance es cerrado: no hay tools para mover, renombrar o borrar notas fuera de `memory/`, ni sync, web, HTTP o embeddings.
- `tests/fixtures/` no se modifica: los tests copian el vault a `tmp_path` antes de escribir.
- Portabilidad a Windows: rutas con `pathlib` u `os.path`, lecturas con `encoding="utf-8"` y escrituras con `newline=""`.
- Un cambio que note quien usa episteme se anota en `CHANGELOG.md`, en «Sin publicar».
- Commits y código en inglés, con Conventional Commits; `README.md` y `docs/` en español.
