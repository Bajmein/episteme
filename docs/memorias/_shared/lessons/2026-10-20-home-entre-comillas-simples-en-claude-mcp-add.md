---
type: lesson
kind: procedural
project: _shared
priority: 3
status: active
created: 2026-10-20
tags: [herramienta/claude-code, herramienta/mcp]
source: episteme README
helpful: 0
---
# ${HOME} entre comillas simples en claude mcp add

En `claude mcp add … -- <comando> --vault '${HOME}/.episteme'`, las comillas simples impiden que la shell expanda `${HOME}`: se guarda tal cual en `~/.claude.json` y Claude Code lo expande al arrancar el servidor. Así la config no lleva la ruta de la máquina.

Con `~` o con comillas dobles, la shell lo expande al registrar y queda guardada la ruta absoluta (`/home/<usuario>/…`).
