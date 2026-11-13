# Tools y memorias

[← Volver al README](../README.md)

## Tools

Todos devuelven texto: JSON en modo agente y, con `hook_event`, exactamente lo que espera el hook. Los errores tienen la forma `<código>: <qué falló>. <qué hacer>`, con los códigos `not_found`, `ambiguous`, `read_only_zone`, `outside_vault`, `invalid_schema` e `invalid_argument`.

| Tool | Solo lectura | Para qué |
| --- | --- | --- |
| `search(query, path?, type?, tags?, project?, status?, zone?, limit=20, facets=false, match="all")` | sí | Búsqueda de texto completo (AND, `"frases"`, `a-b` como dos palabras, sin distinguir mayúsculas ni tildes). Excluye por defecto las memorias `superseded` y `archived` (`status="any"` no filtra). `project` incluye las memorias `_shared`; `zone` filtra por zona de `episteme.toml`. Cada fila trae `path`, `title`, `line`, `snippet`, `score` y, si tienen valor, `zone`, `type`, `status`, `project`, `created`, `priority`, `heading` y `superseded_by`. Con pocos aciertos, `partial` lista notas con solo algunas palabras; sin ninguno, `hints` explica qué filtro no existe y qué hay en el vault. `facets=true` añade recuentos por zona, proyecto, tipo, estado y tag (solo, lista lo que hay en el vault). `match="any"` devuelve las notas con cualquiera de las palabras (varios nombres o variantes en una sola llamada), y cada fila lista en `matched` las que tiene |
| `read(note?, heading?, lines?, outline?, content=true, notes?)` | sí | Nota entera (cortada a 20 000 caracteres), una sección o un rango de líneas, con frontmatter. El esquema de encabezados (cada uno con `line` y `end`) solo viene con la nota entera o con `outline=true`; `content=false` devuelve solo frontmatter y esquema, para elegir sección sin leer la nota; con `heading` o `lines` añade `range`. `notes` (hasta 20) lee varias notas enteras en una llamada: devuelve `notes` (una nota que falla sale como `{note, error}`) y, si la respuesta pasa de 50 000 caracteres, `pending` con las que faltan |
| `links(note, direction="both", depth=1)` | sí | Enlaces salientes, backlinks y notas alcanzables (hasta 3 saltos) |
| `remember(type, title, body, project?, priority?, tags, keywords, files, related, supersedes?, source?, due?, valid_until?, status="active", force=false, slug?)` | no | Crea una memoria con el esquema validado y detección de duplicados (≥ 0,8 del mismo proyecto y tipo no crea salvo `force`; las parecidas de otros tipos y de `_shared` solo avisan, con `type` y `project`). `keywords` (sinónimos, siglas) se buscan con el peso del título. Devuelve además `new_tags` (tags que ninguna otra nota tiene, con grafías cercanas) y `link_candidates` (hasta 5 memorias que comparten un archivo o 2 tags), solo si hay. El nombre sale del título (ver «Memorias»); `slug` lo fija |
| `revise(note, action, …)` | no | `edit`, `append`, `set` en zonas `read-write` y `memory` (en una memoria, un `set` que cambia `type` o `project` la mueve a la carpeta que le toca, con el mismo nombre, y devuelve `moved_from`; se niega si alguna nota la enlaza por ruta o si el nombre ya existe allí); `supersede`, `feedback`, `archive` y `dismiss` (archiva un recordatorio) solo en memorias |
| `review(path?, project?, limit=50, zone?)` | sí | `project="*"` revisa todos los proyectos. Memorias viejas, grupos de memorias parecidas (`similar`: activas de cualquier tipo o proyecto, salvo `session` y `reminder`, con similitud ≥ 0,4), títulos cortados y repetidos en el cuerpo (`cut_titles`), contradicciones posibles con su `similarity` (dos decisiones o constraints que comparten un archivo de `files` o 2 tags y tienen similitud ≥ 0,15, salvo que una enlace a la otra con `supersedes`, `contradicts` o `related`), huérfanas, enlaces rotos, frontmatter inválido y marcadas. `totals` da el total por categoría (las listas se cortan en `limit`); `zone` limita a una zona del `episteme.toml`. Los problemas de las zonas `read-only` (enlaces rotos y frontmatter inválido) van aparte, en `read_only` |
| `context(mode="welcome"\|"task", session?, project?, task?, prompt?, budget_tokens=2000, hook_event?)` | no | `welcome`: bienvenida al primer mensaje de cada `session` (como mucho 3 memorias de `_shared`, más solo si sobra sitio) y otra vez en `SessionStart` (`compact\|clear`); en los mensajes siguientes, los recordatorios vencidos cada 10 mensajes, hasta 5 memorias cuyo título, tags o `keywords` tienen una palabra poco frecuente de `prompt`, y un aviso si en 8 mensajes no se ha guardado ninguna memoria. `task`: memorias que casan con la tarea (con 3 palabras o más, deben tener 2; las constraints con `files` entran siempre), «Memorias enlazadas» por `related` y notas relacionadas. Cada entrada lleva `score` (0-1, o `null` en normas, recordatorios, sugeridas y enlazadas) y `kind` |
| `surface(file?, relative_path?, project_dir?, project?, limit=5, session?, hook_event?)` | sí | Memorias sobre un archivo (por `files` o porque lo mencionan), sin constraints, `session` ni `reminder`; el nombre base solo cuenta si es inequívoco; ignora las vencidas por `valid_until`. `relative_path` sustituye a `file` en las ediciones con Serena; sin ninguno, salida vacía. En modo hook, con `session`, no repite una memoria que `surface` ya mostró en la sesión (si no queda ninguna, salida vacía; si quedan, la cabecera añade `(+M ya mostradas)`); en modo agente nunca se suprime |
| `constraints(file?, relative_path?, project_dir?, project?, hook_event?)` | sí | Constraints activas (no vencidas) que aplican a un archivo. Avisa, no bloquea |
| `checkpoint(action="save"\|"restore", project_dir?, project?, task_title?, hook_event?)` | no | `save` guarda el `estado.md` activo (sin la Bitácora) como memoria de sesión. `restore` lee primero el `estado.md` activo vivo (el de la rama `<tipo>/<ID>-<change>`, si no el más reciente) con una línea de flujo (`etapa` y avance de `tasks.md`); sin estado activo cae al último checkpoint vigente. `task_title` retoma esa tarea. Archiva los checkpoints de tareas sin estado activo |

