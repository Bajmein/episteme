# Hooks

[← Volver al README](../README.md)

![Secuencia del día a día: con cada mensaje, antes y después de usar un archivo y al aprobar un plan, un hook llama a un tool de episteme](../static/diagrams/hooks-sesion.png)

![Secuencia al compactar o con /clear: session gate, capture, end y restore, y el agente extractor que pone al día el estado](../static/diagrams/compactar-clear.png)

Los hooks son `type: "mcp_tool"` y llaman a los mismos tools. En `UserPromptSubmit`, `SessionStart`, `PreToolUse` y `PostToolUse` el tool devuelve el objeto JSON `{"hookSpecificOutput": {"hookEventName", "additionalContext"}}` (en Claude Code 2.1.322 el texto plano de un hook `mcp_tool` no llega al modelo); en `SessionStart` puede llevar además un `systemMessage` para la persona; en `PostCompact` y `SessionEnd`, nada. En `PreCompact`, `session(action="gate")` devuelve **texto plano**: las instrucciones para que el resumen de la compactación termine con el estado de la sesión al día entre `<estado-sesion>` y `</estado-sesion>`. Claude Code añade el stdout de un `PreCompact` que no bloquea a las instrucciones del resumen (manual o automático; comprobado con un hook `mcp_tool` en Claude Code 2.1.330) y se lo muestra a la persona; nunca empieza por `{`, que Claude Code leería como JSON (ver [Estado de la sesión](sesion.md)). Sin nada que decir, la salida es una cadena vacía. Nunca devuelve `decision`, `permissionDecision` ni `continue: false`: ningún hook de episteme bloquea.

