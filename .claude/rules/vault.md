---
paths:
  - src/episteme_mcp/vault.py
  - src/episteme_mcp/index.py
  - src/episteme_mcp/__main__.py
---

# Vault e índice

- La ruta del vault es obligatoria y absoluta (`--vault` o `EPISTEME_VAULT`) y tiene que contener `episteme.toml`. Nunca se deduce del `cwd` ni de `${CLAUDE_PROJECT_DIR}`: una ruta equivocada no debe convertir otra carpeta en vault ni crearle `.episteme/`. Si falta algo, el servidor sale con código distinto de 0 antes de crear nada.
- Toda ruta que llega a un tool se resuelve con `realpath` y tiene que quedar dentro del vault (`outside_vault`). La zona se comprueba sobre la ruta resuelta, no sobre la que llega.
- Una ruta fuera de toda zona es de solo lectura. Entre zonas anidadas manda la más específica.
- Las escrituras de notas son atómicas: archivo temporal en la misma carpeta, con un nombre que el índice nunca recoge, y `os.replace`.
- El índice (`.episteme/index.db`) es una caché: la verdad son los `.md`. Si está corrupto se borra y se reconstruye.
- Varias sesiones abren cada una su proceso sobre el mismo `index.db`: WAL, `busy_timeout` de 5000 ms y cada reindexado en una transacción. Un `database is locked` **no es corrupción**: se reintenta, y solo un `quick_check` fallido justifica borrar (ver la memoria de error «database is locked al abrir el índice no es corrupción»).
