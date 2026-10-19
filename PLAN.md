# episteme-mcp: motor Markdown servido por MCP

> [!NOTE]
> **Decisión.** Hacer de `episteme` un vault **independiente de Obsidian**, de su MCP (mcpvault) y de su CLI, servido por un motor propio con **una sola entrada: un servidor MCP**. El agente y los hooks usan los mismos tools; no hay CLI. Ese motor sustituye a mcpvault (documentación) y a OMEGA (memoria). Se distribuye con `uvx` desde un tag de GitHub y arranca con la ruta del vault obligatoria. Obsidian deja de ser una dependencia y queda como compatibilidad: los archivos siguen siendo Markdown con wikilinks, frontmatter y tags, y la app sirve para mirarlos.

Estado: **listo para ejecutar en Claude Code cloud** sobre el repo privado `Bajmein/episteme-mcp` (ver [Ejecución en Claude Code cloud](#ejecución-en-claude-code-cloud)). Nada implementado. **Este archivo es la fuente del plan**; la nota `plans/episteme-mcp.md` del vault `episteme` es solo un registro.

## Por qué

- Para memoria hacían falta tres piezas que no controlamos: mcpvault (leer y escribir), OMEGA (memoria) y la app de Obsidian (backlinks y propiedades).
- Problemas de OMEGA ya vistos en fabrik:
  - el mantenimiento automático (consolidate y compact) borraba decisiones sin accesos y mezclaba proyectos, y está frenado con fechas de 2099;
  - la búsqueda semántica usa un modelo en inglés y rinde poco en español;
  - la fusión silenciosa («Evolved») descarta las etiquetas nuevas;
  - el grafo existe pero tiene **0 aristas**.
- La memoria en Markdown es legible, editable a mano, versionable con git y navegable como grafo.

## Auditoría de OMEGA (1.5.20, licencia Core)

Estado en fabrik: 167 memorias.

| Tipo | Nº |
| --- | --- |
| decision | 66 |
| task_completion | 29 |
| checkpoint | 19 |
| lesson_learned | 17 |
| project_status | 11 |
| memory | 10 |
| user_preference | 9 |
| constraint | 4 |
| session_summary | 2 |

### MCP: 16 tools gratis (las otras 140 son Pro)

| Tool | Qué ofrece | Uso en fabrik |
| --- | --- | --- |
| `omega_store` | 9 tipos, `priority`, `status` (active, superseded, speculative, archived), `sensitivity`, `derived_from`, `source_uri`, lotes con `items` | Parcial: sin `status`, `derived_from` ni `source_uri` |
| `omega_query` | Modos semantic, phrase, timeline, browse, trace y unified; `context` (error_debug, planning, review, file_edit), `memory_type` (episódica, semántica o procedimental), `valid_at`, `strength_min`, `filter_tags`, `context_file` | Solo semantic, phrase y `filter_tags` |
| `omega_memory` | edit, delete, feedback (útil, inútil, obsoleta), similar, traverse, link (related, contradicts, supersedes, evolves), flagged, check_contradictions, supersede | Solo supersede y similar |
| `omega_checkpoint` y `omega_resume_task` | Continuidad de la tarea | Sí, con `omega_checkpoint.py` |
| `omega_profile` | Perfil del usuario | Sí |
| `omega_remind` | Recordatorios con fecha | No |
| `omega_reflect` | contradictions, evolution, stale | Solo evolution |
| `omega_maintain` | consolidate, compact, discover_connections, backup y restore, constraints por archivo | No (frenado) |
| `context_packet` | Paquete de contexto para una tarea, con presupuesto de tokens y filtro de sensibilidad | No |
| `omega_stats`, `omega_review`, `omega_consult_gpt`, `omega_consult_claude` | Analítica, revisión de diffs, segunda opinión | No |

Pro (no disponible): coordinación entre agentes, entidades, oráculo, router de modelos, «dreaming», base de conocimiento, federación y almacenes tipados.

### CLI (`omega`)

Lo mismo que el MCP y además `timeline`, `remind`, `backup`, `validate`, `eval-retrieval`, `stats` y **`export-obsidian`** (`--output-dir`, `--project`, `--limit`).

Probado `export-obsidian` con 5 memorias: genera `omega-memories/_index.md` y una nota por memoria en carpetas por tipo. El frontmatter trae `id`, `type`, `tags`, `created`, `strength`, `project` y `ttl_seconds`, pero las tags salen basura (rutas como `/fd/eza/yq/mdq`). Sirve como materia prima para migrar, no tal cual.

### Hooks (`omega.hooks.fast_hook`)

En fabrik se usan 5 de 18: `session_start`, `session_stop`, `surface_memories`, `auto_capture` y `assistant_capture`. El resto:
- coordinación entre agentes: `coord_*`, `auto_claim_file`, `pre_file_guard`, `pre_commit_guard`, `pre_push_guard`, `pre_add_guard`, `pre_task_guard`, `pre_deploy_guard`;
- disciplina «leer antes de escribir»: `track_file_read` y `pre_edit_surface`;
- otros: `post_edit_test`, `trace_capture`, `pre_protocol_gate` y `pre_alignment_gate`.

## Auditoría de Obsidian

| Vía | Requiere | Para memoria |
| --- | --- | --- |
| mcpvault (`@bitbonsai/mcpvault` 0.16.0) | Nada, trabaja sobre archivos | Lee y escribe notas, frontmatter y tags, y busca (como máximo 20 resultados). **Sin backlinks.** `wiki_link` con un nombre repetido devuelve uno sin avisar |
| CLI (`obsidian`, 1.12.7+; instalada la 1.14.4) | **La app abierta: si no lo está, la lanza** | Lo más rico: `backlinks`, `links`, `orphans`, `deadends`, `unresolved`, `properties`, `property:set`, `search:context`, `tags`, `base:query`, `tasks`, `history` y `diff`, `eval` |
| URI (`obsidian://open`, `new`, `daily`, `unique`, `search`) | La app abierta y, en Linux, registrar el protocolo con un `.desktop` | Solo abre o crea notas en la interfaz y no devuelve datos (salvo `x-success`). No sirve |
| Headless (`ob`, `obsidian-headless` 0.0.2) | Node 22 y una cuenta de Sync | Solo Sync y Publish (`login`, `sync-*`, `sync`). No busca ni da backlinks. No sirve |
| Bases (`.base`) | La app, para verlas | Paneles para la persona. Opcional |

### Usar la CLI sin ventana

Se descartó:
- La única forma sería correr Obsidian en una pantalla virtual (Xvfb). La sesión es Wayland y Xvfb no está instalado.
- Obsidian es una sola instancia para todas las bóvedas: una instancia oculta capturaría la ventana al abrir el Obsidian normal. No está comprobado que separarlas con `--user-data-dir` funcione con la CLI.
- Los hooks dependerían de un proceso gráfico vivo.

Todo lo útil de la CLI para memoria se puede calcular leyendo los `.md`.

## Arquitectura

```text
                                    ┌─ el agente  → tools (buscar, leer, recordar, revisar)
núcleo (índice) ── servidor MCP ────┤
                   (stdio)          └─ los hooks  → type: "mcp_tool" (welcome, surface, constraints, checkpoint)
```

Una sola entrada. Claude Code permite hooks `type: "mcp_tool"` que llaman a un tool de un servidor MCP configurado, con `input` que admite sustituciones como `${tool_input.file_path}`. El texto que devuelve el tool se trata como el stdout de un hook de comando (ver [MCP tool hook fields](https://code.claude.com/docs/en/hooks#mcp-tool-hook-fields)). Así los hooks usan los mismos tools que el agente y la CLI sobra.

- **Solo tools**: el agente no usa CLI, ni Bash sobre el vault, ni Read, Edit o Write sobre `memory/`. Toda interacción pasa por los tools. Se impone con permisos `deny` en el `settings.json` de fabrik (`Read(//home/ana/src/episteme/**)`, y lo mismo con `Edit` y `Write`; `//` marca una ruta absoluta), no con una regla en el prompt. Bash no se puede cerrar del todo por patrones: se niegan `Bash(obsidian *)` y `Bash(omega *)`, y el resto lo cubre la regla del `CLAUDE.md` de fabrik.
- **Lenguaje**: Python, con el SDK oficial de MCP 2.x (`MCPServer`, antes `FastMCP`) y transporte stdio. Distribución y arranque en [Distribución y arranque](#distribución-y-arranque).
- **`instructions` del servidor**: Claude Code las inyecta en el system prompt. Dicen cuándo llamar a `context` (al empezar una tarea), a `search` (antes de decidir algo ya tratado) y a `remember` (al cerrar una decisión o aprender algo). Se pasan por keyword (`instructions=`): en la versión 2.x, si se pasan por posición, acaban en `title`.
- **Anotaciones**: `ToolAnnotations(read_only_hint=True)` en `search`, `read`, `links`, `review`, `context`, `surface` y `constraints`. Así se pueden permitir sin preguntar en `settings.json`, y `remember`, `revise` y `checkpoint` quedan sujetos a permiso.
- **Índice SQLite** en `.episteme/index.db`, fuera de git:
  - FTS5 con `unicode61 remove_diacritics` para buscar bien en español;
  - tablas de enlaces, tags y propiedades;
  - reindexado incremental por `mtime`, sin servicio vigilando los archivos;
  - modo WAL y escrituras atómicas (temporal + `rename`) para varias sesiones a la vez.
- **Zonas con política propia** en `episteme.toml`, impuestas por el motor y no por una regla en el prompt:
  - `docs/claude-code/`: solo lectura (copia fiel de la fuente);
  - `memory/<proyecto>/`: escritura con validación del esquema.
- **Wikilinks compatibles con Obsidian** (subconjunto): `[[nota]]`, `[[ruta/nota]]`, `#encabezado`, `^bloque`, alias y enlaces dentro de las propiedades. Un nombre ambiguo devuelve **error con los candidatos**.

### Ruta del vault

- **Obligatoria y sin valor por defecto**: `--vault <ruta absoluta>` o la variable `EPISTEME_VAULT` (manda el argumento). Si falta, si no es absoluta o si no existe, el servidor **no arranca** y deja un error claro en stderr. Nunca se deduce del `cwd` ni de `${CLAUDE_PROJECT_DIR}`.
- **Marca de vault**: la carpeta tiene que contener `episteme.toml`, que declara las zonas. Sin ese archivo no arranca, para que una ruta equivocada no convierta otra carpeta en vault ni le cree `.episteme/`.
- **Confinamiento**: toda ruta que llega a un tool se resuelve con `realpath` y tiene que quedar dentro del vault. Se rechazan `..`, las rutas absolutas y los symlinks que salen de él.
- **Índice**: `<vault>/.episteme/index.db`; `.episteme/` va al `.gitignore` del vault.
- **Proyecto por defecto**: `--project <nombre>` (opcional, p. ej. `fabrik`) lo usan `remember`, `context` y `checkpoint` cuando no se indica otro, para no pasarlo en cada llamada.

```toml
# episteme.toml (raíz del vault)
[zones."docs/claude-code"]
mode = "read-only"

[zones."memory"]
mode = "memory"        # escritura solo vía remember/revise, con validación del esquema

[zones."plans"]
mode = "read-write"
```

## Distribución y arranque

Decisión: **`uvx` desde un tag de GitHub**. El código vive en `Bajmein/episteme-mcp` (privado) y `episteme` queda solo para los datos.

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+ssh://git@github.com/Bajmein/episteme-mcp@v0.1.0 episteme-mcp \
  --vault /home/ana/src/episteme --project fabrik
```

- **Scope local** (`~/.claude.json`), como hoy `obsidian-episteme` en fabrik: la ruta del vault es de la máquina y no se versiona. Otro proyecto que lo use se añade igual, con su `--project`.
- **`git+ssh`** porque el repo es privado: `uvx` clona con la clave SSH del usuario, la misma que ya usa `git push`. `git+https` pediría un token.

| Opción | A favor | En contra | Veredicto |
| --- | --- | --- | --- |
| **uvx + tag de git** | La versión queda fijada en la propia config; no instala nada global; caché (tras la primera vez arranca rápido); corre como el usuario, así que los archivos quedan con su dueño y no hay que montar volúmenes; no exige publicar en PyPI | La primera ejecución descarga y necesita red | **Elegida** |
| uvx + PyPI | Igual, con un argumento más corto | Obliga a publicar y a cuidar el nombre en PyPI para un uso personal | Más adelante, si se comparte |
| pipx | Instalación estable | La versión vive en el sistema y no en la config (se desvía entre máquinas); hay que actualizar a mano | Descartada |
| Docker (imagen en GHCR) | Aislamiento y reproducibilidad | Con stdio hay **un contenedor por sesión** (latencia al arrancar); hay que montar el vault (`-v …:/vault:z` por SELinux en Fedora); los archivos se escriben con el UID del contenedor salvo `--user`; depende de un demonio (Fedora trae podman); SQLite en WAL sobre un bind mount compartido entre contenedores está sin probar. Para un servidor cuyo trabajo **es** leer y escribir archivos locales, el aislamiento estorba | Descartada. Solo tendría sentido como servidor HTTP remoto, fuera de alcance |
| `uv run --directory <checkout>` | Cómodo para iterar | No fija versión | Solo para desarrollo |

- **Actualizar** es cambiar el tag en la config. El tag lo crea la persona en local cuando CI está en verde: desde el cloud no se puede, porque el proxy de GitHub de las sesiones cloud rechaza los push de tags.
- **Desarrollo**: una entrada `episteme-dev` con `uv run --directory ~/Bajmein/episteme-mcp episteme-mcp --vault …` en el scope local, sin tocar la de producción.

## Memoria

### Estructura

```text
episteme/memory/
  _shared/            perfil.md y preferencias que valen para todos los proyectos
  <proyecto>/         p. ej. fabrik/
    decisions/  lessons/  errors/  constraints/  preferences/
    sessions/         episódica: resumen por sesión y checkpoints con caducidad
    reminders/
    _dashboard.base   vista para la persona en Obsidian (opcional)
```

### Esquema de una memoria

```yaml
type: decision          # decision | lesson | error | constraint | preference | session | reminder | insight
kind: semantic          # semantic | procedural | episodic (sale del type)
project: fabrik
priority: 4             # 1-5, ver «Prioridad» abajo
status: active          # active | superseded | speculative | archived
created: 2026-10-19
valid_until:            # para preguntar qué valía en una fecha
tags: [dominio/explore, pieza/serena_guard]   # tags anidadas con '/': Obsidian no admite ':'
files: [.claude/hooks/serena_guard.py]        # se muestra al tocar ese archivo
supersedes: "[[2026-09-12-serena-pyright]]"
related: ["[[...]]"]
contradicts: []
source: <sha o PR>
helpful: 0              # equivale al feedback de OMEGA
due:                    # solo en los recordatorios
```

Las relaciones son wikilinks en las propiedades: Obsidian los cuenta como enlaces y backlinks, y el motor los indexa como aristas tipadas (`supersedes`, `related`, `contradicts`, `derived_from`).

- **Nombre del archivo**: `AAAA-MM-DD-<slug>.md` dentro de la carpeta de su tipo (`decision` → `decisions/`, `lesson` → `lessons/`, `error` → `errors/`, `constraint` → `constraints/`, `preference` → `preferences/`, `session` → `sessions/`, `reminder` → `reminders/`, `insight` → `insights/`). El slug sale del título, en minúsculas, sin tildes y con guiones. Si ya existe, se añade `-2`, `-3`…
- **Cuerpo**: un `# Título` y el texto. Debe nombrar los archivos, tools o comandos que toca: son lo que se busca.
- **`kind` sale del `type`**: `session` → `episodic`; `lesson`, `error` y `constraint` → `procedural`; el resto → `semantic`.
- **`priority` por defecto**: 4 en `decision` y `constraint`, 3 en el resto.

### Prioridad

Decide qué sale en la bienvenida de cada sesión (pesa 0,45 frente a 0,35 de lo reciente y 0,20 de `helpful`). En `search` solo desempata. Si todo es 5, nada destaca.

| `priority` | Para | Ejemplo |
| --- | --- | --- |
| 5 | Norma vigente que toda sesión debe tener presente | «Serena usa ty 0.0.89» |
| 4 | Decisión técnica de un cambio o de una herramienta (por defecto en `decision`) | «serena_guard sigue `cd $VAR` sin resolverlo» |
| 3 | Registro: qué se hizo o se auditó, sin norma que seguir | «PR #1 mergeada» |
| 1-2 | Contexto menor; no entra en la bienvenida salvo que no haya nada más | |

Cuando una norma cambia, se hace `revise(action="supersede")` con la nueva: la vieja pasa a `status: superseded` y no se le baja la prioridad.

### Tipos de OMEGA que se activan

Hoy en fabrik no se usan:
- constraints atadas a archivos (aviso antes de editar);
- recordatorios con fecha;
- feedback (`helpful`) que pesa en el orden de la bienvenida;
- `speculative` para lo no verificado;
- `valid_until` para consultas en el tiempo;
- memoria episódica de sesiones;
- revisión de contradicciones y de memorias viejas;
- paquete de contexto con presupuesto de tokens.

Se quedan fuera:
- la búsqueda semántica (fase 4 opcional);
- la captura automática de cada prompt (se reduce a «recuerda» → `preference`);
- todo lo Pro.

## Interfaz

### Tools del MCP

| Tool | Qué hace | Sustituye |
| --- | --- | --- |
| `search` | FTS con filtros (`path`, `type`, `tags`, `project`, `status`) y extracto por línea | `search_notes`, `omega_query` |
| `read` | Nota entera, una sección por encabezado o un rango de líneas, más el outline | `read_note`, `get_note_outline`, `read_note_lines` |
| `links` | Salientes, backlinks y `traverse` a N saltos | `wiki_link`, `omega_memory traverse`, `obsidian backlinks` |
| `remember` | Crea una memoria: valida el esquema, avisa de duplicados y enlaza | `omega_store` |
| `revise` | Edita el cuerpo o el frontmatter, `supersede` y `feedback` | `patch_note`, `update_frontmatter`, `omega_memory` |
| `review` | Memorias viejas sin uso, posibles contradicciones (mismas tags o archivos), enlaces rotos y huérfanas | `omega_reflect`, `obsidian orphans/unresolved` |
| `context` | Bienvenida (`mode="welcome"`: prioridad 0,45 + recencia 0,35 + `helpful` 0,20, más recordatorios vencidos) o paquete de contexto para una tarea, con presupuesto de tokens | `omega_welcome`, `session_start`, `context_packet` |
| `surface` | Memorias ligadas a un archivo (`files`) o a sus tags | `surface_memories` |
| `constraints` | Constraints activas de un archivo, para avisar antes de editarlo | constraints de `omega_maintain` |
| `checkpoint` | `save` o `restore` del estado de la tarea, a partir del archivo de estado del proyecto (ver [Checkpoints](#checkpoints)) | `omega_checkpoint`, `omega_resume_task`, `omega_checkpoint.py` |

### Hooks sobre tools

Los hooks son `type: "mcp_tool"` y llaman a los mismos tools que el agente:

| Evento | Tool | Nota |
| --- | --- | --- |
| `UserPromptSubmit` | `context(mode="welcome", session="${session_id}")` | Da la bienvenida de la sesión (ver abajo) |
| `PostToolUse` sobre `Edit\|Write` | `surface(file="${tool_input.file_path}")` | |
| `PreToolUse` sobre `Edit\|Write` | `constraints(file="${tool_input.file_path}")` | Avisa, no bloquea |
| `PreCompact` | `checkpoint(action="save")` | Es el guardado principal |
| `SessionStart` con matcher `compact\|clear` | `checkpoint(action="restore")` | Tras `/clear` o una compactación sí corren los `mcp_tool` |

**La bienvenida al arrancar.** En `SessionStart` con `startup` o `resume`, Claude Code **se salta** los hooks `mcp_tool`, porque los servidores aún no están conectados. Por eso la bienvenida se cuelga de `UserPromptSubmit`: el servidor guarda en el índice qué `session_id` ya la recibió, y en las llamadas siguientes devuelve vacío y no añade contexto. De respaldo, las `instructions` del servidor piden llamar a `context` al empezar una tarea. No hace falta CLI ni ningún hook de comando.

**`SessionEnd`** queda fuera: es observacional, no espera a un servidor que se esté conectando y tiene un presupuesto de 1,5 s. El checkpoint de `PreCompact` y el `remember` explícito del agente bastan.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "context",
                    "input": { "mode": "welcome", "session": "${session_id}" } }] }
    ],
    "PreToolUse": [
      { "matcher": "Edit|Write",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "constraints",
                    "input": { "file": "${tool_input.file_path}" } }] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "surface",
                    "input": { "file": "${tool_input.file_path}" } }] }
    ],
    "PreCompact": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "checkpoint",
                    "input": { "action": "save", "project_dir": "${cwd}" } }] }
    ],
    "SessionStart": [
      { "matcher": "compact|clear",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "checkpoint",
                    "input": { "action": "restore", "project_dir": "${cwd}" } }] }
    ]
  }
}
```

Si fabrik lo empaqueta como plugin, `server` pasa a ser el nombre con scope: `plugin:fabrik:episteme`.

### Checkpoints

El hook pasa `project_dir` (el `cwd` de la sesión) y el servidor busca ahí el archivo de estado con un patrón declarado en `episteme.toml`. Es la **única lectura fuera del vault** y está limitada a ese patrón. Las escrituras siguen confinadas al vault.

```toml
[checkpoint]
state_glob = ".fabrik/*/*/estado.md"   # relativo a project_dir
```

- **`save`**: toma el `estado.md` con `estado: activo` y el `mtime` más reciente. Guarda en `memory/<proyecto>/sessions/checkpoint-<slug de task_title>.md` (un archivo por tarea, que se sobrescribe) el frontmatter y las secciones Plan, Progreso, Decisiones, Trampas y Siguientes pasos. **La Bitácora no entra.** Lleva `type: session`, `valid_until` a 7 días y `task_title`. Si no hay estado activo, devuelve vacío y no es un error.
- **`restore`**: devuelve el texto del checkpoint vigente más reciente del proyecto, para que el hook lo inyecte al contexto.

Formato del `estado.md` que se lee (lo crea fabrik por cada change):

```markdown
---
task_title: <ID> · <change>
estado: activo         # activo | cerrado
etapa: idea            # idea | spec | design | tasks | build | close
---
# Estado · <ID>-<change> (<dominio>)

