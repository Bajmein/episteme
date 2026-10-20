---
type: decision
kind: semantic
project: episteme-mcp
priority: 4
status: active
created: 2026-10-20
tags: [pieza/checkpoint, pieza/hooks]
files: [src/episteme_mcp/checkpoint.py]
source: PLAN.md@v0.1.0 (Checkpoints)
helpful: 0
---
# Checkpoint desde el estado.md del proyecto

`checkpoint` es la única lectura fuera del vault y está limitada al patrón `state_glob` de `episteme.toml`, resuelto contra `project_dir` (los resultados que salen de él se rechazan). Las escrituras siguen confinadas al vault.

- `save` (hook `PreCompact`) toma el `estado.md` con `estado: activo` más reciente y guarda `memory/<proyecto>/sessions/checkpoint-<slug>.md`, uno por tarea que se sobrescribe, con Plan, Progreso, Decisiones, Trampas y Siguientes pasos. La Bitácora queda fuera porque es un registro largo que no ayuda a retomar.
- `valid_until` a 7 días: un checkpoint más viejo ya no describe la tarea.
- Nunca bloquea `PreCompact`: no devuelve `decision: "block"` ni JSON. Sin estado activo, `saved: false` sin error.
- `restore` (hook `SessionStart` con `compact|clear`) devuelve el checkpoint vigente más reciente del proyecto.
