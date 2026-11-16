# CLAUDE.md

Guía para Claude Code en este repo.

## Qué es

`episteme` es un servidor MCP en Python que sirve un vault Markdown compatible con Obsidian (documentación y memoria de proyectos). `README.md` es la presentación, en lenguaje simple; el detalle está en `docs/` (instalación, configuración, tools y memorias, hooks, mantención, migración de OMEGA y desarrollo) y el contrato de cada tool, en sus docstrings.

- La interfaz es **solo tools MCP**: no hay CLI para el agente. Los scripts son de la persona, en local: `scripts/migrate_omega.py` (una vez), `scripts/measure_recall.py` (solo lectura, para decidir sobre lematización o trigramas), `scripts/bench_calls.py` (solo lectura sobre una copia del vault; mide llamadas por ráfaga), `scripts/measure_uptake.py` (solo lectura; cruza entregas y lecturas del registro de actividad), `scripts/measure_semantic.py` (solo lectura; compara la búsqueda por palabras con los vecinos semánticos de un modelo de Ollama), `scripts/measure_links.py` (solo lectura; mide el grafo de enlaces entre memorias y si habría servido en las búsquedas reales) y `scripts/measure_index.py` (trabaja sobre una copia del vault; mide el indexado completo, el incremental y el `refresh()` sin cambios).
- El repo es además un marketplace de Claude Code (`.claude-plugin/marketplace.json`) con un plugin, `episteme`, en `plugin/`: trae solo skills, no el servidor. Se instala con `claude plugin install episteme@episteme` (ver «El plugin» en `docs/instalacion.md`).
- `plugin/skills/` trae tres skills de uso diario, que no tocan el servidor: `pausa`, `mantencion` y `reminder` (`/episteme:pausa`…). Si cambia un tool que nombran (`remember`, `revise`, `review`, `search`), revisa sus `SKILL.md`.
- `plugin/skills/setup/` (`/episteme:setup`) es la skill que conecta un proyecto (registro con `claude mcp add`, permisos, hooks y `CLAUDE.md`), en Linux, macOS y Windows. Si cambian la instalación, los hooks, los permisos o los tools, actualiza a la vez `README.md`, el documento de `docs/` que corresponda, `SKILL.md` y su `settings.json`.
- Alcance cerrado: no hay tools para mover, renombrar, borrar o crear notas fuera de `memory/`, ni sync, web, HTTP o embeddings.
- El código está en `src/episteme/`. `memory/` e `index/` son paquetes cuyo `__init__.py` reexporta lo que se usa desde fuera (se importa `from episteme import memory`, no el módulo interno). Los tools viven en `tools/` (`reading`, `memories`, `hooks`), cada módulo con una función `register(server, engine…)` que llama a un `_register_<tool>(server, engine…)` por tool, en el orden de `list_tools`; cada uno define su tool dentro, porque el SDK saca nombre, descripción y esquema de la propia función. `server.py` solo tiene las instrucciones, el formato de errores y `build_server`.
- Los invariantes por módulo están en `.claude/rules/` y se cargan al tocar esos archivos. El porqué de las decisiones está en las memorias de episteme (`search` con `project="episteme"`).

## Cómo se trabaja