Los nombres de nota aceptan una ruta relativa al vault (con o sin `.md`) o un nombre que se resuelve como un wikilink: ruta exacta, nombre base, `aliases`. Si hay varios candidatos, el error `ambiguous` los lista. Dentro de una nota, un `[[nombre]]` repetido prefiere la nota de su misma carpeta, como Obsidian; si ninguna está ahí, el enlace queda ambiguo (roto en `review`). Los `#hex` (`#fff`, `#a1b2c3`; con al menos un dígito o una sola letra repetida, así que `#bad` o `#cafe` siguen siendo tags) y el texto dentro de código (bloques, indentado e inline) no cuentan como tags.

## Memorias

Viven en `memory/<proyecto>/<carpeta del tipo>/AAAA-MM-DD-<slug>.md` (`_shared` vale para todos los proyectos). La fecha es la local. El slug son las primeras 3 a 5 palabras útiles del título (sin palabras vacías en español ni inglés, sin lo que ya dice la ruta, hasta 40 caracteres y sin cortar palabras; una versión como `0.4.0` cuenta como una). El título completo queda en el H1. `slug` lo fija a mano (`[a-z0-9]` y guiones, sin la fecha). Si el nombre ya existe se añade `-2`, `-3`… Esquema:

```yaml
type: decision          # decision | lesson | error | constraint | preference | session | reminder | insight
kind: semantic          # sale del type
project: fabrik
priority: 4             # 1-5; 4 por defecto en decision y constraint, 3 en el resto
status: active          # active | superseded | speculative | archived
created: 2026-10-19
valid_until:
tags: [dominio/explore, pieza/serena_guard]
keywords: [mkt, marketing]   # sinónimos y siglas; pesan como el título en search
files: [.claude/hooks/serena_guard.py]
supersedes: "[[2026-09-12-serena-pyright]]"
related: ["[[...]]"]
contradicts: []
source: <sha o PR>
helpful: 0
due:                    # obligatorio en reminder
flagged: false
```

**Credenciales.** `remember` rechaza (`invalid_argument`, sin repetir el valor) un `title`, `body`, `keywords` o `source` que parezca una credencial: bloque PEM de clave privada, claves AWS (`AKIA`/`ASIA`), tokens de GitHub, Anthropic, `sk-`, Stripe, npm, Hugging Face, Slack, Google, JWT y URL con `usuario:clave@`. Son patrones de alta precisión con longitud mínima, así que mencionar un prefijo («empieza por `ghp_`») no dispara. `revise` revisa solo el texto que entra (`new`, `text`, valores de `fields`), no el cuerpo final: una nota con un falso positivo sigue siendo editable. No se redacta en silencio; se dice dónde está guardado el secreto.

**Duplicado bloqueado.** La respuesta `created: false` lleva `hint`: si volvió a ocurrir, `revise(action="feedback", value="helpful")` sobre la existente; si cambió, `remember` con `supersedes=<ruta>`; `force=true` solo para una memoria distinta de verdad.
