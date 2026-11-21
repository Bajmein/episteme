# Planes

[← Volver al README](../README.md)

episteme guarda una **copia de cada plan** de plan mode de Claude Code. El agente la encuentra con `search` y `read`, en la misma sesión o después, y tras «Yes, clear context» recibe una línea que le dice dónde está. Los planes originales de Claude Code (en `plansDirectory`, por defecto `$CLAUDE_CONFIG_DIR/plans`) no se leen ni se tocan.

## Cómo llega la copia

- El hook `PreToolUse` con matcher `ExitPlanMode` llama a `plan(action="save")` con el texto del plan (`${tool_input.plan}`) y su ruta (`${tool_input.planFilePath}`). Ese hook se dispara al presentar el plan, en todas las opciones del diálogo (también si después se rechaza). `PostToolUse` no sirve: con «Yes, clear context» no se dispara.
- La respuesta del hook es siempre vacía, también si algo falla: el plan no vuelve como contexto y `ExitPlanMode` nunca se frena.
- El servidor no lee la carpeta de planes de Claude Code: el texto le llega en el hook. Por eso vale igual con varias cuentas (cada una con su `CLAUDE_CONFIG_DIR`) y con un `plansDirectory` propio.

## Dónde vive

- En `planes/<proyecto>/<slug>.md` del vault, fuera de `memory/`. `planes/` es una zona con modo `plan`; si `episteme.toml` no declara ninguna de ese modo, se añade sola (ver [Configuración](configuracion.md)).
- Solo la escribe el tool `plan`. `revise` responde `read_only_zone: <ruta> is in a plan zone. Use plan.` y `remember` tampoco escribe ahí.
- **Una nota por slug.** El slug es el nombre del archivo del plan sin `.md` (`plan-azul-feliz`), si son letras, dígitos, `.`, `_` o `-` (hasta 80, empezando por letra o dígito); si no, los 12 primeros caracteres del sha1 de la ruta. Si el plan se rechaza y se revisa, el `ExitPlanMode` siguiente sobrescribe la misma nota. No hay estado «aprobado» ni «rechazado».
- El frontmatter:

  | Clave | Valor |
  | --- | --- |
  | `type` | `plan` |
  | `status` | `active` o `archived` |
  | `created` | Fecha en que se guardó por primera vez |
  | `tags` | `[sesion/plan]` |
  | `project` | El proyecto |
  | `slug` | El slug |
  | `title` | La primera línea `# ` del plan, o el slug |
  | `saved_at` | Fecha y hora local del último guardado, a segundos (sin un `saved_at` legible, la rotación cuenta `created`) |
  | `session_id` | El id de la sesión de Claude Code, solo como dato |
  | `worktree` | La carpeta del proyecto (`${cwd}`) |
  | `source_path` | La ruta del plan en Claude Code, solo como dato |

  El cuerpo es el texto del plan.

- **Credenciales y tamaño.** Lo que parezca una credencial en el texto, el título o la ruta se reemplaza por `[credencial omitida]`: se redacta, no se rechaza, porque el plan no se puede perder. El texto se corta en un salto de línea a los 200 000 caracteres, con la marca `[episteme: plan cut at 200,000 characters]`.
- Si Claude Code no sustituye una variable (llega `${tool_input.plan}` tal cual), no se guarda nada.

## Quién lo ve

- `search` lo encuentra mientras está activo; los archivados se ocultan (`status="any"` los muestra).
- No sale en la bienvenida ni en las «Notas relacionadas» de `context(mode="task")`.
- Tras «Yes, clear context», el hook `SessionStart` (`compact|clear`) llama a `plan(action="restore")`. Solo con `source="clear"` devuelve una línea como esta:

  ```
  Plan de esta tarea en episteme: `planes/<proyecto>/<slug>.md` — <título> (guardado <fecha>). Léelo con read si necesitas volver a él.
  ```

  El plan se busca en este orden: el plan vigente del proceso (el servidor sobrevive al `/clear`), el que enlaza el estado de sesión en uso del mismo worktree y el plan activo más reciente del proyecto y el worktree. Sin plan, o tras `/compact`, no devuelve nada.

## El tool `plan`

| `action` | Qué hace |
| --- | --- |
| `save` | Escribe la copia de `plan` con el slug de `plan_path` y la fija como plan vigente. Devuelve `path`, `saved`, `slug`, `title` y `created`. Con `hook_event="PreToolUse"`, respuesta vacía |
| `show` | Sin `slug`, los planes activos del proyecto (`path`, `slug`, `title`, `saved_at`, `worktree`), el más reciente primero. Con `slug`, ese plan con `status` y `content` |
| `archive` | Pone `status: archived` en el plan `slug`, aunque lo enlace un estado de sesión activo (el archivado manual es explícito; la protección del enlace es solo de la rotación automática). No borra nada |
| `restore` | Hook `SessionStart`: la línea de arriba, solo con `source="clear"` |

## Enlace con el estado de la sesión

`session(action="save")` guarda en el estado la clave `plan` con el slug del plan de la tarea: el que se pasa en `plan`; si no, el que ya tenía el estado; si no, el plan vigente del proceso. Así, tras reiniciar el servidor, `restore` sigue encontrando el plan, y la rotación no lo archiva mientras el estado siga activo (ver [Estado de la sesión](sesion.md)).

## Rotación

- Un plan activo cuyo `saved_at` (o, si falta o no se lee, su `created`) tiene más de `[plans] archive_days` días (7 por defecto) se archiva en su sitio. No se borra.
- No se archiva el plan que enlaza un estado de sesión activo del mismo proyecto: tiene trabajo pendiente. La rotación de los estados corre antes que la de los planes en la misma pasada, así que si un estado viejo y su plan viejo vencen a la vez, los dos se archivan juntos.
- La protección del enlace vale solo para la rotación automática: `plan(action="archive")` archiva el plan aunque lo enlace un estado activo.
- Lo hace la mantención de la primera bienvenida de cada sesión, como mucho una vez por periodo de `[maintenance] every_days`, y lo dice en la bienvenida (`episteme · mantención: N planes archivados …`).
- Solo toca las copias de `planes/`: los planes de Claude Code siguen donde estaban.

## Configuración

```toml
[plans]
archive_days = 7   # días sin guardar antes de archivar la copia de un plan (entero >= 1)
```

La tabla es opcional y rechaza claves desconocidas.

## Límites

- Varios planes en una misma sesión no se han comprobado con Claude Code: cada slug es su propia nota y el vigente es el último guardado.
- Comprobado en vivo el 18-11-2026 (Claude Code 2.1.327, opción «Yes, clear context»): el modelo recibe la línea «Plan de esta tarea en episteme: …» como contexto del hook `SessionStart`. Si una versión futura dejara de entregarlo, la copia sigue en `planes/` y `search` la encuentra.
