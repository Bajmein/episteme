---
type: lesson
kind: procedural
project: episteme-mcp
priority: 4
status: active
created: 2026-10-20
tags: [pieza/wikilinks, herramienta/obsidian]
files: [src/episteme_mcp/markdown.py, src/episteme_mcp/links.py]
source: PR #1
helpful: 0
---
# Cómo compara Obsidian encabezados y rutas en los wikilinks

- Al comparar `[[nota#Encabezado]]`, Obsidian ignora `` ` ``, `*`, `:`, `#`, `|`, `^`, `[`, `]` y `%`, además de mayúsculas y espacios sobrantes. `normalize_heading` en `markdown.py` hace lo mismo; sin eso aparecían 571 enlaces rotos falsos en `docs/` (p. ej. ``### `teammateMode` `` o `4. Automatización: Hooks…`). Con la normalización, el vault de prueba tiene 0.
- Un `[[carpeta/nota]]` que no es una ruta exacta se resuelve por sufijo de ruta antes que por nombre base (`links.py`).
- Un enlace ambiguo dentro de una nota se indexa sin destino y `review` lo informa como roto.
- En Obsidian, `%% nav:start %%` es un comentario cerrado en su línea; el motor trata el bloque `%% <nombre>:start %%` … `%% <nombre>:end %%` entero como comentario (texto fuera de la búsqueda, enlaces que cuentan).
