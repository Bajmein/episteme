---
paths:
  - src/episteme/vault.py
  - src/episteme/index.py
  - src/episteme/__main__.py
---

# Vault e índice

- El vault se resuelve como `--vault` > `EPISTEME_VAULT` > `~/.episteme`. Solo el vault por defecto se crea si falta (carpeta y `episteme.toml` mínimo con la zona `memory`). Una ruta explícita tiene que ser absoluta, existir y contener `episteme.toml`; si falta algo, el servidor sale con código distinto de 0 antes de crear nada. Nunca se deduce del `cwd` ni de `${CLAUDE_PROJECT_DIR}`: una ruta equivocada no debe convertir otra carpeta en vault ni crearle `.index/`.
- Toda ruta que llega a un tool se resuelve con `realpath` y tiene que quedar dentro del vault (`outside_vault`). La zona se comprueba sobre la ruta resuelta, no sobre la que llega.
- Una ruta fuera de toda zona es de solo lectura. Entre zonas anidadas manda la más específica.
- Las escrituras de notas son atómicas: archivo temporal en la misma carpeta, con un nombre que el índice nunca recoge, y `os.replace`.
- El índice (`.index/index.db`) es una caché: la verdad son los `.md`. Si está corrupto se borra y se reconstruye. `.index/activity.db` (registro de llamadas) no se borra al reconstruirlo.
- Varias sesiones abren cada una su proceso sobre el mismo `index.db`: WAL, `busy_timeout` de 5000 ms y cada reindexado en una transacción. Un `database is locked` **no es corrupción**: se reintenta, y solo un `quick_check` fallido justifica borrar (ver la memoria de error «database is locked al abrir el índice no es corrupción»).
