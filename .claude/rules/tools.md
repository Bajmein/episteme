---
paths:
  - src/episteme_mcp/server.py
  - src/episteme_mcp/engine.py
  - src/episteme_mcp/errors.py
---

# Tools MCP

- Todos los tools devuelven `str`: en modo agente, JSON con `json.dumps(..., ensure_ascii=False)`; con `hook_event`, lo que diga `hookmode.py`. Así no hay esquemas de salida que mantener.
- Un error es una `EpistemeError` con el formato `<código>: <qué falló>. <qué hacer>`. Los códigos son seis y no se añaden más: `not_found`, `ambiguous`, `read_only_zone`, `outside_vault`, `invalid_schema` e `invalid_argument`. `EpistemeServer.call_tool` quita el prefijo `Error executing tool <name>:` que pone el SDK; no se toca sin entender por qué existe.
- Los 7 tools de solo lectura (`search`, `read`, `links`, `review`, `context`, `surface` y `constraints`) llevan `ToolAnnotations(read_only_hint=True)`, porque los proyectos los permiten sin preguntar. `context(mode="welcome")` escribe en la tabla `welcomed` del índice, pero no toca el vault y cuenta como lectura. `remember`, `revise` y `checkpoint` quedan sujetos a permiso.
- Las descripciones y docstrings de los tools van en inglés: es lo que lee el modelo.
- No se añaden tools para mover, renombrar, borrar o crear notas fuera de `memory/`, ni sync, HTTP o embeddings. Si eso cambia, se sustituye la memoria «Alcance: sin mover, renombrar, borrar ni crear notas fuera de memory/» con `revise(action="supersede")`.
