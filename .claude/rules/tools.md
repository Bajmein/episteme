---
paths:
  - src/episteme/server.py
  - src/episteme/engine.py
  - src/episteme/errors.py
  - src/episteme/prompting.py
  - src/episteme/activity.py
---

# Tools MCP

- Todos los tools devuelven `str`: en modo agente, JSON con `json.dumps(..., ensure_ascii=False)`; con `hook_event`, lo que diga `hookmode.py`. Así no hay esquemas de salida que mantener.
- Un error es una `EpistemeError` con el formato `<código>: <qué falló>. <qué hacer>`. Los códigos son seis y no se añaden más: `not_found`, `ambiguous`, `read_only_zone`, `outside_vault`, `invalid_schema` e `invalid_argument`. `EpistemeServer.call_tool` quita el prefijo `Error executing tool <name>:` que pone el SDK; no se toca sin entender por qué existe.
- Los 7 tools de solo lectura (`search`, `read`, `links`, `review`, `context`, `surface` y `constraints`) llevan `ToolAnnotations(read_only_hint=True)`, porque los proyectos los permiten sin preguntar. `context(mode="welcome")` escribe en la tabla `welcomed` del índice, pero no toca el vault y cuenta como lectura. Toda llamada deja una fila en `.index/activity.db`, que no es parte del vault y cuenta como lectura. `remember`, `revise` y `checkpoint` quedan sujetos a permiso.
- El estado por sesión (contador de mensajes, recordatorios y sugerencias ya enviados en `prompting.py`, memorias ya mostradas por `surface` en `memory._SURFACED`) vive en memoria del proceso, sin tablas: cada sesión de Claude Code abre su propio proceso y perderlo al reiniciar no importa. El `SessionStart` (`compact|clear`) de `context` lo reinicia, porque el contexto del modelo ya no lo tiene.
- Las descripciones y docstrings de los tools van en inglés: es lo que lee el modelo.
- Los lotes van en los tools que ya existen: `search(match="any")` para varias palabras y `read(notes=[…])` para varias notas (hasta 20, 50 000 caracteres de respuesta; lo que no cabe vuelve en `pending`). No se añaden tools para eso.
- No se añaden tools para mover, renombrar, borrar o crear notas fuera de `memory/`, ni sync, HTTP o embeddings. Si eso cambia, se sustituye la memoria «Alcance: sin mover, renombrar, borrar ni crear notas fuera de memory/» con `revise(action="supersede")`.
