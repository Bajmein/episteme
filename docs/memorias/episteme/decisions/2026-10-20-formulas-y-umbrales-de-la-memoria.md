---
type: decision
kind: semantic
project: episteme
priority: 4
status: active
created: 2026-10-20
tags: [pieza/memoria, pieza/bienvenida, pieza/review]
files: [src/episteme/memory.py]
source: PLAN.md@v0.1.0 (Fórmulas)
helpful: 0
---
# Fórmulas y umbrales de la memoria

Valores fijados en `memory.py`. Si cambia alguno, se sustituye esta memoria con `revise(action="supersede")`.

- **Bienvenida** (`context(mode="welcome")`): `0.45·(priority−1)/4 + 0.35·exp(−días/30) + 0.20·min(helpful,10)/10`. Pesa más la prioridad porque es la decisión explícita de la persona; la recencia decae en un mes para que lo nuevo entre sin desplazar las normas; `helpful` satura en 10 para que una memoria muy usada no se quede fija. Secciones, en orden: recordatorios vencidos; «Normas»: toda memoria `active` de prioridad 5, sin importar su edad ni la fórmula (con ella, las normas viejas quedaban fuera en cuanto había más de 10 memorias recientes); «Vencen pronto (7 días)»: recordatorios con `due` en los próximos 7 días; y «Memorias»: las 10 mejores por fórmula, sin las normas ya listadas. Tope de 4000 caracteres en total, cortando por entradas completas, para que no se coma el contexto de cada sesión. Un recordatorio se descarta con `revise(action="dismiss")` (pasa a `archived`).
- **Contexto de tarea** (`context(mode="task")`): `0.5·relevancia + 0.3·(priority−1)/4 + 0.2·exp(−días/30)`. Aquí manda la relevancia FTS a la tarea. La tarea se consulta sin palabras vacías del español (`STOPWORDS_ES`) y se descarta lo que puntúa menos de 0,25 (salvo constraints con `files`). Las notas relacionadas usan la misma escala 0-1: `0.5·relevancia` (min-max entre sus aciertos) y el mismo umbral.
- **Duplicados** (`remember`): Jaccard de tokens (≥ 3 caracteres, sin tildes ni palabras vacías del español) contra memorias `active` del mismo proyecto y `type`. ≥ 0,8 no crea el archivo salvo `force=true`; entre 0,5 y 0,8 crea y devuelve `similar`. Sustituye a la fusión silenciosa «Evolved» de OMEGA, que perdía tags: aquí nunca se fusiona sin avisar.
- **Vieja** (`review`): `active`, más de 90 días y `helpful = 0`, salvo `preference` y `constraint`, que valen mientras no se sustituyan. Solo se informa, nunca se borra (OMEGA borraba).
- **Contradicción posible**: dos `decision`/`constraint` `active` del mismo proyecto que comparten un valor de `files` o al menos 2 tags, sin enlace `supersedes` ni `contradicts` entre ellas.
