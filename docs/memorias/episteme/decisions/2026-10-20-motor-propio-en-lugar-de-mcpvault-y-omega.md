---
type: decision
kind: semantic
project: episteme
priority: 4
status: active
created: 2026-10-20
tags: [pieza/arquitectura, origen/omega, origen/mcpvault]
files: [src/episteme/server.py]
source: PLAN.md@v0.1.0 (Contexto y objetivo, anexos A y B)
helpful: 0
---
# Motor propio en lugar de mcpvault, OMEGA y la app de Obsidian

`episteme` sustituye a mcpvault (`@bitbonsai/mcpvault`, documentación) y a OMEGA (memoria). Obsidian deja de ser una dependencia y queda solo como compatibilidad: las notas siguen siendo Markdown con wikilinks, frontmatter y tags, y la app sirve para mirarlas.

Por qué no OMEGA (1.5.20, 167 memorias en fabrik):
- `consolidate` y `compact` borraban decisiones sin accesos y mezclaban proyectos; estaban frenados con fechas de 2099.
- La búsqueda semántica usa un modelo en inglés y rinde poco en español.
- La fusión silenciosa «Evolved» descarta las tags nuevas.
- El grafo existe pero tiene 0 aristas.
- `export-obsidian` da tags basura (rutas como `/fd/eza/yq/mdq`): sirve como materia prima de la migración, no tal cual.

Por qué no mcpvault: no tiene backlinks, `wiki_link` con un nombre repetido devuelve uno sin avisar y la búsqueda da como máximo 20 resultados.

Por qué no la CLI de Obsidian (`obsidian` 1.14): necesita la app abierta y la lanza si no lo está. Correrla sin ventana exigiría Xvfb en una sesión Wayland, y Obsidian es una sola instancia para todas las bóvedas. Los hooks dependerían de un proceso gráfico vivo. Todo lo útil (backlinks, huérfanas, enlaces rotos, propiedades) se calcula leyendo los `.md`. La URI `obsidian://` y `obsidian-headless` no devuelven datos.

Lo que el motor activa y fabrik no usaba con OMEGA: constraints atadas a archivos, recordatorios con fecha, `helpful` en el orden de la bienvenida, `speculative`, `valid_until`, memoria episódica, revisión de contradicciones y viejas, y paquete de contexto con presupuesto de tokens.
