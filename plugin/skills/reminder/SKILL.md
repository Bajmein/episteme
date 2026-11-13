---
name: reminder
description: Guarda un recordatorio en episteme para el proyecto actual, con prioridad 5 para que salga en la bienvenida de cada sesión. Úsala con /episteme:reminder y el texto, con una fecha opcional.
argument-hint: "<texto del recordatorio> [fecha YYYY-MM-DD]"
disable-model-invocation: true
---

# /episteme:reminder: recordatorio del proyecto en cada sesión

Texto: $ARGUMENTS

Guarda `$ARGUMENTS` en episteme como recordatorio del **proyecto actual**. Si los tools salen como diferidos, cárgalos antes: `ToolSearch select:mcp__episteme__search,mcp__episteme__remember`. Si no existen en la sesión, dilo y no guardes en otro sitio.

Sin texto en `$ARGUMENTS`, pregunta qué recordar; no inventes uno.

1. **Proyecto**: no pases `project`. Vale el del servidor, que es el de esta carpeta, y así el recordatorio no se mezcla con otros proyectos. No uses `_shared` salvo que la persona pida que valga para todos.
2. **Duplicados**: `search` con las palabras clave del texto y `zone="memory"`. Si ya hay uno activo que dice lo mismo, dilo y no crees otro; si el nuevo lo reemplaza, usa `supersedes`.
3. **Tipo**:
   - Con fecha en el texto (`2026-11-05`, «el 5 de noviembre», «el viernes»): conviértela a `YYYY-MM-DD` y usa `type="reminder"` con `due`. Sale en la bienvenida al acercarse la fecha y, vencido, se repite hasta resolverlo.
   - Sin fecha: `type="preference"`. `reminder` exige `due` y no se inventa una.
4. **Campos**:
   - `priority=5` siempre: es lo que lo lleva a la bienvenida de cada sesión.
   - `title`: frase corta en imperativo.
   - `body`: el texto de la persona, sin reescribirlo, con los archivos, tools o comandos que toque.
   - `files` (rutas relativas al proyecto) y `tags` (con `/`, sin `:`) solo si se deducen del texto.
5. **Respuesta**: una línea con la ruta creada, el tipo y, si hay `due`, la fecha. Sin resumen.

Para quitarlo después: `revise(note=<ruta>, action="dismiss")` si es `reminder`, o `action="archive"` si es `preference`.
