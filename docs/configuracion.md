# Configuración

[← Volver al README](../README.md)

## Argumentos del servidor

| Argumento | Qué hace |
| --- | --- |
| `--vault <ruta absoluta>` | Opcional (o la variable `EPISTEME_VAULT`; manda el argumento). Por defecto, `~/.episteme`, que se crea si falta. Una ruta explícita que no es absoluta, no existe o no tiene `episteme.toml` impide arrancar: el servidor sale con código ≠ 0 sin crear nada |
| `--project <nombre>` | Opcional. Proyecto por defecto de `remember`, `context`, `surface`, `constraints`, `checkpoint` y `review` |

Variables:

- `EPISTEME_TODAY=AAAA-MM-DD` fija la fecha de hoy (por defecto, la fecha local). Existe para los tests.
- `EPISTEME_ACTIVITY=0` desactiva el registro de actividad (no se crea `activity.db`).

Cada llamada a un tool deja una fila en `<vault>/.index/activity.db`: tool, hook y sesión, proyecto, argumentos de orientación (consulta, ruta, modo; nunca el cuerpo de las notas ni los mensajes), rutas de las notas que devolvió, tamaño de la respuesta, milisegundos y si fue bien. Si un argumento parece una credencial, se guarda `[redacted: <tipo>]` en su lugar (filtro de mejor esfuerzo). Sirve para diagnosticar y como señal de uso. No se borra al reconstruir el índice, y se descartan las filas de más de 180 días.

```sh
sqlite3 <vault>/.index/activity.db "select at, tool, hook_event, ok, ms from calls order by id desc limit 20"
sqlite3 <vault>/.index/activity.db "select tool, count(*) from calls where at >= date('now') group by tool"
```

El índice vive en `<vault>/.index/index.db`: es una caché que se reconstruye sola. Junto a él, `.index/maintenance.db` guarda cuándo corrió cada tarea de mantención y qué cambió (no se reconstruye). En Linux y macOS, `.index/` se crea con permisos 0700 y sus bases con 0600 (en Windows no aplica). Añade `.index/` al `.gitignore` del vault.

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

[maintenance]            # opcional; estos son los valores por defecto
every_days = 1           # periodo mínimo entre ejecuciones de cada tarea
notify = true            # avisa de los pendientes de review
archive_expired = false  # archiva las memorias con valid_until pasado

[backup]                 # opcional; sin dir no hay backup
dir = '/ruta/absoluta/fuera/del/vault'   # entre comillas simples, también en Windows
keep = 14                # copias que se conservan
```

- `[maintenance]` y `[backup]` rechazan claves desconocidas. `every_days` y `keep` son enteros >= 1; `notify` y `archive_expired`, booleanos; `[backup]` exige un `dir` absoluto fuera del vault.
- `mode` es `read-only`, `read-write` o `memory`. Un valor distinto o una zona repetida impiden arrancar.
- Lo que no está en ninguna zona es de solo lectura. Si dos zonas se anidan, manda la más específica.
- Se ignoran `.obsidian/`, `.index/`, `.git/`, toda carpeta que empiece por `.` y los archivos que no son `.md`.
- Toda ruta se confina al vault: se rechazan `..`, las rutas absolutas y los symlinks que salen (`outside_vault`).
