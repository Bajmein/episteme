---
type: lesson
kind: procedural
project: _shared
priority: 3
status: active
created: 2026-10-20
tags: [herramienta/github-actions, herramienta/uv]
files: [.github/workflows/ci.yml]
source: episteme-mcp PR #1
helpful: 0
---
# astral-sh/setup-uv no publica tags mayores flotantes

Desde la v8, `astral-sh/setup-uv` no publica tags mayores flotantes: `uses: astral-sh/setup-uv@v10` falla porque esa referencia no existe. Hay que fijar la versión exacta, p. ej. `astral-sh/setup-uv@v10.3.0`. Se comprueba con `git ls-remote --tags https://github.com/astral-sh/setup-uv`.
