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
| `source` | sí, salvo `type: index` y las notas propias | URL `http(s)`, única dentro de la suite |
| `origin` | no | Solo `local`: una nota propia de la suite, sin página de origen. No lleva `source` (con las dos es `invalid_schema`), no sale en `pages` ni la compara `docs_check.py`, y `docs_status` la cuenta en `local` |
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
  markdown: null                                     # opcional: plantilla de URL o null
  manual: false                                      # opcional: true si se mantiene a mano
```

Las cuatro primeras claves son obligatorias; `markdown` y `manual` son opcionales y no se admiten otras. `markdown` es una URL `http(s)` con `{path}` (el path de la `source`, con `/` inicial) o `{page}` (ese path sin `/` inicial ni `.html`, `.htm` o `.md`, e `index` si termina en `/`), sin otros `{…}`; `docs_check.py diff --markdown` pide cada página ahí en vez de a la `source`, que sigue siendo la URL pública. Por ejemplo, `https://docs.github.com/api/article/body?pathname={path}` o `https://raw.githubusercontent.com/jdx/mise/main/docs/{page}.md`. `manual: true` marca una suite que se mantiene a mano: `/episteme:docs` no la sincroniza ni espera `synced`. `docs_write(path="README.index.md", fields={"suite": {...}})` reemplaza el mapa entero: las opcionales que no se reenvían se pierden.

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
| `docs_status(suite?, pages=false)` | sí | Sin `suite`, `{"suites": [...]}` con, por suite, `inbox` (la ruta absoluta de su bandeja; no la crea), `notes` (sin el manifiesto), `with_source`, `deprecated`, `invalid`, `local` (notas `origin: local`), `manifest_valid`, `upstream`, `include`, `context7`, `synced`, `markdown` (`null` si falta) y `manual` (`false` si falta). Con `suite` (`docs/mise` o `mise`), ese objeto; con `pages=true` añade `pages`, un TSV con una línea por nota con `source`: `<source>\t<hash>\t<ruta en la suite>\t<status>`. En TSV, una suite de 400 notas cabe en unos 10 000 tokens |
| `docs_write(suite, path?, source?, body?, body_ref?, fields?)` | no | Ver abajo |

`docs_write`:

- **Busca la nota** por `source` y, si no viene, por `path` (relativa a la suite, terminada en `.md`; el manifiesto es `README.index.md`). Un `source` que ya tiene otra nota y un `path` distinto es `invalid_argument`.
- **Si no la encuentra y viene `path`, la crea.** `path` tiene que quedar dentro de la suite (`outside_vault` si sale), no existir y venir con las claves obligatorias en `fields`; `created` y `updated` son hoy si no vienen.
- **`body`**: si su hash es el mismo, el cuerpo no se toca. Sin `body`, el cuerpo queda como está.
- **`body_ref`**: el hash (16 hexadecimales en minúscula) de un cuerpo que `docs_check.py diff` dejó en la bandeja de la suite, `<vault>/.index/docs-inbox/<suite>/<hash>.md`. Sustituye a `body`: pasar los dos es `invalid_argument`, y un hash mal formado también. El servidor lee el archivo, comprueba que su `body_hash` coincide con `body_ref` (si no, `invalid_argument` y el archivo se conserva) y sigue como con `body`. Si el archivo no está, `not_found`; si pesa más de 2 MiB, `invalid_argument`; si es un enlace que sale de la bandeja, `outside_vault`. Tras escribir con éxito, o si el cuerpo no cambió (`changed: false`), borra el archivo; con cualquier error, queda. Así el texto de las páginas no pasa por el contexto del modelo.
- **`fields`** se fusiona en el frontmatter (`null` borra una clave), como `revise set`. Si cambian el cuerpo o los `fields`, `updated` pasa a hoy, salvo que `fields` traiga `updated`. Un `source` repetido en la suite es `invalid_argument`.
- **Secretos**: los textos de `fields` pasan por el mismo filtro de credenciales que `remember`. El `body` no: es texto público, idéntico al de la fuente, y la documentación trae claves de ejemplo que el filtro rechazaría.
- **Frontmatter roto**: si el de la nota no se puede leer, se reconstruye solo con `fields`, que entonces tiene que traer todas las claves obligatorias.
- **Devuelve** `{"path", "created", "changed", "hash"}`. Con `changed: false` no se escribió nada. Cada nota escrita entra en el rastro de la sesión («De esta sesión» tras compactar), pero no cuenta como memoria guardada.

## La skill `/episteme:docs`

`/episteme:docs` revisa todas las suites; `/episteme:docs claude code` solo esa (el argumento se compara con el nombre de la suite, su `title` y sus `aliases`). La descarga la hace `plugin/skills/docs/scripts/docs_check.py`, en la máquina de la persona, con la biblioteca estándar de Python:

