---
paths:
  - src/episteme/hookmode.py
  - src/episteme/checkpoint.py
---

# Modo hook

Los hooks `type: "mcp_tool"` de Claude Code tratan lo que devuelve el tool como el stdout de un hook de comando. La salida depende de `hook_event`:

- `UserPromptSubmit` y `SessionStart`: texto plano, que entra al contexto.
- `PreToolUse` y `PostToolUse`: un único objeto `{"hookSpecificOutput": {"hookEventName": …, "additionalContext": …}}`. En esos eventos el texto plano solo va al debug log y el modelo no lo ve.
- `PreCompact`: cadena vacía.
- Cualquier otro evento: `invalid_argument`.

Invariantes:
- Si no hay nada que decir, la salida es una cadena vacía, nunca un JSON con texto vacío.
- El texto tiene un tope de 10 000 caracteres y se corta en un salto de línea.
- **Nunca** se devuelve `decision`, `permissionDecision` ni `continue: false`. `checkpoint` en `PreCompact` no bloquea jamás la compactación, y `constraints` avisa sin bloquear: si el servidor no está conectado, el hook falla sin bloquear y la sesión sigue.
- `checkpoint` es la única lectura fuera del vault y se limita a `state_glob` resuelto contra `project_dir`.

El contrato de `mcp_tool` es reciente. Si Claude Code cambia la sustitución de variables o el tratamiento de la salida, el arreglo va aquí y en el bloque de hooks del README, y en ningún otro sitio.
