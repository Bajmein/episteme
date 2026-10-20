---
type: lesson
kind: procedural
project: _shared
priority: 3
status: active
created: 2026-10-20
tags: [herramienta/claude-code-cloud, herramienta/git]
source: episteme-mcp PR #1
helpful: 0
---
# Límites del proxy git en Claude Code cloud

En una sesión de Claude Code cloud, el proxy de GitHub:
- rechaza `git push --tags` y el borrado de ramas;
- solo deja subir a la rama asignada a la sesión (`claude/<nombre>`), aunque el plan pida otra (p. ej. `feat/initial-implementation`).

Consecuencia: los tags de versión (`git tag vX && git push --tags`) se crean en local después de mergear, y un plan para el cloud no debe exigir un nombre de rama concreto.