Bloque para el `settings.json` del proyecto:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "context",
                    "input": { "mode": "welcome", "session": "${session_id}",
                               "prompt": "${prompt}", "project_dir": "${cwd}",
                               "transcript": "${transcript_path}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PreToolUse": [
      { "matcher": "Edit|Write|mcp__serena__replace_.*|mcp__serena__insert_.*|mcp__serena__delete_lines|mcp__serena__rename_symbol|mcp__serena__safe_delete_symbol",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "context",
                    "input": { "mode": "constraints", "file": "${tool_input.file_path}",
                               "relative_path": "${tool_input.relative_path}",
                               "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] },
      { "matcher": "ExitPlanMode",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "plan",
                    "input": { "action": "save", "plan": "${tool_input.plan}",
                               "plan_path": "${tool_input.planFilePath}",
                               "session": "${session_id}", "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PostToolUse": [
      { "matcher": "Read|Edit|Write|mcp__serena__.*",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "context",
                    "input": { "mode": "surface", "file": "${tool_input.file_path}",
                               "relative_path": "${tool_input.relative_path}",
                               "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}",
                               "session": "${session_id}" } }] }
    ],
    "PreCompact": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "session",
                    "input": { "action": "gate", "session": "${session_id}",
                               "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PostCompact": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "session",
                    "input": { "action": "capture", "summary": "${compact_summary}",
                               "session": "${session_id}", "transcript": "${transcript_path}",
                               "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "SessionEnd": [
      { "matcher": "clear",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "session",
                    "input": { "action": "end", "transcript": "${transcript_path}",
                               "reason": "${reason}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "SessionStart": [
      { "matcher": "compact|clear",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "session",
                    "input": { "action": "restore", "source": "${source}",
                               "transcript": "${transcript_path}",
                               "session": "${session_id}", "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } },
                  { "type": "mcp_tool", "server": "episteme", "tool": "plan",
                    "input": { "action": "restore", "source": "${source}",
                               "project_dir": "${cwd}", "session": "${session_id}",
                               "hook_event": "${hook_event_name}" } },
                  { "type": "mcp_tool", "server": "episteme", "tool": "context",
                    "input": { "mode": "welcome", "session": "${session_id}",
                               "hook_event": "${hook_event_name}",
                               "source": "${source}" } }] }
    ]
  }
}
```

## Tools quitados

Los tools `surface`, `constraints`, `links`, `docs_status` y `docs_write` ya no existen: sus funciones pasaron a `context(mode="surface"|"constraints")`, `read(note, links=…)` y `docs(action="status"|"write")`. Si un proyecto aún los llama (por ejemplo, con los hooks de una versión anterior), el servidor no ejecuta nada y responde:

- Sin `hook_event` (el agente): un error `not_found: tool "surface" was removed. Use context(mode="surface") instead, and re-run /episteme:setup to update hooks and permissions.`
- Con `hook_event` (un hook): una respuesta sin error, con el aviso como `additionalContext` (`PreToolUse`, `PostToolUse`, `UserPromptSubmit` y `SessionStart`; en los eventos silenciosos, vacía), que nombra el tool que lo reemplaza y pide volver a correr `/episteme:setup`. Nunca bloquea.

La llamada queda en el registro de actividad con su nombre original.

## Después de compactar o de `/clear`

No hay que hacer nada a mano: los tres hooks de `SessionStart` (`compact|clear`) corren solos. Antes, `PostCompact` guardó como estado el bloque `<estado-sesion>` del resumen (o el resumen, si no lo traía) y `SessionEnd` (`clear`) anotó el transcript que se cerró.

| Qué vuelve | De dónde sale |
|---|---|
| El estado de la sesión | Tras compactar con el bloque, una línea que dice dónde se guardó (su contenido ya está en el resumen). Si no, la nota de `sesiones/<proyecto>/` en uso (sin el resumen, que ya está en el contexto), con la orden de lanzar en segundo plano el agente `episteme:extractor`, que lo pone al día con el transcript (ver [Estado de la sesión](sesion.md)). |
| La referencia al plan (solo tras `/clear`) | Una línea que apunta a la copia del plan de la tarea en `planes/<proyecto>/` (el plan vigente del proceso, el que enlaza el estado o el más reciente del worktree), para leerla con `read`. La copia la guardó el hook `PreToolUse` con matcher `ExitPlanMode`, que responde siempre vacío y nunca frena `ExitPlanMode` (ver [Planes](planes.md)) |
| La bienvenida | Normas, recordatorios y las memorias mejor puntuadas del proyecto |
| «De esta sesión» | Hasta 8 memorias que el agente escribió (`remember`, `revise`) o leyó (`read`) antes, primero las escritas; las que ya salen en la bienvenida no se repiten |

La persona ve en el terminal una línea en verde por cada hook que recuperó algo, por ejemplo `SessionStart:clear says: episteme · contexto recuperado tras /clear: 12 memorias del proyecto y 3 de esta sesión` y `episteme · estado de sesión recuperado: «…»`. Con la variable de entorno `NO_COLOR` en el servidor, el texto sale sin color.

Una sesión nueva (no `--resume`) no recibe nada de esto: su primera bienvenida, en `UserPromptSubmit` con `${cwd}`, añade solo una línea que nombra el estado que dejó otra sesión en la misma carpeta, sin cargarlo; `/episteme:sesion retomar` lo trae.

Límites: el rastro «De esta sesión» vive en el proceso del servidor, así que se pierde al cerrar Claude Code (no al compactar ni con `/clear`). Sin estado de sesión guardado, tras `/clear` vuelven la bienvenida, el rastro y la orden de extracción, no la conversación.

Si el servidor va empaquetado en un plugin, `server` pasa a ser el nombre con scope (`plugin:fabrik:episteme`).

Permisos recomendados: `allow` para los tools de consulta (`mcp__episteme__search`, `read`, `review` y `context`; `context` no es de solo lectura solo porque su primera bienvenida puede correr la mantención), para `session` y `plan` (los usan los hooks) y para el script del extractor (`Bash(uv run --no-project --python 3.14 python -I <ruta absoluta del script> *)`, que `/episteme:setup` escribe con la ruta de la versión instalada del plugin y hay que renovar al actualizarlo), porque el extractor corre en segundo plano y no puede pedir permiso, y `deny` de `Read` y `Edit` sobre la ruta del vault (`Read(~/.episteme/**)`, `Edit(~/.episteme/**)`; `Edit` ya cubre Write), para que el agente solo use los tools. El `deny` de `Read`/`Edit` es una barrera contra el uso accidental, no un aislamiento: no cubre Bash. La mantención de `context` (archivar las memorias vencidas y el backup) solo corre si está activada en el `episteme.toml` del vault. El [`settings.json`](../plugin/skills/setup/settings.json) de la skill `setup` del plugin trae los hooks y los permisos juntos, listos para fusionar. Tras actualizar la skill, pídele la comprobación de configuración: lista lo que falta o está repetido en los tres `settings` sin tocar nada hasta que apruebes el diff.

## Comprobar que los hooks llegan al modelo

Con una copia del vault de prueba, una llamada real a Claude Code confirma que el contexto del hook llega al modelo (el recordatorio vencido del vault de prueba contiene «trigger queries»). En zsh, desde la raíz del repo:

```zsh
W=$(mktemp -d) && cp -r tests/fixtures/vault "$W/vault" && mkdir "$W/work"
print -r -- "{\"mcpServers\":{\"episteme\":{\"command\":\"uv\",\"args\":[\"run\",\"--directory\",\"$PWD\",\"episteme\",\"--vault\",\"$W/vault\",\"--project\",\"fabrik\"],\"env\":{\"EPISTEME_TODAY\":\"2026-10-22\"}}}}" > "$W/mcp.json"
uv run python -c 'import json,sys; d=json.load(open("plugin/skills/setup/settings.json", encoding="utf-8")); json.dump({"hooks": d["hooks"]}, open(sys.argv[1], "w", encoding="utf-8"))' "$W/settings.json"
(cd "$W/work" && claude -p "Según el contexto que te dio episteme al empezar, ¿cuál es el título del recordatorio vencido? Responde solo con el título, o NINGUNO si no lo ves." --model haiku --settings "$W/settings.json" --mcp-config "$W/mcp.json" --strict-mcp-config --output-format json < /dev/null)
```

El campo `result` debe contener «trigger queries»; «NINGUNO» significa que el hook no llegó (o que el servidor no conectó a tiempo: repite una vez). Con varias cuentas se usa el lanzador de la cuenta (`claude-<cuenta> -p`).
