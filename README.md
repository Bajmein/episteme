<div align="center">

![episteme: Agentic Memory & Knowledge Vault. Persistent Knowledge Engine for AI Workflows.](static/banner-episteme.jpg)

<a href="https://github.com/Bajmein/episteme/tags"><img alt="Versión" src="https://img.shields.io/badge/versi%C3%B3n-v0.16.0-8B5CF6?style=for-the-badge"></a>
<a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.14+-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54"></a>
<a href="https://docs.astral.sh/uv/"><img alt="uv" src="https://img.shields.io/badge/uv-DE5FE9?style=for-the-badge&logo=uv&logoColor=white"></a>
<a href="https://github.com/modelcontextprotocol/python-sdk"><img alt="MCP SDK" src="https://img.shields.io/badge/MCP_SDK-2.x-005571?style=for-the-badge&logo=modelcontextprotocol&logoColor=white"></a>
<a href="https://www.sqlite.org/fts5.html"><img alt="SQLite FTS5" src="https://img.shields.io/badge/sqlite-FTS5-07405e?style=for-the-badge&logo=sqlite&logoColor=white"></a>
<a href="https://obsidian.md/"><img alt="Obsidian" src="https://img.shields.io/badge/Obsidian-483699?style=for-the-badge&logo=obsidian&logoColor=white"></a>
<a href="https://www.markdownguide.org/"><img alt="Markdown" src="https://img.shields.io/badge/markdown-000000?style=for-the-badge&logo=markdown&logoColor=white"></a>
<a href="https://codescene.io/projects/87754"><img alt="CodeScene" src="https://img.shields.io/badge/CodeScene-analyzed-5F46EB?style=for-the-badge"></a>
<a href="LICENSE"><img alt="Licencia MIT" src="https://img.shields.io/badge/licencia-MIT-yellow?style=for-the-badge"></a>
<br>
<a href="#instalación"><img alt="Linux" src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black"></a>
<a href="#instalación"><img alt="macOS" src="https://img.shields.io/badge/mac%20os-000000?style=for-the-badge&logo=macos&logoColor=F0F0F0"></a>
<a href="#instalación"><img alt="Windows" src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge"></a>
<br>
<a href="https://github.com/Bajmein/episteme/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Bajmein/episteme/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI"></a>

# episteme

**Documentación y memoria de proyectos para agentes, servida por MCP desde un vault Markdown**

</div>

<p align="center">
  <a href="#qué-es">Qué es</a> ·
  <a href="#cómo-funciona">Cómo funciona</a> ·
  <a href="#instalación">Instalación</a> ·
  <a href="#uso-diario">Uso diario</a> ·
  <a href="#las-14-herramientas">Herramientas</a> ·
  <a href="#límites">Límites</a> ·
  <a href="#documentación">Documentación</a>
</p>

---

## Qué es

Claude Code es como un colega brillante que cada mañana llega sin recordar nada de ayer: empieza cada sesión sin saber qué pasó en la anterior. **episteme le da una memoria que dura**: una carpeta de notas en Markdown (el *vault*) donde quedan las decisiones, las lecciones y la documentación de tus proyectos, y que Claude consulta y completa mientras trabaja.

| | Qué hace por ti |
| :-- | :-- |
| **Recuerda** | Guarda decisiones, lecciones, errores y preferencias como notas ordenadas por proyecto |
| **Encuentra** | Busca en todo el vault, en español, sin distinguir mayúsculas ni tildes |
| **Avisa a tiempo** | Antes de editar un archivo, muestra las normas que le aplican; después, lo que ya se sabe de él |
| **Retoma** | Lleva una nota viva de en qué vas, la pone al día sola después de compactar o de `/clear` y la recupera al seguir |
| **Guarda tus planes** | Copia cada plan que apruebas en plan mode y, si limpias el contexto al aprobarlo, le dice a Claude dónde está |
| **Mantiene la documentación al día** | Con `/episteme:docs`, baja las páginas de la documentación de terceros guardada en el vault y actualiza solo las que cambiaron |
| **Cuida el orden** | Detecta duplicados, memorias vencidas, enlaces rotos y memorias sin enlazar; rechaza guardar contraseñas y tokens |

