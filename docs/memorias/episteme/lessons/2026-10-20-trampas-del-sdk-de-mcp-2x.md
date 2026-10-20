---
type: lesson
kind: procedural
project: episteme
priority: 4
status: active
created: 2026-10-20
tags: [herramienta/mcp-sdk]
files: [src/episteme/server.py]
source: PR #1
helpful: 0
---
# Dos trampas del SDK de MCP 2.x

En el paquete `mcp` 2.x (`MCPServer`, antes `FastMCP`):

1. `MCPServer("episteme", INSTRUCTIONS)` pasa el texto a `title`, no a `instructions`. Hay que escribir siempre `instructions=INSTRUCTIONS` por keyword.
2. Todo `ToolError` sale con el prefijo `Error executing tool <name>:`. Para que los errores lleguen como `<código>: <qué falló>. <qué hacer>`, `EpistemeServer` en `server.py` sobrescribe `call_tool`, devuelve el texto de `EpistemeError` tal cual y convierte los `ValidationError` de pydantic (un parámetro con tipo equivocado) en `invalid_argument`.

Si una firma no coincide con lo esperado, manda el código del SDK en `.venv`.
