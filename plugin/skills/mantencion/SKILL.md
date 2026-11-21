---
name: mantencion
description: Mantención de las memorias de episteme con review y revise. Úsala cuando la bienvenida diga «mantención pendiente», o cuando pidan limpiar, ordenar, unificar o revisar memorias, ver duplicadas, contradicciones o vencidas, o con /episteme:mantencion.
argument-hint: "[proyecto | *] [corta | huerfanas]"
---

# /episteme:mantencion: revisar y ordenar las memorias

Argumentos: $ARGUMENTS (en agy, lo que se escribió después del comando)

episteme no fusiona ni borra nada por su cuenta: `review` solo informa. Esta skill lleva ese informe hasta el final, **grupo por grupo y con la aprobación de la persona**. Nada se cambia antes de que diga que sí.

Solo se usan los tools de episteme. En Claude Code, si salen como diferidos, cárgalos con `ToolSearch select:mcp__episteme__review,mcp__episteme__read,mcp__episteme__remember,mcp__episteme__revise,mcp__episteme__search`.

## 1. Informe

`review(zone="memory")`: sin `project` revisa el proyecto del servidor y `_shared`. Si `$ARGUMENTS` trae un proyecto, pásalo en `project`; con `*`, todos.

Muestra los `totals` en una tabla y pregunta por dónde empezar. Si todo está en cero, dilo y termina. Lo que venga bajo `read_only` no se puede arreglar desde aquí: solo se menciona.

## 2. Qué hacer con cada categoría

Antes de proponer algo sobre una memoria, léela: `read(notes=[...])` con todas las del grupo en una llamada.

| Categoría | Qué es | Qué proponer |
|---|---|---|
| `expired` | Activas con `valid_until` ya pasado | Si ya no aplica: `revise(action="archive")`. Si sigue valiendo con cambios: `remember` de la versión nueva con `supersedes=<ruta>` |
| `similar` | Grupos de memorias que dicen casi lo mismo | Unificar (ver el paso 3) |
| `contradictions` | Dos decisiones que comparten archivo y se parecen | Ver el paso 4 |
| `flagged` | Marcadas como desactualizadas | Corregir con `revise(action="edit")` si es un dato puntual, reemplazar con `remember(supersedes=…)` si cambió el fondo, o archivar. Después de corregirla: `revise(action="set", fields={"flagged": null})`, o seguirá saliendo |
| `stale` | Más de 90 días y nunca marcadas como útiles | Preguntar si siguen valiendo. Si sí: `revise(action="feedback", value="helpful")`. Si no: archivar |
| `cut_titles` | El título quedó cortado y la primera línea del cuerpo lo repite | `revise(action="edit")` para quitar la repetición del cuerpo |
| `invalid_frontmatter` | El frontmatter no cumple el esquema | `revise(action="set", fields={…})` con el campo corregido |
| `broken_links` | Enlaces a notas que no existen | Corregir el enlace con `edit`, o quitarlo si la nota ya no existe |
| `orphans` | Memorias activas sin ningún enlace, cada una con hasta 3 `candidates` a enlazar | Proponer enlaces (ver el paso 7). El aviso de la bienvenida las cuenta como «huérfanas enlazables» (`totals.orphans_linkable`: las que traen al menos una candidata) |

## 3. Unificar un grupo de parecidas

1. Lee todas las del grupo y di en qué coinciden y en qué difieren.
2. Elige una de estas salidas y proponla:
   - **Una ya lo dice todo**: se queda esa, y cada una de las otras se marca con `revise(note=<otra>, action="supersede", by=<la que queda>)`.
   - **Cada una aporta algo**: redacta la unificada, con todos los datos concretos de las originales (archivos, comandos, fechas, personas); guárdala con `remember(…, supersedes=<una de ellas>)` y marca las demás con `revise(action="supersede", by=<la nueva>)`. Conserva el `type`, la `priority` más alta del grupo y la unión de `tags`, `keywords` y `files`.
   - **No son lo mismo**: se dejan, enlazadas con `related` para que se lean juntas.
3. Muestra el texto de la unificada antes de guardarla. Si `remember` responde `created: false`, es por parecerse a las que se van a reemplazar: repite con `supersedes`.

## 4. Contradicciones

1. Lee las dos y di cuál es el punto exacto en que chocan.
2. Si una es más nueva y la otra quedó vieja: propón `revise(note=<vieja>, action="supersede", by=<nueva>)`.
3. Si no se sabe cuál vale, **pregunta**: no lo decidas. La respuesta de la persona se guarda como la memoria que reemplaza a las dos.
4. Si en realidad no se contradicen (hablan de casos distintos del mismo archivo), enlázalas con `related`: `revise(action="set", fields={"related": [...]})`. `set` reemplaza la lista: incluye los enlaces que ya tenía más `[[la otra]]`. Así dejan de salir.

## 5. Reglas

- Una propuesta por grupo, con las rutas y la acción exacta; se aplica solo con el sí de la persona. Un «sí a todo» vale para la categoría que se está viendo, no para las siguientes.
- Nada se borra: `archive` y `supersede` son reversibles con `revise(action="set", fields={"status": "active"})`.
- No toques las memorias `session` de checkpoints antiguos (`checkpoint-*`): `review` las deja fuera de `expired`.
- Una norma de prioridad 5 no se archiva ni se reemplaza sin que la persona lo pida de forma explícita.
- Al terminar, corre `review` otra vez y muestra los totales de antes y de después.

## 6. Ronda corta

Con el argumento `corta`, o si la persona dice que tiene poco tiempo, toma como mucho 3 casos, en este orden:

1. Las memorias de `expired` (vencidas).
2. El grupo de `similar` con mayor `similarity`.
3. La contradicción de `contradictions` con mayor `similarity`.

Propón cada caso, aplica solo lo aprobado y termina diciendo cuántos pendientes quedan (los `totals` de un `review` nuevo). Las reglas de la sección 5 siguen valiendo.

## 7. Ronda de huérfanas

Con el argumento `huerfanas`, o cuando la persona lo pida, recorre las `orphans` de `review` de 10 en 10 (vienen primero las que traen `candidates`). Para cada tanda:

1. `read(notes=[…])` con las huérfanas de la tanda y sus `candidates`, en una llamada.
2. Para cada huérfana, propón qué candidatas van de verdad con ella: la misma decisión, el mismo tema, una causa y su efecto. Compartir tags no basta. Si no trae candidatas, busca con `search(query=<palabras del título y de keywords>, match="any", zone="memory")`.
3. Aplica lo aprobado con `revise(note=<huérfana>, action="set", fields={"related": ["[[nombre]]", …]})`. Basta enlazar desde la huérfana: el sentido inverso lo calcula el índice. Para memorias nuevas, `remember(link=true)` ya enlaza las mejores candidatas al guardar.
4. Si nada va con ella, se deja: una huérfana no es un error.

Termina con los `totals` de un `review` nuevo. Las reglas de la sección 5 siguen valiendo.
