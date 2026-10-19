---
type: lesson
kind: procedural
project: fabrik
priority: 3
status: active
created: 2026-10-14
tags: [pieza/omega]
files: [.mcp.json]
related: []
contradicts: []
helpful: 3
---
# El watchdog de OMEGA cierra el proceso al pasar 1024 MB de RSS

OMEGA se «desconectaba» sin error visible: su watchdog cierra el proceso stdio al llegar a 1024 MB de RSS. Arreglo: `OMEGA_RSS_LIMIT_MB=2048` y `OMEGA_IDLE_TIMEOUT=0` en la entrada de `.mcp.json`.
