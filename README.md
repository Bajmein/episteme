# episteme

Servidor MCP que sirve un vault Markdown compatible con Obsidian como documentación y memoria de proyectos. El agente, y los hooks a través de `mcp_tool`, interactúan con él solo mediante tools: no hay CLI.

> Estado: v0.2.0 (10 tools, índice SQLite, modo hook, migración de OMEGA y vault global por defecto en `~/.episteme`).

## Instalación

Se distribuye con `uvx` desde un tag de GitHub. El repo es privado, así que se usa `git+ssh` (la misma clave que `git push`):

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+ssh://git@github.com/Bajmein/episteme@v0.2.0 episteme --project fabrik
```

Sin `--vault` usa el vault global `~/.episteme` y lo crea, con un `episteme.toml` mínimo (zona `memory`), si no existe.

Actualizar es cambiar el tag. Para desarrollo, una entrada aparte que no fija versión:

```bash
claude mcp add --scope local episteme-dev -- \
  uv run --directory '${HOME}/src/episteme' episteme --project fabrik
```

Las comillas simples guardan `${HOME}/src` tal cual y Claude Code lo expande al arrancar el servidor, así la config no lleva la ruta de la máquina. Con comillas dobles la shell lo expande al registrar y queda la ruta completa.

Requiere Python 3.11 o superior con SQLite y FTS5 (el servidor lo comprueba al arrancar).

## Argumentos

| Argumento | Qué hace |
| --- | --- |
| `--vault <ruta absoluta>` | Opcional (o la variable `EPISTEME_VAULT`; manda el argumento). Por defecto, `~/.episteme`, que se crea si falta. Una ruta explícita que no es absoluta, no existe o no tiene `episteme.toml` impide arrancar: el servidor sale con código ≠ 0 sin crear nada |
| `--project <nombre>` | Opcional. Proyecto por defecto de `remember`, `context`, `surface`, `constraints`, `checkpoint` y `review` |

Variables:

- `EPISTEME_TODAY=AAAA-MM-DD` fija la fecha de hoy (por defecto, la fecha UTC). Existe para los tests.

El índice vive en `<vault>/.index/index.db`: es una caché que se reconstruye sola. Añade `.index/` al `.gitignore` del vault.

## `episteme.toml`

Marca la carpeta como vault y declara las zonas:

```toml
[zones."docs/claude-code"]
mode = "read-only"

[zones."memory"]
mode = "memory"        # escritura solo vía remember/revise, con validación del esquema

[zones."plans"]
mode = "read-write"    # revise puede editar; no hay tools para crear ni borrar

[checkpoint]
state_glob = ".fabrik/*/*/estado.md"   # relativo a project_dir; opcional
```

- `mode` es `read-only`, `read-write` o `memory`. Un valor distinto o una zona repetida impiden arrancar.
- Lo que no está en ninguna zona es de solo lectura. Si dos zonas se anidan, manda la más específica.
- Se ignoran `.obsidian/`, `.index/`, `.git/`, toda carpeta que empiece por `.` y los archivos que no son `.md`.
- Toda ruta se confina al vault: se rechazan `..`, las rutas absolutas y los symlinks que salen (`outside_vault`).

## Tools

Todos devuelven texto: JSON en modo agente y, con `hook_event`, exactamente lo que espera el hook. Los errores tienen la forma `<código>: <qué falló>. <qué hacer>`, con los códigos `not_found`, `ambiguous`, `read_only_zone`, `outside_vault`, `invalid_schema` e `invalid_argument`.

| Tool | Solo lectura | Para qué |
| --- | --- | --- |
| `search(query, path?, type?, tags?, project?, status?, limit=20)` | sí | Búsqueda de texto completo (AND, `"frases"`, sin distinguir mayúsculas ni tildes). Excluye por defecto las memorias `superseded` y `archived` (`status="any"` no filtra) |
| `read(note, heading?, lines?)` | sí | Nota entera (cortada a 20 000 caracteres), una sección o un rango de líneas, con frontmatter y esquema de encabezados |
| `links(note, direction="both", depth=1)` | sí | Enlaces salientes, backlinks y notas alcanzables (hasta 3 saltos) |
| `remember(type, title, body, project?, priority?, tags, files, related, supersedes?, source?, due?, valid_until?, status="active", force=false)` | no | Crea una memoria con el esquema validado y detección de duplicados (≥ 0,8 no crea salvo `force`) |
| `revise(note, action, …)` | no | `edit`, `append`, `set` en zonas `read-write` y `memory`; `supersede`, `feedback` y `archive` solo en memorias |
| `review(path?, project?, limit=50, zone?)` | sí | Memorias viejas, contradicciones posibles, huérfanas, enlaces rotos, frontmatter inválido y marcadas. `totals` da el total por categoría (las listas se cortan en `limit`); `zone` limita a una zona del `episteme.toml`. Los problemas de las zonas `read-only` (enlaces rotos y frontmatter inválido) van aparte, en `read_only` |
| `context(mode="welcome"\|"task", session?, project?, task?, budget_tokens=2000, hook_event?)` | sí | Bienvenida de la sesión (una vez por `session`) o paquete de contexto para una tarea |
| `surface(file?, relative_path?, project_dir?, project?, limit=5, hook_event?)` | sí | Memorias sobre un archivo (por `files` o porque lo mencionan), sin constraints, `session` ni `reminder`; el nombre base solo cuenta si es inequívoco; ignora las vencidas por `valid_until`. `relative_path` sustituye a `file` en las ediciones con Serena; sin ninguno, salida vacía |
| `constraints(file?, relative_path?, project_dir?, project?, hook_event?)` | sí | Constraints activas (no vencidas) que aplican a un archivo. Avisa, no bloquea |
| `checkpoint(action="save"\|"restore", project_dir?, project?, hook_event?)` | no | Guarda el `estado.md` activo (sin la Bitácora) como memoria de sesión, o devuelve el último vigente |

Los nombres de nota aceptan una ruta relativa al vault (con o sin `.md`) o un nombre que se resuelve como un wikilink: ruta exacta, nombre base, `aliases`. Si hay varios candidatos, el error `ambiguous` los lista. Dentro de una nota, un `[[nombre]]` repetido prefiere la nota de su misma carpeta, como Obsidian; si ninguna está ahí, el enlace queda ambiguo (roto en `review`). Los `#hex` (`#fff`, `#a1b2c3`; con al menos un dígito o una sola letra repetida, así que `#bad` o `#cafe` siguen siendo tags) y el texto dentro de código (bloques, indentado e inline) no cuentan como tags.

