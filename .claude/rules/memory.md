---
paths:
  - src/episteme/memory.py
  - scripts/migrate_omega.py
---

# Memorias

- El esquema se valida al escribir (`remember`, `revise` en una zona `memory`) y nunca al leer: una memoria editada a mano con un campo mal se indexa igual y `review` la informa.
- Al escribir, las claves siguen `KEY_ORDER` y se omiten las vacías de `OMIT_WHEN_EMPTY` (y `flagged: false`). Así los archivos se pueden comparar con diff y editar a mano.
- Las fórmulas y umbrales (bienvenida, contexto de tarea, duplicados por Jaccard, «vieja» a los 90 días, contradicciones) tienen su porqué en la memoria «Fórmulas y umbrales de la memoria». Si se cambia uno, se sustituye esa memoria con `revise(action="supersede")`.
- Un duplicado nunca se fusiona en silencio: se devuelve en `similar` y no se crea salvo `force=true`.
- `review` informa y nunca borra ni cambia nada.
- `migrate_omega.py` reutiliza `memory.remember` (misma validación y detección de duplicados) y es idempotente: una segunda ejecución no duplica nada. No duplicar lógica del esquema en el script.
