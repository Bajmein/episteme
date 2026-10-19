# episteme-mcp: motor Markdown servido por MCP

> [!NOTE]
> **Decisión.** Hacer de `episteme` un vault **independiente de Obsidian**, de su MCP (mcpvault) y de su CLI, servido por un motor propio con **una sola entrada: un servidor MCP**. El agente y los hooks usan los mismos tools; no hay CLI. Ese motor sustituye a mcpvault (documentación) y a OMEGA (memoria). Se distribuye con `uvx` desde un tag de GitHub y arranca con la ruta del vault obligatoria. Obsidian deja de ser una dependencia y queda como compatibilidad: los archivos siguen siendo Markdown con wikilinks, frontmatter y tags, y la app sirve para mirarlos.

Estado: **listo para ejecutar en Claude Code cloud** sobre el repo privado `Bajmein/episteme-mcp` (ver [Ejecución en Claude Code cloud](#ejecución-en-claude-code-cloud)). Nada implementado. **Este archivo es la fuente del plan**; la nota `plans/episteme-mcp.md` del vault `episteme` es solo un registro.

## Cómo usar este documento

Está escrito para el agente que lo va a ejecutar en una sesión de Claude Code cloud, que **solo ve este repo** y no puede preguntarle nada a nadie.

**Orden de lectura**
1. Este apartado y el [Glosario](#glosario).
2. [Contexto y objetivo](#contexto-y-objetivo) y [Alcance](#alcance): qué se construye y qué no.
3. De [Arquitectura](#arquitectura) a [Migración de OMEGA](#migración-de-omega): la especificación. Es **normativa**.
4. [Ejecución en Claude Code cloud](#ejecución-en-claude-code-cloud): los pasos en orden, el vault de prueba, los casos que deben pasar y la plantilla de la PR. Se trabaja siguiendo los pasos de ahí.
5. Los anexos ([Anexo A Auditoría de OMEGA](#anexo-a-auditoría-de-omega) y [Anexo B Auditoría de Obsidian](#anexo-b-auditoría-de-obsidian)) son antecedentes: explican de dónde sale el diseño y **no son requisitos**. Se consultan solo si una regla no se entiende.

**Reglas**
- «Debe» y «nunca» son requisitos. «Conviene» y «por defecto» admiten un cambio justificado.
- Si algo es ambiguo, elige lo más simple que cumpla los tests y anótalo en «Desvíos del plan» de la PR. Si algo es imposible o se contradice, no lo resuelvas en silencio: anótalo igual.
- Lo que el plan no pide no se construye. En particular, no hay tools que muevan, borren o creen notas fuera de `memory/` (ver [Alcance](#alcance)).
- No hay acceso a nada que no esté en el repo. Lo que haga falta de fabrik, de OMEGA o del vault real ya está volcado en este documento o en `tests/fixtures/`.
- El SDK de MCP es el paquete `mcp` 2.x. Si una firma de este plan no coincide con la del SDK instalado, **manda el SDK**: lee su código en `.venv` y anota el cambio.

### Glosario

| Término | Qué es |
| --- | --- |
| La persona | El dueño del vault (GitHub `Bajmein`). Es quien revisa la PR y hace los pasos locales |
| Vault | Carpeta de Markdown compatible con Obsidian, con un `episteme.toml` en la raíz. El real es `~/src/episteme` |
| Nota | Un archivo `.md` del vault |
| Memoria | Una nota de `memory/` con el esquema de [Memoria](#memoria) |
| Zona | Carpeta del vault con una política de escritura (`read-only`, `read-write` o `memory`), declarada en `episteme.toml` |
| fabrik | Proyecto de la persona: un flujo de trabajo con agentes. Es el primer cliente de este servidor. No se ve desde el cloud |
| change | Unidad de trabajo de fabrik, con un ID (p. ej. `001-demo`) y etapas `idea`, `spec`, `design`, `tasks`, `build` y `close` |
| `estado.md` | Archivo de estado de un change en el proyecto (`.fabrik/<dominio>/<change>/estado.md`). Lo lee `checkpoint` |
| OMEGA | Memoria que usa fabrik hoy y que este servidor sustituye. De ahí viene `scripts/migrate_omega.py` |
| mcpvault | `@bitbonsai/mcpvault`, el MCP que hoy lee y escribe el vault. También se sustituye |
| Hook | Comando que Claude Code ejecuta en un evento. Aquí son `type: "mcp_tool"`: llaman a un tool de este servidor |
| `project_dir` | Carpeta del proyecto del agente (el `cwd` de la sesión). Distinta del vault |

## Contexto y objetivo

La persona usa agentes en varios proyectos y necesita una memoria que sobreviva a las sesiones: decisiones, lecciones, restricciones por archivo, recordatorios y el estado de la tarea. Hoy depende de tres piezas que no controla: mcpvault (leer y escribir), OMEGA (memoria) y la app de Obsidian (backlinks y propiedades).

Problemas de OMEGA ya vistos en fabrik:
- el mantenimiento automático (consolidate y compact) borraba decisiones sin accesos y mezclaba proyectos, y está frenado con fechas de 2099;
- la búsqueda semántica usa un modelo en inglés y rinde poco en español;
- la fusión silenciosa («Evolved») descarta las etiquetas nuevas;
- el grafo existe pero tiene **0 aristas**.

La memoria en Markdown es legible, editable a mano, versionable con git y navegable como grafo.

**Objetivo**: un servidor MCP en Python, `episteme-mcp`, que sirve un vault y ofrece 10 tools para buscar y leer notas, escribir y revisar memorias, y alimentar a los hooks de Claude Code. Funciona sin Obsidian.

## Alcance

**Entra**
- Los 10 tools de [Contrato de los tools](#contrato-de-los-tools).
- Índice SQLite con búsqueda de texto completo, enlaces, tags y propiedades.
- Zonas de escritura y confinamiento de rutas.
- Memoria con esquema, prioridad, recordatorios, feedback y revisión.
- Checkpoints de la tarea a partir del `estado.md` del proyecto.
- `scripts/migrate_omega.py`, que pasa una exportación de OMEGA al esquema.
- Tests, CI y README.

**Queda fuera**
- **Mover, renombrar, borrar o crear notas fuera de `memory/`.** Lo hace la persona en Obsidian. Sí se pueden editar notas de las zonas `read-write` (`revise`). Es lo que más se echa de mcpvault; no se añade para que el motor no crezca.
- **CLI** para el agente. El único script es `migrate_omega.py`.
- Búsqueda semántica o embeddings. Es una fase opcional posterior.
- Sync, publicación, interfaz web y servidor HTTP.
- Configurar fabrik, Claude Code o el vault real: son los [Pasos locales tras la entrega](#pasos-locales-tras-la-entrega).
- Todo lo Pro de OMEGA (ver [Anexo A Auditoría de OMEGA](#anexo-a-auditoría-de-omega)).

## Arquitectura

```text
                                    ┌─ el agente  → tools (buscar, leer, recordar, revisar)
núcleo (índice) ── servidor MCP ────┤
                   (stdio)          └─ los hooks  → type: "mcp_tool" (welcome, surface, constraints, checkpoint)
```

Una sola entrada. Claude Code permite hooks `type: "mcp_tool"` que llaman a un tool de un servidor MCP configurado, con `input` que admite sustituciones como `${tool_input.file_path}`. El texto que devuelve el tool se trata como el stdout de un hook de comando (ver [la referencia de hooks](https://code.claude.com/docs/en/hooks#mcp-tool-hook-fields)). Así los hooks usan los mismos tools que el agente y la CLI sobra.

- **Solo tools**: el agente no usa CLI, ni Bash sobre el vault, ni Read, Edit o Write sobre `memory/`. Toda interacción pasa por los tools. Se impone con permisos `deny` en el `settings.json` de fabrik (`Read(//home/ana/src/episteme/**)`, y lo mismo con `Edit` y `Write`; `//` marca una ruta absoluta), no con una regla en el prompt. Bash no se puede cerrar del todo por patrones: se niegan `Bash(obsidian *)` y `Bash(omega *)`, y el resto lo cubre la regla del `CLAUDE.md` de fabrik. Esto lo configura la persona, no el cloud.
- **Lenguaje**: Python 3.11 o superior, con el SDK oficial de MCP 2.x (`MCPServer`, antes `FastMCP`) y transporte stdio. Distribución y arranque en [Distribución y arranque](#distribución-y-arranque).
- **Todos los tools devuelven `str`**: en modo agente es un JSON (`json.dumps(..., ensure_ascii=False)`); en modo hook es exactamente lo que el hook debe emitir ([Modo hook](#modo-hook)). Un error se lanza como excepción y el SDK lo convierte en `isError` ([Errores](#errores)). Así no hay que lidiar con esquemas de salida.
- **Anotaciones**: `ToolAnnotations(read_only_hint=True)` en `search`, `read`, `links`, `review`, `context`, `surface` y `constraints`. Así se pueden permitir sin preguntar en `settings.json`, y `remember`, `revise` y `checkpoint` quedan sujetos a permiso. Ojo: `context(mode="welcome")` apunta en el índice qué sesión ya recibió la bienvenida; eso no toca el vault y sigue siendo de solo lectura a efectos del permiso.
- **Índice SQLite** en `.episteme/index.db`, fuera de git ([Parser e índice](#parser-e-índice)).
- **Zonas con política propia** en `episteme.toml`, impuestas por el motor y no por una regla en el prompt ([Vault y episteme.toml](#vault-y-epistemetoml)).
- **Wikilinks compatibles con Obsidian** (subconjunto): `[[nota]]`, `[[ruta/nota]]`, `#encabezado`, `^bloque`, alias y enlaces dentro de las propiedades. Un nombre ambiguo devuelve **error con los candidatos**.

### Ruta del vault

- **Obligatoria y sin valor por defecto**: `--vault <ruta absoluta>` o la variable `EPISTEME_VAULT` (manda el argumento). Si falta, si no es absoluta o si no existe, el servidor **no arranca**: sale con código distinto de 0 y un error claro en stderr. Nunca se deduce del `cwd` ni de `${CLAUDE_PROJECT_DIR}`.
- **Marca de vault**: la carpeta tiene que contener `episteme.toml`. Sin ese archivo no arranca, para que una ruta equivocada no convierta otra carpeta en vault ni le cree `.episteme/`.
- **Confinamiento**: toda ruta que llega a un tool se resuelve con `realpath` y tiene que quedar dentro del vault. Se rechazan `..`, las rutas absolutas y los symlinks que salen de él (`outside_vault`).
- **Índice**: `<vault>/.episteme/index.db`; la persona añade `.episteme/` al `.gitignore` del vault.
- **Proyecto por defecto**: `--project <nombre>` (opcional, p. ej. `fabrik`) lo usan `remember`, `context`, `surface`, `constraints` y `checkpoint` cuando no se indica otro, para no pasarlo en cada llamada.
- **Fecha de hoy**: sale del reloj (UTC), salvo que exista la variable `EPISTEME_TODAY=AAAA-MM-DD`, que la fija. Existe para que los tests sean deterministas.

### Texto de instructions

El servidor se crea con `MCPServer("episteme", instructions=INSTRUCTIONS)`. **Siempre por keyword**: en la versión 2.x, si se pasa por posición, acaba en `title`. Claude Code inyecta el texto en el system prompt. Este es el texto, para pegar tal cual:

```text
episteme is the project memory and documentation vault. Use only these tools; never read or edit the vault with Bash, Read, Edit or Write.
- At the start of a task, call context(mode="task", task="<what you are about to do>") to load relevant decisions, constraints and lessons.
- Before deciding something that may already have been decided, call search, then read the best hit.
- When you close a decision, learn a lesson, hit an error worth remembering, or the user says "remember", call remember. Name the files, tools or commands involved in the body: that is what is searched later.
- When a memory is wrong or replaced, call revise (action="supersede" or "archive"), never remember a contradiction next to it.
- Notes under read-only zones (docs/claude-code) cannot be changed. Errors say what failed and what to do.
```

## Vault y episteme.toml

`episteme.toml` en la raíz del vault declara las zonas y, opcionalmente, los checkpoints. Esquema completo:

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

- Las claves de `zones` son rutas relativas a la raíz del vault, sin `/` final. `mode` es `read-only`, `read-write` o `memory`. Cualquier otro valor, o una clave de zona repetida, hace que el servidor no arranque.
- **Una ruta que no está en ninguna zona es de solo lectura.** Una escritura ahí falla con `read_only_zone`. Si dos zonas se anidan, manda la más específica (la ruta más larga).
- Solo hay una zona `memory` útil: `remember` escribe en `memory/<proyecto>/…` de la primera zona con `mode = "memory"`. Si no hay ninguna, `remember` falla con `invalid_argument`.
- El motor **ignora**: `.obsidian/`, `.episteme/`, `.git/`, las carpetas que empiezan por `.` y todo archivo que no sea `.md`. No se indexan ni se pueden leer.
- `[checkpoint]` es opcional. Sin `state_glob`, `checkpoint` falla con `invalid_argument` y dice cómo declararlo.

## Parser e índice

### Qué se extrae de cada nota

- **Frontmatter**: el bloque entre dos líneas `---` al principio. Se carga con `yaml.safe_load`. **Un frontmatter inválido no tumba nada**: se indexa el cuerpo completo, la nota queda marcada con `fm_valid = 0` y el error de YAML en `fm_error`, y `review` la informa ([Contrato de los tools](#contrato-de-los-tools)). Si el YAML carga pero no es un mapa, se trata igual.
- **Título**: la propiedad `title`; si no hay, el primer `# encabezado`; si no, el nombre del archivo sin `.md`.
- **Encabezados**: `#` a `######`, con su nivel y línea, ignorando los que están dentro de bloques de código.
- **Tags**: las del frontmatter (`tags`) y las `#tag` del cuerpo (letras, números, `_`, `-` y `/`; el `#` debe ir tras espacio o inicio de línea y no ser un encabezado). Las tags anidadas (`dominio/auth`) también cuentan por su prefijo (`dominio`).
- **Comentarios `%% … %%`**: su texto **no entra en la búsqueda**, pero los enlaces que contienen **sí cuentan** como enlaces (el bloque `%% nav:start %% … %% nav:end %%` de la documentación es justo eso).
- **Bloques de código**: no se buscan enlaces ni tags dentro.
- **Propiedades**: todo el frontmatter, como pares clave-valor. Los wikilinks dentro de valores de propiedades son enlaces tipados: la clave es el tipo (`supersedes`, `related`, `contradicts`, `derived_from`, `up`…). Los del cuerpo son de tipo `body`.

### Wikilinks

Sintaxis aceptada: `[[destino]]`, `[[destino|alias]]`, `[[destino#Encabezado]]`, `[[destino#^bloque]]`, `[[#Encabezado]]` (misma nota). Dentro de una tabla, `\|` es el separador de alias: se quita la barra invertida antes de interpretar.

**Resolución de un destino** (en este orden; el primero que da resultado gana):
1. **Ruta exacta** desde la raíz del vault, con o sin `.md` y sin distinguir mayúsculas.
2. **Nombre base** (sin carpeta ni `.md`, sin distinguir mayúsculas): si hay un único archivo con ese nombre, es ese.
3. **`aliases`** del frontmatter de alguna nota (sin distinguir mayúsculas).
4. Si en el paso 2 o 3 hay **varios candidatos**, la resolución falla con `ambiguous` y la lista de rutas. Si no hay ninguno, `not_found`.

El `#Encabezado` se compara sin distinguir mayúsculas ni espacios sobrantes; si no existe, el enlace resuelve a la nota pero se marca `heading_missing` (cuenta como roto en `review`). `^bloque` se acepta sin comprobar.

### Tablas

Esbozo (los nombres y tipos concretos los decide la implementación; estas columnas deben existir):

```sql
notes(path PRIMARY KEY, title, mtime_ns, size, zone, fm_valid, fm_error, type, project, status,
      priority, created, due, valid_until, helpful, flagged, body_hash)
fts   -- FTS5(title, tags, body, tokenize='unicode61 remove_diacritics 2'), rowid = notes.rowid
links(src, dst_raw, dst_path NULL, kind, heading, line)       -- dst_path NULL si no resuelve
tags(path, tag)
props(path, key, value)                                        -- value en JSON
welcomed(session_id PRIMARY KEY, at)                           -- bienvenida ya entregada
```

### Reindexado

- Antes de **cada** tool se recorre el vault y se compara `mtime_ns` y `size` con lo guardado: se reindexa lo que cambió y se borran del índice las notas que ya no existen. No hay demonio ni watcher.
- Tras escribir, el propio tool reindexa esa nota.
- SQLite en modo WAL, con `busy_timeout` de 5000 ms. Varias sesiones abren cada una su proceso sobre el mismo `index.db`: cada reindexado va en una transacción y los errores `database is locked` se reintentan.
- Las escrituras de notas son atómicas: archivo temporal en la misma carpeta y `os.replace`.
- Si `index.db` falta o está corrupto, se borra y se reconstruye entero. El índice es una caché: la verdad son los `.md`.

## Memoria

### Estructura

```text
episteme/memory/
  _shared/            perfil.md y preferencias que valen para todos los proyectos
  <proyecto>/         p. ej. fabrik/
    decisions/  lessons/  errors/  constraints/  preferences/  insights/
    sessions/         episódica: resumen por sesión y checkpoints con caducidad
    reminders/
    _dashboard.base   vista para la persona en Obsidian (opcional; el motor la ignora)
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
flagged: false          # lo pone revise(action="feedback", value="outdated")
```

Las relaciones son wikilinks en las propiedades: Obsidian los cuenta como enlaces y backlinks, y el motor los indexa como aristas tipadas.

**Validación** (al escribir con `remember` o `revise` en una zona `memory`; falla con `invalid_schema` y dice qué campo): `type`, `project`, `priority` (entero 1-5), `status` y `created` obligatorios; `reminder` exige `due`; `files` y `tags` son listas de texto; `tags` sin `:` ni espacios ni `#`; `project` sin `/` y distinto de `..`. Al **leer** no se valida: una memoria editada a mano con un campo mal se indexa igual y `review` la informa.

- **Nombre del archivo**: `AAAA-MM-DD-<slug>.md` dentro de la carpeta de su tipo (`decision` → `decisions/`, `lesson` → `lessons/`, `error` → `errors/`, `constraint` → `constraints/`, `preference` → `preferences/`, `session` → `sessions/`, `reminder` → `reminders/`, `insight` → `insights/`). El slug sale del título: minúsculas, sin tildes, solo `a-z0-9` y guiones, como máximo 60 caracteres. Si ya existe, se añade `-2`, `-3`…
- **Cuerpo**: un `# Título` y el texto. Debe nombrar los archivos, tools o comandos que toca: son lo que se busca.
- **`kind` sale del `type`**: `session` → `episodic`; `lesson`, `error` y `constraint` → `procedural`; el resto → `semantic`.
- **`priority` por defecto**: 4 en `decision` y `constraint`, 3 en el resto.
- **Orden de las claves** al escribir: el del esquema de arriba, y solo las que tienen valor (`valid_until`, `due`, `source`, `supersedes`, `related` y `contradicts` se omiten si están vacías).

### Prioridad

Decide qué sale en la bienvenida de cada sesión. En `search` solo desempata. Si todo es 5, nada destaca.

| `priority` | Para | Ejemplo |
| --- | --- | --- |
| 5 | Norma vigente que toda sesión debe tener presente | «Serena usa ty 0.0.89» |
| 4 | Decisión técnica de un cambio o de una herramienta (por defecto en `decision`) | «serena_guard sigue `cd $VAR` sin resolverlo» |
| 3 | Registro: qué se hizo o se auditó, sin norma que seguir | «PR #1 mergeada» |
| 1-2 | Contexto menor; no entra en la bienvenida salvo que no haya nada más | |

Cuando una norma cambia, se hace `revise(action="supersede")` con la nueva: la vieja pasa a `status: superseded` y no se le baja la prioridad.

### Fórmulas

**Bienvenida** (`context(mode="welcome")`)
- Candidatas: memorias del proyecto y de `_shared` con `status: active`, sin `valid_until` vencido (`valid_until` anterior a hoy) y que **no** sean `type: session` ni `type: reminder`.
- Puntuación: `0.45·(priority−1)/4 + 0.35·exp(−días/30) + 0.20·min(helpful,10)/10`, donde `días` son los días desde `created` hasta hoy (mínimo 0). Se ordenan de mayor a menor; el empate lo rompe `created` más reciente y luego la ruta.
- Antes de las memorias van los **recordatorios vencidos**: `type: reminder`, `status: active` y `due` menor o igual que hoy, del más antiguo al más nuevo.
- Tope: 10 entradas en total y 4000 caracteres. Se corta por entradas completas, nunca a media entrada.
- Formato (texto plano):

```text
episteme · memoria de <proyecto>
Recordatorios vencidos:
- [<due>] <título> (<ruta>)
Memorias:
- [<type> p<priority>] <título> (<ruta>) — <primera frase del cuerpo, ≤160 caracteres>
```

**Duplicados** (`remember`)
- Se normaliza el texto de `título + cuerpo`: minúsculas, sin tildes, solo letras y números, se descartan los tokens de menos de 3 caracteres.
- Similitud = Jaccard de los conjuntos de tokens (`|A∩B| / |A∪B|`) contra cada memoria `active` del mismo proyecto y del mismo `type`.
- Si la mayor es **≥ 0,8**, no se crea el archivo: devuelve `created: false` con la lista de parecidas. Con `force=true` se crea igual. Las parecidas entre 0,5 y 0,8 se devuelven en `similar` pero se crea igual.

**`review`**
- **Vieja**: `status: active`, `created` de hace más de 90 días, `helpful = 0` y `type` distinto de `preference` y de `constraint`.
- **Contradicción posible**: dos memorias `active` de `type` `decision` o `constraint`, del mismo proyecto, que **comparten un valor de `files` o al menos 2 tags**, y entre las que no hay enlace `supersedes` ni `contradicts`.
- **Huérfana**: memoria sin ningún enlace saliente a otra nota y sin ningún backlink.
- **Enlace roto**: un enlace sin destino (`dst_path` nulo) o con `heading_missing`, en cualquier zona.
- **Frontmatter inválido**: `fm_valid = 0` (o el esquema de memoria no cumple, para las memorias).
- **Marcada**: memorias con `flagged: true`.

## Contrato de los tools

Convenciones comunes:
- Los nombres de nota (`note`) aceptan una ruta relativa al vault (con o sin `.md`) o un nombre que se resuelve con el algoritmo de [Wikilinks](#wikilinks). Las rutas que devuelven los tools son siempre relativas al vault y con `/`.
- Todos los parámetros opcionales aparecen como `?` con su valor por defecto. Un parámetro con un tipo equivocado falla con `invalid_argument`.
- `project` por defecto es el de `--project`; si no hay ninguno y el tool lo necesita, `invalid_argument`.
- `hook_event` (texto, por defecto ausente) es solo para los hooks; ver [Modo hook](#modo-hook).
- Los ejemplos de respuesta son orientativos: las claves que aparecen deben existir; se pueden añadir más.

### Errores

Un error es una excepción que el SDK convierte en `isError: true`. El mensaje tiene siempre la forma `<código>: <qué falló>. <qué hacer>`:

| Código | Cuándo | Ejemplo |
| --- | --- | --- |
| `not_found` | La nota o el destino no existe | `not_found: no note "foo". Use search to find the path.` |
| `ambiguous` | Varios candidatos | `ambiguous: note name "best-practices" matches 2 notes: a.md, b.md. Pass the full path.` |
| `read_only_zone` | Escritura en una zona `read-only` o fuera de toda zona | `read_only_zone: docs/claude-code/x.md is in a read-only zone. Notes there are changed outside this server.` |
| `outside_vault` | Ruta con `..`, absoluta o con symlink que sale | `outside_vault: "../x" leaves the vault. Use a path relative to the vault.` |
| `invalid_schema` | La memoria no cumple el esquema | `invalid_schema: priority must be 1-5, got 9.` |
| `invalid_argument` | Parámetro faltante, mal tipado o combinación imposible | `invalid_argument: reminder needs due.` |

### `search`

`search(query: str, path: str? = None, type: str? = None, tags: list[str]? = None, project: str? = None, status: str? = None, limit: int = 20)`

- `query`: palabras separadas por espacio, todas deben aparecer (AND); `"entre comillas"` es una frase. Se escapan los operadores de FTS5: la consulta del usuario nunca se interpreta como sintaxis de FTS5. Sin diferenciar mayúsculas ni tildes.
- `path`: prefijo de ruta (p. ej. `docs/claude-code`). `type`, `project`, `status` y `tags` filtran por las propiedades de la nota; `tags` exige todas.
- **Por defecto excluye las memorias `superseded` y `archived`**. Con `status="superseded"` (u otro valor) se piden explícitamente; `status="any"` no filtra.
- `limit`: 1 a 100; fuera de rango, `invalid_argument`.
- Orden: `bm25` (título pesa 5 veces el cuerpo); en memorias, la prioridad solo desempata.
- Respuesta: `{"results": [{"path", "title", "line", "snippet", "score"}], "total": N}`. `line` es la línea (1-based) de la primera coincidencia en el archivo; `snippet`, unos 200 caracteres alrededor, con la coincidencia entre `**…**`; `score` mayor es mejor. `total` cuenta los resultados antes de `limit`.

### `read`

`read(note: str, heading: str? = None, lines: str? = None)`

- Sin más parámetros: la nota entera (frontmatter aparte, `content` es el cuerpo).
- `heading`: solo esa sección, desde su encabezado hasta el siguiente de igual o mayor nivel; se compara sin distinguir mayúsculas. Si no existe, `not_found` con la lista de encabezados.
- `lines`: rango `"10-40"` (1-based, ambos incluidos) sobre el archivo completo. `heading` y `lines` a la vez, `invalid_argument`.
- **Tope**: sin `heading` ni `lines`, el contenido se corta en 20 000 caracteres (en un salto de línea) y `truncated` es `true`; el mensaje del contenido termina con una línea que dice cuántas líneas faltan y que use `heading` o `lines`. Con `heading` o `lines` el tope es 60 000. Existen notas de 440 KB (`settings-reference.md`).
- Respuesta: `{"path", "frontmatter": {…}, "fm_valid": bool, "outline": [{"level", "text", "line"}], "content", "truncated": bool, "total_lines"}`.

### `links`

`links(note: str, direction: str = "both", depth: int = 1)`

- `direction`: `out`, `in` o `both`. `depth`: 1 a 3; con más de 1 se añaden las notas alcanzables siguiendo enlaces salientes.
- Respuesta: `{"path", "outgoing": [{"target", "path", "kind", "heading", "line", "resolved"}], "backlinks": [{"path", "kind", "line"}], "reachable": [{"path", "distance"}]}`. `reachable` solo existe con `depth > 1`. Los enlaces sin resolver aparecen con `path: null` y `resolved: false`.

### `remember`

`remember(type: str, title: str, body: str, project: str? = None, priority: int? = None, tags: list[str] = [], files: list[str] = [], related: list[str] = [], supersedes: str? = None, source: str? = None, due: str? = None, valid_until: str? = None, status: str = "active", force: bool = False)`

- Crea `memory/<project>/<carpeta>/AAAA-MM-DD-<slug>.md` (hoy) con el esquema de [Memoria](#memoria). `related` y `supersedes` aceptan una ruta o un nombre; se guardan como wikilink `"[[nombre]]"` y deben resolver (`not_found` si no).
- `project="_shared"` para lo que vale en todos los proyectos.
- Valida el esquema ([Memoria](#memoria)) y busca duplicados ([Fórmulas](#fórmulas)).
- Con `supersedes`, la nota vieja pasa a `superseded` como en `revise`.
- Respuesta: `{"created": bool, "path": str|null, "similar": [{"path", "title", "similarity"}]}`.

### `revise`

`revise(note: str, action: str, old: str? = None, new: str? = None, text: str? = None, heading: str? = None, fields: dict? = None, by: str? = None, value: str? = None)`

| `action` | Parámetros | Efecto | Zonas |
| --- | --- | --- | --- |
| `edit` | `old`, `new` | Reemplaza `old` por `new` en el cuerpo. `old` debe aparecer **una sola vez** (si no, `invalid_argument`) | `read-write`, `memory` |
| `append` | `text`, `heading?` | Añade `text` al final del cuerpo, o al final de la sección `heading` | `read-write`, `memory` |
| `set` | `fields` | Fusiona esas claves en el frontmatter; un valor `null` borra la clave | `read-write`, `memory` |
| `supersede` | `by` | La nota pasa a `status: superseded`; la nota `by` recibe `supersedes: "[[esta]]"` | `memory` |
| `feedback` | `value` | `helpful`: `helpful` +1. `unhelpful`: −1, mínimo 0. `outdated`: `flagged: true` | `memory` |
| `archive` | — | `status: archived` | `memory` |

- Escritura en una zona `read-only` o en ninguna: `read_only_zone`, sin tocar el archivo. Una acción de la columna `memory` sobre una nota de otra zona: `invalid_argument`.
- Reescribir el frontmatter lo vuelve a serializar con PyYAML (`sort_keys=False`, `allow_unicode=True`): se pierden los comentarios del frontmatter, el cuerpo no se toca. En las memorias se valida el esquema resultante antes de escribir; si falla, no se escribe nada.
- Respuesta: `{"path", "action", "changed": [campos o "body"]}`; en `supersede`, también `"by"`.

### `review`

`review(path: str? = None, project: str? = None, limit: int = 50)`

- Aplica las reglas de [Fórmulas](#fórmulas). `path` es un prefijo para acotar; `project` acota las comprobaciones de memorias; `limit` es por categoría.
- Respuesta: `{"stale": [{"path", "title", "days"}], "contradictions": [{"a", "b", "reason"}], "orphans": [path], "broken_links": [{"path", "target", "line"}], "invalid_frontmatter": [{"path", "error"}], "flagged": [path]}`.

### `context`

`context(mode: str = "welcome", session: str? = None, project: str? = None, task: str? = None, budget_tokens: int = 2000, hook_event: str? = None)`

- `mode="welcome"`: la bienvenida de [Fórmulas](#fórmulas). Con `session`, si ese `session_id` ya está en `welcomed`, devuelve vacío; si no, lo apunta y devuelve la bienvenida. Sin `session`, siempre la devuelve. Respuesta en modo agente: `{"text", "entries": [{"path", "score"}], "already_sent": bool}`.
- `mode="task"` (requiere `task`): paquete de contexto para una tarea.
  1. Candidatas: FTS con las palabras de `task` unidas por OR sobre memorias `active` del proyecto y de `_shared`.
  2. Puntuación: `0.5·relevancia + 0.3·(priority−1)/4 + 0.2·exp(−días/30)`, con la relevancia de `bm25` normalizada a 0-1 sobre el conjunto de candidatas.
  3. Se llena el presupuesto (`budget_tokens`, 1 token ≈ 4 caracteres): por memoria, título, ruta y los primeros 300 caracteres del cuerpo. Las `constraint` con `files` se listan primero.
  4. Al final, hasta 5 notas de otras zonas que coinciden con la tarea, solo como `ruta — título` (para que el agente las abra con `read`).
  Respuesta: `{"text", "entries": [{"path", "score", "kind": "memory|note"}]}`.

### `surface`

`surface(file: str, project_dir: str? = None, project: str? = None, limit: int = 5, hook_event: str? = None)`

- Memorias `active` del proyecto y de `_shared` que **no** son `constraint` y que (a) tienen ese archivo en `files`, o (b) mencionan su ruta relativa o su nombre de archivo en el cuerpo (frase en FTS). Las de (a) van antes. Hasta `limit`.
- Texto: `Memories about <file>:` y una línea por memoria: `- [<type> p<priority>] <título> (<ruta>) — <primera frase>`.
- Respuesta en modo agente: `{"file", "memories": [{"path", "title", "type", "priority", "match": "files|mention"}]}`. Si no hay ninguna, `memories` vacío (y en modo hook, salida vacía).

### `constraints`

`constraints(file: str, project_dir: str? = None, project: str? = None, hook_event: str? = None)`

- Memorias `type: constraint`, `status: active`, del proyecto y de `_shared`, con ese archivo en `files`.
- Texto: `Constraints that apply to <file>:` y, por cada una, `- <título> (<ruta>)` seguido del cuerpo (máx. 600 caracteres). Avisa, no bloquea.
- Respuesta en modo agente: `{"file", "constraints": [{"path", "title", "priority", "body"}]}`.

### `checkpoint`

`checkpoint(action: str, project_dir: str? = None, project: str? = None, hook_event: str? = None)`

- `action`: `save` o `restore`. `project_dir` por defecto es el `cwd` del proceso del servidor, pero los hooks lo pasan siempre (`${cwd}`). Detalle en [Checkpoints](#checkpoints).
- `save` → `{"saved": bool, "path", "task_title"}`; `saved: false` (sin error) si no hay `estado.md` activo.
- `restore` → `{"found": bool, "path", "task_title", "content"}`.

### Casado de `file` con `files`

`${tool_input.file_path}` llega como **ruta absoluta**; `files` en las memorias es **relativo al proyecto**. El casado, en `surface` y `constraints`:
1. Si `file` es absoluta y `project_dir` está presente y la contiene, se usa la ruta relativa a `project_dir`.
2. Si la entrada de `files` tiene `*`, `?` o `[`, se compara con `fnmatch` contra la ruta relativa.
3. Si no, coincide si la ruta relativa es igual a la entrada, o si `file` termina en `/` + entrada (sufijo por componentes completos: `x/.claude/hooks/a.py` casa con `.claude/hooks/a.py`, pero `a.py` no casa con `data.py`).

### Modo hook

Con `hook_event` presente el tool deja de devolver el JSON del modo agente y devuelve **exactamente lo que Claude Code espera de ese evento**:

| `hook_event` | Cómo llega al modelo | Salida del tool |
| --- | --- | --- |
| `UserPromptSubmit`, `SessionStart` | El texto plano del hook entra al contexto | El texto, sin JSON |
| `PreToolUse`, `PostToolUse` | El texto plano **solo va al debug log**; el modelo no lo ve | Un único objeto JSON: `{"hookSpecificOutput": {"hookEventName": "<evento>", "additionalContext": "<texto>"}}` |
| `PreCompact` | — | Cadena vacía |

- Si no hay nada que decir, la salida es **una cadena vacía** (no un JSON con texto vacío).
- El texto (`additionalContext` o plano) tiene un tope de **10 000 caracteres**; se corta en un salto de línea.
- El tool **nunca** devuelve `decision`, `permissionDecision` ni `continue: false`. En particular, `PreCompact` puede bloquear la compactación con `decision: "block"` y `checkpoint` no debe hacerlo jamás.
- Un fallo del tool es una excepción (`isError`): Claude Code lo trata como un error no bloqueante.
- Un `hook_event` que no es ninguno de los de arriba: `invalid_argument`.

## Hooks sobre tools

Los hooks son `type: "mcp_tool"` y llaman a los mismos tools que el agente:

| Evento | Tool | Nota |
| --- | --- | --- |
| `UserPromptSubmit` | `context(mode="welcome", session="${session_id}")` | Da la bienvenida de la sesión (ver abajo) |
| `PostToolUse` sobre `Edit\|Write` | `surface(file="${tool_input.file_path}")` | |
| `PreToolUse` sobre `Edit\|Write` | `constraints(file="${tool_input.file_path}")` | Avisa, no bloquea |
| `PreCompact` | `checkpoint(action="save")` | Es el guardado principal |
| `SessionStart` con matcher `compact\|clear` | `checkpoint(action="restore")` | Tras `/clear` o una compactación sí corren los `mcp_tool` |

Todos pasan `hook_event: "${hook_event_name}"`, y los que tocan archivos del proyecto pasan `project_dir: "${cwd}"`.

**Por qué el JSON en `Pre/PostToolUse`.** Según la referencia de hooks, en esos dos eventos el stdout en texto plano no llega al modelo. Por eso `constraints` y `surface` devuelven en esos eventos un objeto `hookSpecificOutput` con `additionalContext`, y el servidor decide el formato por `hook_event` ([Modo hook](#modo-hook)).

**La bienvenida al arrancar.** En `SessionStart` con `startup` o `resume`, Claude Code **se salta** los hooks `mcp_tool`, porque los servidores aún no están conectados. Por eso la bienvenida se cuelga de `UserPromptSubmit`: el servidor guarda en el índice qué `session_id` ya la recibió, y en las llamadas siguientes devuelve vacío y no añade contexto. De respaldo, las `instructions` del servidor piden llamar a `context` al empezar una tarea. No hace falta CLI ni ningún hook de comando.

**`SessionEnd`** queda fuera: es observacional, no espera a un servidor que se esté conectando y tiene un presupuesto de 1,5 s. El checkpoint de `PreCompact` y el `remember` explícito del agente bastan.

Este es el bloque que va al `settings.json` de fabrik (y al README):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "context",
                    "input": { "mode": "welcome", "session": "${session_id}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PreToolUse": [
      { "matcher": "Edit|Write",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "constraints",
                    "input": { "file": "${tool_input.file_path}", "project_dir": "${cwd}",
                               "hook_event": "${hook_event_name}" } }] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write",
        "hooks": [{ "type": "mcp_tool", "server": "episteme", "tool": "surface",
                    "input": { "file": "${tool_input.file_path}", "project_dir": "${cwd}",
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

Si fabrik lo empaqueta como plugin, `server` pasa a ser el nombre con scope: `plugin:fabrik:episteme`.

## Checkpoints

El hook pasa `project_dir` (el `cwd` de la sesión) y el servidor busca ahí el archivo de estado con el patrón `state_glob` de `episteme.toml`. Es la **única lectura fuera del vault** y está limitada a ese patrón (el glob se resuelve contra `project_dir` y se rechazan los resultados que salgan de él). Las escrituras siguen confinadas al vault.

- **`save`**: toma el `estado.md` con `estado: activo` y el `mtime` más reciente. Guarda en `memory/<proyecto>/sessions/checkpoint-<slug de task_title>.md` (un archivo por tarea, que se sobrescribe) el frontmatter y las secciones Plan, Progreso, Decisiones, Trampas y Siguientes pasos. **La Bitácora no entra.** Lleva `type: session`, `valid_until` a 7 días y `task_title`. Si no hay estado activo, devuelve vacío y no es un error. **Nunca bloquea `PreCompact`** ([Modo hook](#modo-hook)).
- **`restore`**: devuelve el texto del checkpoint vigente (`valid_until` no vencido) más reciente del proyecto, para que el hook lo inyecte al contexto. Si no hay, vacío.

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

## Migración de OMEGA

`scripts/migrate_omega.py` es el único script. La persona lo corre una vez en local; el cloud solo lo prueba con el fixture.

```bash
uv run scripts/migrate_omega.py --export <dir-omega-memories> --vault <dir-vault> --project fabrik [--dry-run]
```

- `--export`: la carpeta `omega-memories/` generada por OMEGA. `--vault`: vault de destino (con `episteme.toml`). `--project`: proyecto de las memorias. `--dry-run`: no escribe nada y muestra lo que haría.
- Salida: una línea por memoria (`+ decision → memory/fabrik/decisions/…` o `- checkpoint (descartada)`) y un resumen por tipo al final.
- Escribe con la misma validación que `remember` (reutiliza `memory.py`) y respeta la detección de duplicados. Es idempotente: una segunda ejecución no duplica nada.

### Formato de la exportación

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

### Reglas de conversión

- **Tipos**: `decision` → `decision`; `lesson_learned` → `lesson`; `error_pattern` → `error`; `constraint` → `constraint`; `user_preference` → `preference`; `session_summary` → `session`; `project_status`, `memory` y `task_completion` → `insight`. Los `checkpoint` **se descartan**.
- **Tags**: se conservan las que tienen prefijo, cambiando `:` por `/` (`dominio:auth` → `dominio/auth`). Se tiran las que son rutas (`/fd/eza`) o palabras sueltas añadidas por OMEGA.
- **Título**: la primera línea no vacía del texto, sin `#`, recortada a 80 caracteres.
- **`created`**: la fecha (sin hora) de `created`. **`priority`** no viene en la exportación: se pone el valor por defecto del tipo. `helpful` = `Access count`. `source` = `Source` si existe.
- **Relaciones**: `[[mem-…]] - Evolution` pasa a `related`, con el nombre del archivo nuevo (se hace en una segunda pasada, cuando todos los archivos ya tienen nombre).
- Se prueba con `tests/fixtures/omega-export/`, sintético y con el formato de arriba. La migración real se hace en local.

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
    markdown.py      frontmatter, encabezados, bloques, comentarios y extractos
    links.py         resolución de wikilinks y grafo
    memory.py        esquema, remember, revise, review, welcome y surface
    checkpoint.py
    hookmode.py      formato de salida por hook_event
  scripts/migrate_omega.py
  tests/
    fixtures/vault/          copia de docs/ de episteme más episteme.toml y memory/ de ejemplo
    fixtures/project/        project_dir de mentira con .fabrik/*/*/estado.md
    fixtures/omega-export/   exportación de OMEGA sintética
    test_*.py
  .github/workflows/ci.yml   uv sync, ruff check y pytest
```

- `pyproject.toml`: con `hatchling`, `requires-python = ">=3.11"` (por `tomllib`), dependencias **`mcp>=2.3,<3`** y `pyyaml`, y el entry point `episteme-mcp = "episteme_mcp.__main__:main"`. Dependencias de desarrollo (grupo `dev`): `pytest` y `ruff`.
- Python con tipos y sin más dependencias de las necesarias. SQLite viene en la biblioteca estándar; comprueba al arrancar que tiene FTS5 y, si no, sal con un error claro.
- `ci.yml`: `actions/checkout`, **`astral-sh/setup-uv@v10`**, `uv sync`, `uv run ruff check`, `uv run pytest`. En `push` y `pull_request`.

### Pasos

Un commit (Conventional Commits, en inglés) por paso, con `ruff` y `pytest` en verde antes de hacerlo. No pases al siguiente paso con el anterior en rojo. Todo en la rama `feat/initial-implementation`.

1. **Andamiaje**: `pyproject.toml`, `uv.lock`, paquete `episteme_mcp` con `__main__.py` que parsea `--vault` y `--project`, arranca un `MCPServer` con las `instructions` ([Texto de instructions](#texto-de-instructions)) y ningún tool todavía, y CI. *Verifica*: `uv run python -m episteme_mcp --vault <fixture>` arranca; sin `--vault` sale con error (caso 12 parcial). Commit: `chore: scaffold package, entry point and CI`.
2. **Vault y zonas**: `vault.py` con lectura de `episteme.toml`, validación de arranque, zonas, confinamiento (`realpath`), `read_only_zone` y escritura atómica. *Verifica*: casos 3 (a nivel de módulo), 4 y 12. Commit: `feat: vault config, zones and path confinement`.
3. **Parser e índice**: `markdown.py`, `links.py`, `index.py` ([Parser e índice](#parser-e-índice)). *Verifica*: frontmatter inválido tolerado (caso 14 a nivel de módulo), `%% %%`, resolución de wikilinks con ambigüedad, reindexado incremental, índice reconstruible. Commit: `feat: markdown parser, link resolution and SQLite index`.
4. **`search`, `read` y `links`**: los tools de lectura con sus anotaciones, y los tests de integración por stdio. *Verifica*: casos 1, 2, 5, 6, 17. Commit: `feat: search, read and links tools`.
5. **`remember` y `revise`**: esquema, nombres de archivo, duplicados, `supersede`, `feedback`, `archive`. *Verifica*: casos 3, 7, 8, 13. Commit: `feat: remember and revise tools with schema validation`.
6. **Tools de hooks y modo hook**: `context(mode="welcome")`, `surface`, `constraints`, `checkpoint` y `hookmode.py`. *Verifica*: casos 9, 10, 11, 15, 16, 19. Commit: `feat: hook tools and hook output mode`.
7. **`review` y `context(mode="task")`**. *Verifica*: casos 14 y 18, y los recordatorios vencidos. Commit: `feat: review and task context tools`.
8. **`migrate_omega`**: el script y sus tests con el fixture. Commit: `feat: OMEGA export migration script`.
9. **README y PR**: README en español con la instalación por `uvx`, los argumentos, el `episteme.toml`, los 10 tools y el bloque de hooks de [Hooks sobre tools](#hooks-sobre-tools); actualizar el estado de `README.md`. Push de la rama y PR con la [Plantilla de la PR](#plantilla-de-la-pr). Commit: `docs: add usage, tools and hook configuration`.

### Cómo se prueba

- **Unitarios** del núcleo (`vault`, `markdown`, `links`, `index`, `memory`, `checkpoint`, `hookmode`) llamando a las funciones.
- **Integración**: cada tool, al menos una vez, a través de un cliente MCP real. Se arranca `python -m episteme_mcp --vault <tmp_path>/vault --project fabrik` como subproceso con el cliente stdio del SDK (`stdio_client` y `ClientSession`), se hace `initialize`, `list_tools` (deben salir los 10 tools) y `call_tool`. Los errores se comprueban con `result.isError`. Se fija `EPISTEME_TODAY` en el entorno del subproceso. Comprueba la API exacta del SDK instalado.
- Los tests copian `tests/fixtures/vault/` a `tmp_path` antes de cualquier escritura (fixture de pytest). **El fixture no se modifica nunca.**
- Los tests no usan la red ni nada fuera del repo.

### Vault de prueba

`tests/fixtures/vault/` es una copia del vault real con `docs/` completo (≈2,6 MB, 40 notas con frontmatter, wikilinks y bloques `%% nav %%`), más:

- `episteme.toml` con las zonas de [Vault y episteme.toml](#vault-y-epistemetoml) y el `[checkpoint]`;
- `memory/fabrik/` con memorias sintéticas que cubren el esquema: una decisión sustituida por otra (`supersedes`), una constraint con `files` (`.claude/hooks/serena_guard.py`), un recordatorio con `due: 2026-10-21` y una lección con `helpful: 3`; y `memory/_shared/perfil.md`;
- fuera del vault, `tests/fixtures/project/.fabrik/core/001-demo/estado.md`: un proyecto de mentira que hace de `project_dir` para `checkpoint`;
- `tests/fixtures/omega-export/omega-memories/`: 5 memorias sintéticas en el formato de [Formato de la exportación](#formato-de-la-exportación).

El fixture no tiene carpeta `plans/` (el `episteme.toml` la declara igual). Para probar una zona `read-write`, el test crea `plans/x.md` en su copia.

### Casos que se deben cumplir

Vienen de los evals de la skill `obsidian` de fabrik, pasados a los tools nuevos, y de lo que esta especificación añade. Van como tests de pytest; los marcados con (i) pasan por el cliente MCP en stdio.

| # | Caso | Se espera |
| --- | --- | --- |
| 1 | (i) `search("PreToolUse", path="docs/claude-code")` | `hooks-reference.md` entre los primeros resultados, con extracto y número de línea; `read(note, heading="PreToolUse")` devuelve solo esa sección |
| 2 | (i) `read("best-practices")` | Error `ambiguous` que lista los dos candidatos: `docs/claude-code/best-practices.md` y `docs/claude-code/agent-skill-open-standard-doc-reference/best-practices.md` |
| 3 | (i) `revise` o `remember` sobre `docs/claude-code/hooks-reference.md` | Rechazado por la zona de solo lectura, y el archivo queda igual |
| 4 | (i) Rutas con `..`, absolutas o con un symlink que sale del vault | Rechazadas en todos los tools |
| 5 | (i) Buscar «configuracion» sin tilde | Encuentra «configuración» (`remove_diacritics`) |
| 6 | (i) `links("hooks-reference")` | Backlinks que incluyen `README.index.md` |
| 7 | (i) `remember` con un duplicado casi exacto | `created: false` y la parecida en `similar`; no crea un archivo en silencio. Con `force=true` lo crea |
| 8 | (i) `revise(action="supersede")` | La vieja queda `superseded` y la nueva enlaza con `supersedes` |
| 9 | (i) `context(mode="welcome", session="s1")` dos veces (con `EPISTEME_TODAY=2026-10-22`) | La primera devuelve primero el recordatorio vencido y luego las memorias ordenadas por la fórmula, sin las `superseded`; la segunda, vacío |
| 10 | (i) `surface(file=".claude/hooks/serena_guard.py")` y `constraints(...)` | `surface` devuelve las memorias del archivo y no la constraint; `constraints` devuelve la constraint |
| 11 | (i) `checkpoint` save y luego restore con `project_dir` del fixture | Guarda sin la Bitácora y lo devuelve; sin estado activo, `saved: false` sin error |
| 12 | Arrancar sin `--vault`, con una ruta relativa, con una ruta inexistente o sin `episteme.toml` | Sale con código ≠ 0 y error en stderr, y no crea `.episteme/` |
| 13 | Dos procesos escribiendo a la vez | No se corrompe el índice ni se pierden notas |
| 14 | `docs/claude-code/README.index.md`, cuyo frontmatter es YAML inválido (un `:` sin comillas en `description`; viene así del vault real) | Se indexa el cuerpo igualmente y `review` lo informa como frontmatter inválido; no tumba el reindexado |
| 15 | (i) `surface` y `constraints` con `hook_event="PostToolUse"` / `"PreToolUse"` | Un único objeto JSON con `hookSpecificOutput.hookEventName` igual al evento y `additionalContext` ≤ 10 000 caracteres; sin claves `decision`. Sin coincidencias, cadena vacía |
| 16 | (i) `constraints(file="<tmp>/proyecto/.claude/hooks/serena_guard.py", project_dir="<tmp>/proyecto")` | Casa con el `files` relativo de la constraint; `a.py` no casa con `data.py` |
| 17 | (i) `read("settings-reference")` sin `heading` | `truncated: true`, `content` ≤ 20 000 caracteres, aviso de cuántas líneas faltan |
| 18 | (i) `revise(action="append")` sobre una nota fuera de toda zona (p. ej. `scratch/x.md` creada en el test) | `read_only_zone`; en `plans/x.md` sí funciona |
| 19 | (i) `checkpoint(action="save", hook_event="PreCompact")` | Cadena vacía, nunca un JSON con `decision` |

### Criterio de terminado

- `uv run ruff check` y `uv run pytest` en verde en local y en CI.
- Los 19 casos de [Casos que se deben cumplir](#casos-que-se-deben-cumplir) cubiertos por tests.
- Los 10 tools (`search`, `read`, `links`, `remember`, `revise`, `review`, `context`, `surface`, `constraints`, `checkpoint`) aparecen en `list_tools` con descripciones en inglés.
- `README.md` con la instalación por `uvx`, los argumentos, el `episteme.toml` y el bloque de hooks de [Hooks sobre tools](#hooks-sobre-tools).
- PR abierta desde `feat/initial-implementation` con la [Plantilla de la PR](#plantilla-de-la-pr) rellena.

### Plantilla de la PR

```markdown
## Resumen
<qué se construyó, en 3-5 líneas>

## Cómo probar
uv sync && uv run ruff check && uv run pytest
uv run python -m episteme_mcp --vault tests/fixtures/vault --project fabrik

## Casos
<los 19 casos, con ✔ o ✘ y el test que los cubre>

## Desvíos del plan
<cada diferencia con PLAN.md y su motivo; «ninguno» si no hay>

## Pendiente
<lo que queda para la persona: tag v0.1.0 y los pasos locales>
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
- **Desarrollo**: una entrada `episteme-dev` con `uv run --directory ~/src/episteme-mcp episteme-mcp --vault …` en el scope local, sin tocar la de producción.

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
- Varias sesiones escribiendo a la vez: cada sesión arranca su propio proceso stdio sobre el mismo `index.db`. Se cubre con escrituras atómicas y WAL, y se prueba en el paso 5 (caso 13).
- Los hooks dependen de que el servidor esté conectado. Si no lo está, el hook da un error no bloqueante: se pierde el aviso, pero la sesión sigue. Por eso `constraints` avisa y no actúa como barrera.
- `uvx` necesita red la primera vez que ve un tag. Después tira de la caché.
- El contrato de `mcp_tool` es reciente: si Claude Code cambia la sustitución de variables o el tratamiento de la salida, se rompe el modo hook. Está aislado en `hookmode.py` y en el bloque de hooks.

## Decisiones cerradas

- **Nombre**: `episteme-mcp`.
- **Dónde vive el código**: repo aparte, `Bajmein/episteme-mcp`. `episteme` queda solo para los datos.
- **Distribución**: `uvx` desde un tag de GitHub (ver [Distribución y arranque](#distribución-y-arranque)).
- **Interfaz**: solo tools MCP, también para los hooks (`mcp_tool`); sin CLI.
- **Cómo se construye**: en una sesión de Claude Code cloud sobre `Bajmein/episteme-mcp`, **sin el flujo de fabrik**, que aún no está listo. El plan y el contexto van en el propio repo.
- **Sin mover ni borrar notas**: lo hace la persona en Obsidian.

## Anexo A Auditoría de OMEGA

Antecedente; no es un requisito. OMEGA 1.5.20, licencia Core. Estado en fabrik: 167 memorias.

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

### Qué se activa y qué se descarta

Hoy en fabrik no se usan y este servidor activa:
- constraints atadas a archivos (aviso antes de editar);
- recordatorios con fecha;
- feedback (`helpful`) que pesa en el orden de la bienvenida;
- `speculative` para lo no verificado;
- `valid_until` para consultas en el tiempo;
- memoria episódica de sesiones;
- revisión de contradicciones y de memorias viejas;
- paquete de contexto con presupuesto de tokens.

Se quedan fuera:
- la búsqueda semántica (fase opcional posterior);
- la captura automática de cada prompt (se reduce a «recuerda» → `preference`);
- todo lo Pro.

## Anexo B Auditoría de Obsidian

Antecedente; no es un requisito.

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
