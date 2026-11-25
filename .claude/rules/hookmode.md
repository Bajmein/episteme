---
paths:
  - src/episteme/hookmode.py
  - src/episteme/worktree.py
  - src/episteme/session/**
  - src/episteme/plans/**
  - src/episteme/tools/plans.py
---

# Modo hook

Los hooks `type: "mcp_tool"` de Claude Code tratan lo que devuelve el tool como el stdout de un hook de comando. La salida depende de `hook_event`:

- `UserPromptSubmit`, `SessionStart`, `PreToolUse` y `PostToolUse`: un único objeto `{"hookSpecificOutput": {"hookEventName": …, "additionalContext": …}}`. No se usa texto plano: Claude Code 2.1.322 no lo entrega al modelo en hooks `mcp_tool` (comprobado el 11-11-2026).
- `SessionStart` admite además un `systemMessage` (`render(..., notice)`): unas líneas para la persona, cada una limpia de secuencias de escape enteras y de caracteres de control (`clean_block`, que usa `clean_line`), en negrita verde salvo con `NO_COLOR`. Claude Code 2.1.323 la muestra como «SessionStart:clear says: …» y conserva el color (comprobado el 13-11-2026). En los demás eventos el aviso se descarta.
- `PreCompact`, `PostCompact` y `SessionEnd` (`SILENT_EVENTS`): `render` da cadena vacía. La excepción es `session(action="gate")` en `PreCompact`, que devuelve `render_instructions(text)`: **texto plano**, no JSON, porque Claude Code añade el stdout de un `PreCompact` que no bloquea a las instrucciones del resumen de compactación (y se lo muestra a la persona, así que va corto). Cada línea pasa por la limpieza de `clean_line` sin acortarse, el tope es el mismo `CAP` y nunca empieza por `{` (Claude Code lo leería como JSON).
- Cualquier otro evento: `invalid_argument`.

Invariantes:
- Si no hay nada que decir, la salida es una cadena vacía, nunca un JSON con texto vacío.
- El texto tiene un tope de 10 000 caracteres, marca incluida: si lo pasa, se corta en un salto de línea y termina con `\n[episteme: output cut at 10,000 characters]`.
- **Nunca** se devuelve `decision`, `permissionDecision` ni `continue: false`: ningún hook de episteme bloquea (el bloqueo del `/compact` manual se quitó en 0.18 y `[session] block_manual_compact`, en 0.19). `context(mode="constraints")` avisa sin bloquear: si el servidor no está conectado, el hook falla sin bloquear y la sesión sigue.
- Los tools no leen fuera del vault: `project_dir` solo se resuelve (`worktree.py`) para comparar el worktree. El transcript no lo lee el servidor: `end` y `restore` solo pasan su ruta (limpia con `clean_line` y terminada en `.jsonl`) en la orden de extracción, y lo lee `transcript_digest.py` de la skill `sesion`.
- `plan(action="save")` con `hook_event="PreToolUse"` (matcher `ExitPlanMode`) responde **siempre** cadena vacía, también ante un error (se traga con `# nosec B110`): el plan no vuelve como contexto y `ExitPlanMode` nunca se frena. Una variable sin sustituir (`\$\{[\w.]+\}`, con punto por `${tool_input.plan}`) no guarda nada. `plan(action="restore")` solo habla con `source="clear"`.
- Lo que llega de un hook y acaba en texto o en el vault pasa por limpieza: la ruta del transcript por `clean_line`, el `session_id` solo si son letras, dígitos, `-` y `_` (`[\w-]{1,128}`: hasta 128), el resumen de `capture` por `redact_secrets` (se redacta, no se rechaza: es texto generado), y el texto, el título y la ruta del plan de `plan` save también por `redact_secrets` (el plan no se puede perder), con un tope de `PLAN_MAX` (200 000) caracteres cortado en un salto de línea.

El contrato de `mcp_tool` es reciente. Si Claude Code cambia la sustitución de variables o el tratamiento de la salida, el arreglo va aquí y en el bloque de hooks de `docs/hooks.md`, y en ningún otro sitio.
