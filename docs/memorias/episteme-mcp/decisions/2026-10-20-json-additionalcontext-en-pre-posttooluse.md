---
type: decision
kind: semantic
project: episteme-mcp
priority: 4
status: active
created: 2026-10-20
tags: [pieza/hooks, pieza/hookmode]
files: [src/episteme_mcp/hookmode.py]
source: PLAN.md@v0.1.0 (Modo hook, Hooks sobre tools)
helpful: 0
---
# En Pre/PostToolUse la salida es JSON hookSpecificOutput.additionalContext

Según la referencia de hooks de Claude Code, en `PreToolUse` y `PostToolUse` el stdout en texto plano solo va al debug log y el modelo no lo ve. Por eso `constraints` y `surface`, cuando reciben `hook_event` de esos eventos, devuelven un único objeto `{"hookSpecificOutput": {"hookEventName": "<evento>", "additionalContext": "<texto>"}}`. En `UserPromptSubmit` y `SessionStart` el texto plano sí entra al contexto, y en `PreCompact` la salida es vacía.

El servidor decide el formato por `hook_event` en `hookmode.py`. El contrato de `mcp_tool` es reciente: si Claude Code cambia la sustitución de variables o el tratamiento de la salida, el cambio queda aislado ahí y en el bloque de hooks.
