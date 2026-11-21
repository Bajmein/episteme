# Changelog

Cambios de cada versión de `episteme`. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones, [SemVer](https://semver.org/lang/es/). Cada versión es un tag `vX.Y.Z` del repo, que es lo que los proyectos fijan en su config. Solo se conservan los tags de las versiones recientes: las anteriores a 0.6.0 no llevan enlace de comparación.

## [Sin publicar]

## [0.20.0] - 2026-11-21

**Aviso de rotura:** tras actualizar, vuelve a correr `/episteme:setup` en cada proyecto (los hooks llaman ahora a `context` con `mode` y se quitan del `allow` los permisos de tools que ya no existen). De 13 a 9 tools, sin alias.

### Añadido

- Llamar a un tool quitado (`surface`, `constraints`, `links`, `docs_status`, `docs_write`) no ejecuta nada: sin `hook_event` da `not_found: tool "<nombre>" was removed. Use <reemplazo> instead, and re-run /episteme:setup …`, y con `hook_event` una respuesta sin error con el aviso como `additionalContext`. Las instrucciones del servidor recomiendan `description` y `link=true` al guardar y `read(note, links=…)` para seguir enlaces; el README, el plugin y los diagramas hablan de 9 tools (8 sin zona `docs`).
- `remember(link=true)` escribe en `related` de la memoria nueva las mejores `link_candidates` (hasta 3) y las lista en `linked` de la respuesta. Las memorias viejas no se editan: sus enlaces de vuelta los calcula el índice. Sin `link`, nada cambia.
- `review` suma `orphans_linkable` a `totals` (huérfanas con al menos una candidata de enlace) y la «mantención pendiente» de la bienvenida lo cuenta como «huérfanas enlazables».
- `read(note, links="out"|"in"|"both", depth=1-3)` añade la clave `links` (enlaces salientes, backlinks y notas alcanzables); con `content=false` da frontmatter, esquema y enlaces sin cuerpo. Con `notes` da `invalid_argument`.
- `search` filtra por `priority_min` (1-5), `valid` (`"current"` o `"expired"`, según `valid_until`) y `linked_to` (notas con un enlace hacia o desde la nota dada). Si un filtro no deja nada, `hints` lo dice.
- **`description` en las memorias.** `remember` acepta una `description` opcional (una línea, hasta 160 caracteres) que se guarda en el frontmatter, se pasa por el filtro de credenciales y se valida también con `revise(action="set")`. Se muestra en la bienvenida, el contexto de tarea, las memorias sugeridas y las filas de `search`; si falta, se muestra la primera frase del cuerpo sin guardarla, y `remember` devuelve `description_hint`. Lee la `description` de las propiedades que el índice ya guarda: el esquema del índice no cambia y no se reconstruye. Sin migración de memorias viejas.

### Cambiado

- **Rotura:** el tool `links` se fusiona en `read` y desaparece, sin alias: `read(note, links=...)` devuelve lo mismo en la clave `links`. Vuelve a correr `/episteme:setup` para quitar `mcp__episteme__links` de los permisos.
- Los tools `surface` y `constraints` pasan a `context` como modos: `context(mode="surface", file|relative_path, limit, session)` y `context(mode="constraints", file|relative_path)`, con la misma salida y el mismo modo hook. Sin `file` ni `relative_path`, error `invalid_argument`. Rotura sin alias: vuelve a correr `/episteme:setup` para que los hooks `PreToolUse` y `PostToolUse` llamen a `context` y se quiten `mcp__episteme__surface` y `mcp__episteme__constraints` del `allow`. `scripts/measure_uptake.py` cuenta las entregas nuevas (`context` con `mode=surface|constraints`) y las filas antiguas del registro de actividad.
- `docs_status` y `docs_write` pasan a ser un solo tool, `docs(action="status"|"write", …)`, con los mismos argumentos y las mismas salidas. Un argumento que no corresponde a la acción, o la falta de `suite` en `write`, responde `invalid_argument`. Sigue registrándose solo con una zona `docs` y no lleva `read_only_hint`, porque escribe. Rotura sin alias: actualiza el plugin `episteme-docs` (su skill ya llama a `docs`) y vuelve a correr `/episteme:setup`, que ya no pone `docs_status` en el `allow` (`docs` pide permiso). Un `docs_status` que quedara en el `allow` de un proyecto no hace nada: bórralo.
- `revise` en una zona `docs` pide `docs(action="write")` (antes `docs_write`).

### Quitado

- Los tools `surface`, `constraints`, `links`, `docs_status` y `docs_write`, sin alias: sus reemplazos son `context(mode="surface")`, `context(mode="constraints")`, `read(note, links=…)`, `docs(action="status")` y `docs(action="write")`. De 13 tools quedan 9 (8 sin zona `docs`).

## [0.19.0] - 2026-11-21

### Quitado

- `[session] block_manual_compact`, que se ignoraba desde 0.18. Si sigue en el `episteme.toml`, el servidor no arranca («unknown key»): bórrala.

### Corregido

- La línea de la bienvenida que nombra el estado de una sesión anterior ya no sale sin `project_dir`, no cuenta los estados guardados sin carpeta (`worktree`), que valían para cualquiera, y un `--resume` que vuelve a recibir la bienvenida no nombra su propio estado.
- `session(action="save")` sin `project_dir`, la llamada habitual del agente, guarda la carpeta (`worktree`) que mandó un hook de esta sesión: el estado ya no vale para cualquier carpeta.
- Las suites de documentación ya no duplican el frontmatter cuando la página descargada trae el suyo (las de mise desde noviembre de 2026): `docs_check.py` y `docs_write` lo quitan antes de calcular el hash y de escribir. Las notas que quedaron con dos bloques se arreglan solas en la próxima revisión con `/episteme-docs:docs`, que las ve como cambiadas.

## [0.18.0] - 2026-11-21

### Cambiado

- **Al compactar, el resumen escribe el estado de la sesión.** El hook `PreCompact` (`session(action="gate")`) ya no frena el `/compact` manual: devuelve instrucciones para que el resumen termine con el estado al día entre `<estado-sesion>` y `</estado-sesion>`, y `PostCompact` (`capture`) lo guarda como el estado. Si lo último lo guardó el extractor, las instrucciones llevan su cuerpo. Tras compactar, `restore` responde una línea en lugar de repetir el estado, y no hace falta extractor. Si el resumen no trae el bloque, todo sigue como antes, pero el estado vuelve sin el resumen, que ya está en el contexto. `[session] compact_state = false` lo apaga.
- **Un estado por sesión.** El estado en uso es el del proceso o el de esta sesión de Claude Code (`session_id`), nunca «el más reciente de la carpeta»: una sesión nueva, o una segunda ventana en la misma carpeta, ya no reescribe el estado de otra. `/episteme:sesion retomar` toma el más reciente a propósito.
- **Una sesión nueva no carga el estado anterior.** Su primera bienvenida lo nombra en una línea, con su ruta y cuándo se guardó, y dice cómo retomarlo.
- **Extracción al retomar.** El estado guarda la ruta de su transcript (`transcript`). Si se retoma en otra sesión, `restore` pide extraer lo que esa sesión dijo después del último guardado, aunque se cerrara sin compactar ni limpiar.
- El hook de despertar del plugin (`extract-wake.py`) solo actúa tras `/clear`.
- El aviso «el estado de la sesión no se actualiza desde hace N mensajes» está apagado por defecto (`[session] nudge_every = 0`; con 1 o más vuelve).
- El registro de actividad anota la sesión también en las llamadas del agente (la que pasaron los hooks).
- **Menos memorias repetidas.** La bienvenida lista hasta 8 memorias (antes 10), con una sola de `_shared` (antes 3) salvo que sobre sitio; tras compactar se reenvía breve, solo con los recordatorios vencidos y las normas. `surface` trae 3 por defecto (antes 5), solo cuenta una mención del archivo si la memoria tiene prioridad 4 o más (como mucho 2 así) y no repite lo que la sesión ya recibió por la bienvenida o por mensaje. `context(mode="task")` ya no repite las normas entregadas.
- El hook `constraints` solo corre antes de las tools que editan (`Edit`, `Write` y las de edición de Serena), no antes de las de lectura de Serena.

### Obsoleto

- `[session] block_manual_compact` se acepta y se ignora; se quitará en la versión menor siguiente. El parámetro `trigger` de `session` también se ignora.

**Tras actualizar el plugin, vuelve a correr `/episteme:setup`**: los hooks `UserPromptSubmit` y `PostCompact` pasan `${cwd}` y `${transcript_path}`, y `PreCompact` ya no pasa `${trigger}`.

### Corregido

- El servidor anuncia su versión al conectarse (`serverInfo.version`, antes vacía), y `episteme.__version__` se lee de los metadatos del paquete en lugar de estar escrita a mano (seguía en 0.11.0). La versión solo se fija en `pyproject.toml`.

## [0.17.0] - 2026-11-21

### Añadido

- `docs_write` acepta `body_ref`: el cuerpo de la página por su hash, desde la bandeja `.index/docs-inbox/<suite>/<hash>.md` del vault, en vez de `body`. Comprueba el hash, respeta el tope de 2 MiB y borra el archivo tras escribir. `docs_status` devuelve `inbox`, la ruta de la bandeja de cada suite.
- Claves opcionales del manifiesto de una suite: `suite.markdown`, una plantilla de URL con `{path}` o `{page}` desde la que `docs_check.py diff --markdown` baja cada página en Markdown (la `source` sigue siendo la pública), y `suite.manual: true`, para una suite que se mantiene a mano y `/episteme-docs:docs` salta. `docs_status` devuelve las dos (#32).
- Notas propias de una suite con `origin: local` en vez de `source`: son válidas, quedan fuera de la comparación con el origen y `docs_status` las cuenta en `local`.

### Cambiado

- `docs_status` y `docs_write` solo existen si `episteme.toml` declara al menos una zona `mode = "docs"` (cambiar las zonas pide reiniciar el servidor); sin ella, las instrucciones del servidor tampoco nombran la skill de documentación.
- La skill de documentación pasa al plugin aparte `episteme-docs` (`plugin-docs/`, depende de `episteme`): ahora es `/episteme-docs:docs` y se instala con `claude plugin install episteme-docs@episteme`. Ya no carga en agy.
- `docs_check.py diff` usa `--inbox <dir>` en vez de `--out`, guarda cada página como `<hash>.md` y devuelve `hash` (y `title` en las nuevas). `/episteme-docs:docs` ya no pasa cuerpos de página por el modelo: sincroniza suites grandes (uv, mise, render) sin copiar cientos de KB en las llamadas.
- Las entradas `new` de `docs_check.py diff` traen `excerpt`, el primer párrafo de la página: `/episteme-docs:docs` saca de él el `type` y el `summary` sin leer el archivo de la bandeja.

### Eliminado

- El tool `checkpoint` y `[checkpoint] state_glob` (obsoletos desde 0.15.0; usa `session`). Una tabla `[checkpoint]` que quede en `episteme.toml` se ignora en silencio. Se van también el aviso por stderr al arrancar, el guardado del `estado.md` que hacía `session` gate y la caída de `session(action="restore")` al `estado.md` o al último checkpoint: sin estado en `sesiones/`, responde `found: false`. Quien tenga hooks que llamen a `checkpoint`, vuelva a correr `/episteme:setup`.

### Corregido

- El registro de actividad guarda el `slug` de las llamadas a `plan` (antes no quedaba rastro de qué plan se mostraba o archivaba). El texto del plan sigue sin registrarse.
- La rotación de planes ya no deja un plan para siempre cuando le falta `saved_at` o no se lee: cuenta desde `created`.
- `docs_check.py diff` ya no da por «cambiadas» las páginas cuya fuente se guardó sin `.md`: las baja por su variante Markdown, como las nuevas, y si solo hay HTML lo cuenta como error (`HTML instead of Markdown`) sin guardar nada. Reconoce `X`, `X/`, `X.md`, `X/index.md` y `X#sec` como la misma página (adiós a los duplicados) y ya no ofrece como nuevas las plantillas con `{…}`, `/.well-known/`, los `.json` ni los `.txt`. Una página nueva del `llms.txt` que falla va a `skipped` y no a `errors` (un enlace roto de un tercero ya no impide poner `synced`), y las páginas `deprecated` no se descargan.
- `docs_check.py diff` reconoce mejor lo que no es Markdown: HTML con BOM, con un comentario antes del doctype o que empieza por `<head>`, `<body>`, `<?xml` o `<svg`, JSON (`JSON instead of Markdown`) y páginas vacías (`empty page`). Ya no rechaza Markdown que empieza por una etiqueta como `<html-tag-in-md>` o `<div>`.

## [0.16.0] - 2026-11-19

### Añadido

- Hook `SessionStart` (`compact|clear`) en el plugin (`plugin/hooks/hooks.json` y `extract-wake.py`): de tipo `command` con `asyncRewake`, despierta al modelo tras `/compact` o `/clear` para que lance `episteme:extractor` sin esperar al siguiente mensaje. Solo actúa en proyectos con el hook `restore` de episteme en su `settings` (o en el de usuario). Necesita `uv`, como el extractor.
- `session(action="save")` acepta `until` (solo con `origin="extractor"`): la hora de la última entrada del transcript que leyó el extractor. Se guarda como `extracted_until`, `show` la devuelve y la orden de extracción siguiente empieza ahí.

### Cambiado

- El módulo `serena-python` de `/episteme:scaffold` solo pasa al aviso de Serena (`serena-hooks remind`) las búsquedas y lecturas de Python; las de Markdown, JSON y demás ya no cuentan para la racha. El hook `python-serena.py` gana la acción `remind` y `serena-python.json` la usa en lugar de llamar a `serena-hooks` directamente.
- Autor del paquete en `pyproject.toml` y titular de la licencia en `LICENSE` y en el `README.md`: Benjamín C. Rossa. `pyproject.toml` declara también Python 3.15 en sus clasificadores.
- Diagramas del `README.md` al día con 0.15.0: la arquitectura muestra las 14 tools, agy y las zonas `sesiones/` y `planes/`; el de hooks cubre el día a día (con la copia del plan al aprobarlo) y dos nuevos explican el ciclo de una memoria y qué pasa al compactar o con `/clear`. `docs/hooks.md` incrusta también el de compactar.
- `SECURITY.md` cuenta entre los riesgos aceptados el estado de sesión y las copias de planes, que `session` y `plan` guardan sin pedir permiso y vuelven al contexto.

### Corregido

- La extracción tras un `/clear` (o un segundo `/compact`) ya no pierde lo que la sesión dijo mientras corría el extractor anterior: empezaba en el `saved_at` de su guardado, posterior a lo que había leído. El extractor pasa ahora el `hasta` del resumen como `until`.
- `/episteme:docs` usa la versión Markdown (`<url>.md`) de las páginas que un `llms.txt` lista sin extensión (Antigravity), en vez de guardar el HTML.

## [0.15.0] - 2026-11-18

### Añadido

- Tool `plan` y zona `planes/`: una copia de cada plan de plan mode en `planes/<proyecto>/<slug>.md`, una nota por slug (el nombre del archivo del plan) que se sobrescribe. `save` redacta las credenciales y corta a 200 000 caracteres; `show` lista los planes activos o devuelve uno; `archive` lo archiva sin borrarlo; `restore` apunta a la copia tras «clear context». La zona se añade sola si `episteme.toml` no la declara; solo la escribe `plan` (`revise` y `remember` responden `read_only_zone`), `search` la encuentra (sin las archivadas) y no sale en la bienvenida ni en las notas relacionadas de `context`. Los planes de Claude Code no se leen ni se tocan. Ver `docs/planes.md`.
- Hooks de `/episteme:setup`: `plan` save en `PreToolUse` con matcher `ExitPlanMode` (responde siempre vacío y nunca frena `ExitPlanMode`) y `plan` restore en `SessionStart` (`compact|clear`), que solo tras `clear` devuelve una línea con la ruta de la copia del plan de la tarea. `mcp__episteme__plan` va en el `allow`.
- Tabla `[plans]` en `episteme.toml` (`archive_days = 7`): la mantención de la primera bienvenida archiva los planes con `saved_at` de más de `archive_days` días, salvo el que enlaza un estado de sesión activo.
- Clave `plan` en el estado de sesión: `session(action="save")` acepta `plan` (un slug) y, si no se pasa, conserva el que tenía el estado o toma el plan vigente del proceso.
- Skill `/episteme:agy [tarea]`: activa agy (Google Antigravity CLI) en un proyecto ya conectado (`<proyecto>/.agents/mcp_config.json` con los `args` del registro de Claude Code, aviso de la entrada global `episteme` que choca de nombre, `.agents/` en `.git/info/exclude` y una comprobación con `agy -p`) y le delega tareas en segundo plano con `--mode plan`; agy propone memorias y Claude guarda las que valgan, anotando «propuesto por agy».
- Plugin para agy: `plugin/.antigravity-plugin/plugin.json` y la regla `plugin/rules/AGENTS.md` (`trigger: always_on`), con lo esencial de las instrucciones del servidor, que en agy no llegan al modelo. Se instala con `agy plugin install`. En agy no hay hooks.
- Columna `client` en el registro de actividad (`activity.db`): el nombre del cliente MCP de cada llamada. La migración de v1 a v2 conserva el historial. Con agy, la sesión sale de `_meta` (`antigravity.google/root_conversation_id`).

### Cambiado

- Las skills `reminder`, `mantencion` y `sesion` sirven a Claude Code y a agy: la carga con `ToolSearch` solo vale «En Claude Code» y, en agy, los argumentos son lo que se escribió después del comando.
- Las instrucciones del servidor (`INSTRUCTIONS`) son neutras respecto del cliente.

## [0.14.0] - 2026-11-18

### Añadido

- Skill `/episteme:scaffold`: crea desde plantillas o audita `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `.github/` (`CONTRIBUTING.md`, `ESTILO.md`, plantilla de PR y `.gitmessage`), `.claude/rules/docs.md` y `.gitignore`, con los comandos del stack detectado. Con `auditar` es de solo lectura; nunca hace commits. Ofrece módulos locales: `reglas-python`, `serena-python`, `session-brief`, `doc-review` y `claude-local`.
- Módulo `doc-review`: un hook de `SessionStart` que mide la actividad de git desde la marca `<!-- doc-review: … -->` de `README.md` y `CLAUDE.md` y pide a Claude revisarlos al cerrar la tarea cuando pasan del umbral.
- `/episteme:setup` sugiere `/episteme:scaffold` al final si al proyecto le falta `README.md`, `CLAUDE.md` o `.github/CONTRIBUTING.md`.
- Suites de documentación: un modo de zona nuevo, `docs`, para la documentación de terceros en `docs/` del vault. Solo la cambia el tool nuevo `docs_write`, que crea o actualiza una página y no la reescribe si el cuerpo no cambió; `docs_status` (solo lectura) lista las suites con sus conteos y, por suite, las páginas con el hash de su cuerpo. El manifiesto de cada suite va en el frontmatter de su `README.index.md` (`suite: {upstream, include, context7, synced}`). Ver `docs/documentacion.md`.
- La skill `/episteme:docs [suite]` pone al día todas las suites o la que se nombre: filtra por la fecha de Context7, baja las páginas con su script (`docs_check.py`, en la máquina de la persona: el servidor sigue sin HTTP), muestra cuántas cambiaron, son nuevas o desaparecieron, y las escribe con `docs_write`. Las que desaparecen pasan a `status: deprecated`; nada se borra.
- `/episteme:setup` añade `docs_status` al `allow`; `docs_write` sigue pidiendo permiso.
- Tool `session` y zona `sesiones/`: el estado de la sesión es una nota viva por hilo de trabajo en `sesiones/<proyecto>/`, con la plantilla de `session`. `save` lo crea o lo reescribe entero, `show` y `restore` lo devuelven (el de este proceso o el activo más reciente del mismo worktree), `template` da el esqueleto de cualquier tipo y `archive` lo archiva sin borrarlo. Rechaza credenciales como `remember`. La zona se añade sola si `episteme.toml` no la declara; solo la escribe `session` (`revise` y `remember` responden `read_only_zone`) y no sale en la bienvenida ni en las notas relacionadas de `context`. Ver `docs/sesion.md`.
- Tabla `[session]` en `episteme.toml` (`extract`, `block_manual_compact`, `archive_days = 7`, `nudge_every = 12`). La mantención de la primera bienvenida archiva los estados con `saved_at` de más de `archive_days` días, aunque `archive_expired` esté desactivado.
- El registro de actividad guarda también los argumentos `trigger`, `source`, `reason` y `origin`.
- Momentos de guardado del estado: las instrucciones del servidor piden `session(action="save")` en los hitos de la tarea, la bienvenida avisa tras 12 mensajes sin guardar (`[session] nudge_every`) y `session(action="gate")` en `PreCompact` frena una vez un `/compact` manual cuando el estado lleva 5 mensajes o más sin guardarse (repetirlo compacta igual).
- Acciones de hook de `session`: `capture` (`PostCompact`) guarda el resumen de la compactación en `## Resumen de compactación`, sin el bloque `<analysis>` y con las credenciales redactadas; `end` (`SessionEnd` con `clear`) recuerda el transcript; `restore` con `source` añade la orden de lanzar el agente `episteme:extractor`.
- Agente `episteme:extractor` del plugin (Sonnet, esfuerzo bajo, en segundo plano): resume el transcript con `transcript_digest.py`, reescribe el estado con la plantilla y guarda como mucho 3 memorias con el tag `origen/extractor`.
- Skill `/episteme:sesion` (`guardar`, `retomar`, `plantilla`), que reemplaza a `/episteme:pausa`.
- Plantillas de cuerpo para cada tipo de memoria (secciones `## …`, con «Nada.» en las vacías). `remember` avisa con `template_hint` cuando un cuerpo de 300 caracteres o más no trae las secciones de su tipo (sin contar mayúsculas, tildes ni la numeración: `## 1. Situación` vale); nunca rechaza por formato. Ver «Plantillas» en `docs/tools.md`.

### Cambiado

- `revise` responde `read_only_zone` en una zona `docs` y pide `docs_write`. `review` cuenta esas zonas como de solo lectura y el backup no las incluye.
- Las instrucciones del servidor dicen que las suites de `docs/` cambian solo con `/episteme:docs`.
- `search` oculta por defecto los estados de sesión archivados, como las memorias archivadas.
- Hooks de `/episteme:setup`: `session` gate en `PreCompact`, capture en `PostCompact`, end en `SessionEnd` (`clear`) y restore en `SessionStart` (`compact|clear`) en lugar de los de `checkpoint`. `session` y el script del extractor van al `allow`. Vuelve a correr `/episteme:setup` para fusionarlos.
- Los eventos `PostCompact` y `SessionEnd` se aceptan como `hook_event` y no devuelven nada.

### Eliminado

- Skill `/episteme:pausa`: usa `/episteme:sesion`. Las memorias que guardó siguen en `memory/` y caducan solas.

### Obsoleto

- `checkpoint` y `[checkpoint] state_glob`: siguen funcionando en esta versión y se eliminan en la próxima; usa `session`. Con `state_glob` configurado, el servidor avisa por stderr al arrancar y las respuestas de `checkpoint` traen `deprecated`. `session(action="restore")` cae a `checkpoint` cuando no hay estado gestionado.

## [0.13.2] - 2026-11-16

### Seguridad

- `checkpoint` (save) rechaza con `invalid` los patrones de `files` que casan con todo (`*`, `**`, `**/*`, `*.*`) copiados del `estado.md`, igual que `remember` y `revise`.

## [0.13.1] - 2026-11-16

### Cambiado

- Las consultas SQL de `index/store.py` que llevan nombres de tabla o de columna se arman con un helper en vez de f-strings. Ya no hacen falta los `# nosec B608` y bandit no da hallazgos ni avisos.

### Seguridad

- Los avisos y listados que llegan a la terminal quitan las secuencias de escape enteras (CSI, OSC, DCS…), no solo su carácter inicial. Antes quedaban restos como `[2J` o `]0;título` en el texto.

## [0.13.0] - 2026-11-16

### Añadido

- Licencia MIT (`LICENSE`), con sus metadatos en `pyproject.toml` (autor, palabras clave, clasificadores y URLs), `plugin.json` y `marketplace.json`, y la sección «Licencia» del README.
- Archivos de comunidad: `SECURITY.md`, `.github/CONTRIBUTING.md`, plantillas de issue y de PR, `CODEOWNERS`, `.gitmessage`, `copilot-instructions.md`, `.gitattributes` y `.editorconfig`.
- Workflows `stale` y `dependency-review`, y `zizmor` en el job `lint` del CI.

### Cambiado

- La instalación es por HTTPS (`git+https://github.com/Bajmein/episteme@<tag>`) y no pide credenciales; `git+ssh` queda como alternativa. La documentación, `/episteme:setup` y `scripts/bench_calls.py` ya no hablan de repo privado ni de colaboradores.
- `docs/instalacion.md` avisa de que `episteme` en PyPI es otro proyecto.
- El ejemplo de `keywords` en la descripción de `remember` usa un nombre ficticio.
- Los workflows fijan las acciones por SHA, declaran `permissions` mínimos y desvían los PR de forks y de Dependabot a `ubuntu-latest`.
- El CI de Windows vuelve a correr en `main` y en los PR que tocan código, tests o dependencias, pero solo en un repo público (en uno privado se omite).
- El vault de prueba (`tests/fixtures/vault/docs/claude-code/` y `docs/llms.txt`) ya no copia documentación de terceros: son 45 notas propias, breves y sintéticas, con títulos y aliases propios; conservan su ruta salvo cinco de `others/`, renombradas sin nombres de terceros. Solo afecta a los tests.
- Se quitan los `# nosec` que sobraban, y el de `yaml.load` pasa a una línea propia para que bandit no avise. Los de SQL en `index/store.py` se quedan: sin ellos sale B608, y bandit 1.9.4 avisa igual porque revisa cada trozo del f-string.

### Seguridad

- Una nota con alias YAML en el frontmatter (`&a` y `*a` anidados) ya no deja el servidor colgado: los alias se rechazan, la nota queda con `fm_valid` falso y el frontmatter no puede pasar de 64 KB. Efecto: una nota que reutilice un ancla (`<<: *base`) queda con `fm_valid` falso.
- El índice salta las notas de más de 2 MB (con un aviso en el log, una vez por nota y tamaño); `read` explica que la nota pesa demasiado en vez de dar `not_found`; `revise` rechaza un cambio que dejaría una nota por encima de 2 MB (antes la memoria desaparecía del índice), y `remember` rechaza un `body` de más de 100.000 caracteres.
- `search` y `context` (`task`) descartan lo que pase de 32 términos o 2.000 caracteres en la consulta.
- Los avisos y listados que llegan a la terminal o al contexto (`systemMessage` de `SessionStart`, el aviso de `checkpoint`, las líneas de bienvenida, `surface` y recordatorios) quitan los caracteres de control (`ESC`, `BEL`, C1, marcas bidi) de los títulos, de `task_title` y de la primera frase de cada línea, y cortan cada título a 120 caracteres. El aviso de `SessionStart` conserva sus líneas. Antes, un `estado.md` o una memoria podían cambiar el título de la ventana o borrar la pantalla.
- El filtro de credenciales detecta más casos: claves `sk-proj-…`, `Authorization: Bearer …` (sin distinguir mayúsculas), asignaciones como `DB_PASSWORD=…`, `AWS_SECRET_ACCESS_KEY=…` o `"password": "…"` (en una asignación, el valor tiene que tener un dígito y no llevar corchetes ni paréntesis, para que «token: identificador» no bloquee), claves con caracteres de ancho cero (se normaliza antes de buscar) y `$secreto` en una URL (solo `$NOMBRE` en mayúsculas cuenta como marcador). Ahora también revisa `project` en `remember` y los valores anidados de `revise(action="set")`; `edit` rechaza un texto con más credenciales que el que reemplaza.
- `remember` y `revise` rechazan en `files` los patrones que casan con todo (`*`, `**`, `**/*`, `*.*`).
- `project` solo admite `[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}`: ya no se crean carpetas ocultas ni nombres de 300 caracteres, y una ruta con byte nulo o demasiado larga da `invalid_argument` sin mostrar la ruta absoluta del vault.
- `/episteme:setup` ya no copia la base y la clave de OMEGA a una ruta fija de `/tmp`: usa una carpeta privada (`mktemp -d`) y pide borrarla al terminar. `docs/migracion-omega.md` también usa `mktemp -d`.
- La skill de setup y la documentación dejan de llamar «de solo lectura» a `context` (su primera bienvenida puede archivar memorias vencidas y lanzar el backup) y aclaran que el `deny` de `Read`/`Edit` sobre el vault no cubre Bash: es una barrera contra el uso accidental, no un aislamiento.
- El backup ya no sigue enlaces simbólicos: un `episteme.toml` que es un symlink se rechaza al arrancar, y los temporales del backup llevan el prefijo `.episteme-backup-` (la rotación solo borra esos, no los `.tmp-*` de otros programas en `backup.dir`).
- `.index/` se crea con permisos 0700 y sus bases (`index.db`, `activity.db`, `maintenance.db`) con 0600 en Linux y macOS.
- El registro de actividad sustituye por `[redacted: <tipo>]` los argumentos que parecen una credencial.
- `checkpoint` (save) copia del frontmatter de `estado.md` solo `estado`, `etapa`, `tags`, `keywords` y `files`, y rechaza con `invalid_argument` un `estado.md` que parece contener una credencial.

## [0.12.0] - 2026-11-16

### Añadido

- `scripts/measure_semantic.py` lista las memorias huérfanas con sus candidatas a enlazar por significado, y dice cuáles ya ofrece `review` (`--link-score`).

### Cambiado

- `index.db` ocupa cerca de la mitad: el índice de búsqueda ya no guarda su propia copia del texto (con SQLite 3.43 o posterior) y el cuerpo solo se guarda para las memorias. Al arrancar la versión nueva, el índice se rehace una vez y devuelve al disco el espacio que sobra.

## [0.11.0] - 2026-11-16

### Añadido

- `remember` avisa con `keywords_hint` cuando una memoria se guarda sin `keywords`.
- `remember` avisa con `links_hint` cuando una memoria se guarda sin enlaces.
- `scripts/measure_index.py`: mide cuánto tarda el indexado completo, el incremental y la comprobación sin cambios, sobre una copia del vault.
- `scripts/measure_semantic.py`: compara la búsqueda por palabras con los vecinos semánticos de un modelo de Ollama.
- `scripts/measure_links.py`: mide cuántas memorias están enlazadas por `related` y qué aportarían sus vecinas.
- `scripts/measure_links.py` mide además todos los wikilinks en ambos sentidos (qué alcanzan los backlinks), separa los enlaces migrados de OMEGA de los nativos, da una línea base con los pares del mismo proyecto y, con el registro de actividad (`--days`), cuenta las memorias leídas tras un `search` que no estaban en el resultado pero eran vecinas de uno.

### Cambiado

- El aviso de mantención y `/episteme:mantencion corta` ofrecen una ronda corta con los 3 casos más claros.
- `context(mode="task")` sigue los enlaces de cualquier tipo, no solo `related`.
- `review` entrega cada huérfana con hasta 3 candidatas a enlazar y solo cuenta las memorias activas; `/episteme:mantencion huerfanas` las recorre por tandas.

### Corregido

- `surface` ya no deja de mostrar memorias nuevas cuando las primeras ya habían salido en la sesión.
- `scripts/measure_uptake.py` ya empareja las entregas con las lecturas del agente. Las llamadas del agente no traen sesión, así que el informe daba 0 entregas seguidas de lectura y 0 sesiones con lecturas. Ahora cada llamada sin sesión toma la última que informó un hook desde el mismo proceso del servidor.

## [0.10.1] - 2026-11-13

### Cambiado

- Refactor interno para bajar la complejidad del código (PR #63 a #75), guiado por el análisis de CodeScene: funciones más cortas y con menos anidación en el motor de búsqueda y lectura, el vault, el parser de Markdown, el índice, las memorias y los hooks. No cambia nada de lo que se usa: las herramientas, sus parámetros, sus respuestas y sus mensajes de error son los mismos.
- Segunda ronda del mismo refactor (PR #77 a #84): el motor, la memoria de cada mensaje, el registro de las herramientas y los scripts `migrate_omega.py`, `bench_calls.py` y `measure_uptake.py`. Tampoco cambia nada de lo que se usa: las opciones y la salida de los scripts son las mismas.

### Corregido

- El archivado automático de memorias vencidas (`archive_expired = true`) ya no archiva una memoria a la que se le quitó `valid_until` a mano después de indexarla. Antes, si el índice aún no se había puesto al día, la daba por vencida. Ahora todas las comprobaciones de vencimiento leen `valid_until` como fecha, y una fecha ausente o ilegible nunca vence.

## [0.10.0] - 2026-11-13

### Añadido

- El plugin `episteme` de Claude Code, con el propio repo como marketplace (`claude plugin marketplace add Bajmein/episteme` y `claude plugin install episteme@episteme`). Trae las skills y no el servidor, que se sigue registrando por proyecto. Además de `/episteme:setup`, suma tres skills: `/episteme:pausa` (guarda el estado de la tarea antes de `/clear` o de cerrar y lo retoma después, para los proyectos sin `estado.md`), `/episteme:mantencion` (guía la revisión de memorias que informa `review`, con aprobación grupo por grupo) y `/episteme:reminder` (un recordatorio de prioridad 5 del proyecto). Las skills se actualizan con `claude plugin update episteme@episteme` cuando sale una versión nueva.
- Después de compactar o de `/clear`, la bienvenida trae además las memorias que el agente escribió o leyó antes en esa sesión («De esta sesión», hasta 8), y la persona ve en el terminal una línea en verde que dice qué se recuperó y qué tarea se retomó. El hook `SessionStart` de `context` pasa a recibir `"source": "${source}"`: quien ya tenga los hooks instalados puede añadirlo con `/episteme:setup` (sin él, el aviso no distingue entre compactar y `/clear`).

### Cambiado

- La skill `episteme-setup` pasa a ser `/episteme:setup` y se instala con el plugin, no enlazando una carpeta del clone. Quien la tenía enlazada borra el enlace (`~/.claude/skills/episteme-setup`) e instala el plugin; si no, quedan las dos.
- El `README.md` pasa a ser una presentación en lenguaje simple, con dos diagramas (arquitectura y hooks de una sesión, en `static/diagrams/`). El detalle que tenía se mueve sin cambios a `docs/`: instalación, configuración, tools y memorias, hooks, mantención, migración de OMEGA y desarrollo.

## [0.9.1] - 2026-11-13

### Cambiado

- `review` solo marca como contradicción posible un par de decisiones o constraints con similitud de texto de 0,15 o más. Antes bastaba con compartir un archivo de `files`, y las decisiones que tocan un archivo concurrido (`server.py`) salían todas emparejadas entre sí.
- El paquete se construye con `uv_build` en lugar de hatchling. El wheel no cambia; el sdist ya solo lleva `src/`, `README.md` y `pyproject.toml` (antes arrastraba `tests/`, `.claude/` y `.github/`).

## [0.9.0] - 2026-11-13

### Añadido

- Mantención automática configurable (`[maintenance]` y `[backup]` en `episteme.toml`): en la primera bienvenida de cada sesión, `context` avisa de los pendientes de `review`, archiva las memorias vencidas (opcional) y deja un `.tar.gz` rotado del vault (opcional), una vez por periodo y coordinado entre procesos con `.index/maintenance.db`. `context` deja de ser de solo lectura.
- Dependabot: PR semanal del ecosistema `uv` y mensual de GitHub Actions.
- Este `CHANGELOG.md`.

### Cambiado

- El paquete pide Python 3.14 o superior (antes 3.11); el repo y el CI usan 3.15, fijado en `.python-version`.
- Dependencias actualizadas en `uv.lock` (pydantic 2.14.3, pytest 9.2.0, ruff 0.17.5).
- El `README.md` abre con banner y badges.

## [0.8.0] - 2026-11-13

### Añadido

- `remember` rechaza el texto que parece una credencial (también en tags y archivos) y, cuando bloquea un duplicado, dice qué hacer.
- Aviso para guardar cuando la sesión no ha escrito ninguna memoria, registro de lo entregado por sesión y `surface` por memoria.
- La bienvenida reserva 160 caracteres y avisa de las normas y los recordatorios vencidos que quedaron fuera.
- `review` informa de las memorias vencidas.
- `checkpoint`: marca de corte, aviso de checkpoint guardado y filtro por worktree.
- `episteme-setup` desactiva la memoria automática nativa, carga los tools diferidos y revisa los settings.
- `scripts/measure_uptake.py`: cruza entregas y lecturas del registro de actividad.

### Corregido

- `checkpoint` archiva lo obsoleto solo dentro del worktree y no usa el worktree sin `project_dir`.
- La reserva de la bienvenida se calcula con la línea de aviso real.
- `measure_uptake` conserva las llamadas de la sesión con `--project` y respeta las rutas de lectura pedidas.

## [0.7.0] - 2026-11-12

### Añadido

- `search(match="any")`: varias palabras o variantes en una sola llamada.
- `read(notes=[…])`: varias notas en una sola llamada.
- `scripts/bench_calls.py`: reproduce una ráfaga de llamadas y corre un A/B con un agente.

### Cambiado

- Rendimiento: el snippet de `search` se busca por líneas y se omite en las llamadas internas; `fold_with_map` pliega de una vez los tramos ASCII.
- Las instrucciones del servidor, el `README.md` y las reglas explican las consultas por lote.

## [0.6.0] - 2026-11-11

### Añadido

- Registro de las llamadas a los tools en `.index/activity.db`.
- `context`: recordatorios, memorias que coinciden con el mensaje del usuario y bienvenida reenviada tras compactar.
- `remember`: `keywords`, similares de otros ámbitos, tags nuevos y candidatas a enlazar.
- `read`: outline a pedido y modo solo outline.
- `search`: filas más completas, filtro por zona, facetas y pistas cuando no hay resultados.
- `review`: grupos de memorias similares, títulos cortados y alcance de todos los proyectos.
- `surface` corre también en `Read` y no repite dentro de una sesión.
- `scripts/measure_recall.py`: mide el recall con lematización y trigramas sobre un vault.
- `episteme-setup`: registro multicuenta con scope local o de proyecto.

### Cambiado

- La bienvenida limita las memorias compartidas y el contexto de tarea se filtra por relevancia.
- Instrucciones del servidor más precisas, con la regla para cuando el servidor no aparece.

### Corregido

- La salida de `UserPromptSubmit` y `SessionStart` se entrega como `additionalContext`.
- `surface` vuelve a entregar tras una compactación.

## 0.5.0 - 2026-10-29

### Añadido

- `revise` con `set` mueve la memoria cuando cambia su `type` o su `project`.
- `migrate_omega.py`: rutas de Windows, informe de los proyectos omitidos y `--unassigned`.
- `episteme-setup`: migración en Windows, reinicio tras registrar y `settings.local.json`.

## 0.4.1 - 2026-10-29

### Añadido

- Instalación en Windows por `git+https` y skill `episteme-setup`.
- El CI corre también en `windows-latest`.

### Corregido

- `project_relative` reconoce `project_dir` con rutas de Windows.
- El índice cierra la conexión cuando un pragma falla sobre un índice corrupto.

## 0.4.0 - 2026-10-24

### Añadido

- `remember` nombra el archivo con un slug corto, sin palabras vacías, y acepta el parámetro `slug`.

### Corregido

- Los nombres y las fechas de las memorias usan la fecha local.

## 0.3.3 - 2026-10-22

### Corregido

- La migración de OMEGA reconoce el texto del harness después del prefijo «Decision:».

## 0.3.2 - 2026-10-22

Sin tag propio: salió dentro de `v0.3.3`.

### Corregido

- La migración de OMEGA acepta frontmatter en estilo de bloque y se salta el texto del harness.

## 0.3.1 - 2026-10-22

### Corregido

- `search` encuentra palabras con guion, `review` agrupa las notas de solo lectura y las líneas de las listas se calculan a demanda.

## 0.3.0 - 2026-10-22

### Añadido

- `search`: búsqueda solo por tags, reintento con OR, términos por prefijo y palabras vacías del español.
- La bienvenida trae las normas y los recordatorios próximos; `revise` acepta `dismiss`.
- `checkpoint` restaura desde el `estado.md` vivo, con `task_title`, y archiva lo obsoleto.
- `surface` y `constraints` aceptan `relative_path` y se saltan las memorias vencidas y los tipos que son ruido.
- Los enlaces se resuelven primero en la misma carpeta; `review` da totales y filtra por zona; la extracción de tags es más estricta.
- `migrate_omega.py` asocia rutas a archivos, limpia prefijos y lee la prioridad y los recordatorios de `omega.db`.

### Cambiado

- Rendimiento del índice: caché de los listados de directorio y reenlace incremental.

### Corregido

- El parser reinicia el estado de código indentado alrededor de los bloques con cerca.

## 0.2.0 - 2026-10-20

### Cambiado

- **Incompatible:** `episteme-mcp` pasa a llamarse `episteme` (paquete y comando) y el índice se mueve de `<vault>/.episteme/` a `<vault>/.index/`.
- Sin `--vault` ni `EPISTEME_VAULT`, el servidor usa `~/.episteme` y lo crea con un `episteme.toml` mínimo si no existe.

## 0.1.0 - 2026-10-19

### Añadido

- Primera versión: servidor MCP por stdio sobre un vault Markdown, con configuración de zonas y confinamiento de rutas.
- Parser de Markdown, resolución de enlaces e índice en SQLite.
- Tools `search`, `read` y `links`; `remember` y `revise` con validación del esquema; `review` y `context`; los tools para hooks.
- `scripts/migrate_omega.py` para migrar un export de OMEGA.

[Sin publicar]: https://github.com/Bajmein/episteme/compare/v0.20.0...HEAD
[0.20.0]: https://github.com/Bajmein/episteme/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/Bajmein/episteme/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/Bajmein/episteme/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/Bajmein/episteme/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/Bajmein/episteme/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/Bajmein/episteme/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/Bajmein/episteme/compare/v0.13.2...v0.14.0
[0.13.2]: https://github.com/Bajmein/episteme/compare/v0.13.1...v0.13.2
[0.13.1]: https://github.com/Bajmein/episteme/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/Bajmein/episteme/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/Bajmein/episteme/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Bajmein/episteme/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/Bajmein/episteme/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/Bajmein/episteme/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/Bajmein/episteme/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/Bajmein/episteme/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Bajmein/episteme/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Bajmein/episteme/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Bajmein/episteme/releases/tag/v0.6.0
