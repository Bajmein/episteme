# CLAUDE.local.md

Instrucciones locales de este clone. No se versionan: `.git/info/exclude`.

<!-- guía: una sección por módulo instalado (solo las de los módulos que se instalan) y una fila por pieza en el índice. Si el archivo ya existe, se completa: nunca se reemplaza. -->

## Python con Serena y ty

- Para trabajar con código Python, usa de preferencia el MCP de Serena, con ty como servidor de lenguaje. Qué tool usar para cada tarea está en `.claude/rules/python-serena.md`.
- Tras cada edición de Python, un hook corre `uv run --frozen ty check` y avisa si hay errores: corrígelos antes de seguir.
- `serena-hooks remind` niega la llamada que completa una racha larga de búsquedas o lecturas sin Serena: repite la llamada; no es un rechazo de la persona.
- Comprobar Serena: `serena project health-check .`

## Revisión de README.md y CLAUDE.md

- El hook `doc-review` avisa al empezar la sesión cuando `README.md` o `CLAUDE.md` acumulan actividad desde su última revisión. Al cerrar la tarea en curso, revísalo con `/episteme:scaffold auditar <parte>`.
- Posponer: `python3 .claude/hooks/doc-review.py snooze README.md 7`.

## Índice de la config local

| Qué | Dónde |
|---|---|
| {{pieza}} | {{ruta}} |
