---
type: decision
kind: semantic
project: episteme-mcp
priority: 3
status: active
created: 2026-10-20
tags: [pieza/repo]
source: PLAN.md@v0.1.0 (Decisiones cerradas)
helpful: 0
---
# El código vive en un repo aparte del vault

El código de `episteme-mcp` vive en `Bajmein/episteme-mcp` (privado). El repo `episteme` queda solo para los datos (`docs/`, `memory/`, `plans/`, `episteme.toml`). Así el vault no lleva `pyproject.toml` ni CI, y el servidor se versiona con tags propios que la config de cada proyecto fija.
