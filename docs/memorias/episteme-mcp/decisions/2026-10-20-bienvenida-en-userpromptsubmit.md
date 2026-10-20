---
type: decision
kind: semantic
project: episteme-mcp
priority: 4
status: active
created: 2026-10-20
tags: [pieza/hooks, pieza/bienvenida]
files: [src/episteme_mcp/memory.py]
source: PLAN.md (Hooks sobre tools)
helpful: 0
---
# La bienvenida va en UserPromptSubmit con registro en welcomed

En `SessionStart` con `startup` o `resume`, Claude Code se salta los hooks `mcp_tool` porque los servidores MCP aún no están conectados. Por eso la bienvenida (`context(mode="welcome", session="${session_id}")`) cuelga de `UserPromptSubmit`: el servidor apunta en la tabla `welcomed` del índice qué `session_id` ya la recibió y en las llamadas siguientes devuelve una cadena vacía. De respaldo, las `instructions` del servidor piden llamar a `context(mode="task")` al empezar.

`SessionStart` con matcher `compact|clear` sí corre `mcp_tool`, y ahí va `checkpoint(action="restore")`.

`SessionEnd` queda fuera: es observacional, no espera a un servidor que se esté conectando y tiene un presupuesto de 1,5 s. Bastan el checkpoint de `PreCompact` y el `remember` explícito del agente.
