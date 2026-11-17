# Suites de documentación

[← Volver al README](../README.md)

Además de memorias, el vault guarda documentación de terceros (Claude Code, mise, uv…) en `docs/`, para que Claude la busque con `search` y la lea con `read` sin salir a la web. Cada conjunto de páginas de una misma fuente es una **suite**, y se mantiene al día bajo demanda con la skill `/episteme:docs`.

## Qué es una suite

Una suite es una zona del `episteme.toml` con `mode = "docs"`:

```toml
[zones."docs/mise"]
mode = "docs"
```

- Cada página de la fuente es una nota `.md`: el frontmatter lo pone episteme y el cuerpo es el texto de la página tal cual se descarga (las páginas de `llms.txt` suelen empezar con `> ## Documentation Index …`).
- Solo `docs_write` escribe en una zona `docs`. `revise` y `remember` responden `read_only_zone`; `review` trata la zona como de solo lectura (sus problemas van en `read_only`), y el backup no la incluye, porque las páginas se pueden volver a bajar.
- Una zona que no es `docs` (por ejemplo, una `read-only`) no es una suite: `docs_status` y `docs_write` responden `read_only_zone`.

## Esquema de las notas

Toda nota de la suite, salvo el manifiesto:

| Clave | Obligatoria | Regla |
| --- | --- | --- |
| `title` | sí | texto no vacío |
| `type` | sí | `reference`, `guide`, `concept`, `how-to` o `index` |
| `status` | sí | `stable` o `deprecated` |
| `lang` | sí | código corto (`en`, `es`) |
| `source` | sí, salvo `type: index` | URL `http(s)`, única dentro de la suite |
| `created`, `updated` | sí | `YYYY-MM-DD` |
| `tags` | sí | lista, puede ir vacía |
| `description`, `summary`, `aliases`, `category`, `up`, `related` | no | libres |

Las claves que no están en la tabla se conservan. `docs_status` cuenta en `invalid` las notas que no cumplen el esquema (también las de YAML roto); `docs_write` no escribe una nota que no lo cumpla (`invalid_schema`).

## El manifiesto

Va en el frontmatter de `<suite>/README.index.md` (`type: index`), bajo la clave `suite`. Así se lee con `read` como cualquier nota:

```yaml
suite:
  upstream: ["https://docs.astral.sh/uv/llms.txt"]   # índices llms.txt; puede ir vacío
  include: ["https://docs.astral.sh/uv/"]            # prefijos de URL que entran en la suite
  context7: /astral-sh/uv                            # ID de Context7 o null
  synced: 2026-11-16                                 # última revisión completa, o null
```

Las cuatro claves son obligatorias y no se admiten otras. `docs_write(path="README.index.md", fields={"suite": {...}})` reemplaza el mapa entero.

## El hash del cuerpo

Para saber si una página cambió, se compara un hash de su cuerpo (lo que sigue al frontmatter) con el de la página descargada:

```python
HASH_LEN = 16
def body_hash(body: str) -> str:
    text = body.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_LEN]
```

Se calcula al vuelo y no se guarda en el frontmatter: la primera revisión solo reescribe las páginas que de verdad cambiaron. El script de la skill lleva una copia idéntica (`episteme.docs.body_hash`); un test comprueba que dan lo mismo.

## Los tools

| Tool | Solo lectura | Qué hace |
| --- | --- | --- |
| `docs_status(suite?, pages=false)` | sí | Sin `suite`, `{"suites": [...]}` con, por suite, `notes` (sin el manifiesto), `with_source`, `deprecated`, `invalid`, `manifest_valid`, `upstream`, `include`, `context7` y `synced`. Con `suite` (`docs/mise` o `mise`), ese objeto; con `pages=true` añade `pages`, un TSV con una línea por nota con `source`: `<source>\t<hash>\t<ruta en la suite>\t<status>`. En TSV, una suite de 400 notas cabe en unos 10 000 tokens |
| `docs_write(suite, path?, source?, body?, fields?)` | no | Ver abajo |

`docs_write`:

