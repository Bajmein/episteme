---
type: decision
kind: semantic
project: _shared
priority: 5
status: active
created: 2026-10-20
tags: [pieza/memoria, pieza/prioridad]
source: PLAN.md@v0.1.0 (Prioridad)
helpful: 0
---
# Escala de prioridad de las memorias

`priority` decide qué sale en la bienvenida de cada sesión; en `search` solo desempata. Si todo es 5, nada destaca.

- 5: norma vigente que toda sesión debe tener presente («Serena usa ty 0.0.89»).
- 4: decisión técnica de un cambio o de una herramienta. Es el valor por defecto en `decision` y `constraint`.
- 3: registro de qué se hizo o se auditó, sin norma que seguir («PR #1 mergeada»). Por defecto en el resto de tipos.
- 1-2: contexto menor; no entra en la bienvenida salvo que no haya nada más.

Cuando una norma cambia, se llama a `revise(action="supersede")` con la nueva: la vieja pasa a `status: superseded` y no se le baja la prioridad.
