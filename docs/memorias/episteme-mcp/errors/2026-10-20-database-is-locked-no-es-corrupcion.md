---
type: error
kind: procedural
project: episteme-mcp
priority: 4
status: active
created: 2026-10-20
tags: [pieza/indice, herramienta/sqlite]
files: [src/episteme_mcp/index.py]
source: PR #1
helpful: 0
---
# database is locked al abrir el índice no es corrupción

Varias sesiones abren cada una su proceso de `episteme-mcp` sobre el mismo `.episteme/index.db`. Al principio, `index.py` trataba cualquier error al abrir como corrupción y borraba el índice para reconstruirlo, así que un proceso borraba una base que otro estaba usando. El caso 13 (dos procesos escribiendo a la vez) falló en CI por eso.

Arreglo: `sqlite3.OperationalError` con `database is locked` o `busy` se reintenta (`_is_lock`), con WAL y `pragma busy_timeout = 5000`. Solo un `pragma quick_check` distinto de `ok` o un error que no sea de bloqueo hace que se borre y reconstruya.