- **Busca la nota** por `source` y, si no viene, por `path` (relativa a la suite, terminada en `.md`; el manifiesto es `README.index.md`). Un `source` que ya tiene otra nota y un `path` distinto es `invalid_argument`.
- **Si no la encuentra y viene `path`, la crea.** `path` tiene que quedar dentro de la suite (`outside_vault` si sale), no existir y venir con las claves obligatorias en `fields`; `created` y `updated` son hoy si no vienen.
- **`body`**: si su hash es el mismo, el cuerpo no se toca. Sin `body`, el cuerpo queda como está.
- **`fields`** se fusiona en el frontmatter (`null` borra una clave), como `revise set`. Si cambian el cuerpo o los `fields`, `updated` pasa a hoy, salvo que `fields` traiga `updated`. Un `source` repetido en la suite es `invalid_argument`.
- **Secretos**: los textos de `fields` pasan por el mismo filtro de credenciales que `remember`. El `body` no: es texto público, idéntico al de la fuente, y la documentación trae claves de ejemplo que el filtro rechazaría.
- **Frontmatter roto**: si el de la nota no se puede leer, se reconstruye solo con `fields`, que entonces tiene que traer todas las claves obligatorias.
- **Devuelve** `{"path", "created", "changed", "hash"}`. Con `changed: false` no se escribió nada. Cada nota escrita entra en el rastro de la sesión («De esta sesión» tras compactar), pero no cuenta como memoria guardada.

## La skill `/episteme:docs`

`/episteme:docs` revisa todas las suites; `/episteme:docs claude code` solo esa (el argumento se compara con el nombre de la suite, su `title` y sus `aliases`). La descarga la hace `plugin/skills/docs/scripts/docs_check.py`, en la máquina de la persona, con la biblioteca estándar de Python:

| Comando | Qué hace |
| --- | --- |
| `docs_check.py context7 <id>…` | Pregunta a la API pública de Context7 la `lastUpdateDate` de cada ID. Si existe `CONTEXT7_API_KEY`, la manda como `Authorization: Bearer` |
| `docs_check.py diff --pages <tsv> --out <dir> [--upstream <url>…] [--include <prefijo>…]` | Baja cada `source` del TSV (8 a la vez, 30 s de espera, 2 reintentos) y guarda cada página en `<dir>/<sha1 de la url>.md`. Lee los `llms.txt` de `--upstream` y busca las URL bajo `--include` que la suite no tiene. Devuelve `changed`, `unchanged`, `gone` (404 o 410), `new` (con `suggested_path`) y `errors` (5xx, tiempo agotado y demás) |

El flujo tiene tres fases:

1. **Revisión rápida.** `docs_status()`; las suites sin manifiesto válido se configuran primero, con la persona. Context7 sirve solo de filtro por fecha: si su `lastUpdateDate` es anterior a `synced`, la suite está al día y no se revisa más. Context7 no sirve como fuente, porque devuelve fragmentos según una consulta y no páginas enteras.
2. **Conteo.** Un subagente por suite, en paralelo: pide las páginas con `docs_status(suite, pages=true)`, corre `docs_check.py diff` y devuelve los conteos. La skill muestra una tabla antes de escribir nada.
3. **Actualización.** El mismo subagente escribe con `docs_write`: las cambiadas con su cuerpo nuevo, las nuevas con su frontmatter, las desaparecidas como `status: deprecated` y, si no hubo errores, `synced` en el manifiesto. Con más de 100 cambiadas en una suite, pregunta antes.

Una segunda corrida seguida tiene que dar 0 cambiadas.

## Límites

- **El servidor no tiene HTTP.** episteme solo lista hashes y escribe lo que recibe; las descargas son del script, en la máquina de la persona.
- **No se borra ni se mueve nada.** Una página que desaparece de la fuente queda como `deprecated`.
- **El índice de la suite no se reescribe.** El cuerpo del `README.index.md` (la lista de páginas) es de la persona: las páginas nuevas se informan para enlazarlas a mano.

## Agregar una suite nueva

1. Crea la carpeta en el vault (por ejemplo `docs/render`) y declárala en `episteme.toml` con `mode = "docs"`. Reinicia Claude Code para que el servidor la lea.
2. Crea el manifiesto con `docs_write(suite="render", path="README.index.md", fields={"title": "Render", "type": "index", "status": "stable", "lang": "es", "tags": ["render"], "suite": {"upstream": ["https://render.com/docs/llms.txt"], "include": ["https://render.com/docs/"], "context7": null, "synced": null}})`.
3. Corre `/episteme:docs render`: con `synced: null`, todas las páginas del `llms.txt` salen como nuevas y la skill las crea.
