# Desarrollo

[← Volver al README](../README.md)

```bash
uv sync
uv run ruff check
uv run pytest
# lo que además corre el job lint del CI:
uv run ty check
uv run bandit -c pyproject.toml -r src scripts -q
uv run vulture
uv run deptry .
uv run python -m episteme --vault "$PWD/tests/fixtures/vault" --project fabrik
```

Los tests copian `tests/fixtures/vault/` a un directorio temporal antes de escribir y arrancan el servidor por stdio con el cliente del SDK de MCP.

El paquete pide Python 3.14 o superior (`requires-python`); el repo se desarrolla y se prueba en 3.15, fijado en `.python-version`, que es la versión que `uv` usa aquí y en el CI (Linux y Windows).

Dependabot (`.github/dependabot.yml`) abre un PR agrupado por semana con las dependencias de Python (`pyproject.toml` y `uv.lock`) y otro al mes con las GitHub Actions.

El banner es `static/banner-episteme.jpg` (1600 px de ancho, JPEG progresivo). El badge de versión de la cabecera es estático: se cambia en cada release, junto con el tag de los ejemplos de instalación.

## Salud del código

CodeScene Cloud analiza `main` cada día y revisa cada PR: el check «CodeScene Code Health Review (main)» aplica el perfil de quality gates «The Bare Minimum» y deja un comentario con el code health de cada archivo tocado, antes y después. Un PR no debería bajar el de ningún archivo; si lo baja, se corrige en el mismo PR.

Para bajar la complejidad sin cambiar lo que ve el agente:

- Se extraen funciones privadas en el mismo módulo, se nombran las condiciones compuestas con un predicado (`_is_…`, `_wants_…`) y se usan retornos anticipados o `continue` en vez de anidar.
- No se tocan las firmas de los tools ni las funciones que las reflejan (`Engine.search`, `Engine.read`, `memory.remember`…): el SDK saca el esquema de la firma.
- Cada módulo de `tools/` tiene un `register(...)` corto que llama a un `_register_<tool>(...)` por tool, en el orden de `list_tools`. El tool se define dentro de su `_register_<tool>`, con su docstring, porque el SDK saca de la función el nombre, la descripción y el esquema. Los argumentos con `Annotated` van como alias privados del módulo (`_LimitArg`…).
- La meta es 9 o más en cada archivo de `src/` y `scripts/`. Un archivo nuevo o tocado no baja de 9.
- Los tests no se modifican: son la red del refactor. CodeScene avisa entonces «Absence of Expected Change Pattern», que en un refactor es esperable.
- Se compara la foto del contrato antes y después: arrancar el servidor por stdio, volcar las instrucciones y `list_tools` a JSON con las claves ordenadas y comprobar con `cmp` que no cambió.

