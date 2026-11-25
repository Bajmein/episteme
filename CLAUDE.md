# CLAUDE.md

Servidor MCP en Python que sirve un vault Markdown compatible con Obsidian (documentación y memoria de proyectos). El contrato de cada tool está en su docstring; el detalle para personas, en `docs/`.

## Comandos

```sh
uv sync                                  # dependencias solo con uv (uv add), nunca pip
uv run ruff check && uv run pytest       # antes de cada commit
uv run ty check                          # job lint del CI: si tocas tipos
uv run bandit -c pyproject.toml -r src scripts plugin plugin-docs -q
uv run vulture && uv run deptry .        # si borras código o cambias dependencias
uv run zizmor .github/workflows          # si tocas .github/workflows
```

Python: el paquete pide `>=3.14` (`requires-python`, ruff `py314`); aquí y en el CI, 3.15 (`.python-version`).

## Invariantes

- **Alcance cerrado.** Solo tools MCP, sin CLI para el agente; `scripts/` es de la persona, en local. Fuera de `memory/`, los tools escriben solo en zonas con tool propio (`docs`, `sesiones` con `session`, `planes` con `plan`). No hay mover, renombrar, borrar, sync, web, HTTP ni embeddings. Nada de tools, parámetros u opciones sin pedido.
- **Paquetes.** `memory/`, `index/`, `docs/`, `session/` y `plans/` reexportan en `__init__.py`: `from episteme import memory`, no el módulo interno.
- **SDK de MCP 2.x** (`mcp>=2.3,<3`). La clase es `MCPServer`; `instructions=` siempre por keyword (por posición acaba en `title`). Los tipos de `mcp.types` son pydantic en snake_case (`input_schema`, `structured_content`, `is_error`); el camelCase solo sale con `model_dump(by_alias=True)`. Si algo no cuadra, manda el código del SDK en `.venv`.
- **Tests.** `tests/fixtures/vault/` no se modifica: los tests lo copian a `tmp_path`. Los de integración arrancan el servidor por stdio (`stdio_client`, `ClientSession`).
- **Multiplataforma.**
  - Rutas con `pathlib` u `os.path`, nunca comparando con `"/"`.
  - Lee con `encoding="utf-8"`; escribe con `newline=""`.
  - Test solo POSIX: `skipif(sys.platform == "win32", reason=…)`. Windows en Linux: `monkeypatch.setattr(os, "path", ntpath)`.
  - Los subprocesos de los tests heredan `os.environ` (sin `SYSTEMROOT`, Python no arranca en Windows).
- **Cambio de interfaz.** Si cambian un tool, la instalación, los hooks o los permisos, actualiza en el mismo PR `README.md`, `README.en.md`, su documento de `docs/` y lo que lo nombra en `plugin/` (regla `plugin.md`).
- **`uv_build`** va acotado a la serie menor de uv en `[build-system]`: al subir de serie, cambia la cota a mano.

## PR y calidad

- `main` solo recibe cambios por PR, también el de release. Los tags `v*` no se mueven ni se borran.
- CI: `ci.yml` (`lint`, `test` y `changes`, que salta `test` si solo cambian docs), `ci-windows.yml` y `dependency-review.yml` (revisa las dependencias de cada PR). Cobertura a Codecov, informativa.
- CodeScene revisa cada PR y su check (gate «The Bare Minimum») tiene que pasar. En `src/` y `scripts/`: 9 o más por archivo, y un archivo tocado no baja su code health. `@CodeScene(disable:"<regla>")` solo con una línea que diga por qué.
- MCP `codescene`, si está: `code_health_review` de lo tocado → si baja, corrige y confirma con `code_health_score` → `pre_commit_code_health_safeguard` en verde. Si falta el login o falla, dilo en una línea: basta el check del PR.
- `CHANGELOG.md` (español, Keep a Changelog): lo que nota quien usa episteme (tools, hooks, skills, scripts, instalación) va en «Sin publicar», en el mismo PR.
- Release: tag en local con CI en verde. Qué archivos cambian: «Publicar una versión» en `docs/desarrollo.md`.

## Al cambiar código

- **Piensa antes.** Di los supuestos; si el pedido admite varias lecturas, nómbralas. Antes de decidir algo que quizá ya se decidió: `search` en episteme con `project="episteme"`.
- **Lo mínimo.** Sin abstracciones de un solo uso ni manejo de errores para casos imposibles.
- **Quirúrgico.** Cada línea del diff responde a la tarea; no reformatees lo de al lado. El código muerto ajeno se menciona en el PR; lo que tu cambio dejó huérfano se borra (`vulture`). Única excepción: si CodeScene baja un archivo tocado, refactoriza solo esa función.
- **Verificable.** Bug → test que lo reproduce. Cambio de tool → test de integración por stdio. Refactor → `pytest` igual antes y después.

## Convenciones

- Código, identificadores, docstrings, descripciones de tools y commits en inglés (Conventional Commits: `feat:`, `fix:`, `docs:`).
- `README.md` y `docs/` en español; `README.en.md` se traduce en el mismo PR. Estilo y cabecera: regla `readme.md`.

## Dónde está el resto

| Qué | Dónde |
|---|---|
| Invariantes por módulo (se cargan al tocar sus archivos) | `.claude/rules/`: `hookmode`, `maintenance`, `memory`, `plugin`, `readme`, `tools`, `vault` |
| CI, cobertura, Dependabot, Imgbot, CodeScene, scripts de medición, release | [`docs/desarrollo.md`](docs/desarrollo.md) |
| Plugins e instalación | [`docs/instalacion.md`](docs/instalacion.md) |
| Por qué se decidió cada cosa | memorias de episteme (`search` con `project="episteme"`) |
| Instrucciones para agy | `GEMINI.md`, que remite aquí: revísalo si cambian `.claude/rules/` o lo que aquí es solo de Claude Code |
| Ramas, commits y cómo se mezcla un PR | [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) |
| Instrucciones para Copilot | `.github/copilot-instructions.md`, que remite aquí: revísalo si cambia lo que nombra |
