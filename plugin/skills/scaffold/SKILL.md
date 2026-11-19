---
name: scaffold
description: Crear o auditar README.md, CLAUDE.md, CHANGELOG.md, las convenciones de .github (CONTRIBUTING, ESTILO, plantilla de PR y de commit), las reglas de .claude/rules y el .gitignore de un proyecto a partir de plantillas, y ofrecer módulos locales de desarrollo (reglas de Python, Serena con ty, session-brief, doc-review). Úsala cuando la persona lo pida (/episteme:scaffold) o cuando el hook doc-review avise de que README.md o CLAUDE.md están sin revisar.
argument-hint: "[auditar] [readme|claude|changelog|github|reglas|gitignore|modulos] …"
disable-model-invocation: false
---

# /episteme:scaffold: crear y auditar la base del proyecto

Deja definido lo que queda suelto al conectar un proyecto a episteme: `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `.github/` (`CONTRIBUTING.md`, `ESTILO.md`, `pull_request_template.md`, `.gitmessage`), `.claude/rules/docs.md` y `.gitignore`. Crea lo que falta desde `${CLAUDE_SKILL_DIR}/templates/` y audita lo que existe con `${CLAUDE_SKILL_DIR}/referencia/auditoria.md`. **Nunca hace commits** (los decide la persona) y nunca escribe en el vault.

Trabaja desde la raíz de git del proyecto (`git rev-parse --show-toplevel`).

## Argumentos

- Sin argumentos: todas las partes, crear y auditar.
- `auditar`: solo lectura. Entrega el informe y no escribe nada. Excepción: si la invocación viene del aviso del hook `doc-review` (el contexto trae `doc-review: <doc> lleva …`), aplica lo que diga su `MODE` (abajo, «Revisión pedida por doc-review»).
- Partes, una o varias: `readme`, `claude`, `changelog`, `github`, `reglas` (`.claude/rules/docs.md`), `gitignore`, `modulos`.

## Convenciones por defecto

- Docs y README en español; código, identificadores y commits en inglés. Conventional Commits y Keep a Changelog.
- El README lo entiende alguien no técnico; el detalle va en `docs/`.
- PR con squash (`gh pr merge --squash --delete-branch`): el título del PR es el commit final.
- **Si el repo ya sigue otra convención** (commits en español, merge commit…), la auditoría lo informa y pregunta. No impone la plantilla.

## Placeholders

Las plantillas llevan `{{nombre}}` y guías en `<!-- guía: … -->`. Al rellenar, quita las guías y las secciones que la guía dice omitir. Lo que no se detecta se pregunta; **nunca se inventa un comando**. `{{fecha}}` y `{{sha}}` de la marca `doc-review` son la fecha de hoy y `git rev-parse --short HEAD` (sin commits todavía, la marca se añade tras el primero: dilo). Las rutas de ejemplo son neutras (`/home/ana/…`, `${HOME}`).

## Pasos

### 0. Tools

Si salen como diferidas, carga `mcp__episteme__search` y `mcp__episteme__remember` con ToolSearch. Sin episteme todo funciona salvo el registro del paso 7: dilo y sigue.

### 1. Inventario (una sola llamada de Bash)

```sh
cd "$(git rev-parse --show-toplevel)" && \
ls -a README.md CLAUDE.md CLAUDE.local.md CHANGELOG.md LICENSE .gitignore .github/CONTRIBUTING.md .github/ESTILO.md .github/pull_request_template.md .github/.gitmessage .claude/rules .github/workflows 2>/dev/null; \
git log -20 --format=%s; git tag --sort=-v:refname | head -5; git config commit.template; \
ls pyproject.toml uv.lock package.json pnpm-lock.yaml bun.lock package-lock.json composer.json mise.toml wp-content 2>/dev/null
```

Con eso: qué partes existen, el idioma y el formato de los commits, el último tag y el stack (`${CLAUDE_SKILL_DIR}/referencia/stacks.md`, que dice además de dónde sale cada comando).

### 2. Preguntas mínimas

Con `AskUserQuestion`, y solo lo que no se infiere:
- el nombre visible y la frase de una línea, si no hay README;
- las partes, si no vienen en `$ARGUMENTS`;
- los módulos (abajo) que cumplen sus precondiciones, en multiSelect, y si se versionan (por defecto, locales);
- si la convención del repo choca con la de la plantilla.

### 3. Por cada parte

- **Si falta:** rellena la plantilla, enséñala y escríbela cuando la persona la apruebe. Se puede aprobar todo junto.
- **Si existe:** aplica la lista de `referencia/auditoria.md`. Lista los hallazgos con su evidencia (`ruta:línea` del archivo y del repo que lo contradice), propone el diff y aplica solo lo aprobado. Los archivos existentes se completan; nunca se reemplazan enteros.
- Al revisar entero `README.md` o `CLAUDE.md`, escribe su marca `<!-- doc-review: AAAA-MM-DD <sha> -->` en la línea 1, aunque el documento no cambie: revisado y sin cambios también cuenta como al día. Una corrección puntual no la toca.

| Parte | Plantilla | Destino |
| --- | --- | --- |
| `readme` | `templates/README.md` | `README.md` |
| `claude` | `templates/CLAUDE.md` | `CLAUDE.md` |
| `changelog` | `templates/CHANGELOG.md` | `CHANGELOG.md` |
| `github` | `templates/github/{CONTRIBUTING.md,ESTILO.md,pull_request_template.md,gitmessage}` | `.github/` (`gitmessage` → `.github/.gitmessage`) |
| `reglas` | `templates/rules/docs.md` (siempre que se crea la base) y `templates/rules/regla.md` para una regla nueva | `.claude/rules/` |
| `gitignore` | `templates/gitignore`: la base y los bloques `# stack: <id>` de los stacks detectados | `.gitignore` (solo añade) |

