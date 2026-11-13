# Mantención

[← Volver al README](../README.md)

episteme no fusiona ni borra nada por su cuenta. Con las tablas `[maintenance]` y `[backup]` de [`episteme.toml`](configuracion.md#epistemetoml), la primera bienvenida de cada sesión (con `session`) corre, como mucho una vez por periodo (`every_days`) y coordinada entre procesos con `.index/maintenance.db`:

- **Aviso** (`notify`, activo por defecto): una línea con los pendientes de `review` del proyecto, una vez por periodo y proyecto.
- **Archivado de vencidas** (`archive_expired`, apagado por defecto): archiva las memorias activas con `valid_until` pasado y lo dice en la bienvenida; se revierte con `revise`. Lo archivado queda en la tabla `log` de `maintenance.db`.
- **Backup** (solo con `[backup] dir`): un `episteme-*.tar.gz` rotado (`keep`) con las zonas escribibles y `episteme.toml`; no se crea si nada cambió. Para restaurar: `tar -xzf <archivo> -C <vault>`.

Sigue siendo manual, con `review` y `revise`, unificar, revisar parecidas y contradicciones. La skill [`/episteme:mantencion`](../plugin/skills/mantencion/SKILL.md) del plugin guía ese ciclo paso a paso. El ciclo, siempre con la aprobación de la persona y grupo por grupo:

1. `review(project="*", zone="memory")`.
2. Por cada grupo de `similar`: leer las memorias, guardar la unificada con `remember` y marcar cada antigua con `revise(action="supersede", by=…)`.
3. Archivar lo que ya no aplica con `revise(action="archive")` (reversible).
4. Revisar las `expired` (memorias activas con `valid_until` ya pasado, sin contar los checkpoints, que gestiona `checkpoint`): `revise(action="archive")` o una memoria nueva con `supersedes`.
5. Corregir los `cut_titles` (el título quedó cortado y repetido en la primera línea del cuerpo).
