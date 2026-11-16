# Mantención

[← Volver al README](../README.md)

episteme no fusiona ni borra nada por su cuenta. Con las tablas `[maintenance]` y `[backup]` de [`episteme.toml`](configuracion.md#epistemetoml), la primera bienvenida de cada sesión (con `session`) corre, como mucho una vez por periodo (`every_days`) y coordinada entre procesos con `.index/maintenance.db`:

- **Aviso** (`notify`, activo por defecto): una línea con los pendientes de `review` del proyecto, una vez por periodo y proyecto.
- **Archivado de vencidas** (`archive_expired`, apagado por defecto): archiva las memorias activas con `valid_until` pasado y lo dice en la bienvenida; se revierte con `revise`. Lo archivado queda en la tabla `log` de `maintenance.db`.
- **Backup** (solo con `[backup] dir`): un `episteme-*.tar.gz` rotado (`keep`) con las zonas escribibles y `episteme.toml`; no se crea si nada cambió. Para restaurar: `tar -xzf <archivo> -C <vault>`.

Sigue siendo manual, con `review` y `revise`, unificar, revisar parecidas y contradicciones. La skill [`/episteme:mantencion`](../plugin/skills/mantencion/SKILL.md) del plugin guía ese ciclo paso a paso; con `/episteme:mantencion corta` (o si el aviso se sigue con poco tiempo) hace una ronda corta de como mucho 3 casos: vencidas, el grupo parecido más claro y la contradicción más clara. Con `/episteme:mantencion huerfanas` recorre de 10 en 10 las huérfanas (memorias activas sin ningún enlace, sin contar `session` ni `reminder`): `review` trae para cada una hasta 3 candidatas del mismo proyecto o de `_shared` que comparten un archivo o 2 tags, y la skill propone cuáles enlazar con `related`. Basta el enlace desde la huérfana, porque el índice calcula el sentido inverso.

El ciclo, siempre con la aprobación de la persona y grupo por grupo:

1. `review(project="*", zone="memory")`.
2. Por cada grupo de `similar`: leer las memorias, guardar la unificada con `remember` y marcar cada antigua con `revise(action="supersede", by=…)`.
3. Archivar lo que ya no aplica con `revise(action="archive")` (reversible).
4. Revisar las `expired` (memorias activas con `valid_until` ya pasado, sin contar los checkpoints, que gestiona `checkpoint`): `revise(action="archive")` o una memoria nueva con `supersedes`.
5. Corregir los `cut_titles` (el título quedó cortado y repetido en la primera línea del cuerpo).
