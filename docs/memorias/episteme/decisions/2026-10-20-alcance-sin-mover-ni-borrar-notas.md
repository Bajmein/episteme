---
type: decision
kind: semantic
project: episteme
priority: 5
status: active
created: 2026-10-20
tags: [pieza/alcance]
files: [src/episteme/server.py]
source: PLAN.md@v0.1.0 (Alcance, Riesgos)
helpful: 0
---
# Alcance: sin mover, renombrar, borrar ni crear notas fuera de memory/

`episteme` no tiene tools para mover, renombrar, borrar o crear notas fuera de `memory/`. Eso lo hace la persona en Obsidian. Sí se editan notas de zonas `read-write` con `revise`. Es lo que más se echaba de menos de mcpvault, y se deja fuera a propósito para que el motor no crezca.

También quedan fuera: sync, publicación, interfaz web, servidor HTTP y búsqueda semántica o embeddings (esta última como fase opcional posterior, si FTS5 se queda corto).

El riesgo principal del proyecto es convertirse en un producto que hay que mantener; el freno es este alcance. Antes de añadir un tool nuevo en `server.py`, buscar esta memoria y sustituirla con `revise(action="supersede")` si cambia.
