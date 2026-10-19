---
task_title: 001 · demo
estado: activo
etapa: build
---
# Estado · 001-demo (core)

## Plan
Añadir el comando `demo` al plugin y cubrirlo con tests.

## Progreso
- Comando creado en `src/demo.py`.
- Faltan los tests de error.

## Decisiones
- El comando no escribe fuera del proyecto (decisión de la persona).

## Trampas
- `pytest -k demo` también recoge `test_demolition.py`: usar la ruta.

## Siguientes pasos
1. Tests de error.
2. Actualizar `docs/flujo.md`.

## Bitácora
- 2026-10-18 10:02 salida larga de pytest que no debe entrar al checkpoint.