| Comando | Qué hace |
| --- | --- |
| `docs_check.py context7 <id>…` | Pregunta a la API pública de Context7 la `lastUpdateDate` de cada ID. Si existe `CONTEXT7_API_KEY`, la manda como `Authorization: Bearer` |
| `docs_check.py diff --pages <tsv> --inbox <dir> [--upstream <url>…] [--include <prefijo>…] [--markdown <plantilla>]` | Baja cada `source` del TSV (8 a la vez, 30 s de espera, 2 reintentos). `<dir>` es la bandeja que da `docs_status`: al empezar la crea y borra sus archivos `<16 hexadecimales>.md` de una corrida anterior (nada más), y guarda cada página `changed` o `new` como `<dir>/<body_hash>.md`; dos páginas con el mismo cuerpo comparten archivo. Lee los `llms.txt` de `--upstream` y busca las URL bajo `--include` que la suite no tiene. De cada URL, las existentes y las nuevas, prueba primero su variante Markdown (`<url>.md`, `<url>/index.md`, o `.html` cambiado por `.md`; no la pide si el último segmento ya tiene otra extensión, como `.txt` o `.json`) y, si no responde Markdown, usa la URL tal cual. Con `--markdown` (la plantilla `suite.markdown`) pide solo la URL de la plantilla, sin variante, también para las nuevas; un 404 o 410 ahí es `gone`. No es Markdown lo que, quitando el BOM, los espacios y los comentarios `<!-- -->` iniciales, queda vacío (`empty page`), empieza por `<!doctype`, `<html`, `<head`, `<body`, `<?xml` o `<svg` (`HTML instead of Markdown`) o es JSON entero (`JSON instead of Markdown`, salvo en una fuente `.json`); un `Content-Type` HTML, JSON o XML solo cuenta si además el cuerpo empieza por `<`. Si lo que vuelve de una página de la suite no es Markdown, no es un cambio sino un error con ese motivo y no se guarda nada: la suite necesita una fuente Markdown. Las páginas `deprecated` no se descargan y cuentan como `unchanged`: es la salida para una nota curada cuya fuente solo sirve HTML. Si una página nueva del `llms.txt` falla (HTTP 4xx/5xx, HTML, más de 2 MB), va a `skipped` (`source` y `reason`, sin archivo) y no a `errors`: un enlace roto de un tercero no impide poner `synced`, y la próxima corrida la intenta de nuevo. Para saber si una URL del `llms.txt` ya está en la suite, compara páginas y no cadenas: `X`, `X/`, `X.md`, `X/index.md` y `X#sec` son la misma, y las variantes de una página nueva salen una sola vez. Quedan fuera de las nuevas las URL con `{` o `}`, `/.well-known/`, las `.json` y todas las `.txt`, como `llms.txt` o `_llms/fr.txt` (las notas existentes no se filtran: `llms/api.txt` de supabase se sigue descargando). Devuelve `changed`, `unchanged`, `gone` (404 o 410), `skipped`, `new` (con `suggested_path`, `title`, el primer encabezado `# `, y `excerpt`, el primer párrafo de texto en una línea y de hasta 300 caracteres, o `null`) y `errors` (solo páginas de la suite y `llms.txt` que no se pueden leer: 5xx, tiempo agotado, HTML en vez de Markdown y demás); cada `changed` y `new` trae `hash` (el `body_ref` para `docs_write`) y `file` |

El flujo tiene tres fases:

1. **Revisión rápida.** `docs_status()`; las suites sin manifiesto válido se configuran primero, con la persona. Context7 sirve solo de filtro por fecha: si su `lastUpdateDate` es anterior a `synced`, la suite está al día y no se revisa más. Context7 no sirve como fuente, porque devuelve fragmentos según una consulta y no páginas enteras.
2. **Conteo.** Un subagente por suite, en paralelo: pide las páginas con `docs_status(suite, pages=true)`, corre `docs_check.py diff --inbox <inbox>` (el `inbox` de `docs_status`) y devuelve los conteos. La skill muestra una tabla antes de escribir nada.
3. **Actualización.** El mismo subagente escribe con `docs_write`: las cambiadas con `body_ref=<hash>`, las nuevas con `body_ref` y su frontmatter (`type` y `summary` salen del `title` y el `excerpt` de la entrada), las desaparecidas como `status: deprecated` y, si no hubo errores, `synced` en el manifiesto. Con más de 100 cambiadas en una suite, pregunta antes. Si `docs_write` da `not_found` para un `body_ref` (cuerpo compartido por dos páginas o bandeja vaciada), al final se corre `diff` otra vez y se escribe lo que quede. Ningún cuerpo pasa por el modelo.

Una segunda corrida seguida tiene que dar 0 cambiadas.

## Límites

- **El servidor no tiene HTTP.** episteme solo lista hashes y escribe lo que recibe; las descargas son del script, en la máquina de la persona.
- **La bandeja está dentro del vault**, en `.index/docs-inbox/<suite>/` (fuera de toda zona, sin indexar, fuera del backup). El único escritor fuera de los tools es `docs_check.py`; `docs_write` solo lee y borra ahí, confinado a la bandeja y por nombre-hash. Cada cuerpo pesa como mucho 2 MiB (el tope de indexado); una página mayor no se escribe, porque episteme no la indexaría (`reference/cli.md` de uv, con 807 KB, cabe).
- **`read` corta a 20.000 caracteres**: las páginas grandes de una suite se leen por `heading`.
- **No se borra ni se mueve nada.** Una página que desaparece de la fuente queda como `deprecated`.
- **El índice de la suite no se reescribe.** El cuerpo del `README.index.md` (la lista de páginas) es de la persona: las páginas nuevas se informan para enlazarlas a mano.

## Agregar una suite nueva

1. Crea la carpeta en el vault (por ejemplo `docs/render`) y declárala en `episteme.toml` con `mode = "docs"`. Reinicia Claude Code para que el servidor la lea.
2. Crea el manifiesto con `docs_write(suite="render", path="README.index.md", fields={"title": "Render", "type": "index", "status": "stable", "lang": "es", "tags": ["render"], "suite": {"upstream": ["https://render.com/docs/llms.txt"], "include": ["https://render.com/docs/"], "context7": null, "synced": null}})`.
3. Corre `/episteme:docs render`: con `synced: null`, todas las páginas del `llms.txt` salen como nuevas y la skill las crea.
