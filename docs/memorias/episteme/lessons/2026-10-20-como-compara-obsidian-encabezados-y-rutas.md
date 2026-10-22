---
type: lesson
kind: procedural
project: episteme
priority: 4
status: active
created: 2026-10-20
tags: [pieza/wikilinks, herramienta/obsidian]
files: [src/episteme/markdown.py, src/episteme/links.py]
source: PR #1
helpful: 0
---
# Cómo compara Obsidian encabezados y rutas en los wikilinks

- Al comparar `[[nota#Encabezado]]`, Obsidian ignora `` ` ``, `*`, `:`, `#`, `|`, `^`, `[`, `]` y `%`, además de mayúsculas y espacios sobrantes. `normalize_heading` en `markdown.py` hace lo mismo; sin eso aparecían 571 enlaces rotos falsos en `docs/` (p. ej. ``### `teammateMode` `` o `4. Automatización: Hooks…`). Con la normalización, el vault de prueba tiene 0.
- Un `[[carpeta/nota]]` que no es una ruta exacta se resuelve por sufijo de ruta antes que por nombre base (`links.py`).
- Un nombre repetido dentro de una nota prefiere la nota de la misma carpeta que el enlace (`Resolver.resolve(target, source)`). Si ninguna (o más de una) está ahí, el enlace ambiguo se indexa sin destino y `review` lo informa como roto. No se imita el resto de Obsidian (elige una en silencio): mantiene el aviso.
- En Obsidian, `%% nav:start %%` es un comentario cerrado en su línea; el motor trata el bloque `%% <nombre>:start %%` … `%% <nombre>:end %%` entero como comentario (texto fuera de la búsqueda, enlaces que cuentan).
