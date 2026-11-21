# Configuración

[← Volver al README](../README.md)

## Argumentos del servidor

| Argumento | Qué hace |
| --- | --- |
| `--vault <ruta absoluta>` | Opcional (o la variable `EPISTEME_VAULT`; manda el argumento). Por defecto, `~/.episteme`, que se crea si falta. Una ruta explícita que no es absoluta, no existe o no tiene `episteme.toml` impide arrancar: el servidor sale con código ≠ 0 sin crear nada |
| `--project <nombre>` | Opcional. Proyecto por defecto de `remember`, `context`, `surface`, `constraints`, `session`, `plan` y `review` |

Variables:

- `EPISTEME_TODAY=AAAA-MM-DD` fija la fecha de hoy (por defecto, la fecha local). Existe para los tests.
- `EPISTEME_ACTIVITY=0` desactiva el registro de actividad (no se crea `activity.db`).

Cada llamada a un tool deja una fila en `<vault>/.index/activity.db`: tool, hook y sesión, proyecto, argumentos de orientación (consulta, ruta, modo; nunca el cuerpo de las notas ni los mensajes), rutas de las notas que devolvió, tamaño de la respuesta, milisegundos, si fue bien y el cliente MCP (`client`: el `clientInfo.name` del `initialize` o, si no lo hubo, del `_meta` de la petición). Cuando la llamada no trae `session`, la sesión sale del `_meta` `antigravity.google/root_conversation_id` (agy). Un `activity.db` del esquema 1 gana la columna `client` sin perder filas. Si un argumento parece una credencial, se guarda `[redacted: <tipo>]` en su lugar (filtro de mejor esfuerzo). Sirve para diagnosticar y como señal de uso. No se borra al reconstruir el índice, y se descartan las filas de más de 180 días.

```sh
sqlite3 <vault>/.index/activity.db "select at, tool, hook_event, ok, ms from calls order by id desc limit 20"
sqlite3 <vault>/.index/activity.db "select tool, count(*) from calls where at >= date('now') group by tool"
```

El índice vive en `<vault>/.index/index.db`: es una caché que se reconstruye sola. Junto a él, `.index/maintenance.db` guarda cuándo corrió cada tarea de mantención y qué cambió (no se reconstruye). En Linux y macOS, `.index/` se crea con permisos 0700 y sus bases con 0600 (en Windows no aplica). Añade `.index/` al `.gitignore` del vault. Dentro está también `.index/docs-inbox/<suite>/`, la bandeja donde `docs_check.py` deja las páginas descargadas hasta que `docs_write` las toma con `body_ref`; no es caché del índice.

## `episteme.toml`

Marca la carpeta como vault y declara las zonas:

```toml
[zones."docs/claude-code"]
mode = "read-only"

[zones."memory"]
mode = "memory"        # escritura solo vía remember/revise, con validación del esquema

[zones."plans"]
mode = "read-write"    # revise puede editar; no hay tools para crear ni borrar

[zones."docs/mise"]
mode = "docs"          # suite de documentación: solo docs_write escribe (ver documentacion.md)

[zones."sesiones"]
mode = "session"       # estado de la sesión: solo el tool session escribe; se añade si no se declara

[zones."planes"]
mode = "plan"          # copias de los planes: solo el tool plan escribe; se añade si no se declara

[session]                     # opcional; estos son los valores por defecto
extract = true                # orden de extracción tras /clear, compact sin bloque y al retomar
compact_state = true          # el resumen de compactación escribe el estado de la sesión
archive_days = 7              # días sin guardar antes de archivar el estado
nudge_every = 0               # mensajes sin guardar antes del aviso (0: apagado)

[plans]                       # opcional; este es el valor por defecto
archive_days = 7              # días sin guardar antes de archivar la copia de un plan

[maintenance]            # opcional; estos son los valores por defecto
every_days = 1           # periodo mínimo entre ejecuciones de cada tarea
notify = true            # avisa de los pendientes de review
archive_expired = false  # archiva las memorias con valid_until pasado

[backup]                 # opcional; sin dir no hay backup
dir = '/ruta/absoluta/fuera/del/vault'   # entre comillas simples, también en Windows
keep = 14                # copias que se conservan
```

- `[maintenance]`, `[backup]`, `[session]` y `[plans]` rechazan claves desconocidas. `every_days`, `keep` y `archive_days` son enteros >= 1 y `nudge_every`, un entero >= 0; `notify`, `archive_expired`, `extract` y `compact_state`, booleanos (`block_manual_compact`, obsoleta desde 0.18, se acepta si es booleana y se ignora); `[backup]` exige un `dir` absoluto fuera del vault.
- `mode` es `read-only`, `read-write`, `memory`, `docs`, `session` o `plan`. Un valor distinto o una zona repetida impiden arrancar.
- Una zona `docs` es una suite de documentación de terceros: solo la cambia `docs_write` (lo usa la skill `/episteme-docs:docs`, del plugin `episteme-docs`); los tools `docs_status` y `docs_write` existen solo si hay al menos una zona `docs`, y cambiar las zonas pide reiniciar el servidor; `revise` responde `read_only_zone`, `review` la trata como de solo lectura y el backup no la incluye, porque las páginas se pueden volver a bajar. Ver [Suites de documentación](documentacion.md).
- Una zona `session` guarda el estado de la sesión: solo la cambia el tool `session`; `revise` y `remember` responden `read_only_zone` y `review` la trata como de solo lectura. Si `episteme.toml` no declara ninguna, se añade `sesiones` con ese modo (declarar `sesiones` con otro modo impide arrancar). A diferencia de `docs`, entra en el backup. Ver [Estado de la sesión](sesion.md).
- Una zona `plan` guarda las copias de los planes de plan mode: solo la cambia el tool `plan`; `revise` y `remember` responden `read_only_zone` y `review` la trata como de solo lectura. Si `episteme.toml` no declara ninguna, se añade `planes` con ese modo (declarar `planes` con otro modo impide arrancar). Entra en el backup. No tiene que ver con una zona `read-write` llamada `plans`. Ver [Planes](planes.md).
- Una tabla `[checkpoint]` de versiones anteriores se ignora: el tool `checkpoint` ya no existe.
- Lo que no está en ninguna zona es de solo lectura. Si dos zonas se anidan, manda la más específica.
- Se ignoran `.obsidian/`, `.index/`, `.git/`, toda carpeta que empiece por `.` y los archivos que no son `.md`.
- Toda ruta se confina al vault: se rechazan `..`, las rutas absolutas y los symlinks que salen (`outside_vault`).
