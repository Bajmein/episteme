---
paths:
  - src/episteme/server.py
  - src/episteme/tools/**
  - src/episteme/engine.py
  - src/episteme/errors.py
  - src/episteme/prompting.py
  - src/episteme/activity.py
---

# Tools MCP

- Todos los tools devuelven `str`: en modo agente, JSON con `json.dumps(..., ensure_ascii=False)`; con `hook_event`, lo que diga `hookmode.py`. Así no hay esquemas de salida que mantener.
- Un error es una `EpistemeError` con el formato `<código>: <qué falló>. <qué hacer>`. Los códigos son seis y no se añaden más: `not_found`, `ambiguous`, `read_only_zone`, `outside_vault`, `invalid_schema` e `invalid_argument`. `EpistemeServer.call_tool` quita el prefijo `Error executing tool <name>:` que pone el SDK; no se toca sin entender por qué existe.
- Los 7 tools de solo lectura (`search`, `read`, `links`, `review`, `surface`, `constraints` y `docs_status`) llevan `ToolAnnotations(read_only_hint=True)`, porque los proyectos los permiten sin preguntar. `context` no lleva la anotación (su bienvenida puede archivar memorias y lanzar el backup), pero va en el `allow` de `/episteme:setup` porque los hooks lo necesitan sin preguntar; `context(mode="welcome")` escribe en la tabla `welcomed` del índice. Toda llamada deja una fila en `.index/activity.db`, que no es parte del vault y cuenta como lectura. `remember`, `revise`, `checkpoint` y `docs_write` quedan sujetos a permiso.
- El estado por sesión (contador de mensajes, recordatorios y sugerencias ya enviados en `prompting.py`, memorias ya mostradas por `surface` en `SessionState.surfaced`, lo entregado en `delivered` y el contador de escrituras `prompting.WRITES`, que sube en `call_tool` con `remember` (si `created`) y `revise`, no con `docs_write`) vive en memoria del proceso, sin tablas: cada sesión de Claude Code abre su propio proceso y perderlo al reiniciar no importa. El `SessionStart` (`compact|clear`) de `context` lo reinicia, porque el contexto del modelo ya no lo tiene. La excepción es `prompting.TRAIL` (notas escritas o leídas por el agente, hasta 30; también las que `docs_write` cambia): es del proceso y no de la sesión, porque `/clear` cambia el id de sesión y el rastro tiene que cruzarlo; ese `SessionStart` lo lista («De esta sesión») y no lo borra.
- Las descripciones y docstrings de los tools van en inglés: es lo que lee el modelo.
- Los lotes van en los tools que ya existen: `search(match="any")` para varias palabras y `read(notes=[…])` para varias notas (hasta 20, 50 000 caracteres de respuesta; lo que no cabe vuelve en `pending`). No se añaden tools para eso.
- Los tools escriben fuera de `memory/` solo en zonas gestionadas por un tool propio (`docs` con `docs_write`); siguen sin existir mover, renombrar, borrar, sync, web, HTTP ni embeddings. Una zona así va en `vault.TOOL_MODES` (modo → tool): `revise` la rechaza con `read_only_zone` y `review` la trata como de solo lectura. Si el alcance cambia, se sustituye la memoria de alcance con `revise(action="supersede")`.