### Memorias

Viven en `memory/<proyecto>/<carpeta del tipo>/AAAA-MM-DD-<slug>.md` (`_shared` vale para todos los proyectos). Esquema:

```yaml
type: decision          # decision | lesson | error | constraint | preference | session | reminder | insight
kind: semantic          # sale del type
project: fabrik
priority: 4             # 1-5; 4 por defecto en decision y constraint, 3 en el resto
status: active          # active | superseded | speculative | archived
created: 2026-10-19
valid_until:
tags: [dominio/explore, pieza/serena_guard]
files: [.claude/hooks/serena_guard.py]
supersedes: "[[2026-09-12-serena-pyright]]"
related: ["[[...]]"]
contradicts: []
source: <sha o PR>
helpful: 0
due:                    # obligatorio en reminder
flagged: false
```

## Hooks

Los hooks son `type: "mcp_tool"` y llaman a los mismos tools. En `PreToolUse` y `PostToolUse` el tool devuelve `{"hookSpecificOutput": {"hookEventName", "additionalContext"}}`; en `UserPromptSubmit` y `SessionStart`, texto plano; en `PreCompact`, nada. Sin nada que decir, la salida es una cadena vacía. Nunca devuelve `decision`, `permissionDecision` ni `continue: false`.

Bloque para el `settings.json` del proyecto:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "context",
                    "input": { "mode": "welcome", "session": "${session_id}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PreToolUse": [
      { "matcher": "Edit|Write|mcp__serena__.*",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "constraints",
                    "input": { "file": "${tool_input.file_path}",
                               "relative_path": "${tool_input.relative_path}",
                               "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write|mcp__serena__.*",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "surface",
                    "input": { "file": "${tool_input.file_path}",
                               "relative_path": "${tool_input.relative_path}",
                               "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PreCompact": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "checkpoint",
                    "input": { "action": "save", "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "SessionStart": [
      { "matcher": "compact|clear",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "checkpoint",
                    "input": { "action": "restore", "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ]
  }
}
```

Si el servidor va empaquetado en un plugin, `server` pasa a ser el nombre con scope (`plugin:fabrik:episteme`).

Permisos recomendados: `allow` para los tools de solo lectura (`mcp__episteme__search`, `read`, `links`, `review`, `context`, `surface` y `constraints`) y `deny` de `Read`, `Edit` y `Write` sobre la ruta del vault, para que el agente solo use los tools.

## Migración de OMEGA

```bash
omega export-obsidian --output-dir /tmp/omega --project fabrik --limit 1000
uv run scripts/migrate_omega.py --export /tmp/omega/omega-memories \
  --vault "$HOME/.episteme" --project fabrik --dry-run
```

Sin `--dry-run` escribe. Usa la misma validación y detección de duplicados que `remember`, así que una segunda ejecución no duplica nada. Los `checkpoint` se descartan y las etiquetas `dominio:x` pasan a `dominio/x`.

## Desarrollo

```bash
uv sync
uv run ruff check
uv run pytest
uv run python -m episteme --vault "$PWD/tests/fixtures/vault" --project fabrik
```

Los tests copian `tests/fixtures/vault/` a un directorio temporal antes de escribir y arrancan el servidor por stdio con el cliente del SDK de MCP.
