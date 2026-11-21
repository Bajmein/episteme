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
  | `saved_at` | Fecha y hora local del último guardado del agente o del extractor, a segundos |
  | `saved_by` | `agent`, `extractor` o `compact` (lo último que lo escribió fue el hook `PostCompact`) |
  | `extracted_until` | Solo si lo último fue un guardado del extractor: hasta qué hora local (a segundos) leyó el transcript (el `until` de `save`). Cualquier otro guardado lo quita |
  | `compacted_at` | Fecha y hora del último resumen de compactación, si lo hubo |
  | `worktree` | La carpeta del proyecto (`project_dir`), si se pasa |
  | `session_id` | El id de la sesión de Claude Code, solo como dato |
  | `plan` | El slug del plan de la tarea en `planes/<proyecto>/` (ver [Planes](planes.md)): el que se pasa a `save`; si no, el que ya tenía el estado; si no, el plan vigente del proceso. Mientras el estado esté activo, ese plan no rota |

  No lleva `kind`, `priority`, `helpful` ni `valid_until`: no es una memoria.

## Quién lo ve

- `search` lo encuentra mientras está activo; los archivados se ocultan, como las memorias archivadas (`status="any"` los muestra).
- No sale en la bienvenida ni en las «Notas relacionadas» de `context(mode="task")`: lo trae `session(action="restore")`.
- Las memorias `session` que guardaba `/episteme:pausa` no se migran: siguen en `memory/` y caducan solas. La skill pasa a ser `/episteme:sesion` (guardar, retomar y plantilla).

## El tool `session`

| `action` | Qué hace |
| --- | --- |
| `save` | Crea o reescribe el estado. `plan` (un slug) lo enlaza con su plan. Destino: `note`, si viene; si no, el estado en uso; si no hay, uno nuevo, que pide `title`. `body` reemplaza el cuerpo entero (si empieza con `# título`, esa línea se quita). Con `note` de un estado archivado, lo reescribe y lo vuelve a activar. Rechaza una credencial en `title`, `body`, `files` o `session` (`invalid_argument`). Devuelve `path`, `created`, `missing_sections` y, si a un cuerpo de 300 caracteres o más le faltan secciones de la plantilla, `template_hint`. Nunca rechaza por formato |
| `show` | Devuelve el estado en uso (`found`, `path`, `task_title`, `saved_at`, `content`). No escribe |
| `restore` | Lo mismo, como contexto (`Estado de la sesión «…» (guardado …; compruébalo contra el repo antes de repetir pasos):`), y lo fija como estado en uso. Con `hook_event` sale en formato de hook, con el aviso `episteme · estado de sesión recuperado: «…»` |
| `template` | El esqueleto de `type` (`session` por defecto; vale cualquier tipo de memoria) |
| `archive` | Pone `status: archived` en `note` o en el estado en uso. No borra nada |
| `gate` | Solo con `hook_event="PreCompact"` (si no, `invalid_argument`): decide si frena un `/compact` manual (ver «Los momentos de guardado») |
| `capture` | Hook `PostCompact`: guarda `summary` en la sección `## Resumen de compactación` del estado en uso (la reemplaza si ya está); sin estado, crea uno titulado `Sesión <fecha>`. Un `summary` vacío o sin sustituir (`${compact_summary}`) no escribe nada |
| `end` | Hook `SessionEnd` (`clear`): recuerda `transcript` en el proceso para el `restore` que sigue. No escribe en el vault |

`restore` con `source` (`compact` o `clear`) y un transcript conocido añade `extract`, la orden de extracción (ver más abajo). En modo hook va debajo del estado.

**El estado en uso** es el que este proceso guardó o recuperó para ese proyecto y esa carpeta. Si el servidor acaba de arrancar, es el estado activo más reciente (por `saved_at`) del mismo `worktree`; los que no tienen `worktree` valen para cualquiera. El `session_id` no se usa para buscarlo, porque cambia con `/clear`.

Para empezar otro hilo de trabajo, archiva el estado en uso y guarda uno nuevo con su `title`.

## Los momentos de guardado

El estado se guarda en cuatro momentos:

| Momento | Quién | Cómo |
| --- | --- | --- |
| Mientras se trabaja | El agente | Las instrucciones del servidor le piden `session(action="save")` cuando se acuerda un plan, acaba una fase, cambia el enfoque, antes de un paso arriesgado y cuando la persona lo pide (`/episteme:sesion`) |
| Cada 12 mensajes sin guardar | Hook `UserPromptSubmit` | La bienvenida añade `episteme · el estado de la sesión no se actualiza desde hace N mensajes: …` (cada `[session] nudge_every` mensajes) |
| Antes de un `/compact` manual | Hook `PreCompact` (`gate`) | Si la sesión lleva 5 mensajes o más y el estado no se guarda hace 5 o más, frena el `/compact` una vez y le dice a la persona que pida guardarlo. Repetir `/compact` compacta igual. El automático nunca se frena |
| Después de compactar o de `/clear` | Hooks `PostCompact`, `SessionEnd` y `SessionStart` | `capture` guarda el resumen de la compactación; `restore` devuelve el estado y pide lanzar el extractor |

