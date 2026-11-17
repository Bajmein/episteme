<!-- doc-review: {{fecha}} {{sha}} -->
# CLAUDE.md

Guía para Claude Code en este repo.

<!-- guía: menos de 80 líneas. Cada línea es una regla que no se deduce del código. Lo que es de un módulo va a .claude/rules/. No copies el árbol del repo: una enumeración de archivos se queda vieja. -->

## Qué es

{{que_es}} La presentación está en `README.md` y el detalle, en `docs/`.

- {{donde_vive_el_codigo}}
- Alcance: {{lo_que_no_se_hace}}.
- Reglas por módulo en `.claude/rules/` ({{reglas}}); el porqué de las decisiones, en episteme (`search` con `project="{{proyecto}}"`).

## Cómo se trabaja

- Dependencias: {{gestor}}.
- Antes de cada commit: `{{lint}}` y `{{tests}}` en verde.
- CI: {{workflows}}.
- Release: {{release}}; en `CHANGELOG.md`, «Sin publicar» pasa a ser la versión con su fecha.
- Un cambio que nota quien usa el proyecto se anota en «Sin publicar» en el mismo PR.

## Convenciones

- Código, identificadores y commits en inglés; `README.md` y `docs/`, en español.
- Commits, ramas y PR: `.github/CONTRIBUTING.md`. Nombres y redacción: `.github/ESTILO.md`.
- Vault `episteme`: solo los tools de episteme; ni CLI, ni Bash, ni Read/Edit/Write sobre el vault. Si los tools `mcp__episteme__*` salen como diferidos, cárgalos con ToolSearch (`select:mcp__episteme__context,mcp__episteme__search,mcp__episteme__read,mcp__episteme__remember,mcp__episteme__revise`) antes de usarlos; si no aparecen ni diferidos, dilo antes de seguir.