- Dependencias con `uv` (`uv sync`, `uv add`). Nada de `pip install` suelto.
- Python: el paquete pide `>=3.14` (`requires-python`, ruff `py314`); aquí y en el CI se usa 3.15, fijado en `.python-version`.
- Dependabot (`.github/dependabot.yml`): PR semanal agrupado del ecosistema `uv` (`chore(deps)`) y mensual de GitHub Actions (`chore(ci)`).
- Antes de cada commit: `uv run ruff check` y `uv run pytest` en verde. El job `lint` del CI corre además `uv run ty check`, `uv run bandit -c pyproject.toml -r src scripts -q`, `uv run vulture` y `uv run deptry .` (configurados en `pyproject.toml`); pásalos si tocaste tipos, dependencias o borraste código.
- CodeScene revisa cada PR (check «CodeScene Code Health Review (main)», quality gates «The Bare Minimum») y analiza `main` cada día: un PR no baja el code health de ningún archivo. Para bajar complejidad: funciones privadas en el mismo módulo, predicados para las condiciones compuestas y retornos anticipados, sin tocar las firmas de los tools ni los tests. La meta es 9 o más en cada archivo de `src/` y `scripts/`: un archivo nuevo o tocado no baja de 9. Detalle y cifras en «Salud del código» de `docs/desarrollo.md`.
- El paquete se construye con `uv_build` (acotado a la serie menor de uv en `[build-system]`); al subir de serie se cambia la cota a mano.
- SDK de MCP 2.x: la clase es `MCPServer` (antes `FastMCP`). `instructions=` se pasa siempre por keyword (por posición acaba en `title`). Dependencia fijada: `mcp>=2.3,<3`. Si algo no coincide con lo esperado, manda el código del SDK en `.venv`.
- `tests/fixtures/vault/` es el vault de prueba (`docs/` es una copia real; `memory/` y `episteme.toml` son sintéticos). **No se modifica**: los tests lo copian a `tmp_path` antes de escribir. `tests/fixtures/project/` hace de `project_dir` para `checkpoint` y `tests/fixtures/omega-export/` sirve para `migrate_omega.py`.
- Los tests de integración arrancan el servidor por stdio (`stdio_client` y `ClientSession` del SDK) y llaman a los tools como lo haría Claude Code.
- El CI corre en `ubuntu-latest` y `windows-latest`, y en local no hay Windows. En `src/`, rutas con `os.path` o `pathlib`, nunca comparando contra `"/"` fijo (así nació el bug de `project_relative` en 0.4.0); las lecturas con `encoding="utf-8"` y las escrituras con `newline=""`. Un test que solo tiene sentido en POSIX lleva `skipif(sys.platform == "win32", reason=…)`; uno que reproduce Windows en Linux hace `monkeypatch.setattr(os, "path", ntpath)`. Los subprocesos de los tests heredan `os.environ` (sin `SYSTEMROOT` Python no arranca en Windows).
- Las versiones se publican con un tag en local (`git tag vX && git push --tags`) con CI en verde; los proyectos fijan el tag en su config. En el release también se sube `version` en `plugin/.claude-plugin/plugin.json` al número de `pyproject.toml` (un test lo comprueba; sin ese cambio las skills no se actualizan), y se cambian el badge de versión del `README.md`, que es estático, y el tag de los ejemplos de instalación (`README.md` y `docs/instalacion.md`), y en `CHANGELOG.md` «Sin publicar» pasa a ser la versión con su fecha.
- `CHANGELOG.md` va en español, con el formato de Keep a Changelog. Un cambio que nota quien usa episteme (tools, hooks, skill, scripts, instalación) se anota en «Sin publicar» en el mismo PR.
- La cabecera del `README.md` es un bloque centrado con el banner (`static/banner-episteme.jpg`) y los badges en estilo plano; el de CI es el nativo de GitHub porque shields.io no lee workflows de un repo privado.

## Convenciones

- Código, identificadores y commits en inglés, con Conventional Commits (`feat: …`, `fix: …`, `docs: …`).
- Docstrings y descripciones de tools en inglés, que es lo que lee el modelo. `README.md` y `docs/`, en español.
- El `README.md` lo tiene que entender alguien no técnico: frases cortas, tablas y tecnicismos al mínimo. Los parámetros, los umbrales y los casos límite van en `docs/`, no en el README.
- Los diagramas están en `static/diagrams/`: el HTML es la fuente (plugin diagram-design, variante oscura) y el PNG, exportado a 2x, es lo que se incrusta. Si cambia el HTML, se vuelve a exportar.
- Los errores de los tools siguen `<código>: <qué falló>. <qué hacer>`, por ejemplo: `ambiguous: note name "best-practices" matches 2 notes: a.md, b.md. Pass the full path.`
