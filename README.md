# episteme

Servidor MCP que sirve un vault Markdown compatible con Obsidian como documentación y memoria de proyectos. El agente, y los hooks a través de `mcp_tool`, interactúan con él solo mediante tools: no hay CLI.

> Estado: v0.5.0 (10 tools, índice SQLite con caché incremental, modo hook, búsqueda en español, checkpoint por rama, migración de OMEGA v2, vault global por defecto en `~/.episteme` y soporte de Windows nativo).

## Instalación

Se distribuye con `uvx` desde un tag de GitHub. El repo es privado: hay que ser colaborador de `Bajmein/episteme`. Requiere [uv](https://docs.astral.sh/uv/) y git; uv consigue Python 3.11 o superior si falta (el servidor comprueba al arrancar que SQLite tiene FTS5).

Lo más corto es instalar la skill `episteme-setup` (ver más abajo) y correr `/episteme-setup` en cada proyecto: registra el servidor, fusiona permisos y hooks en `.claude/settings.json` y añade la regla al `CLAUDE.md`. A mano, son estos pasos.

### Linux y macOS

Por `git+ssh`, con la misma clave que `git push`:

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+ssh://git@github.com/Bajmein/episteme@v0.5.0 episteme --project fabrik
```

Sin clave SSH, vale la URL de Windows (`git+https://…`). Sin `--vault` usa el vault global `~/.episteme` y lo crea, con un `episteme.toml` mínimo (zona `memory`), si no existe.

Actualizar es cambiar el tag (`claude mcp remove --scope local episteme` y otra vez el `add`). Para desarrollo, una entrada aparte que no fija versión:

```bash
claude mcp add --scope local episteme-dev -- \
  uv run --directory '${HOME}/src/episteme' episteme --project fabrik
```

Las comillas simples guardan `${HOME}/src` tal cual y Claude Code lo expande al arrancar el servidor, así la config no lleva la ruta de la máquina. Con comillas dobles la shell lo expande al registrar y queda la ruta completa.

### Windows

Requiere [Git for Windows](https://git-scm.com/download/win) (Claude Code ya lo pide) y uv:

```powershell
winget install --id=astral-sh.uv -e
```

Se instala por HTTPS, y la primera vez Git Credential Manager abre el navegador para iniciar sesión en GitHub:

```powershell
claude mcp add --scope local episteme -- uvx --from git+https://github.com/Bajmein/episteme@v0.5.0 episteme --project <proyecto>
```

En una sola línea: el `\` de bash no parte líneas en PowerShell. El vault por defecto es `%USERPROFILE%\.episteme`; `--vault` acepta una ruta absoluta de Windows (`C:\Users\ana\notas`). El bloque de hooks es el mismo. Dentro de WSL, sigue la instalación de Linux.

### Después de registrar

1. `claude mcp list` (o `/mcp` dentro de Claude Code) muestra `episteme` conectado. La primera vez tarda: uv descarga el repo y las dependencias. Una sesión abierta antes del registro no ve los tools (ni sus subagentes) hasta reiniciar Claude Code.
2. Copia el bloque de [Hooks](#hooks) y los permisos recomendados en `.claude/settings.local.json` del proyecto, o en `.claude/settings.json` si todo el equipo tiene episteme registrado (con el servidor en scope local, a quien no lo tenga le fallarían los hooks). En modo auto, Claude Code no deja que el agente edite estos archivos: lo hace la persona.
3. Añade al `CLAUDE.md` del proyecto: «Vault `episteme`: solo los tools de episteme; ni CLI, ni Bash, ni Read/Edit/Write sobre el vault.»

### La skill `episteme-setup`

Vive en [`skills/episteme-setup/`](skills/episteme-setup/SKILL.md) y se instala una vez, a nivel de usuario (en `~/.claude/skills/`), enlazada a un clone del repo para que `git pull` la actualice:

```bash
git clone git@github.com:Bajmein/episteme ~/src/episteme
mkdir -p ~/.claude/skills
ln -s ~/src/episteme/skills/episteme-setup ~/.claude/skills/episteme-setup
```

En Windows (PowerShell), con una unión de directorios, que no necesita el modo de desarrollador:

```powershell
git clone https://github.com/Bajmein/episteme "$HOME\src\episteme"
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$HOME\.claude\skills\episteme-setup" -Target "$HOME\src\episteme\skills\episteme-setup"
```

Se invoca a mano (`/episteme-setup`), desde la raíz del proyecto que se quiere conectar; Claude no la carga solo. Después de instalarla, reinicia Claude Code.

### Uso

Con el servidor conectado, Claude recibe las instrucciones de uso en el handshake de MCP: carga el contexto de la tarea con `context`, busca antes de decidir con `search` y guarda decisiones, lecciones y errores con `remember`. Los hooks hacen el resto: bienvenida al primer mensaje de cada sesión, `constraints` y `surface` al editar un archivo y `checkpoint` al compactar. Para que Claude guarde algo, basta con decirle «recuerda que…». El detalle de cada tool está en [Tools](#tools).

## Argumentos

| Argumento | Qué hace |
| --- | --- |
| `--vault <ruta absoluta>` | Opcional (o la variable `EPISTEME_VAULT`; manda el argumento). Por defecto, `~/.episteme`, que se crea si falta. Una ruta explícita que no es absoluta, no existe o no tiene `episteme.toml` impide arrancar: el servidor sale con código ≠ 0 sin crear nada |
| `--project <nombre>` | Opcional. Proyecto por defecto de `remember`, `context`, `surface`, `constraints`, `checkpoint` y `review` |

Variables:

- `EPISTEME_TODAY=AAAA-MM-DD` fija la fecha de hoy (por defecto, la fecha local). Existe para los tests.

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
| `search(query, path?, type?, tags?, project?, status?, limit=20)` | sí | Búsqueda de texto completo (AND, `"frases"`, `a-b` como dos palabras, sin distinguir mayúsculas ni tildes). Excluye por defecto las memorias `superseded` y `archived` (`status="any"` no filtra) |
| `read(note, heading?, lines?)` | sí | Nota entera (cortada a 20 000 caracteres), una sección o un rango de líneas, con frontmatter y esquema de encabezados |
| `links(note, direction="both", depth=1)` | sí | Enlaces salientes, backlinks y notas alcanzables (hasta 3 saltos) |
| `remember(type, title, body, project?, priority?, tags, files, related, supersedes?, source?, due?, valid_until?, status="active", force=false, slug?)` | no | Crea una memoria con el esquema validado y detección de duplicados (≥ 0,8 no crea salvo `force`). El nombre sale del título (ver «Memorias»); `slug` lo fija |
| `revise(note, action, …)` | no | `edit`, `append`, `set` en zonas `read-write` y `memory` (en una memoria, un `set` que cambia `type` o `project` la mueve a la carpeta que le toca, con el mismo nombre, y devuelve `moved_from`; se niega si alguna nota la enlaza por ruta o si el nombre ya existe allí); `supersede`, `feedback`, `archive` y `dismiss` (archiva un recordatorio) solo en memorias |
| `review(path?, project?, limit=50, zone?)` | sí | Memorias viejas, contradicciones posibles (dos decisiones o constraints que comparten un archivo de `files` o 2 tags, salvo que una enlace a la otra con `supersedes`, `contradicts` o `related`), huérfanas, enlaces rotos, frontmatter inválido y marcadas. `totals` da el total por categoría (las listas se cortan en `limit`); `zone` limita a una zona del `episteme.toml`. Los problemas de las zonas `read-only` (enlaces rotos y frontmatter inválido) van aparte, en `read_only` |
| `context(mode="welcome"\|"task", session?, project?, task?, budget_tokens=2000, hook_event?)` | sí | Bienvenida de la sesión (una vez por `session`) o paquete de contexto para una tarea |
| `surface(file?, relative_path?, project_dir?, project?, limit=5, hook_event?)` | sí | Memorias sobre un archivo (por `files` o porque lo mencionan), sin constraints, `session` ni `reminder`; el nombre base solo cuenta si es inequívoco; ignora las vencidas por `valid_until`. `relative_path` sustituye a `file` en las ediciones con Serena; sin ninguno, salida vacía |
| `constraints(file?, relative_path?, project_dir?, project?, hook_event?)` | sí | Constraints activas (no vencidas) que aplican a un archivo. Avisa, no bloquea |
| `checkpoint(action="save"\|"restore", project_dir?, project?, task_title?, hook_event?)` | no | `save` guarda el `estado.md` activo (sin la Bitácora) como memoria de sesión. `restore` lee primero el `estado.md` activo vivo (el de la rama `<tipo>/<ID>-<change>`, si no el más reciente) con una línea de flujo (`etapa` y avance de `tasks.md`); sin estado activo cae al último checkpoint vigente. `task_title` retoma esa tarea. Archiva los checkpoints de tareas sin estado activo |

Los nombres de nota aceptan una ruta relativa al vault (con o sin `.md`) o un nombre que se resuelve como un wikilink: ruta exacta, nombre base, `aliases`. Si hay varios candidatos, el error `ambiguous` los lista. Dentro de una nota, un `[[nombre]]` repetido prefiere la nota de su misma carpeta, como Obsidian; si ninguna está ahí, el enlace queda ambiguo (roto en `review`). Los `#hex` (`#fff`, `#a1b2c3`; con al menos un dígito o una sola letra repetida, así que `#bad` o `#cafe` siguen siendo tags) y el texto dentro de código (bloques, indentado e inline) no cuentan como tags.

### Memorias

Viven en `memory/<proyecto>/<carpeta del tipo>/AAAA-MM-DD-<slug>.md` (`_shared` vale para todos los proyectos). La fecha es la local. El slug son las primeras 3 a 5 palabras útiles del título (sin palabras vacías en español ni inglés, sin lo que ya dice la ruta, hasta 40 caracteres y sin cortar palabras; una versión como `0.4.0` cuenta como una). El título completo queda en el H1. `slug` lo fija a mano (`[a-z0-9]` y guiones, sin la fecha). Si el nombre ya existe se añade `-2`, `-3`… Esquema:

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

Los hooks son `type: "mcp_tool"` y llaman a los mismos tools. En `UserPromptSubmit`, `SessionStart`, `PreToolUse` y `PostToolUse` el tool devuelve el objeto JSON `{"hookSpecificOutput": {"hookEventName", "additionalContext"}}` (en Claude Code 2.1.322 el texto plano de un hook `mcp_tool` no llega al modelo); en `PreCompact`, nada. Sin nada que decir, la salida es una cadena vacía. Nunca devuelve `decision`, `permissionDecision` ni `continue: false`.

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

Permisos recomendados: `allow` para los tools de solo lectura (`mcp__episteme__search`, `read`, `links`, `review`, `context`, `surface` y `constraints`) y `deny` de `Read` y `Edit` sobre la ruta del vault (`Read(~/.episteme/**)`, `Edit(~/.episteme/**)`; `Edit` ya cubre Write), para que el agente solo use los tools. El [`settings.json`](skills/episteme-setup/settings.json) de la skill `episteme-setup` trae los hooks y los permisos juntos, listos para fusionar.

### Comprobar que los hooks llegan al modelo

Con una copia del vault de prueba, una llamada real a Claude Code confirma que el contexto del hook llega al modelo (el recordatorio vencido del vault de prueba contiene «trigger queries»). En zsh, desde la raíz del repo:

```zsh
W=$(mktemp -d) && cp -r tests/fixtures/vault "$W/vault" && mkdir "$W/work"
print -r -- "{\"mcpServers\":{\"episteme\":{\"command\":\"uv\",\"args\":[\"run\",\"--directory\",\"$PWD\",\"episteme\",\"--vault\",\"$W/vault\",\"--project\",\"fabrik\"],\"env\":{\"EPISTEME_TODAY\":\"2026-10-22\"}}}}" > "$W/mcp.json"
uv run python -c 'import json,sys; d=json.load(open("skills/episteme-setup/settings.json", encoding="utf-8")); json.dump({"hooks": d["hooks"]}, open(sys.argv[1], "w", encoding="utf-8"))' "$W/settings.json"
(cd "$W/work" && claude -p "Según el contexto que te dio episteme al empezar, ¿cuál es el título del recordatorio vencido? Responde solo con el título, o NINGUNO si no lo ves." --model haiku --settings "$W/settings.json" --mcp-config "$W/mcp.json" --strict-mcp-config --output-format json < /dev/null)
```

El campo `result` debe contener «trigger queries»; «NINGUNO» significa que el hook no llegó (o que el servidor no conectó a tiempo: repite una vez). Con varias cuentas se usa el lanzador de la cuenta (`claude-<cuenta> -p`).

## Migración de OMEGA

```bash
omega export-obsidian --output-dir /tmp/omega --project fabrik --limit 1000
uv run scripts/migrate_omega.py --export /tmp/omega/omega-memories \
  --vault "$HOME/.episteme" --project fabrik \
  --omega-db ~/.omega/omega.db \
  --map-project /home/ana/src/fabrik=fabrik --dry-run
```

Sin `--dry-run` escribe; `--dry-run` cuenta lo mismo que la ejecución real. Usa la misma validación y detección de duplicados que `remember`, así que una segunda ejecución no duplica nada. Qué hace con cada cosa:

- Se descartan los `checkpoint`, los `project_status`, los «Edit pattern…», las capturas automáticas de sesión y las reemplazadas en OMEGA.
- Se quitan los prefijos «fabrik (fecha):», «Decision:», «Lesson:» y «Assistant fix:». Del título (y por tanto del nombre del archivo) se quita además una etiqueta inicial entre corchetes, como `[MEMORIA GI - feedback]`; el cuerpo la conserva.
- Las etiquetas `dominio:x` pasan a `dominio/x`; las que son una ruta (`/…` o `C:\…`) pasan a `files`, relativas al proyecto; el resto se descarta. `helpful` queda en 0.
- Los tipos se traducen tal cual (`user_preference` → `preference`, `lesson_learned` → `lesson`…): OMEGA no distingue una preferencia de una decisión, así que conviene revisar las `preference` migradas y corregir el tipo con `revise(action="set", fields={"type": …})`, que mueve la nota a su carpeta.
- `source` lleva el id de OMEGA (`omega:mem-…`): una memoria con ese `source` ya en el vault no se vuelve a crear. Entre duplicados del export se queda el más reciente por fecha.
- `--omega-db` abre `omega.db` solo para lectura (`mode=ro`) y no toca nada de `~/.omega`. De ahí salen `priority` (el export no la trae) y los recordatorios: los `pending` pasan a `reminder` con `due` = `remind_at`; los `dismissed` no se migran.
- `--map-project VIEJO=NUEVO` (repetible) lleva proyectos de OMEGA, por nombre o ruta, a uno de episteme. Las rutas se comparan sin la barra final y, en Windows, sin distinguir mayúsculas ni `\` de `/`. Lo que no sea `--project` ni esté mapeado se omite, y la salida termina con `Proyectos omitidos: <proyecto> (n), …` para saber qué mapear. OMEGA suele guardar el mismo proyecto con el nombre y con la ruta; antes del ensayo, `select project, count(*) from memories group by project` sobre `omega.db` dice cuáles hay.
- Las memorias sin proyecto en OMEGA entran en `--project` (la salida dice cuántas, para revisarlas); `--unassigned skip` las omite.

## Desarrollo

```bash
uv sync
uv run ruff check
uv run pytest
uv run python -m episteme --vault "$PWD/tests/fixtures/vault" --project fabrik
```

Los tests copian `tests/fixtures/vault/` a un directorio temporal antes de escribir y arrancan el servidor por stdio con el cliente del SDK de MCP.
