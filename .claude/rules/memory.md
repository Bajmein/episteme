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
- El nombre de archivo sale de `memory_slug` (≤ 5 palabras, ≤ 40 caracteres, sin palabras vacías ni lo que ya dice la ruta) o del parámetro `slug`; la colisión añade `-2`, `-3`… y nunca sobrescribe. `checkpoint` conserva `slugify` a propósito: su ruta debe ser estable para que se sobrescriba.
- `revise(action="set")` que cambia `type` o `project` de una memoria la mueve a `<zona>/<proyecto>/<carpeta del tipo>/` con el mismo nombre (y recalcula `kind`), para que los `[[nombre]]` sigan resolviendo. Se niega si otra nota la enlaza por ruta o si el nombre ya existe en la carpeta nueva: nunca sobrescribe ni deja enlaces rotos. Es el único caso en que el servidor borra una nota, y no sale de `memory/`.
- Una contradicción posible de `review` es un par de `decision`/`constraint` que comparten un valor de `files` o 2 tags, sin enlace `supersedes`, `contradicts` ni `related` entre ellas: enlazarlas con `related` dice que ya se compararon.
