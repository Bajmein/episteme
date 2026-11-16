# Changelog

Cambios de cada versión de `episteme`. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones, [SemVer](https://semver.org/lang/es/). Cada versión es un tag `vX.Y.Z` del repo, que es lo que los proyectos fijan en su config.

## [Sin publicar]

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

### Cambiado

- El paquete pide Python 3.14 o superior (antes 3.11); el repo y el CI usan 3.15, fijado en `.python-version`.
- Dependencias actualizadas en `uv.lock` (pydantic 2.14.3, pytest 9.2.0, ruff 0.17.5).
- El `README.md` abre con banner y badges.

### Añadido

- Mantención automática configurable (`[maintenance]` y `[backup]` en `episteme.toml`): en la primera bienvenida de cada sesión, `context` avisa de los pendientes de `review`, archiva las memorias vencidas (opcional) y deja un `.tar.gz` rotado del vault (opcional), una vez por periodo y coordinado entre procesos con `.index/maintenance.db`. `context` deja de ser de solo lectura.
- Dependabot: PR semanal del ecosistema `uv` y mensual de GitHub Actions.
- Este `CHANGELOG.md`.

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

## [0.5.0] - 2026-10-29

### Añadido

- `revise` con `set` mueve la memoria cuando cambia su `type` o su `project`.
- `migrate_omega.py`: rutas de Windows, informe de los proyectos omitidos y `--unassigned`.
- `episteme-setup`: migración en Windows, reinicio tras registrar y `settings.local.json`.

## [0.4.1] - 2026-10-29

### Añadido

- Instalación en Windows por `git+https` y skill `episteme-setup`.
- El CI corre también en `windows-latest`.

### Corregido

- `project_relative` reconoce `project_dir` con rutas de Windows.
- El índice cierra la conexión cuando un pragma falla sobre un índice corrupto.

## [0.4.0] - 2026-10-24

### Añadido

- `remember` nombra el archivo con un slug corto, sin palabras vacías, y acepta el parámetro `slug`.

### Corregido

- Los nombres y las fechas de las memorias usan la fecha local.

## [0.3.3] - 2026-10-22

### Corregido

- La migración de OMEGA reconoce el texto del harness después del prefijo «Decision:».

## [0.3.2] - 2026-10-22

Sin tag propio: salió dentro de `v0.3.3`.

### Corregido

- La migración de OMEGA acepta frontmatter en estilo de bloque y se salta el texto del harness.

## [0.3.1] - 2026-10-22

### Corregido

- `search` encuentra palabras con guion, `review` agrupa las notas de solo lectura y las líneas de las listas se calculan a demanda.

## [0.3.0] - 2026-10-22

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

## [0.2.0] - 2026-10-20

### Cambiado

- **Incompatible:** `episteme-mcp` pasa a llamarse `episteme` (paquete y comando) y el índice se mueve de `<vault>/.episteme/` a `<vault>/.index/`.
- Sin `--vault` ni `EPISTEME_VAULT`, el servidor usa `~/.episteme` y lo crea con un `episteme.toml` mínimo si no existe.

## [0.1.0] - 2026-10-19

### Añadido

- Primera versión: servidor MCP por stdio sobre un vault Markdown, con configuración de zonas y confinamiento de rutas.
- Parser de Markdown, resolución de enlaces e índice en SQLite.
- Tools `search`, `read` y `links`; `remember` y `revise` con validación del esquema; `review` y `context`; los tools para hooks.
- `scripts/migrate_omega.py` para migrar un export de OMEGA.

[Sin publicar]: https://github.com/Bajmein/episteme/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/Bajmein/episteme/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/Bajmein/episteme/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/Bajmein/episteme/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/Bajmein/episteme/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/Bajmein/episteme/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Bajmein/episteme/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Bajmein/episteme/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Bajmein/episteme/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Bajmein/episteme/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/Bajmein/episteme/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/Bajmein/episteme/compare/v0.3.3...v0.4.0
[0.3.3]: https://github.com/Bajmein/episteme/compare/v0.3.1...v0.3.3
[0.3.2]: https://github.com/Bajmein/episteme/commit/09df069
[0.3.1]: https://github.com/Bajmein/episteme/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Bajmein/episteme/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Bajmein/episteme/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Bajmein/episteme/releases/tag/v0.1.0
