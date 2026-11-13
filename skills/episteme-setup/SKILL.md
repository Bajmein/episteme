---
name: episteme-setup
description: Conectar un proyecto al servidor MCP episteme (Linux, macOS o Windows), migrar sus memorias de OMEGA y retirar OMEGA y mcpvault; también cómo actualizar episteme y publicar una versión nueva.
disable-model-invocation: true
---

# Conectar un proyecto a episteme

episteme (repo privado `Bajmein/episteme`) sirve un vault Markdown, por defecto el global `~/.episteme` (`%USERPROFILE%\.episteme` en Windows), como documentación y memoria. Toda interacción pasa por sus 10 tools MCP; no hay CLI. El uso de cada tool está en el `README.md` del repo.

Pide a la persona el nombre del proyecto (`<p>`, p. ej. `fabrik`). Trabaja desde la raíz del proyecto.

Antes de empezar, comprueba:
- `uv --version` y `git --version` responden. Si falta uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` en Linux o macOS, `winget install --id=astral-sh.uv -e` en Windows.
- Cómo llega la persona a GitHub: por SSH si `ssh -T git@github.com` saluda con su usuario; si no, por HTTPS. En Windows, HTTPS (Git for Windows trae Git Credential Manager, que abre el navegador para iniciar sesión la primera vez). El repo es privado: hace falta ser colaborador de `Bajmein/episteme`.
- El último tag: `git ls-remote --tags --sort=-v:refname --refs <url> | head -1` (en PowerShell, `Select-Object -First 1` en vez de `head -1`), con `<url>` igual a `git@github.com:Bajmein/episteme` o `https://github.com/Bajmein/episteme`.

## 1. Registrar el servidor (scope local)

