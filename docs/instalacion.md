# Instalación

[← Volver al README](../README.md)

Se distribuye con `uvx` desde un tag de GitHub. El repo es privado: hay que ser colaborador de `Bajmein/episteme`. Requiere [uv](https://docs.astral.sh/uv/) y git; uv consigue Python 3.14 o superior si falta (el servidor comprueba al arrancar que SQLite tiene FTS5).

Lo más corto es instalar la skill `episteme-setup` (ver más abajo) y correr `/episteme-setup` en cada proyecto: registra el servidor, fusiona permisos y hooks en `.claude/settings.json` y añade la regla al `CLAUDE.md`. A mano, son estos pasos.

## Linux y macOS

Por `git+ssh`, con la misma clave que `git push`:

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+ssh://git@github.com/Bajmein/episteme@v0.9.1 episteme --project fabrik
```

Sin clave SSH, vale la URL de Windows (`git+https://…`). Sin `--vault` usa el vault global `~/.episteme` y lo crea, con un `episteme.toml` mínimo (zona `memory`), si no existe.

Actualizar es cambiar el tag (`claude mcp remove --scope local episteme` y otra vez el `add`). Para desarrollo, una entrada aparte que no fija versión:

```bash
claude mcp add --scope local episteme-dev -- \
  uv run --directory '${HOME}/src/episteme' episteme --project fabrik
```

Las comillas simples guardan `${HOME}` tal cual y Claude Code lo expande al arrancar el servidor, así la config no lleva la ruta de la máquina. Con comillas dobles la shell lo expande al registrar y queda la ruta completa.

## Windows

Requiere [Git for Windows](https://git-scm.com/download/win) (Claude Code ya lo pide) y uv:

```powershell
winget install --id=astral-sh.uv -e
```

Se instala por HTTPS, y la primera vez Git Credential Manager abre el navegador para iniciar sesión en GitHub:

```powershell
claude mcp add --scope local episteme -- uvx --from git+https://github.com/Bajmein/episteme@v0.9.1 episteme --project <proyecto>
```

En una sola línea: el `\` de bash no parte líneas en PowerShell. El vault por defecto es `%USERPROFILE%\.episteme`; `--vault` acepta una ruta absoluta de Windows (`C:\Users\ana\notas`). El bloque de hooks es el mismo. Dentro de WSL, sigue la instalación de Linux.

## Después de registrar

1. `claude mcp list` (o `/mcp` dentro de Claude Code) muestra `episteme` conectado. La primera vez tarda: uv descarga el repo y las dependencias. Una sesión abierta antes del registro no ve los tools (ni sus subagentes) hasta reiniciar Claude Code.
2. Copia el bloque de [Hooks](hooks.md) y los permisos recomendados en `.claude/settings.local.json` del proyecto, o en `.claude/settings.json` si todo el equipo tiene episteme registrado (con el servidor en scope local, a quien no lo tenga le fallarían los hooks). En modo auto, Claude Code no deja que el agente edite estos archivos: lo hace la persona.
3. Añade al `CLAUDE.md` del proyecto: «Vault `episteme`: solo los tools de episteme; ni CLI, ni Bash, ni Read/Edit/Write sobre el vault. Si los tools `mcp__episteme__*` salen como diferidos, cárgalos con ToolSearch (`select:mcp__episteme__context,mcp__episteme__search,mcp__episteme__read,mcp__episteme__remember,mcp__episteme__revise`) antes de usarlos; si no aparecen ni diferidos, dilo antes de seguir.»

## La skill `episteme-setup`

Vive en [`skills/episteme-setup/`](../skills/episteme-setup/SKILL.md) y se instala una vez, a nivel de usuario (en `~/.claude/skills/`), enlazada a un clone del repo para que `git pull` la actualice:

```bash
git clone git@github.com:Bajmein/episteme ~/src/episteme
mkdir -p ~/.claude/skills
ln -s ~/src/episteme/skills/episteme-setup ~/.claude/skills/episteme-setup
```

En Windows (PowerShell), con una unión de directorios, que no necesita el modo de desarrollador:

```powershell
git clone https://github.com/Bajmein/episteme "$HOME\src\episteme"
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$HOME\.claude\skills\episteme-setup" -Target "$HOME\src\episteme\skills\episteme-setup"
```

Se invoca a mano (`/episteme-setup`), desde la raíz del proyecto que se quiere conectar; Claude no la carga solo. Después de instalarla, reinicia Claude Code.

Además de registrar el servidor, la skill fusiona en el proyecto la clave `autoMemoryEnabled: false` (con permiso de la persona): la memoria automática de Claude Code (`MEMORY.md`) compite con episteme. También hace una comprobación de solo lectura de la configuración: compara `.claude/settings.local.json`, `.claude/settings.json` y el `settings.json` de usuario con el de la skill, y lista hooks que faltan, repetidos o con `matcher`/`input` distintos, permisos que faltan y `autoMemoryEnabled`. Muestra el diff y solo fusiona si la persona lo aprueba.

## Uso

Con el servidor conectado, Claude recibe las instrucciones de uso en el handshake de MCP: carga el contexto de la tarea con `context`, busca antes de decidir con `search` y guarda decisiones, lecciones y errores con `remember`. Los hooks hacen el resto: bienvenida al primer mensaje de cada sesión y otra vez tras compactar, recordatorios vencidos y memorias que vienen al caso según cada mensaje, `constraints` antes de editar un archivo, `surface` después de leerlo o editarlo (sin repetir lo ya mostrado en la sesión) y `checkpoint` al compactar. Para que Claude guarde algo, basta con decirle «recuerda que…». El detalle de cada tool está en [Tools](tools.md).
