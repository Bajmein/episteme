---
type: decision
kind: semantic
project: episteme-mcp
priority: 4
status: active
created: 2026-10-20
tags: [pieza/distribucion, herramienta/uv]
files: [pyproject.toml, README.md]
source: PLAN.md@v0.1.0 (Distribución y arranque)
helpful: 0
---
# Distribución con uvx desde un tag git+ssh, en scope local

`episteme-mcp` se registra con `claude mcp add --scope local episteme -- uvx --from git+ssh://git@github.com/Bajmein/episteme-mcp@<tag> episteme-mcp --vault … --project …`.

- `uvx` + tag: la versión queda fijada en la propia config, no instala nada global, tira de caché tras la primera vez y corre como el usuario (los archivos quedan con su dueño). Actualizar es cambiar el tag.
- `git+ssh` porque el repo es privado: usa la misma clave que `git push`. `git+https` pediría un token.
- Scope local (`~/.claude.json`): la ruta del vault es de la máquina y no se versiona.

Descartado:
- pipx: la versión vive en el sistema y no en la config, se desvía entre máquinas.
- Docker (GHCR): con stdio hay un contenedor por sesión, hay que montar el vault (`-v …:/vault:z` por SELinux), el UID del contenedor escribe los archivos, depende de un demonio y SQLite en WAL sobre un bind mount compartido está sin probar. Para un servidor cuyo trabajo es leer y escribir archivos locales, el aislamiento estorba.
- PyPI: obliga a publicar y cuidar el nombre para un uso personal. Más adelante, si se comparte.
- `uv run --directory <checkout>`: no fija versión. Solo para la entrada de desarrollo `episteme-dev`.
