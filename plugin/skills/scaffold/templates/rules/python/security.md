---
paths:
  - "{{src_glob}}"
---

# Seguridad en {{proyecto}}

Regla local de desarrollo (módulo `reglas-python` de `/episteme:scaffold`). Si choca con una regla de `.claude/rules/` versionada o con `CLAUDE.md`, mandan esas.

<!-- guía: quita las filas que no apliquen al proyecto (sin web no hay XSS ni CSRF; sin SQL no hay inyección) y añade los riesgos propios. -->

| Riesgo | Regla |
|---|---|
| Rutas que llegan de fuera | Se resuelven contra su raíz y se rechazan si se salen (`..`, rutas absolutas) |
| SQL | Los valores van siempre como parámetros. Un f-string en SQL solo interpola nombres que vienen del código, nunca texto de fuera |
| YAML | Solo `yaml.safe_load` |
| Procesos | `subprocess` con lista de argumentos y sin `shell=True`; nada de `eval`, `exec` ni `pickle` con datos de fuera |
| Hooks | Un fallo del hook no puede bloquear la sesión: sale con 0 y sin salida |
| Mensajes de error | Dicen qué falló y qué hacer, sin secretos ni rutas del equipo |
| Datos de personas | En fixtures, ejemplos y docs, rutas y nombres neutros (`/home/ana/…`) |

## Secretos

- Ninguno en el código, en los fixtures ni en los ejemplos. Los secretos van en variables de entorno o en un `.env` fuera de git (`.env.example` sí se versiona).
- Si aparece un secreto en un diff: para, avisa a la persona y no hagas commit. Hay que rotarlo, no solo borrarlo.

## Comprobaciones

- `{{security_check}}` antes del commit si tocaste rutas, SQL, YAML o procesos. Un `# nosec` nuevo lleva su código (`B603`, `B110`) y se explica en el PR.
- Para un cambio que toca rutas, permisos o escritura, pide la revisión con `/security-review`.
- Si encuentras un problema de seguridad mientras haces otra cosa: para, dilo y busca el mismo patrón en el resto del código antes de seguir.
