# Mantención

[← Volver al README](../README.md)

episteme no fusiona ni borra nada por su cuenta. Con las tablas `[maintenance]` y `[backup]` de [`episteme.toml`](configuracion.md#epistemetoml), la primera bienvenida de cada sesión (un `context` con `session`) corre, como mucho una vez por periodo (`every_days`) y coordinada entre procesos con `.index/maintenance.db`:

- **Aviso** (`notify`, activo por defecto): una línea con los pendientes de `review` del proyecto, una vez por periodo y proyecto.
- **Archivado de vencidas** (`archive_expired`, apagado por defecto): archiva las memorias activas con `valid_until` pasado y lo dice en la bienvenida; se revierte con `revise`. Lo archivado queda en la tabla `log` de `maintenance.db`.
- **Rotación de estados y planes** (siempre, aunque `archive_expired` esté apagado): archiva los estados de sesión de `sesiones/` con `saved_at` de más de `[session] archive_days` días y las copias de planes de `planes/` con más de `[plans] archive_days` días, salvo el plan que enlaza un estado activo. Lo dice en la bienvenida (`episteme · mantención: N planes archivados …`). Nada se borra. Ver [Estado de la sesión](sesion.md#rotación) y [Planes](planes.md#rotación).
- **Backup** (solo con `[backup] dir`): un `episteme-*.tar.gz` rotado (`keep`) con las zonas escribibles (también `sesiones/` y `planes/`; no las suites `docs`, que se vuelven a bajar) y `episteme.toml`; no se crea si nada cambió. Para restaurar: `tar -xzf <archivo> -C <vault>`.

Sigue siendo manual, con `review` y `revise`, unificar, revisar parecidas y contradicciones. La skill [`/episteme:mantencion`](../plugin/skills/mantencion/SKILL.md) del plugin guía ese ciclo paso a paso; con `/episteme:mantencion corta` (o si el aviso se sigue con poco tiempo) hace una ronda corta de como mucho 3 casos: vencidas, el grupo parecido más claro y la contradicción más clara. Con `/episteme:mantencion huerfanas` recorre de 10 en 10 las huérfanas (memorias activas sin ningún enlace, sin contar `session` ni `reminder`): `review` trae para cada una hasta 3 candidatas del mismo proyecto o de `_shared` que comparten un archivo o 2 tags, y la skill propone cuáles enlazar con `related`. Basta el enlace desde la huérfana, porque el índice calcula el sentido inverso. `totals.orphans_linkable` cuenta las huérfanas con al menos una candidata, y la «mantención pendiente» de la bienvenida las muestra como «huérfanas enlazables». Al guardar, `remember(link=true)` evita crearlas: enlaza la memoria nueva con sus mejores candidatas (hasta 3).

El ciclo, siempre con la aprobación de la persona y grupo por grupo:

1. `review(project="*", zone="memory")`.
2. Por cada grupo de `similar`: leer las memorias, guardar la unificada con `remember` y marcar cada antigua con `revise(action="supersede", by=…)`.
3. Archivar lo que ya no aplica con `revise(action="archive")` (reversible).
4. Revisar las `expired` (memorias activas con `valid_until` ya pasado, sin contar las memorias `checkpoint-*` antiguas): `revise(action="archive")` o una memoria nueva con `supersedes`.
5. Corregir los `cut_titles` (el título quedó cortado y repetido en la primera línea del cuerpo).