Por SSH (Linux o macOS):

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+ssh://git@github.com/Bajmein/episteme@<tag> episteme --project <p>
```

Por HTTPS (Windows, o sin clave SSH), en una sola línea, porque el `\` de bash no parte líneas en PowerShell:

```powershell
claude mcp add --scope local episteme -- uvx --from git+https://github.com/Bajmein/episteme@<tag> episteme --project <p>
```

- Sin `--vault` usa el vault global y lo crea si falta. Para otro vault, `--vault '<ruta absoluta>'` (en Windows vale `C:\Users\ana\notas`).
- Comillas **simples** en `'${HOME}…'` (o en otra variable, como `'${HOME}/src…'`): Claude Code la expande al arrancar y la config no lleva la ruta de la máquina. Con comillas dobles, la shell la expande al registrar y queda la ruta absoluta.
- Scope local porque el proyecto (`--project`) es de la máquina.
- **Varias cuentas de Claude Code en la máquina** (`CLAUDE_CONFIG_DIR` definido, o lanzadores como `claude-gmail`): el scope local se guarda en el `.claude.json` de *una* cuenta, la del `claude` con que se registre. En una shell con lanzadores, `claude` a secas puede ser otra cuenta que la de la sesión: comprueba en la salida de `mcp add` qué archivo dice `File modified`.
  - Si el proyecto solo se abre desde una cuenta, registra con su lanzador (`claude-<cuenta> mcp add --scope local …`).
  - Si se abre desde varias, usa `--scope project` en vez de `--scope local`: queda en `.mcp.json` en la raíz del proyecto, que leen todas las cuentas (cada una pide aprobar el servidor la primera vez). Si los hooks del paso 2 van en `settings.local.json`, saca también `.mcp.json` de git con `.git/info/exclude`: si no, a quien clone el repo sin episteme le aparecería el servidor.
  - Los hooks del paso 2 son de proyecto y se cargan en todas las cuentas: si el servidor solo está en una, en las demás fallan.
- Opcional, para desarrollar el servidor desde un clone sin tocar la entrada fijada:
  ```bash
  claude mcp add --scope local episteme-dev -- \
    uv run --directory '<ruta del clone>' episteme --project <p>
  ```
- Comprueba con `claude mcp list` que `episteme` sale conectado. La primera vez tarda: uv descarga el repo y las dependencias.
- **Los tools de episteme no aparecen en esta sesión hasta reiniciar Claude Code**, y los subagentes que lances tampoco los ven. Los pasos 2 a 4 no los necesitan; la comprobación (paso 5) y la migración (paso 6) sí, así que pide a la persona que reinicie antes de esos pasos.

## 2. Hooks y permisos del proyecto

Elige el archivo con la persona:
- `.claude/settings.local.json` (no se versiona) si el resto del equipo no usa episteme. Es lo normal, porque el servidor está en scope local: con los hooks en el `settings.json` versionado, a quien no tenga el servidor le fallarían.
- `.claude/settings.json` si todos los que trabajan en el repo tienen episteme registrado.

Fusiona en ese archivo el contenido de [settings.json](settings.json) de esta skill, sin pisar lo que ya haya:
- `allow` de los 7 tools de solo lectura (`remember`, `revise` y `checkpoint` siguen pidiendo permiso);
- `deny` de `Read/Edit(~/.episteme/**)` (`Edit` ya cubre Write; una regla `Write(...)` nunca coincide), `Bash(obsidian *)` y `Bash(omega *)`: el acceso al vault se cierra con permisos, no con el prompt. Si el vault no es el de por defecto, cambia la ruta en las dos reglas;
- los 6 hooks `mcp_tool`: bienvenida, recordatorios y sugerencias por mensaje en `UserPromptSubmit` (con `${prompt}`), `constraints` antes de `Edit|Write|mcp__serena__.*` y `surface` después de `Read|Edit|Write|mcp__serena__.*` (con Serena el tool no trae `file_path`: pasa `relative_path`), `checkpoint` save en `PreCompact`, y en `SessionStart` (`compact|clear`) `checkpoint` restore y la bienvenida otra vez. Todos devuelven `hookSpecificOutput.additionalContext`.
- `"autoMemoryEnabled": false`: la memoria automática de Claude Code (`MEMORY.md`) compite con episteme y el agente acaba guardando en dos sitios. Pregunta a la persona antes de escribirlo. Si el proyecto ya tiene un `MEMORY.md` con contenido, ofrece pasarlo a episteme con `remember` antes de desactivarla. Un `autoMemoryEnabled: true` explícito se respeta: no lo cambies.

Si el proyecto se empaqueta como plugin, `"server": "episteme"` pasa a `"plugin:<plugin>:episteme"`.

No añadas hooks en `SessionStart startup|resume` (Claude Code se salta ahí los `mcp_tool`) ni en `SessionEnd`.

Claude Code puede negarse a que el agente escriba su propia configuración (en modo auto, el clasificador bloquea editar `.claude/settings*.json`). Si pasa, no lo intentes por otra vía: muestra a la persona el JSON fusionado completo y pídele que lo guarde ella.

## 3. `CLAUDE.md` del proyecto

Añade (o cambia la regla que hubiera sobre Obsidian/mcpvault por) esta línea:

> Vault `episteme`: solo los tools de episteme; ni CLI, ni Bash, ni Read/Edit/Write sobre el vault. Si los tools `mcp__episteme__*` salen como diferidos, cárgalos con ToolSearch (`select:mcp__episteme__context,mcp__episteme__search,mcp__episteme__read,mcp__episteme__remember,mcp__episteme__revise`) antes de usarlos; si no aparecen ni diferidos, dilo antes de seguir.

El aviso existe porque sin servidor los hooks no corren y nada lo delata. La frase de los diferidos existe porque la versión anterior se leía como «no están disponibles» cuando los tools solo estaban diferidos (Claude Code los carga bajo demanda). Si el proyecto se empaqueta como plugin, el prefijo es `mcp__plugin_<plugin>_episteme__` y hay que ajustar los nombres del `select:`.

## 4. `episteme.toml` del vault

Solo si el proyecto tiene archivos de estado por tarea (como el `estado.md` de fabrik), comprueba que el `episteme.toml` del vault tiene el patrón, relativo a la raíz del proyecto:

```toml
[checkpoint]
state_glob = ".fabrik/**/estado.md"
```

Es un único `state_glob` para todo el vault: si dos proyectos usan patrones distintos, avisa a la persona en vez de cambiarlo. Los cambios en el vault se los propones a la persona; no los hagas con Edit (el `deny` lo impide).

## 5. Comprobar

Reinicia Claude Code en el proyecto. En `/mcp`, `episteme` sale conectado; el primer mensaje recibe la bienvenida de `context(mode="welcome")`. Prueba un `remember` de una decisión del proyecto y búscala con `search`.

### Comprobar que la configuración está al día

Es de solo lectura. Compara `.claude/settings.local.json`, `.claude/settings.json` y el `settings.json` de usuario (`~/.claude/settings.json`, o el de la cuenta en uso) con el [settings.json](settings.json) de esta skill, y lista:
- hooks que faltan;
- hooks repetidos entre archivos (se ejecutarían dos veces);
- hooks con `matcher` o `input` distintos de los de la skill;
- reglas `allow` o `deny` que faltan;
- `autoMemoryEnabled`: ausente, o `true` explícito (se respeta, solo se informa).

Muestra el diff a la persona y fusiona solo si lo aprueba. Si el clasificador bloquea la edición, entrega el JSON fusionado (regla del paso 2).

## 6. Migrar desde OMEGA (solo si el proyecto lo usa)

Necesita un clone de episteme (`<clone>`) y Claude Code reiniciado (paso 1). En Linux o macOS:

```bash
# 1. Copia de OMEGA en reposo (sin sesiones abiertas): ~/.omega solo se lee.
mkdir -p /tmp/omega-home && cp ~/.omega/{omega.db,omega.db-wal,omega.db-shm,.key} /tmp/omega-home/
sqlite3 /tmp/omega-home/omega.db 'PRAGMA wal_checkpoint(TRUNCATE)'
# 2. Con qué etiquetas de proyecto guardó OMEGA las memorias (nombre, ruta o ninguna).
sqlite3 /tmp/omega-home/omega.db 'select project, count(*) from memories group by project'
# 3. Exportar desde la copia, para que OMEGA no escriba en ~/.omega.
OMEGA_HOME=/tmp/omega-home omega export-obsidian --output-dir /tmp/omega --project <p> --limit 0
# 4. Ensayo sobre el vault (el dry-run refresca el índice: mejor sobre una copia).
cd <clone>
uv run scripts/migrate_omega.py --export /tmp/omega/omega-memories \
  --vault "$HOME/.episteme" --project <p> --omega-db /tmp/omega-home/omega.db \
  --map-project '<ruta del proyecto en OMEGA>=<p>' --dry-run
```

En Windows (PowerShell; sin la CLI de `sqlite3`, se usa la de Python a través de uv):

```powershell
# 1. Copia de OMEGA en reposo (sin sesiones abiertas).
$omega = "$env:TEMP\omega-home"
New-Item -ItemType Directory -Force $omega | Out-Null
Copy-Item "$HOME\.omega\omega.db*", "$HOME\.omega\.key" $omega
uv run --no-project python -c "import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute('PRAGMA wal_checkpoint(TRUNCATE)')" "$omega\omega.db"
# 2. Etiquetas de proyecto.
uv run --no-project python -c "import sqlite3,sys; [print(*r) for r in sqlite3.connect(sys.argv[1]).execute('select project, count(*) from memories group by project')]" "$omega\omega.db"
# 3. Exportar desde la copia.
$env:OMEGA_HOME = $omega
omega export-obsidian --output-dir "$env:TEMP\omega" --project <p> --limit 0
Remove-Item Env:OMEGA_HOME
# 4. Ensayo, en una sola línea.
cd <clone>
uv run scripts/migrate_omega.py --export "$env:TEMP\omega\omega-memories" --vault "$HOME\.episteme" --project <p> --omega-db "$omega\omega.db" --map-project '<ruta del proyecto en OMEGA>=<p>' --dry-run
```

- OMEGA suele etiquetar el mismo proyecto con el nombre y con la ruta (`/home/ana/app`, `C:\Users\ana\app`). Lo que no sea `--project` ni esté en un `--map-project` se omite: pasa un `--map-project` por cada ruta del paso 2. La salida del ensayo termina con `Proyectos omitidos: …` para comprobar que no queda ninguna del proyecto.
- Las memorias sin proyecto (`NULL` en el paso 2) entran en `<p>` y la salida dice cuántas. Si pueden ser de otros proyectos, revísalas tras migrar o usa `--unassigned skip`.
- Sin `--limit 0`, `export-obsidian` exporta solo 25 memorias.
- Sin `--omega-db` se pierden la prioridad, los recordatorios y el filtro de superseded.
- Revisa la salida del `--dry-run` con la persona y luego repite sin `--dry-run`. Es idempotente: una segunda ejecución no duplica.
- Los tags pasan de `dominio:x` a `dominio/x`, los `checkpoint` se descartan y la prioridad sale de `omega.db` (`--omega-db`). Revisa con la persona las normas vigentes y las contradicciones que marca `review`.
- El tipo sale tal cual de OMEGA, que guarda como `user_preference` muchas decisiones y hechos del proyecto. Repasa las `preference` migradas (`search(type="preference", project="<p>")`) y corrige el tipo con `revise(action="set", fields={"type": "decision"})`, que mueve la nota a su carpeta.
- En `review`, dos decisiones que comparten un archivo de `files` salen como contradicción posible. Si de verdad no se contradicen, enlaza una a la otra con `related` (`revise(action="set", fields={"related": [...]})`, con los enlaces que ya tuviera más `[[otra]]`: `set` reemplaza la lista) y dejan de salir.

Unas semanas en paralelo con OMEGA, comparando la bienvenida y lo que sale al tocar archivos. Después, retira del proyecto:
- OMEGA: sus hooks (`omega.hooks.fast_hook`) en `.claude/settings.json` y `.claude/rules/omega.md`;
- mcpvault: `claude mcp remove --scope local obsidian-episteme`;
- skills que lean el vault por otra vía (en fabrik, la skill `obsidian`).

Al empezar la convivencia, crea un recordatorio con `remember(type="reminder", project="<p>", due=…)` para la retirada si no existe ya.

# Actualizar episteme

En cada proyecto conectado, vuelve a registrar `episteme` con el tag nuevo: `claude mcp remove --scope local episteme` y el `add` del paso 1 (con el scope y el lanzador con que se registró: `--scope project` si está en `.mcp.json`). La primera ejecución descarga; después tira de la caché de uv. Después, haz la comprobación de configuración del paso 5 en cada proyecto: los hooks o permisos nuevos de la skill no llegan solos. Para actualizar esta skill, `git pull` en el clone del que se instaló (ver «La skill episteme-setup» en el `README.md`).

# Publicar una versión de episteme (mantenedor)

1. CI en verde en `main` (`gh run list --branch main --limit 1`), en Ubuntu y en Windows.
2. En local (el cloud no puede subir tags), desde el clone: `git tag vX.Y.Z && git push --tags`.
3. Actualiza los proyectos conectados como en «Actualizar episteme».
