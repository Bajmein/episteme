# Instalación

[← Volver al README](../README.md)

Se distribuye con `uvx` desde un tag de GitHub. El repo es privado: hay que ser colaborador de `Bajmein/episteme`. Requiere [uv](https://docs.astral.sh/uv/) y git; uv consigue Python 3.14 o superior si falta (el servidor comprueba al arrancar que SQLite tiene FTS5).

Lo más corto es instalar el plugin (ver [El plugin](#el-plugin)) y correr `/episteme:setup` en cada proyecto: registra el servidor, fusiona permisos y hooks en `.claude/settings.json` y añade la regla al `CLAUDE.md`. A mano, son estos pasos.

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

## El plugin

El repo es también un marketplace de Claude Code con un plugin, `episteme`, que trae las skills (en [`plugin/skills/`](../plugin/skills/)). El servidor no va en el plugin: se sigue registrando en cada proyecto con `claude mcp add` y fijado a un tag.

```bash
claude plugin marketplace add Bajmein/episteme
claude plugin install episteme@episteme
```

Los mismos dos comandos sirven en PowerShell. Después, reinicia Claude Code.

- **Por máquina y por cuenta.** Los plugins viven en el directorio de configuración de Claude Code. Si usas varias cuentas (`CLAUDE_CONFIG_DIR` o lanzadores que lo cambian), repite la instalación con cada una.
- **Repo privado.** Claude Code clona por SSH si `ssh -T git@github.com` responde; si no, por HTTPS, y entonces no pide credenciales: hace falta `gh auth login` y `gh auth setup-git` antes. `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` fuerza HTTPS. En Windows hace falta Git for Windows en el `PATH`.
- **Actualizar.** `claude plugin update episteme@episteme` y reinicia Claude Code (o `/reload-plugins`). Llegan cambios cuando sube la versión del plugin, que es la del release. La actualización automática viene apagada en los marketplaces de terceros; se enciende en `/plugin` → Marketplaces.
- **Quitar.** `claude plugin uninstall episteme@episteme`.
- **Quien tenía la skill enlazada** (versiones anteriores, en `~/.claude/skills/episteme-setup`): borra el enlace; si no, quedan las dos, `/episteme-setup` y `/episteme:setup`.

| Skill | Quién la usa | Qué hace |
|---|---|---|
| [`/episteme:setup`](../plugin/skills/setup/SKILL.md) | La persona | Conecta un proyecto: registro, hooks, permisos y `CLAUDE.md` |
| [`/episteme:pausa`](../plugin/skills/pausa/SKILL.md) | La persona | Guarda el estado de la tarea como memoria de sesión (`sesion/pausa`, vigente 14 días) antes de `/clear` o de cerrar; `/episteme:pausa retomar` la recupera. Es para los proyectos sin `estado.md`, donde `checkpoint` no tiene tarea que guardar |
| [`/episteme:mantencion`](../plugin/skills/mantencion/SKILL.md) | Claude, cuando la bienvenida avisa de mantención pendiente o se le pide ordenar las memorias; o la persona | Recorre lo que informa `review`, propone grupo por grupo qué unificar, reemplazar o archivar, y aplica solo lo aprobado |
| [`/episteme:reminder <texto>`](../plugin/skills/reminder/SKILL.md) | La persona | Guarda un recordatorio de prioridad 5 del proyecto: `reminder` si el texto trae fecha, `preference` si no |

El plugin sigue a la versión del release y el servidor al tag fijado en cada proyecto: si actualizas uno, actualiza el otro (ver «Actualizar episteme» en `/episteme:setup`).

Para desarrollar las skills desde un clone, `claude --plugin-dir plugin` en la raíz carga los archivos en su sitio para esa sesión (los cambios valen con `/reload-plugins`). También se puede instalar desde el clone (`claude plugin marketplace add ./` y el `install`), pero Claude Code copia el plugin a su caché: los cambios llegan solo al subir `version` y hacer `claude plugin update episteme@episteme`.

### `/episteme:setup`

Se invoca a mano (`/episteme:setup`), desde la raíz del proyecto que se quiere conectar; Claude no la carga solo.

Además de registrar el servidor, la skill fusiona en el proyecto la clave `autoMemoryEnabled: false` (con permiso de la persona): la memoria automática de Claude Code (`MEMORY.md`) compite con episteme. También hace una comprobación de solo lectura de la configuración: compara `.claude/settings.local.json`, `.claude/settings.json` y el `settings.json` de usuario con el de la skill, y lista hooks que faltan, repetidos o con `matcher`/`input` distintos, permisos que faltan y `autoMemoryEnabled`. Muestra el diff y solo fusiona si la persona lo aprueba.

## Uso

Con el servidor conectado, Claude recibe las instrucciones de uso en el handshake de MCP: carga el contexto de la tarea con `context`, busca antes de decidir con `search` y guarda decisiones, lecciones y errores con `remember`. Los hooks hacen el resto: bienvenida al primer mensaje de cada sesión y otra vez tras compactar, recordatorios vencidos y memorias que vienen al caso según cada mensaje, `constraints` antes de editar un archivo, `surface` después de leerlo o editarlo (sin repetir lo ya mostrado en la sesión) y `checkpoint` al compactar. Para que Claude guarde algo, basta con decirle «recuerda que…». El detalle de cada tool está en [Tools](tools.md).
