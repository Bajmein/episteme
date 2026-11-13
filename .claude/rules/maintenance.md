---
paths:
  - src/episteme/maintenance.py
  - src/episteme/backup.py
---

# Mantención automática

- Lo automático solo archiva y respalda: nunca borra ni fusiona notas.
- Nunca rompe un tool: todo error se traga (`Store` no lanza; `run` y el hilo del backup restauran la marca con `restore` si fallan) y la bienvenida sigue.
- `review` no cambia de comportamiento: solo informa.
- La coordinación entre procesos pasa solo por `Store.claim` (`.index/maintenance.db`); nada de `flock`, `index.db` ni `activity.db`.