## Plan
## Progreso
## Decisiones
## Trampas
## Siguientes pasos
## Bitácora
```

## Fases

Las fases 1 a 3 se construyen en el cloud; lo que exige la máquina local está en [Pasos locales tras la entrega](#pasos-locales-tras-la-entrega).

1. **Lectura**: arranque con `--vault` obligatorio, `episteme.toml` y confinamiento de rutas. Índice, `search`, `read` y `links`. CI en GitHub Actions. Sustituye a mcpvault.
2. **Memoria**: esquema, `remember` y `revise`, y los tools de hooks: `context` en modo welcome, `surface`, `constraints` y `checkpoint`. Además, `scripts/migrate_omega.py`, que pasa una exportación de OMEGA al esquema (ver [Formato de la exportación de OMEGA](#formato-de-la-exportación-de-omega)).
3. **Revisión**: `review`, recordatorios y `context` en modo paquete de tarea.
4. **Opcional, fuera de este encargo**: embeddings multilingües con sqlite-vec, solo si la búsqueda léxica se queda corta.

## Ejecución en Claude Code cloud

La sesión cloud clona **solo** `Bajmein/episteme-mcp`. No ve fabrik, ni el vault real, ni OMEGA, ni nada de `~/.claude`. Todo lo que necesita está en el repo: este plan (`PLAN.md`), `CLAUDE.md` con las reglas de trabajo y un vault de prueba en `tests/fixtures/vault/`.

### Entorno

- VM Ubuntu 24.04 x86_64 con Python 3, `uv`, `pytest` y `ruff` preinstalados. La red **Trusted** por defecto llega a PyPI.
- **Sin setup script**: las dependencias se instalan con `uv sync` al empezar.
- El proxy de GitHub permite hacer push de **ramas**. No permite tags ni borrar ramas.
- **Entrega**: rama `feat/initial-implementation` y PR contra `main`. No se mergea desde el cloud.

### Estructura del repo

```text
episteme-mcp/
  PLAN.md  CLAUDE.md  README.md  pyproject.toml  uv.lock
  src/episteme_mcp/
    __main__.py      argumentos (--vault, --project), validación y arranque
    server.py        MCPServer: tools, anotaciones e instructions
    vault.py         episteme.toml, zonas, confinamiento y escrituras atómicas
    index.py         SQLite: FTS5, enlaces, tags, propiedades y reindexado por mtime
    markdown.py      frontmatter, encabezados, bloques y extractos
    links.py         resolución de wikilinks y grafo
    memory.py        esquema, remember, revise, review, welcome y surface
    checkpoint.py
  scripts/migrate_omega.py
  tests/
    fixtures/vault/          copia de docs/ de episteme más episteme.toml y memory/ de ejemplo
    fixtures/project/        project_dir de mentira con .fabrik/*/*/estado.md
    fixtures/omega-export/   exportación de OMEGA sintética
    test_*.py
  .github/workflows/ci.yml   uv sync, ruff check y pytest