La línea de episteme de `templates/CLAUDE.md` es la misma que añade `/episteme:setup`: se deja solo si el proyecto está conectado a episteme.

### 4. Módulos

Locales por defecto: sus rutas van a `.git/info/exclude` y se indexan en `CLAUDE.local.md`; sus hooks, en `.claude/settings.local.json`. Si la persona pide versionarlos, van a `.claude/settings.json` y no a `exclude`.

| Módulo | Archivos (`templates/` → proyecto) | Precondición |
| --- | --- | --- |
| `reglas-python` | `rules/python/{style,testing,security}.md` → `.claude/rules/python-{style,testing,security}.md` | Hay `pyproject.toml`. `{{requires_python}}` sale de `requires-python` |
| `serena-python` | `rules/python/serena.md` → `.claude/rules/python-serena.md`; `hooks/python-serena.py` → `.claude/hooks/`; `serena/project.yml` y `serena/ty-lsp.sh` → `.serena/` (`chmod +x`); `settings/serena-python.json` | `uv.lock`, `ty` en el grupo `dev`, y `serena` y `serena-hooks` en el PATH (`command -v`). Si falta alguna, se informa y no se instala. Después: `serena project health-check .` |
| `session-brief` | `hooks/session-brief.py` → `.claude/hooks/`; `settings/session-brief.json` | Ninguna. Rellena `MAP_DIRS` con las carpetas de código Python detectadas (vacía si no hay Python) y `BASE_BRANCH` con la rama principal |
| `doc-review` | `hooks/doc-review.py` → `.claude/hooks/`; `settings/doc-review.json` | Hay `README.md` o `CLAUDE.md`. Pregunta `MODE` (`auto` por defecto, o `propose`) y si añade otros documentos a `DOCS` |
| `claude-local` | `CLAUDE.local.md` | Se crea, o se completa, cuando se instala cualquier otro módulo |

- Fusiona cada `settings/*.json` en `.claude/settings.local.json` sin pisar lo que haya (añade a las listas; no dupliques un hook que ya está). Si el clasificador bloquea la edición, no lo intentes por otra vía: muestra el JSON fusionado completo y pide a la persona que lo guarde.
- Añade las rutas a `.git/info/exclude` y una fila por pieza a «Índice de la config local» de `CLAUDE.local.md`.
- Si el proyecto pasa los hooks por `ruff`, `ty` o `vulture` (Python), comprueba que su config los incluye.

### 5. Plantilla de commit

`git config commit.template .github/.gitmessage`: pregunta antes, porque es config local del clone.

### 6. Comprobaciones

- `grep -rn '{{' <archivos escritos>` sale vacío.
- Los enlaces relativos de `README.md` y `CLAUDE.md` existen.
- Cada glob de `paths:` de las reglas escritas coincide con al menos un archivo (`git ls-files '<glob>'`).
- Los hooks copiados arrancan: `python3 .claude/hooks/<hook>.py < /dev/null` sale con 0 (`python-serena.py` con los argumentos `pre` y `remind`).

### 7. Registro en episteme

Guarda con `remember` una memoria `decision` del proyecto, título «Convenciones del proyecto: scaffold de episteme»: las partes creadas o auditadas, la convención elegida, lo que quedó local y `files` con las rutas. Si ya existe una (`search` con ese título y `project`), usa `supersedes`. Con `auditar` no se guarda nada.

### 8. Respuesta

Una tabla «archivo | creado / cambiado / sin cambios / omitido» y lo que quedó local. Sin commits: los cambios se revisan con `git diff`.

## Revisión pedida por doc-review

El hook `doc-review` avisa al empezar la sesión cuando `README.md` o `CLAUDE.md` acumulan actividad de git desde su marca. Su instrucción pide no interrumpir la tarea en curso.

1. Termina la tarea en curso.
2. Audita solo ese documento (`readme` o `claude`) con `referencia/auditoria.md`.
3. Con `MODE = "auto"` (por defecto): aplica sin preguntar las correcciones de hechos (lo que contradice al repo), actualiza la marca y al final informa del diff. Lo que no es un hecho (estilo, estructura) se propone y espera aprobación.
4. Con `MODE = "propose"`: propone el diff, aplica solo lo aprobado y actualiza la marca.
5. Sin commit. Si la persona pide posponerlo: `python3 .claude/hooks/doc-review.py snooze <doc> <días>`.
