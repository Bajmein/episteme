---
name: docs
description: Actualiza las suites de documentación de terceros en docs/ del vault de episteme (claude-code, mise, uv…) con docs_status, docs_write y un script que descarga las páginas. Úsala cuando pidan revisar «docs vencidas», «actualiza la documentación», poner al día una suite, o con /episteme:docs.
argument-hint: "[suite en lenguaje natural]"
---

# /episteme:docs: poner al día las suites de documentación

Argumentos: $ARGUMENTS

Una **suite** es una zona del vault con `mode = "docs"` (`docs/mise`, `docs/uv`…): páginas de documentación de terceros copiadas tal cual. Solo `docs_write` las cambia. episteme no tiene HTTP: las descarga el script de esta skill, en la máquina de la persona, y deja cada cuerpo en la **bandeja** de la suite (`.index/docs-inbox/<suite>/<hash>.md`, dentro del vault), de donde `docs_write(body_ref=<hash>)` lo toma: ningún cuerpo de página pasa por tu contexto. Nunca se editan las suites a mano ni con Bash, Read, Edit o Write. La única excepción es el script, que escribe solo en la carpeta `inbox` que da `docs_status`; nada más del vault se toca fuera de los tools.

Herramientas: los tools de episteme son diferidos. Cárgalos antes de empezar: `ToolSearch select:mcp__episteme__docs_status,mcp__episteme__docs_write,mcp__episteme__read`. Si no aparecen, dilo y detente.

El script se corre siempre así (biblioteca estándar, sin dependencias):

```bash
uv run --no-project --python 3.14 python -I ${CLAUDE_SKILL_DIR}/scripts/docs_check.py <comando> …
```

Los archivos de trabajo van en el scratchpad de la sesión: `<scratchpad>/docs-<suite>/`.

## Fase A: revisión rápida (agente principal)

1. `docs_status()`. Resuelve `$ARGUMENTS` contra el nombre de cada suite (`docs/claude-code`, `claude-code`), su `title` y sus `aliases` (léelos con `read(notes=["<suite>/README.index.md", …])`, todas en una llamada, si hace falta): «claude code» → `docs/claude-code`. Si queda ambiguo, pregunta. Sin argumentos entran todas.
2. **Suite sin manifiesto válido** (`manifest_valid: false`): configúrala primero, con la persona.
   - `upstream`: la URL de la línea `Fetch the complete documentation index at: <url>` de sus notas (búscala con `search`).
   - `include`: el prefijo común de sus `source` (míralo en `docs_status(suite, pages=true)`).
   - `context7`: el ID que devuelva `docs_check.py context7 <id>` con fecha (prueba `/<org>/<repo>`); confírmalo con la persona. Si no hay, `null`.
   - Guárdalo con `docs_write(suite, path="README.index.md", fields={"suite": {"upstream": [...], "include": [...], "context7": ..., "synced": null}})`. `suite` se reemplaza entero: manda siempre las cuatro claves. Si el frontmatter del manifiesto no se puede leer, `fields` tiene que traer además `title`, `type: index`, `status`, `lang`, `created`, `updated` y `tags`.
3. `docs_check.py context7 <id>…` con los ID de las suites. Si `lastUpdateDate` (su fecha) es anterior a `synced`, la suite está **al día según Context7** y no se revisa más. Las demás, y las que tienen `context7: null` o `synced: null`, pasan a la fase B.

## Fase B: conteo (un subagente por suite, en paralelo)

Lanza todos los subagentes en **un solo mensaje**: `general-purpose`, `model: "sonnet"`, `effort: "medium"`. El brief de cada uno trae la suite, la ruta de trabajo y estas instrucciones:

1. Cargar `mcp__episteme__docs_status` y `mcp__episteme__docs_write` con ToolSearch; si no aparecen, decirlo y parar.
2. `docs_status(suite="<suite>", pages=true)`: guardar `inbox` (la bandeja) y escribir `pages` tal cual en `<scratchpad>/docs-<suite>/pages.tsv`.
3. Correr `docs_check.py diff --pages <scratchpad>/docs-<suite>/pages.tsv --inbox <inbox> --upstream <upstream…> --include <include…>`.
4. Devolver solo los conteos (cambiadas, nuevas, desaparecidas, errores) y el JSON del diff. No escribir nada todavía.

Muestra una tabla con suite, cambiadas, nuevas, desaparecidas, errores y «al día según Context7».

## Fase C: actualización (`SendMessage` al mismo subagente)

Si una suite tiene **más de 100 cambiadas**, pregunta antes de seguir con ella: puede ser un cambio de formato en la fuente.

El subagente conserva su contexto; mándale con `SendMessage` que escriba:

| Caso | Llamada |
| --- | --- |
| `changed` | `docs_write(suite, source=…, body_ref=<hash>)`. Solo cambia `summary` o `description` si cambió el sentido de la página (léelo en las primeras ~40 líneas de `file`, nunca el archivo entero) |
| `new` | `docs_write(suite, path=<suggested_path>, source=…, body_ref=<hash>, fields={"title": <el `title` de la entrada; si es `null`, deduce uno del `excerpt` o de `suggested_path`>, "type": <reference, guide, concept o how-to>, "status": "stable", "lang": "en", "tags": [<suite>, <suite>/<primera carpeta>], "summary": <una frase en español>, "up": "[[README.index]]"})` |
| `gone` | `docs_write(suite, source=…, fields={"status": "deprecated"})`. Nada se borra |
| Sin `errors` al final | `docs_write(suite, path="README.index.md", fields={"suite": {…las cuatro claves…, "synced": <hoy>}})` |

`type` y `summary` de una página `new` salen de su `title` y su `excerpt` (el primer párrafo de texto, en una línea y cortado a 300 caracteres; `null` si no hay): no leas el archivo de la bandeja, el vault no se lee con Read. Un error `HTML instead of Markdown` en `errors` significa que esa fuente solo sirve HTML y la suite necesita una fuente Markdown; no impide escribir las demás páginas, pero deja `synced` sin poner, como cualquier error del `diff`. `docs_write` lee el cuerpo de la bandeja, comprueba que su hash es `body_ref`, no reescribe lo que no cambió y borra el archivo al terminar. No se escanea en busca de secretos (es texto público); los `fields` sí. Si `docs_write` responde `not_found` para un `body_ref` (dos páginas con el mismo cuerpo comparten archivo, o la bandeja se vació), al final vuelve a correr `diff` de esa suite y escribe lo que quede. Con `errors`, `synced` no se toca: la próxima corrida vuelve a revisar la suite.

El subagente devuelve lo que escribió y lo que falló. Cierra con una tabla final por suite. El cuerpo del `README.index.md` (la lista de páginas) **no** se reescribe: las páginas nuevas se informan para enlazarlas a mano en Obsidian.

## Límites

- Una segunda corrida seguida tiene que dar 0 cambiadas; si no, la fuente cambia en cada descarga (fechas, contadores): dilo en vez de escribir otra vez.
- `docs_write` responde `read_only_zone` fuera de una zona `docs` y `outside_vault` si `path` se sale de la suite. No lo rodees: el `episteme.toml` lo cambia la persona.
