---
type: decision
kind: semantic
project: episteme
priority: 5
status: active
created: 2026-10-20
tags: [pieza/arquitectura, pieza/hooks, pieza/permisos]
files: [src/episteme/server.py, src/episteme/hookmode.py]
source: PLAN.md@v0.1.0 (Arquitectura, Decisiones cerradas)
helpful: 0
---
# Interfaz solo de tools MCP, con los hooks vía mcp_tool y sin CLI

`episteme` tiene una sola entrada: el servidor MCP por stdio. El agente usa los 10 tools y los hooks de Claude Code los llaman con `type: "mcp_tool"` (el texto que devuelve el tool se trata como el stdout de un hook de comando). Así los hooks y el agente comparten código y no hace falta CLI. El único script es `scripts/migrate_omega.py`, que la persona corre una vez en local.

El acceso al vault se cierra con permisos y no con una regla en el prompt: `deny` de `Read(~/.episteme/**)`, `Edit(…)` y `Write(…)` en el `settings.json` del proyecto, más `Bash(obsidian *)` y `Bash(omega *)`. Bash no se puede cerrar del todo por patrones; el resto lo cubre una línea en el `CLAUDE.md` del proyecto. Las zonas de escritura las impone el motor (`episteme.toml`), no el prompt.

No añadir una CLI para el agente: duplicaría la interfaz y saltaría las zonas.
