---
type: constraint
kind: procedural
project: fabrik
priority: 4
status: active
created: 2026-10-10
tags: [pieza/serena_guard]
files: [.claude/hooks/serena_guard.py]
related: ["[[2026-10-02-serena-ty]]"]
contradicts: []
helpful: 1
---
# serena_guard sigue `cd $VAR` sin resolverlo

Al editar `.claude/hooks/serena_guard.py`, no intentes expandir variables en `cd $VAR`: el guard las sigue como texto y deja pasar el comando. Expandirlas rompió los worktrees en el change 004.