```

- `pyproject.toml`: con `hatchling`, `requires-python = ">=3.11"` (por `tomllib`), dependencias `mcp>=2` y `pyyaml`, y el entry point `episteme-mcp = "episteme_mcp.__main__:main"`.
- Python con tipos y sin dependencias más allá de las necesarias. SQLite viene en la biblioteca estándar.

### Vault de prueba

`tests/fixtures/vault/` es una copia del vault real con `docs/` completo (≈2,6 MB, 40 notas con frontmatter, wikilinks y bloques `%% nav %%`), más:

- `episteme.toml` con las zonas de [Ruta del vault](#ruta-del-vault) y el `[checkpoint]`;
- `memory/fabrik/` con memorias sintéticas que cubren el esquema: una decisión sustituida por otra (`supersedes`), una constraint con `files`, un recordatorio con `due` y una lección con `helpful`;
- fuera del vault, `tests/fixtures/project/.fabrik/core/001-demo/estado.md`: un proyecto de mentira que hace de `project_dir` para `checkpoint`.

Los tests copian el vault a un directorio temporal (`tmp_path`) antes de escribir: el fixture no se modifica.

**Casos que se deben cumplir.** Vienen de los evals de la skill `obsidian` de fabrik, pasados a los tools nuevos, y van como tests de pytest que llaman a los tools por un cliente MCP en stdio:

| # | Caso | Se espera |
| --- | --- | --- |
| 1 | `search("PreToolUse", path="docs/claude-code")` | `hooks-reference.md` entre los primeros resultados, con extracto y número de línea; `read(note, heading="PreToolUse")` devuelve solo esa sección |
| 2 | `read("best-practices")` | Error que lista los dos candidatos: `docs/claude-code/best-practices.md` y `docs/claude-code/agent-skill-open-standard-doc-reference/best-practices.md` |
| 3 | `revise` o `remember` sobre `docs/claude-code/hooks-reference.md` | Rechazado por la zona de solo lectura, y el archivo queda igual |
| 4 | Rutas con `..`, absolutas o con un symlink que sale del vault | Rechazadas en todos los tools |
| 5 | Buscar «configuracion» sin tilde | Encuentra «configuración» (`remove_diacritics`) |
| 6 | `links("hooks-reference")` | Backlinks que incluyen `README.index.md` |
| 7 | `remember` con un duplicado casi exacto | Avisa del parecido y no crea un archivo en silencio |
| 8 | `revise(action="supersede")` | La vieja queda `superseded` y la nueva enlaza con `supersedes` |
| 9 | `context(mode="welcome", session="s1")` dos veces | La primera devuelve la bienvenida ordenada por la fórmula; la segunda, vacío |
| 10 | `surface(file=".claude/hooks/serena_guard.py")` y `constraints(...)` | Devuelven las memorias y la constraint de ese archivo |
| 11 | `checkpoint` save y luego restore con `project_dir` del fixture | Guarda sin la Bitácora y lo devuelve |
| 12 | Arrancar sin `--vault`, con una ruta relativa o sin `episteme.toml` | Sale con error y no crea `.episteme/` |
| 13 | Dos procesos escribiendo a la vez | No se corrompe el índice ni se pierden notas |
| 14 | `docs/claude-code/README.index.md`, cuyo frontmatter es YAML inválido (un `:` sin comillas en `description`; viene así del vault real) | Se indexa el cuerpo igualmente y `review` lo informa como frontmatter inválido; no tumba el reindexado |

### Formato de la exportación de OMEGA

`omega export-obsidian --output-dir <dir> --project fabrik --limit 1000` genera `omega-memories/_index.md` y una carpeta por tipo: `decisions/`, `checkpoints/`, `lessons/`, `sessions/` y `memories/` (esta última para `project_status` y `memory`). Sin `--limit`, solo exporta 25 memorias. Cada nota sigue este formato:

```markdown
---
id: mem-2af67ff7cad1
type: decision
tags: [pieza:omega]
created: 2026-10-19T05:15:25.686406+00:00
strength: 0.10
project: fabrik
ttl_seconds: 604800        # solo en algunas
---

