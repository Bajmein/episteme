# Estado de la sesión

[← Volver al README](../README.md)

episteme guarda el **estado de la sesión**: una nota viva por hilo de trabajo y proyecto, para que tras `/compact`, `/clear` o al día siguiente se retome con lo que vale (el objetivo, lo hecho y cómo se comprobó, lo que falló y por qué, el siguiente paso, las decisiones y las restricciones). No hace falta un `estado.md` en el proyecto ni configurar nada.

## Dónde vive

- En `sesiones/<proyecto>/` del vault, fuera de `memory/`, con el nombre `AAAA-MM-DD-estado-<título>.md`. La ruta no cambia: cada guardado reescribe la nota entera.
- `sesiones/` es una zona con modo `session`. Si `episteme.toml` no declara ninguna zona de ese modo, se añade sola (ver [Configuración](configuracion.md)).
- Solo la escribe el tool `session`. `revise` responde `read_only_zone: <ruta> is in a session zone. Use session.` y `remember` tampoco escribe ahí.
- El frontmatter:

  | Clave | Valor |
  | --- | --- |
  | `type` | `session` |
  | `status` | `active` o `archived` |
  | `created` | Fecha en que se creó |
  | `tags` | `[sesion/estado]` |
  | `files` | Archivos de la tarea, si se pasan |
  | `project` | El proyecto |
  | `task_title` | El título |
  | `saved_at` | Fecha y hora local del último guardado, a segundos |
  | `saved_by` | `agent` o `extractor` |
  | `worktree` | La carpeta del proyecto (`project_dir`), si se pasa |
  | `session_id` | El id de la sesión de Claude Code, solo como dato |

  No lleva `kind`, `priority`, `helpful` ni `valid_until`: no es una memoria.

## Quién lo ve

- `search` lo encuentra mientras está activo; los archivados se ocultan, como las memorias archivadas (`status="any"` los muestra).
- No sale en la bienvenida ni en las «Notas relacionadas» de `context(mode="task")`: lo trae `session(action="restore")`.
- Las memorias `session` que guardaba `/episteme:pausa` no se migran: siguen en `memory/` y caducan solas.

## El tool `session`

| `action` | Qué hace |
| --- | --- |
| `save` | Crea o reescribe el estado. Destino: `note`, si viene; si no, el estado en uso; si no hay, uno nuevo, que pide `title`. `body` reemplaza el cuerpo entero (si empieza con `# título`, esa línea se quita). Con `note` de un estado archivado, lo reescribe y lo vuelve a activar. Rechaza una credencial en `title`, `body`, `files` o `session` (`invalid_argument`). Devuelve `path`, `created`, `missing_sections` y, si a un cuerpo de 300 caracteres o más le faltan secciones de la plantilla, `template_hint`. Nunca rechaza por formato |
| `show` | Devuelve el estado en uso (`found`, `path`, `task_title`, `saved_at`, `content`). No escribe |
| `restore` | Lo mismo, como contexto (`Estado de la sesión «…» (guardado …; compruébalo contra el repo antes de repetir pasos):`), y lo fija como estado en uso. Con `hook_event` sale en formato de hook, con el aviso `episteme · estado de sesión recuperado: «…»` |
| `template` | El esqueleto de `type` (`session` por defecto; vale cualquier tipo de memoria) |
| `archive` | Pone `status: archived` en `note` o en el estado en uso. No borra nada |

**El estado en uso** es el que este proceso guardó o recuperó para ese proyecto y esa carpeta. Si el servidor acaba de arrancar, es el estado activo más reciente (por `saved_at`) del mismo `worktree`; los que no tienen `worktree` valen para cualquiera. El `session_id` no se usa para buscarlo, porque cambia con `/clear`.

Para empezar otro hilo de trabajo, archiva el estado en uso y guarda uno nuevo con su `title`.

## La plantilla

El cuerpo sigue la plantilla de `session`: Objetivo · Hecho (con evidencia) · En curso · Lo que no funcionó · Siguiente paso · Pendiente · Decisiones cerradas · Restricciones y preferencias · Archivos. Una sección sin contenido lleva «Nada.» y no se quita. `session(action="template")` devuelve el esqueleto con lo que va en cada sección. Las plantillas de los demás tipos están en «Plantillas» de [Tools y memorias](tools.md).

## Rotación

- Un estado activo cuyo `saved_at` tiene más de `[session] archive_days` días (7 por defecto) se archiva en su sitio. No se borra.
- Lo hace la mantención de la primera bienvenida de cada sesión, que en la práctica corre al empezar la sesión y en el `SessionStart` que sigue a un `/clear`, como mucho una vez por periodo de `[maintenance] every_days`. No depende de `archive_expired`.
- Cuenta solo `saved_at`: leer el estado con `show` o `restore` no lo renueva.

## Configuración

```toml
[session]
extract = true                # orden de extracción tras compact/clear
block_manual_compact = true   # bloquea una vez un /compact manual con el estado desactualizado
archive_days = 7              # días sin guardar antes de archivar el estado (entero >= 1)
nudge_every = 12              # mensajes sin guardar antes del aviso (entero >= 1)
```

La tabla es opcional y rechaza claves desconocidas. `extract`, `block_manual_compact` y `nudge_every` son para los hooks de sesión.

## Desde `estado.md` y `checkpoint`

`checkpoint` y `[checkpoint] state_glob` están obsoletos y se eliminan en la próxima versión. Mientras tanto:

- Con `state_glob` configurado, el servidor avisa por stderr al arrancar y las respuestas de `checkpoint` traen `deprecated`.
- `session(action="restore")` cae a `checkpoint` (el `estado.md` activo o el último checkpoint guardado) cuando no hay estado en `sesiones/`, y la respuesta trae `deprecated`.
- Para migrar, guarda el estado con `session(action="save")` siguiendo la plantilla: desde ese momento `restore` trae ese y no el `estado.md`.
