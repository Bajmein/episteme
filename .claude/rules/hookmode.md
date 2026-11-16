---
paths:
  - src/episteme/hookmode.py
  - src/episteme/checkpoint.py
---

# Modo hook

Los hooks `type: "mcp_tool"` de Claude Code tratan lo que devuelve el tool como el stdout de un hook de comando. La salida depende de `hook_event`:

- `UserPromptSubmit`, `SessionStart`, `PreToolUse` y `PostToolUse`: un único objeto `{"hookSpecificOutput": {"hookEventName": …, "additionalContext": …}}`. No se usa texto plano: Claude Code 2.1.322 no lo entrega al modelo en hooks `mcp_tool` (comprobado el 11-11-2026).
- `SessionStart` admite además un `systemMessage` (`render(..., notice)`): unas líneas para la persona, cada una limpia de secuencias de escape enteras y de caracteres de control (`clean_block`, que usa `clean_line`), en negrita verde salvo con `NO_COLOR`. Claude Code 2.1.323 la muestra como «SessionStart:clear says: …» y conserva el color (comprobado el 13-11-2026). En los demás eventos el aviso se descarta.
- `PreCompact`: cadena vacía.
- Cualquier otro evento: `invalid_argument`.

Invariantes:
- Si no hay nada que decir, la salida es una cadena vacía, nunca un JSON con texto vacío.
- El texto tiene un tope de 10 000 caracteres, marca incluida: si lo pasa, se corta en un salto de línea y termina con `\n[episteme: output cut at 10,000 characters]`.
- **Nunca** se devuelve `decision`, `permissionDecision` ni `continue: false`. `checkpoint` en `PreCompact` no bloquea jamás la compactación, y `constraints` avisa sin bloquear: si el servidor no está conectado, el hook falla sin bloquear y la sesión sigue.
- `checkpoint` es la única lectura fuera del vault y se limita a `state_glob` resuelto contra `project_dir`.

El contrato de `mcp_tool` es reciente. Si Claude Code cambia la sustitución de variables o el tratamiento de la salida, el arreglo va aquí y en el bloque de hooks de `docs/hooks.md`, y en ningún otro sitio.
