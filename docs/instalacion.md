# Instalación

[← Volver al README](../README.md)

Se distribuye con `uvx` desde un tag de GitHub. El repo es público y se instala por HTTPS, sin credenciales. `episteme` en PyPI es otro proyecto: instala siempre con `--from git+https://…`. Requiere [uv](https://docs.astral.sh/uv/) y git; uv consigue Python 3.14 o superior si falta (el servidor comprueba al arrancar que SQLite tiene FTS5).

Lo más corto es instalar el plugin (ver [El plugin](#el-plugin)) y correr `/episteme:setup` en cada proyecto: registra el servidor, fusiona permisos y hooks en `.claude/settings.json` y añade la regla al `CLAUDE.md`. A mano, son estos pasos.

## Linux y macOS

Por HTTPS, que no pide credenciales:

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+https://github.com/Bajmein/episteme@v0.19.0 episteme --project fabrik
```

Quien ya use SSH con GitHub puede usar `git+ssh://git@github.com/Bajmein/episteme@v0.19.0` en su lugar. Sin `--vault` usa el vault global `~/.episteme` y lo crea, con un `episteme.toml` mínimo (zona `memory`), si no existe.

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

Se instala por HTTPS, sin iniciar sesión en GitHub:

```powershell
claude mcp add --scope local episteme -- uvx --from git+https://github.com/Bajmein/episteme@v0.19.0 episteme --project <proyecto>
```

En una sola línea: el `\` de bash no parte líneas en PowerShell. El vault por defecto es `%USERPROFILE%\.episteme`; `--vault` acepta una ruta absoluta de Windows (`C:\Users\ana\notas`). El bloque de hooks es el mismo. Dentro de WSL, sigue la instalación de Linux.

## Después de registrar

1. `claude mcp list` (o `/mcp` dentro de Claude Code) muestra `episteme` conectado. La primera vez tarda: uv descarga el repo y las dependencias. Una sesión abierta antes del registro no ve los tools (ni sus subagentes) hasta reiniciar Claude Code.
2. Copia el bloque de [Hooks](hooks.md) y los permisos recomendados en `.claude/settings.local.json` del proyecto, o en `.claude/settings.json` si todo el equipo tiene episteme registrado (con el servidor en scope local, a quien no lo tenga le fallarían los hooks). En modo auto, Claude Code no deja que el agente edite estos archivos: lo hace la persona.
3. Añade al `CLAUDE.md` del proyecto: «Vault `episteme`: solo los tools de episteme; ni CLI, ni Bash, ni Read/Edit/Write sobre el vault. Si los tools `mcp__episteme__*` salen como diferidos, cárgalos con ToolSearch (`select:mcp__episteme__context,mcp__episteme__search,mcp__episteme__read,mcp__episteme__remember,mcp__episteme__revise`) antes de usarlos; si no aparecen ni diferidos, dilo antes de seguir.»

## Los plugins

El repo es también un marketplace de Claude Code con dos plugins. `episteme` que trae las skills (en [`plugin/skills/`](../plugin/skills/)) y el agente `episteme:extractor` (en [`plugin/agents/`](../plugin/agents/extractor.md)), que pone al día el estado de la sesión tras `/compact` o `/clear` cuando un hook lo pide, y un hook `SessionStart` (en [`plugin/hooks/`](../plugin/hooks/hooks.json)) que despierta al modelo para que lo lance sin esperar al siguiente mensaje (ver [Estado de la sesión](sesion.md)). El servidor no va en el plugin: se sigue registrando en cada proyecto con `claude mcp add` y fijado a un tag. `episteme-docs` (en [`plugin-docs/`](../plugin-docs/)) trae solo la skill `/episteme-docs:docs` y es opcional: sirve si el vault tiene suites de documentación (zonas `mode = "docs"`); depende de `episteme`, que se instala con él.

```bash
claude plugin marketplace add Bajmein/episteme
claude plugin install episteme@episteme
claude plugin install episteme-docs@episteme   # opcional
```

Los mismos comandos sirven en PowerShell. Después, reinicia Claude Code.

- **Por máquina y por cuenta.** Los plugins viven en el directorio de configuración de Claude Code. Si usas varias cuentas (`CLAUDE_CONFIG_DIR` o lanzadores que lo cambian), repite la instalación con cada una.
- **Sin credenciales.** El repo es público, así que el marketplace se clona sin iniciar sesión. El atajo `Bajmein/episteme` puede clonar por SSH: si no tienes clave SSH, usa `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` o la URL completa (`claude plugin marketplace add https://github.com/Bajmein/episteme`). En Windows hace falta Git for Windows en el `PATH`.
- **Actualizar.** `claude plugin update episteme@episteme` y reinicia Claude Code (o `/reload-plugins`). Llegan cambios cuando sube la versión del plugin, que es la del release. La actualización automática viene apagada en los marketplaces de terceros; se enciende en `/plugin` → Marketplaces.
- **Quitar.** `claude plugin uninstall episteme@episteme`.
- **Quien tenía la skill enlazada** (versiones anteriores, en `~/.claude/skills/episteme-setup`): borra el enlace; si no, quedan las dos, `/episteme-setup` y `/episteme:setup`.

| Skill | Quién la usa | Qué hace |
|---|---|---|
| [`/episteme:setup`](../plugin/skills/setup/SKILL.md) | La persona | Conecta un proyecto: registro, hooks, permisos y `CLAUDE.md` |
| [`/episteme:sesion`](../plugin/skills/sesion/SKILL.md) | La persona y el agente | Guarda el estado de la sesión en `sesiones/<proyecto>/` con la plantilla (`guardar`), lo recupera (`retomar`) o muestra la plantilla de un tipo (`plantilla`). Reemplaza a `/episteme:pausa` (ver [Estado de la sesión](sesion.md)) |
| [`/episteme:mantencion`](../plugin/skills/mantencion/SKILL.md) | Claude, cuando la bienvenida avisa de mantención pendiente o se le pide ordenar las memorias; o la persona | Recorre lo que informa `review`, propone grupo por grupo qué unificar, reemplazar o archivar, y aplica solo lo aprobado |
| [`/episteme:reminder <texto>`](../plugin/skills/reminder/SKILL.md) | La persona | Guarda un recordatorio de prioridad 5 del proyecto: `reminder` si el texto trae fecha, `preference` si no |
| [`/episteme:scaffold`](../plugin/skills/scaffold/SKILL.md) | La persona; o Claude, cuando el hook `doc-review` avisa | Crea o audita `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `.github/`, `.claude/rules/docs.md` y `.gitignore` desde plantillas, y ofrece módulos locales de desarrollo. No hace commits |
| [`/episteme-docs:docs [suite]`](../plugin-docs/skills/docs/SKILL.md) | La persona, o Claude cuando se le pide poner al día la documentación | Revisa las suites de documentación de `docs/` del vault contra su fuente y escribe lo que cambió con `docs(action="write")` (ver [Suites de documentación](documentacion.md)) |
| [`/episteme:agy [tarea]`](../plugin/skills/agy/SKILL.md) | La persona, o Claude cuando se le pide «pásale esto a agy» | Activa agy con episteme en el proyecto o le delega una tarea en modo headless (ver «agy (opcional)») |

El plugin sigue a la versión del release y el servidor al tag fijado en cada proyecto: si actualizas uno, actualiza el otro (ver «Actualizar episteme» en `/episteme:setup`).

Para desarrollar las skills desde un clone, `claude --plugin-dir plugin` en la raíz carga los archivos en su sitio para esa sesión (los cambios valen con `/reload-plugins`). También se puede instalar desde el clone (`claude plugin marketplace add ./` y el `install`), pero Claude Code copia el plugin a su caché: los cambios llegan solo al subir `version` y hacer `claude plugin update episteme@episteme`.

### `/episteme:setup`

Se invoca a mano (`/episteme:setup`), desde la raíz del proyecto que se quiere conectar; Claude no la carga solo.

Además de registrar el servidor, la skill fusiona en el proyecto la clave `autoMemoryEnabled: false` (con permiso de la persona): la memoria automática de Claude Code (`MEMORY.md`) compite con episteme. También hace una comprobación de solo lectura de la configuración: compara `.claude/settings.local.json`, `.claude/settings.json` y el `settings.json` de usuario con el de la skill, y lista hooks que faltan, repetidos o con `matcher`/`input` distintos, permisos que faltan y `autoMemoryEnabled`. Muestra el diff y solo fusiona si la persona lo aprueba.

### `/episteme:scaffold`

Deja definida la base de un proyecto. La invoca la persona (`/episteme:scaffold`) o Claude, cuando el hook `doc-review` le pide revisar un documento. Nunca hace commits y nunca escribe en el vault.

- **Modo.** Sin argumentos crea lo que falta desde las plantillas y audita lo que existe: lista los hallazgos con su evidencia (`ruta:línea`), propone el diff y aplica solo lo aprobado. Un archivo existente se completa; nunca se reemplaza entero. Con `auditar` es de solo lectura.
- **Partes.** `readme`, `claude`, `changelog`, `github` (`CONTRIBUTING.md`, `ESTILO.md`, la plantilla de PR y `.gitmessage`), `reglas` (`.claude/rules/docs.md`), `gitignore` y `modulos`. Se puede acotar a una o varias: `/episteme:scaffold auditar readme`.
- **Convenciones por defecto.** Docs en español; código y commits en inglés, con Conventional Commits; Keep a Changelog; PR con squash. Si el repo sigue otra convención, la auditoría lo informa y pregunta.
- **Stack.** Detecta Python con uv, Node, PHP, WordPress y las tareas de mise, y rellena los comandos (instalar, lint, tests) y los bloques de `.gitignore`. Lo que no detecta lo pregunta: nunca inventa un comando.
- **Módulos.** Se ofrecen solo si se cumplen sus precondiciones:

  | Módulo | Qué instala | Precondición |
  |---|---|---|
  | `reglas-python` | Reglas de estilo, pruebas y seguridad en `.claude/rules/python-*.md` | `pyproject.toml` |
  | `serena-python` | Regla y hook para usar Serena con ty, `.serena/` y sus permisos y hooks | `uv.lock`, `ty` en el grupo `dev`, `serena` y `serena-hooks` en el `PATH` |
  | `session-brief` | Hook de `SessionStart` con el estado del trabajo (rama, tags, CHANGELOG, PR e issues por `gh`), el mapa de módulos Python y el índice de reglas | Ninguna |
  | `doc-review` | Hook de `SessionStart` que avisa cuando `README.md` o `CLAUDE.md` llevan tiempo y actividad sin revisar | `README.md` o `CLAUDE.md` |
  | `claude-local` | `CLAUDE.local.md` con el índice de la config local | Se crea con cualquier otro módulo |

- **Qué queda local.** La base se versiona. Los módulos son locales por defecto: sus rutas van a `.git/info/exclude`, sus hooks a `.claude/settings.local.json` y se indexan en `CLAUDE.local.md`. La skill pregunta si versionarlos. También pregunta antes de `git config commit.template .github/.gitmessage`.
- **Registro.** Al terminar guarda en episteme una memoria `decision` del proyecto («Convenciones del proyecto: scaffold de episteme»).

#### Revisión periódica (`doc-review`)

`README.md` y `CLAUDE.md` llevan en la línea 1 una marca de última revisión completa, `<!-- doc-review: 2026-11-16 03ec174 -->` (fecha y sha de `HEAD`), que GitHub no muestra. Solo la escribe una revisión completa; un retoque no la mueve. Sin marca, o con un sha que ya no existe, se usa la fecha del último commit que tocó el archivo.

Al empezar la sesión, el hook suma puntos por cada commit desde la marca que no toque solo `*.md`:

| Documento | `feat` | `fix` | `refactor` / `perf` | `ci` / `build` / `chore` | Archivo nuevo, borrado o renombrado | Tag nuevo |
|---|---|---|---|---|---|---|
| `README.md` | 3 | 1 | 0 | 0 | 0 | 10 |
| `CLAUDE.md` | 2 | 1 | 2 | 2 | 2 por archivo | 10 |

Un tipo que no está en la tabla suma 1. El documento está vencido con 7 días y 15 puntos, con 30 días y 1 punto, o con un tag nuevo; con 0 puntos, nunca. Avisa una vez por sesión (no en `compact` ni en `clear`): la persona ve una línea y Claude, al cerrar la tarea en curso, revisa el documento con `/episteme:scaffold auditar <parte>`, corrige lo que contradice al repo, actualiza la marca y dice qué cambió, sin commit. Con `MODE = "propose"` en el hook, propone el diff y espera la aprobación. Para posponerlo: `python3 .claude/hooks/doc-review.py snooze README.md 7`. El estado se guarda en `.git/doc-review.json` (`git rev-parse --git-path`), fuera del repo versionado.

### agy (opcional)

El mismo plugin sirve a agy (Google Antigravity CLI): agy lee `plugin/.antigravity-plugin/plugin.json`, las skills de `plugin/skills/` y la regla `plugin/rules/AGENTS.md` (`trigger: always_on`), que le da lo esencial de las instrucciones del servidor, porque en agy no llegan al modelo. El plugin de agy es global; la regla se ignora en los workspaces sin episteme. La skill de documentación está en el plugin `episteme-docs`, que no tiene manifiesto de agy: no carga en agy. `setup`, `scaffold` y `agy` cargan en agy, pero no hacen nada útil ahí. `agy plugin validate` informa 1 error esperado: agy salta el agente `extractor` (`model: sonnet` no es un tier de agy), y el resto carga.

`/episteme:agy`, sin argumentos y desde Claude Code, activa agy en el proyecto ya conectado con `/episteme:setup`:

1. Comprueba `agy --version` y lee el registro de Claude Code (`claude mcp get episteme`).
2. Si falta, propone instalar el plugin en agy (`agy plugin install <ruta del plugin | URL del repo>`).
3. Escribe o fusiona `<proyecto>/.agents/mcp_config.json` con los mismos `command` y `args` del registro de Claude Code y `eager: true` para `context`, `search`, `read`, `remember` y `revise` (`agy mcp add` solo escribe en global).
4. Si `~/.gemini/config/mcp_config.json` trae una entrada global `episteme`, avisa de que choca de nombre con la del proyecto y propone quitarla.
5. Pregunta si añadir `.agents/` a `.git/info/exclude`.
6. Lo comprueba con una ejecución corta de `agy -p … --mode plan` (`agy mcp list` no muestra el MCP de proyecto).
7. Muestra las reglas `mcp(episteme/*)` para el `settings.json` global de agy, sin tocarlo: agy no aplica permisos de proyecto.

Todo lo que toca fuera del proyecto lo hace solo con la aprobación de la persona.

**Qué no hay en agy.** Ni hooks ni bienvenida automática, ni los modos `surface` y `constraints` de `context`, el extractor tras compactar o la copia de planes. agy usa los tools cuando la regla o el prompt se lo piden. Las respuestas de más de ~10 KB llegan truncadas, así que la regla pide lecturas acotadas.

**Delegar.** `/episteme:agy <tarea>` (o «pásale esto a agy») corre en segundo plano `agy -p '<prompt>' --output-format json --mode plan --print-timeout 15m --settings '{"permissions":{"allow":["mcp(episteme/*)"]}}'`; `--mode accept-edits` solo si se piden cambios, y nunca `--dangerously-skip-permissions`. agy no guarda memorias: termina con «Resultado», «Memorias propuestas» y «Tools de episteme usados», y Claude guarda con `remember` lo que valga, anotando «propuesto por agy». Un permiso denegado no da error: sale `status: SUCCESS` con `response` vacío y `denied_actions` con contenido. Para seguir la conversación, `--conversation <conversation_id>`.

## Uso

Con el servidor conectado, Claude recibe las instrucciones de uso en el handshake de MCP: carga el contexto de la tarea con `context`, busca antes de decidir con `search` y guarda decisiones, lecciones y errores con `remember`. Los hooks hacen el resto: bienvenida al primer mensaje de cada sesión y otra vez tras compactar, recordatorios vencidos y memorias que vienen al caso según cada mensaje, `context(mode="constraints")` antes de editar un archivo, `context(mode="surface")` después de leerlo o editarlo (sin repetir lo que la sesión ya recibió), el estado de la sesión al compactar o con `/clear` y una copia de cada plan al salir de plan mode. Para que Claude guarde algo, basta con decirle «recuerda que…». El detalle de cada tool está en [Tools](tools.md).