<texto de la memoria>

## Related
- [[mem-5feda1094832]] - Evolution

## Metadata
- Access count: 2
- Source: session <uuid>   # solo en algunas
```

Reglas de `migrate_omega.py`:
- **Tipos**: `decision` → `decision`; `lesson_learned` → `lesson`; `error_pattern` → `error`; `constraint` → `constraint`; `user_preference` → `preference`; `session_summary` → `session`; `project_status`, `memory` y `task_completion` → `insight`. Los `checkpoint` **se descartan**.
- **Tags**: se conservan las que tienen prefijo, cambiando `:` por `/` (`dominio:auth` → `dominio/auth`). Se tiran las que son rutas (`/fd/eza`) o palabras sueltas añadidas por OMEGA.
- **`priority`** no viene en la exportación: se pone el valor por defecto del tipo. `helpful` = `Access count`.
- **Relaciones**: `[[mem-…]] - Evolution` pasa a `related`, con el nombre del archivo nuevo.
- Escribe en un vault de destino con la misma validación que `remember`, y con `--dry-run` muestra lo que haría.
- Se prueba con `tests/fixtures/omega-export/`, sintético y con el formato de arriba. La migración real se hace en local.

### Criterio de terminado

- `uv run ruff check` y `uv run pytest` en verde en local y en CI.
- Los 14 casos de [Vault de prueba](#vault-de-prueba) cubiertos por tests.
- `README.md` con la instalación por `uvx`, los argumentos, el `episteme.toml` y el bloque de hooks de [Hooks sobre tools](#hooks-sobre-tools).
- PR abierta desde `feat/initial-implementation` con el resumen de lo hecho y lo que queda.

## Pasos locales tras la entrega

Los hace la persona en su máquina, fuera del cloud:

1. **Revisar y mergear la PR**, y luego `git tag v0.1.0 && git push --tags`.
2. **En `episteme`**:
   - crear `episteme.toml`;
   - añadir `.episteme/` al `.gitignore`;
   - documentar `memory/`, `plans/`, `episteme.toml` y `.episteme/` en la sección «Estructura» del `CLAUDE.md`.
3. **En fabrik**:
   - registrar el servidor con `claude mcp add --scope local` (ver [Distribución y arranque](#distribución-y-arranque));
   - añadir a `settings.json` los hooks de [Hooks sobre tools](#hooks-sobre-tools), los `deny` de [Arquitectura](#arquitectura) y el `allow` de los tools de solo lectura (`mcp__episteme__search`, `read`, `links`, `review`, `context`, `surface` y `constraints`);
   - en `CLAUDE.md`, cambiar «Solo MCP: ni CLI de Obsidian ni git sobre el vault» por «solo los tools de episteme-mcp: ni CLI, ni Bash, ni Read/Edit/Write sobre el vault».
4. **Migrar OMEGA**:
   - exportar con `omega export-obsidian --project fabrik --limit 1000`;
   - probar `scripts/migrate_omega.py --dry-run` y luego ejecutarlo de verdad sobre `episteme`;
   - las etiquetas pasan de `dominio:x` a `dominio/x`.
5. **Convivencia**: unas semanas **en paralelo con OMEGA**, comparando la bienvenida y lo que sale al tocar archivos.
6. **Retirada**: mcpvault (`obsidian-episteme`), la skill `obsidian` de fabrik y OMEGA (sus hooks en `.claude/settings.json` y `.claude/rules/omega.md`).

## Riesgos

- Se convierte en un producto que hay que mantener. El freno es el alcance: nada de sync, publicación ni interfaz.
- La resolución de wikilinks de Obsidian tiene casos raros. Con el subconjunto de arriba y `review` detectando enlaces rotos basta.
- Varias sesiones escribiendo a la vez: cada sesión arranca su propio proceso stdio sobre el mismo `index.db`. Se cubre con escrituras atómicas y WAL, y hay que probarlo en la fase 2.
- Los hooks dependen de que el servidor esté conectado. Si no lo está, el hook da un error no bloqueante: se pierde el aviso, pero la sesión sigue. Por eso `constraints` avisa y no actúa como barrera.
- `uvx` necesita red la primera vez que ve un tag. Después tira de la caché.

## Decisiones cerradas

- **Dónde vive el código**: repo aparte, `Bajmein/episteme-mcp`. `episteme` queda solo para los datos.
- **Distribución**: `uvx` desde un tag de GitHub (ver [Distribución y arranque](#distribución-y-arranque)).
- **Interfaz**: solo tools MCP, también para los hooks (`mcp_tool`); sin CLI.
- **Cómo se construye**: en una sesión de Claude Code cloud sobre `Bajmein/episteme-mcp`, **sin el flujo de fabrik**, que aún no está listo. El plan y el contexto van en el propio repo.