### La extracción

Tras `/compact` o `/clear`, el `restore` del `SessionStart` añade una línea como esta:

```
episteme · extracción pendiente: lanza en segundo plano el agente episteme:extractor con este encargo y sigue sin esperarlo: desde=<extracted_until, saved_at o "inicio"> estado=<ruta o "nuevo"> proyecto=<proyecto> transcript=<ruta>
```

El agente lanza el subagente `episteme:extractor` (del plugin, Sonnet con esfuerzo bajo), que corre `transcript_digest.py` de la skill `sesion` sobre el transcript desde `desde`, reescribe el estado con la plantilla (`origin="extractor"`) y guarda como mucho 3 memorias duraderas con el tag `origen/extractor`. El servidor no lee el transcript: lo lee el script, en la máquina de la persona.

- Tras `/compact`, el transcript es el de la sesión en curso (`${transcript_path}` del `SessionStart`). Tras `/clear`, el que guardó `end` en el `SessionEnd`; se entrega una sola vez.
- `desde` es el `saved_at` del estado: lo anterior ya está en él. `capture` no lo mueve, para que la extracción tras compactar incluya lo que se habló antes. Si lo último fue un guardado del extractor, `desde` es su `extracted_until`.
- El modelo no toma un turno solo tras `/compact` o `/clear`: el hook `SessionStart` del plugin (`plugin/hooks/extract-wake.py`, de tipo `command` con `asyncRewake`) sale con código 2 y Claude Code lo despierta con un aviso que le pide lanzar el extractor si el contexto trae la orden. Solo actúa si el `settings.local.json` o el `settings.json` del proyecto, o el `settings.json` de usuario, tienen el hook `restore` de episteme; en los demás proyectos calla. Sin el plugin, la orden espera al siguiente mensaje de la persona.
- Con `[session] extract = false` no hay orden (el transcript que guardó `end` se descarta igual).
- La ruta del transcript va al final de la orden y se acepta solo si termina en `.jsonl` y no trae comillas ni caracteres de la shell (`` ` ``, `$`, `;`, `|`, `&`, `<`, `>`): el extractor la pasa a un comando. `end` la guarda solo con `reason` vacío o `clear`.
- Antes de guardar, el extractor vuelve a leer el estado: si la sesión principal lo guardó mientras trabajaba, parte de ese.
- El extractor guarda con `until`, la línea `hasta` del resumen (la última entrada que leyó): la extracción siguiente empieza ahí y no en el `saved_at` de su guardado, así que lo que se habló mientras trabajaba no se pierde.

### Límites

- Sin el hook `SessionEnd` (`clear`) no hay extracción tras `/clear`: el servidor no sabe qué transcript se cerró.
- El extractor cuesta tokens de Sonnet en cada `/compact` y `/clear`.
- El bloqueo es solo del `/compact` manual y una vez por mensaje.
- El extractor corre en segundo plano y no puede pedir permiso: `/episteme:setup` deja en `allow` el tool `session` y el script, pero no `remember`. Si nadie aprueba `remember`, guarda solo el estado y lo dice.
- El permiso del script lleva su ruta absoluta en la caché del plugin, que cambia con cada versión: **tras actualizar el plugin, vuelve a correr `/episteme:setup`**. Si no, el extractor no puede correr el script y lo dice en su respuesta.
- `desde` solo lleva un `saved_at` con el formato que escribe `session` (`AAAA-MM-DDTHH:MM:SS`); si alguien lo editó a mano con otra cosa, la orden dice `desde=inicio`.
- El contador de mensajes es del proceso: si el servidor se reinicia, el aviso y el bloqueo empiezan de cero.

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

La tabla es opcional y rechaza claves desconocidas. `extract` activa la orden de extracción, `block_manual_compact` el freno de `gate` y `nudge_every` el aviso periódico.

## Desde `estado.md` y `checkpoint`

El tool `checkpoint` y `[checkpoint] state_glob` ya no existen (una tabla `[checkpoint]` en `episteme.toml` se ignora). Para migrar, guarda el estado con `session(action="save")` siguiendo la plantilla, y vuelve a correr `/episteme:setup` si el proyecto tenía hooks que llamaban a `checkpoint`.