El refactor de noviembre de 2026 (PR #63 a #75) partió de 8,73 de code health y 8,02 en hotspots (análisis sobre `266ab09`). Por archivo, según la revisión de cada PR:

| Archivo | Antes | Después |
| :-- | --: | --: |
| `engine.py` | 6,07 | 8,42 |
| `memory/reviewing.py` | 6,98 | 9,69 |
| `index/text.py` | 7,11 | 10,00 |
| `memory/writing.py` | 7,32 | 9,39 |
| `vault.py` | 7,40 | 9,10 |
| `memory/schema.py` | 7,65 | 9,84 |
| `prompting.py` | 7,87 | 8,74 |
| `markdown.py` | 7,90 | 9,69 |
| `memory/task.py` | 8,03 | 9,39 |
| `memory/files.py` | 8,16 | 9,54 |
| `memory/welcoming.py` | 8,43 | 9,69 |
| `tools/hooks.py` | 8,46 | 8,99 |
| `index/store.py` | 8,47 | 9,36 |
| `memory/revising.py` | 8,62 | 9,10 |
| `index/ingest.py` | 8,82 | 9,69 |
| `server.py` | 9,14 | 9,54 |

Tras ese refactor, el análisis 8419179 sobre `0dd494b` dio 9,29 de code health y 8,99 en hotspots. Una segunda ronda (PR #77 a #84) llevó a 9 o más los archivos que quedaban por debajo, incluidos los scripts. En esa ronda, los `register(...)` de `tools/` dejaron de ser un método largo y se partieron en un `_register_<tool>` por tool:

| Archivo | Antes | Después |
| :-- | --: | --: |
| `scripts/bench_calls.py` | 6,75 | 9,24 |
| `scripts/migrate_omega.py` | 7,20 | 9,24 |
| `scripts/measure_uptake.py` | 8,11 | 9,69 |
| `engine.py` | 8,42 | 9,69 |
| `prompting.py` | 8,74 | 9,69 |
| `tools/reading.py` | 8,88 | 10,00 |
| `tools/memories.py` | 8,99 | 10,00 |
| `tools/hooks.py` | 8,99 | 9,69 |

## Medir variantes de búsqueda

Para decidir con números si conviene un lematizador de español o los trigramas de SQLite, corre el script sobre tu vault. Es de solo lectura: recorre las notas con el parser, no abre ni crea el índice y no escribe nada en el vault.

```bash
uv run scripts/measure_recall.py --vault ~/.episteme [--zone memory] [--terms a,b,c] [--terms-file t.txt] [--top 200] [--min-len 4] [--examples 15]
```

Sin `--terms`, mide los `--top` tokens alfabéticos de `--min-len` letras o más con más documentos. Por término compara cuatro conjuntos de documentos: `exact` (el token), `prefix` (tokens que empiezan por él), `stem` (misma raíz según `snowballstemmer` en español) y `trigram` (el texto plegado lo contiene como subcadena). La salida trae las familias de raíz, la tabla de los términos con mayor ganancia, la ganancia relativa media y mediana de cada estrategia y el «ruido estimado del trigrama» (documentos que solo añade el trigrama, con ejemplos `término → token que lo contiene` para juzgar a ojo).

Criterio: adoptar el lematizador si une variantes que hoy se pierden (ganancia de `stem` sobre `exact`) sin el ruido del trigrama; si casi todo lo que añade el trigrama son coincidencias dentro de otras palabras, no compensa.

## Medir si los embeddings aportan

Para decidir si vale la pena un módulo de búsqueda semántica, el script compara la búsqueda por palabras con los vecinos de un modelo de embeddings servido por Ollama. Es de solo lectura: recorre las notas con `Vault.iter_notes`, abre `.index/activity.db` con `mode=ro` y no abre ni crea el índice del vault.

```bash
ollama pull bge-m3
uv run scripts/measure_semantic.py --vault ~/.episteme [--zone memory] [--url http://localhost:11434] [--model bge-m3] [--queries-file q.txt] [--days 30] [--top-k 5] [--min-score 0.5] [--examples 15]
```

Requisitos: Ollama en marcha (`ollama serve`) y el modelo descargado. La URL solo puede ser `http` en `localhost`, `127.0.0.1` o `::1`; no hay dependencias nuevas. Las consultas salen de `--queries-file` (una por línea) y de las consultas de `search` y las tareas de `context` de los últimos `--days` días del registro de actividad.

El informe trae: por consulta, las memorias que da la coincidencia por palabras (todas las palabras útiles están en la nota) frente a los `--top-k` vecinos sobre `--min-score`, con los nuevos; los pares de memorias muy parecidos en significado que la similitud por tokens no detecta; la latencia de la primera llamada y la mediana de las siguientes, y el tiempo de calcular todos los vectores; y un resumen con cuántas consultas ganan algo.

Criterio: construir el módulo solo si hay aciertos nuevos claros en español (vecinos nuevos que de verdad responden a la consulta, no ruido).

## Medir llamadas por ráfaga

Para ver cuántas llamadas hace un agente al consultar el vault y cuánto ahorran los lotes (`search(match="any")` y `read(notes=[…])`), el script lee el registro de actividad. Es de solo lectura: abre `.index/activity.db` con `mode=ro` y trabaja sobre una copia temporal de las notas; el índice del vault real no se abre ni se crea.

```bash
uv run scripts/bench_calls.py replay --vault ~/.episteme [--pid N] [--gap 60] [--show]
uv run scripts/bench_calls.py ab --vault ~/.episteme --project <proyecto> --prompt-file <archivo> [--runs 5] [--out <dir>] [--model <m>] [--claude-bin claude] [--baseline-cmd "<cmd>"]
```

- `replay` toma la ráfaga más larga de `search` y `read` del registro (llamadas del mismo proceso separadas por menos de `--gap` segundos; `--pid` la limita a un proceso) y la repite dos veces sobre la copia: tal como quedó registrada y por lotes (las búsquedas de una palabra con los mismos filtros, en un `search` con `match="any"`; las lecturas de nota entera, en `read(notes=[…])`). Imprime llamadas, caracteres y milisegundos de cada variante, las rutas únicas que devuelve `search` y cuántas de las notas leídas salen en el `search` por lote. Las consultas y las rutas solo se imprimen con `--show`.
- `ab` lanza `claude -p` con el mismo prompt contra dos servidores, cada uno con su copia del vault: el de referencia (`--baseline-cmd`, por defecto el tag `v0.6.0`) y el de este checkout. Alterna `--runs` corridas por variante y cuenta lo que cada una deja en el registro de su copia: llamadas por tool, cuántas usan `match="any"` (`search_any`) y `notes` (`read_batch`), caracteres, turnos y coste. Las respuestas quedan en `--out` (por defecto `~/.cache/episteme-bench/<fecha>/`) para juzgar la calidad a mano.

## Medir si las memorias entregadas se leen

Para saber si lo que los hooks entregan (`context`, `surface`, `constraints`) llega a leerse, el script cruza el registro de actividad con las lecturas del agente. Es de solo lectura: abre `.index/activity.db` con `mode=ro` y lee la fecha `created` de las memorias desde las notas; no abre ni crea el índice.

```bash
uv run scripts/measure_uptake.py --vault ~/.episteme [--project <proyecto>] [--days 30] [--min-deliveries 3] [--old-days 90]
```

Imprime una tabla por memoria (entregas por hook, lecturas del agente, las que ocurren en la misma sesión después de una entrega y apariciones en `search`) y un resumen: (a) porcentaje de entregas seguidas de lectura, (b) memorias entregadas `--min-deliveries` veces o más y nunca leídas, (c) memorias de más de `--old-days` días con y sin lectura, (d) sesiones con lecturas y sin ninguna llamada a `remember` o `revise`, (e) búsquedas del agente sin resultados agrupadas por consulta, `match` y `zone`, por frecuencia (es el dato que decide el reintento con prefijo).

Límites: una fila de `context` no distingue la bienvenida del recall, así que se cuentan juntas (`welcome` es solo el subconjunto con `mode=welcome`); las entregas sin sesión no se pueden emparejar con una lectura y cuentan como no seguidas.

Los diagramas del README y de `docs/` están en `static/diagrams/`: cada uno es un HTML (la fuente, hecho con el plugin diagram-design en su variante oscura) y el PNG que se incrusta, exportado del HTML a 2x. Si cambia el HTML, se vuelve a exportar el PNG.

## Medir el grafo de enlaces

Para decidir si conviene que los hooks sugieran memorias vecinas por `related`, el script mide cuánto grafo hay de verdad entre las memorias. Es de solo lectura: recorre el vault con `Vault.iter_notes` y `parse`, y no abre ni crea el índice.

```bash
uv run scripts/measure_links.py --vault ~/.episteme [--zone memory] [--project <proyecto>] [--examples 15]
```

Sin índice, un destino se resuelve por ruta exacta (con o sin `.md`) o por nombre base único en el vault; lo demás cuenta como «sin resolver» (el informe lo dice). Solo se miden las memorias activas; con `--project` se miden las de ese proyecto (sus vecinas pueden ser también `_shared`).

El informe trae: memorias activas; enlaces por tipo (`body`, `related`, `supersedes`, `contradicts`) con los no resueltos; memorias con al menos un `related` (saliente o entrante) y su porcentaje; huérfanas (sin enlaces en ningún sentido); la distribución de vecinas `related` activas del mismo proyecto o `_shared` por memoria (0, 1, 2, 3 o más); cuántos de esos pares comparten pocas palabras (Jaccard de tokens < 0,2, es decir, vocabulario distinto) y ejemplos de pares, de menor a mayor similitud.

Criterio: vale la pena usar las vecinas si una parte apreciable de las memorias tiene `related` y esas vecinas usan otro vocabulario (es lo que un hook ganaría, porque la búsqueda literal ya encuentra las que comparten palabras). Si casi ninguna memoria tiene `related`, o las vecinas repiten el vocabulario, no compensa.
