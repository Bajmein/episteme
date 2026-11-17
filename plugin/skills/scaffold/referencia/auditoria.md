# Lista de comprobación de la auditoría

Cada hallazgo se informa con su evidencia: `ruta:línea` del archivo y `ruta:línea` (o el comando) del repo que lo contradice. Se propone el diff; nada se aplica sin aprobación, salvo cuando lo pide el hook `doc-review` en modo `auto` (ver `SKILL.md`). Un archivo existente se completa: nunca se reemplaza entero.

## Convención del repo

- Idioma y formato de los commits según `git log -20 --format=%s`. Si el repo escribe los commits en otro idioma o sin Conventional Commits, se informa y se pregunta: la plantilla no se impone.
- Lo mismo con el idioma de `README.md` y `docs/`, y con la forma de mezclar los PR (squash o merge commit, según la historia de `main`).

## `README.md`

- Marca `<!-- doc-review: AAAA-MM-DD <sha> -->` en la línea 1. Si falta, se propone añadirla.
- Frases cortas, sin parámetros, umbrales ni casos límite (eso va a `docs/`).
- La versión y los tags de los ejemplos son los del último tag (`git tag --sort=-v:refname | head -1`).
- Cada afirmación sobre el comportamiento coincide con el código o la config. Ejemplo: decir «al compactar y al reanudar» cuando el hook usa el matcher `compact|clear` y no corre en `resume`.
- Los enlaces relativos existen.
- Las funciones visibles de las versiones del CHANGELOG posteriores a la última edición del README están reflejadas (`git log -1 --format=%cs -- README.md` contra las fechas del CHANGELOG).
- Badges: solo de lo que el repo tiene; el de versión, con el último tag.

## `CLAUDE.md`

- Marca `doc-review` en la línea 1, antes de `# CLAUDE.md`.
- Menos de 80 líneas; lo que es de un módulo va a `.claude/rules/`.
- Cada línea es una regla que no se deduce del código.
- **Toda enumeración del árbol** (scripts, módulos, reglas, workflows) se comprueba contra `git ls-files`: falta lo nuevo, sobra lo borrado, cambió lo que hace. Se propone quitar las enumeraciones que no aportan.
- Los comandos existen (`uv run <x>` está en el grupo `dev`, `npm run <x>` en `scripts`).
- Las afirmaciones sobre el CI coinciden con `.github/workflows/*.yml` (activo o en pausa, en qué runner, en qué eventos).
- La línea de episteme está si el proyecto está conectado, idéntica a la de `/episteme:setup`.
- Nombra `.github/CONTRIBUTING.md` y `.github/ESTILO.md` si existen.

## `CHANGELOG.md`

- Encabezado con Keep a Changelog y «Sin publicar».
- Orden de las secciones dentro de cada versión: Añadido, Cambiado, Obsoleto, Eliminado, Corregido, Seguridad.
- La fecha de cada versión es la de su tag (`git log -1 --format=%cs <tag>`).
- Cada enlace del pie apunta a un tag que existe (`git ls-remote --tags origin`).
- «Sin publicar» compara desde el último tag.
- Si `git log <último tag>..HEAD` tiene `feat` o `fix`, «Sin publicar» no está vacío.

## `.github/`

- Existen `CONTRIBUTING.md`, `ESTILO.md`, `pull_request_template.md` y `.gitmessage`. Si falta alguno, se informa.
- `CONTRIBUTING.md`: ramas, commits (idioma, formato, atómicos, `git add` por ruta), forma de mezclar, CHANGELOG en el mismo PR y los comandos de antes del commit, que existen y coinciden con el CI.
- `.gitmessage` solo tiene líneas de comentario.
- `git config commit.template` apunta a `.github/.gitmessage` (config local: solo se informa).

## `.claude/rules/`

- Existe `.claude/rules/docs.md`. Si falta, se informa.
- Cada glob de `paths:` coincide con al menos un archivo (`git ls-files '<glob>'`).
- Cada regla tiene 15 viñetas o menos y no repite `CLAUDE.md`.

## `.gitignore`

- Están la base (`.DS_Store`, `Thumbs.db`, `*.swp`, `.env`, `.env.*` con `!.env.example`, `CLAUDE.local.md`, `.claude/settings.local.json`) y el bloque de cada stack detectado.
- Solo se añade, nunca se quita.
- Se avisa de los archivos versionados que ya coinciden con un patrón (`git ls-files -ci --exclude-standard`).

## Módulos instalados

- Si hay `.claude/hooks/doc-review.py`: la marca de `README.md` y `CLAUDE.md` existe y su sha está en la historia.
- Los hooks registrados en `.claude/settings.local.json` existen y arrancan (`python3 <hook> < /dev/null` sale con 0).
- `CLAUDE.local.md` tiene una fila por cada pieza local, y cada pieza está en `.git/info/exclude`.