Las notas son archivos de texto tuyos: se abren con [Obsidian](https://obsidian.md/) o con cualquier editor, y no dependen de ningún servicio externo.

> [!NOTE]
> **Versión actual: v0.16.0.** Funciona en Linux, macOS y Windows. Las novedades de cada versión están en el [CHANGELOG](CHANGELOG.md).

## Cómo funciona

<p align="center">
  <img src="static/diagrams/arquitectura.png" alt="Claude Code (el agente y sus hooks) y, si lo activas, agy llaman al servidor episteme, que lee y escribe las notas Markdown del vault (memorias, documentación, sesiones y planes) y mantiene un índice de búsqueda; Obsidian puede abrir el mismo vault" width="880">
</p>

1. **Claude Code** habla con episteme de dos formas: el agente usa sus herramientas cuando las necesita, y los *hooks* las llaman solos en momentos fijos de la sesión. **agy** (Google Antigravity CLI) es opcional: usa las mismas herramientas, pero sin hooks.
2. **episteme** es un programa pequeño que corre en tu máquina. Es la única puerta al vault: valida lo que se guarda y mantiene un índice para buscar rápido.
3. **El vault** es una carpeta de notas Markdown, por defecto `~/.episteme`. Tú puedes leerlo y editarlo con Obsidian.

<details>
<summary><b>Glosario rápido</b></summary>

| Término | Qué significa |
| :-- | :-- |
| **Vault** | La carpeta con todas las notas. Se divide en zonas: memorias, documentación, estado de las sesiones y planes |
| **Memoria** | Una nota corta con algo que vale la pena recordar: una decisión, una lección, un recordatorio |
| **Herramienta (tool)** | Una acción que Claude puede pedirle a episteme: buscar, leer, guardar |
| **Hook** | Un automatismo de Claude Code que llama a una herramienta sin que nadie lo pida |
| **MCP** | El protocolo estándar con el que Claude Code se conecta a programas como episteme |

</details>

## Instalación

**Necesitas** [uv](https://docs.astral.sh/uv/) y git. uv consigue Python por ti si falta.

### Opción A · Con la skill (recomendada)

Las skills vienen en un plugin de Claude Code. Se instala una vez por máquina, con dos comandos (igual en Linux, macOS y Windows):

```bash
claude plugin marketplace add Bajmein/episteme
claude plugin install episteme@episteme
```

Más detalles (actualizar, quitar) en la [guía de instalación](docs/instalacion.md#el-plugin).

Después, en cada proyecto que quieras conectar:

1. Reinicia Claude Code y ábrelo en la raíz del proyecto.
2. Escribe `/episteme:setup`.
3. Aprueba los cambios que te muestra. La skill registra el servidor, configura los hooks y los permisos, y añade la regla al `CLAUDE.md`.

El plugin trae además estas skills:

| Skill | Para qué |
| :-- | :-- |
| `/episteme:sesion` | Guardar en qué estás (`guardar`) y retomarlo después (`retomar`) |
| `/episteme:mantencion` | Revisar las memorias contigo: unificar las repetidas, resolver contradicciones y archivar lo vencido. Con `corta` hace una ronda rápida de 3 casos; con `huerfanas`, enlaza las memorias que quedaron sueltas |
| `/episteme:reminder <texto>` | Dejar un recordatorio que sale al empezar cada sesión del proyecto |
| `/episteme:scaffold` | Crear o revisar la base del proyecto: `README.md`, `CLAUDE.md`, `CHANGELOG.md`, las reglas para contribuir y el `.gitignore`. Con `auditar` solo revisa, sin cambiar nada. También avisa cuando el README o el `CLAUDE.md` llevan tiempo sin revisar |
| `/episteme:docs [suite]` | Poner al día la documentación de terceros guardada en `docs/` del vault (todas las suites, o solo la que nombres, como `claude code`): baja las páginas, muestra qué cambió y lo guarda |
| `/episteme:agy [tarea]` | Activar agy (Google Antigravity CLI) en el proyecto y pasarle tareas. Claude revisa lo que agy propone recordar |

El plugin también funciona con agy, sin los automatismos: ni hooks ni bienvenida automática (ver «agy (opcional)» en [Instalación](docs/instalacion.md)).

### Opción B · A mano

Un solo comando registra el servidor. Cambia `<proyecto>` por el nombre del tuyo.

**Linux y macOS**

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+https://github.com/Bajmein/episteme@v0.16.0 episteme --project <proyecto>
```

**Windows** (PowerShell, en una sola línea)

```powershell
claude mcp add --scope local episteme -- uvx --from git+https://github.com/Bajmein/episteme@v0.16.0 episteme --project <proyecto>
```

Luego faltan los hooks, los permisos y la regla del `CLAUDE.md`: los pasos están en la [guía de instalación](docs/instalacion.md#después-de-registrar).

> [!TIP]
> Para comprobar que quedó bien, `claude mcp list` debe mostrar `episteme` conectado. La primera vez tarda un poco, porque se descarga. Para actualizar, repite el registro con el tag nuevo.

## Uso diario

No hay comandos que aprender: se usa conversando con Claude. Cada memoria pasa por un ciclo: se guarda, se encuentra cuando hace falta, avisa a tiempo y, cuando queda vieja, se corrige o se ordena.

<p align="center">
  <img src="static/diagrams/ciclo-memoria.png" alt="Ciclo de una memoria en episteme, alrededor del vault: guardar con remember, encontrar con search y read, avisar a tiempo con context, constraints y surface, corregir con revise y ordenar con /episteme:mantencion" width="720">
</p>

| Tú | episteme |
| :-- | :-- |
| Empiezas una sesión | Le entrega a Claude las normas del proyecto, los recordatorios vencidos y las memorias más importantes |
| Escribes un mensaje | Sugiere las memorias que vienen al caso |
| Dices «recuerda que…» | Guarda una memoria nueva, salvo que ya exista una casi igual |
| Preguntas «¿qué decidimos sobre…?» | Claude busca en el vault antes de responder |
| Claude va a editar un archivo | Le muestra las normas que aplican a ese archivo |
| Apruebas un plan en plan mode | Guarda una copia del plan; si eliges limpiar el contexto, le dice a Claude dónde quedó |
| La conversación se compacta o la limpias con `/clear` | Recupera el estado del trabajo y lo pone al día en segundo plano con lo que se habló. Si vas a compactar a mano sin haberlo guardado, te avisa una vez |

### Lo que pasa solo en cada sesión

<p align="center">
  <img src="static/diagrams/hooks-sesion.png" alt="Secuencia del día a día: con cada mensaje, antes y después de usar un archivo y al aprobar un plan, un hook de Claude Code llama a una herramienta de episteme, que responde con la bienvenida, memorias o normas, o guarda una copia del plan en el vault" width="880">
</p>

Los hooks nunca bloquean a Claude ni deciden por él: solo le acercan contexto. Funcionan como un semáforo, no como un muro: Claude puede leer la norma y aun así equivocarse. La configuración está en [Hooks](docs/hooks.md).

#### Al compactar o con `/clear`

<p align="center">
  <img src="static/diagrams/compactar-clear.png" alt="Secuencia de cómo el estado del trabajo sobrevive a /compact y a /clear: episteme guarda el resumen al compactar, lo devuelve con la bienvenida al volver a empezar y el agente extractor lo pone al día en segundo plano" width="880">
</p>

Si vas a compactar a mano y el estado lleva rato sin guardarse, episteme te lo pide una sola vez; si repites `/compact`, compacta igual. El detalle está en [Estado de la sesión](docs/sesion.md).

#### El resto: quién hace qué

| Cuándo | Quién | Qué pasa |
| :-- | :-- | :-- |
| En la primera bienvenida, como mucho una vez por periodo | episteme | Avisa de lo pendiente de revisar y propone una ronda corta; si lo activas, archiva lo vencido y hace un backup |
| Cuando lo necesita | Claude | Busca, lee, guarda («recuerda que…») y corrige memorias |
| Cuando tú lo pides | tú | `/episteme:mantencion` para revisar y ordenar |

Guardar una memoria siempre lo decide Claude: ningún hook copia lo que escribes. episteme no revisa el vault en segundo plano: la revisión corre cuando alguien la pide.

## Las 14 herramientas

| Herramienta | Para qué sirve | Escribe |
| :-- | :-- | :-: |
| `search` | Buscar en las notas y las memorias | |
| `read` | Leer una nota, una sección o varias notas a la vez | |
| `links` | Ver qué notas enlazan con otra | |
| `context` | Dar la bienvenida de la sesión y reunir lo relevante para una tarea | ● |
| `surface` | Mostrar lo que se sabe de un archivo | |
| `constraints` | Mostrar las normas que aplican a un archivo | |
| `remember` | Guardar una memoria nueva; avisa si le faltan palabras clave o enlaces | ● |
| `revise` | Corregir, reemplazar o archivar una nota | ● |
| `review` | Revisar el vault: duplicados, vencidas, enlaces rotos y memorias sueltas, con sugerencias de a qué enlazarlas | |
| `session` | Guardar y retomar el estado de la sesión (objetivo, lo hecho, el siguiente paso), con una plantilla | ● |
| `plan` | Guardar una copia de cada plan de plan mode y señalarla tras «clear context» (la usan los hooks) | ● |
| `checkpoint` | Obsoleto: guardar y recuperar el `estado.md` del proyecto (usa `session`) | ● |
| `docs_status` | Ver las suites de documentación y qué páginas tienen | |
| `docs_write` | Guardar una página de documentación descargada (lo usa `/episteme:docs`) | ● |

Los parámetros y el comportamiento exacto de cada una están en [Tools y memorias](docs/tools.md).

### Tipos de memoria

| Tipo | Qué guarda |
| :-- | :-- |
| `decision` | Algo que se decidió y por qué |
| `constraint` | Una norma que hay que respetar al tocar ciertos archivos |
| `lesson` | Algo aprendido que conviene repetir o evitar |
| `error` | Un fallo y cómo se resolvió |
| `preference` | Cómo le gusta trabajar a la persona |
| `insight` | Un hallazgo o una conclusión |
| `reminder` | Algo pendiente, con fecha |
| `session` | El estado del trabajo: guardarlo, recuperarlo y lo que hacen los hooks al compactar |

Cada memoria lleva una prioridad del 1 al 5: las de prioridad 5 son las normas que Claude ve al empezar cada sesión.

## Límites

- **Busca por palabras, no por significado.** «marketing» no encuentra una nota que solo dice «mkt». Por eso cada memoria lleva `keywords` con sinónimos y siglas, que Claude añade al guardar.
- **Avisa, no obliga.** Las normas llegan a Claude a tiempo, pero nada le impide ignorarlas.
- **No se ordena solo.** Unificar memorias repetidas y resolver contradicciones lo apruebas tú, con `/episteme:mantencion`. Conviene activar `archive_expired = true` (ver [Mantención](docs/mantencion.md)).
- **El filtro de contraseñas conoce los formatos habituales.** Una clave con un formato raro puede pasar: no dictes secretos.

## Documentación

El detalle técnico vive en [`docs/`](docs/):

| Documento | Contenido |
| :-- | :-- |
| [Instalación](docs/instalacion.md) | Pasos a mano en Linux, macOS y Windows, y el plugin con las skills |
| [Configuración](docs/configuracion.md) | Argumentos del servidor, variables, `episteme.toml`, zonas y registro de actividad |
| [Tools y memorias](docs/tools.md) | Las 14 herramientas con sus parámetros, el esquema de las memorias y los errores |
| [Estado de la sesión](docs/sesion.md) | La nota viva de cada hilo de trabajo en `sesiones/`, su plantilla y cuándo se archiva |
| [Planes](docs/planes.md) | La copia de cada plan de plan mode en `planes/`, cómo se recupera tras «clear context» y cuándo se archiva |
| [Suites de documentación](docs/documentacion.md) | La documentación de terceros en `docs/` del vault y cómo se mantiene al día con `/episteme:docs` |
| [Hooks](docs/hooks.md) | El bloque para `settings.json`, los permisos recomendados y cómo comprobar que funcionan |
| [Mantención](docs/mantencion.md) | Avisos, archivado de memorias vencidas, backup y el ciclo de revisión |
| [Migración de OMEGA](docs/migracion-omega.md) | Cómo traer las memorias de OMEGA |
| [Desarrollo](docs/desarrollo.md) | Tests, lint, salud del código y scripts de medición |
| [CHANGELOG](CHANGELOG.md) | Cambios de cada versión |

## Desarrollo

```bash
uv sync            # instala las dependencias
uv run ruff check  # lint
uv run pytest      # tests
```

El resto (el lint completo del CI, la revisión de calidad de cada PR con CodeScene y los scripts de medición) está en [Desarrollo](docs/desarrollo.md).

## Licencia

[MIT](LICENSE), © 2026 Benjamín C. Rossa.
