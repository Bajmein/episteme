---
type: reminder
kind: semantic
project: fabrik
priority: 3
status: active
created: 2026-10-20
tags: [origen/omega, origen/mcpvault, pieza/episteme]
files: [.claude/settings.json, .claude/rules/omega.md]
helpful: 0
due: 2026-11-10
---
# Retirar OMEGA, mcpvault y la skill obsidian de fabrik

Tras unas semanas de convivencia con `episteme` (comparando la bienvenida y lo que sale al tocar archivos), retirar de `${HOME}/src/fabrik`:
- OMEGA: los hooks `omega.hooks.fast_hook` de `.claude/settings.json` y `.claude/rules/omega.md`;
- mcpvault: el servidor `obsidian-episteme` (scope local);
- la skill `obsidian` de fabrik.

Antes, confirmar que la migración (`scripts/migrate_omega.py`) se hizo y que no falta nada en `memory/fabrik/`. Procedimiento en la skill `episteme-setup`. El `due` es una propuesta (+3 semanas); ajustarlo con `revise(action="set")`.
