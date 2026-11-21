---
paths:
  - src/episteme/vault.py
  - src/episteme/index/**
  - src/episteme/__main__.py
---

# Vault e índice

- El vault se resuelve como `--vault` > `EPISTEME_VAULT` > `~/.episteme`. Solo el vault por defecto se crea si falta (carpeta y `episteme.toml` mínimo con la zona `memory`). Una ruta explícita tiene que ser absoluta, existir y contener `episteme.toml`; si falta algo, el servidor sale con código distinto de 0 antes de crear nada. Nunca se deduce del `cwd` ni de `${CLAUDE_PROJECT_DIR}`: una ruta equivocada no debe convertir otra carpeta en vault ni crearle `.index/`.
- Toda ruta que llega a un tool se resuelve con `realpath` y tiene que quedar dentro del vault (`outside_vault`). La zona se comprueba sobre la ruta resuelta, no sobre la que llega.
- Una ruta fuera de toda zona es de solo lectura. Entre zonas anidadas manda la más específica.
- Los modos son `read-only`, `read-write`, `memory`, `docs`, `session` y `plan` (`MODES`). Los que solo escribe su propio tool están en `TOOL_MODES` (`docs` → `docs(action="write")`, `session` → `session`, `plan` → `plan`): `check_writable` no los niega, así que quien escribe de forma genérica (`revise`) los rechaza aparte. Las zonas `docs` no entran en el backup (`backup.SKIPPED_MODES`); las `session` y `plan`, sí. `load_config` añade la zona `sesiones` (`SESSION_ZONE`) con modo `session` y la zona `planes` (`PLAN_ZONE`) con modo `plan` si no hay ninguna de ese modo (`_with_implicit_zone`), para que el estado de sesión y las copias de los planes funcionen sin configuración. Las búsquedas ocultan por defecto los `archived` de las zonas `memory`, `session` y `plan`, y `context(mode="task")` no trae las de `session` ni `plan` como notas relacionadas.
- Las escrituras de notas son atómicas: archivo temporal en la misma carpeta, con un nombre que el índice nunca recoge, y `os.replace`.
- El índice (`.index/index.db`) es una caché: la verdad son los `.md`. Si está corrupto se borra y se reconstruye. `.index/activity.db` (registro de llamadas) no se borra al reconstruirlo.
- El texto de una nota se guarda una vez, en `notes.search_text`. La `fts` es contentless (`fts_schema`, SQLite ≥ 3.43): no se le piden columnas ni `snippet()`/`highlight()`, solo `match` y `bm25`, y se borra por `rowid`. `notes.body` es `NULL` fuera de las memorias: quien lo lea, que lea solo filas de memorias. Cambiar el esquema sube `SCHEMA_VERSION`.
- `.index/docs-inbox/<suite>/<hash>.md` es la bandeja de `/episteme-docs:docs`: el único escritor fuera de los tools es `docs_check.py` (`diff --inbox`); `docs(action="write", body_ref=…)` lee ahí (ruta confinada con `realpath`, nombre `^[0-9a-f]{16}$`, tope `NOTE_MAX_BYTES`) y borra el archivo con `os.unlink`. No es caché del índice (reconstruirlo solo borra `index.db`), no se indexa y no entra en el backup.
- Varias sesiones abren cada una su proceso sobre el mismo `index.db`: WAL, `busy_timeout` de 5000 ms y cada reindexado en una transacción. Un `database is locked` **no es corrupción**: se reintenta, y solo un `quick_check` fallido justifica borrar (ver la memoria de error «database is locked al abrir el índice no es corrupción»).
