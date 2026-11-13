---
name: pausa
description: Guarda en episteme el estado de la tarea en curso antes de /clear o de cerrar la sesión, y lo recupera después. Úsala con /episteme:pausa antes de limpiar el contexto y con /episteme:pausa retomar para seguir donde quedó.
argument-hint: "[nota para quien retome] | retomar"
disable-model-invocation: true
---

# /episteme:pausa: guardar la tarea antes de limpiar y retomarla después

Argumentos: $ARGUMENTS

Sirve para los proyectos sin `estado.md`: ahí `checkpoint` no tiene tarea que guardar, y tras `/clear` o al cerrar se pierde en qué se estaba. Esta skill lo deja en una memoria de sesión. Después de `/clear`, esa memoria sale primera en el bloque «De esta sesión» de la bienvenida.

Solo se usan los tools de episteme. Si salen como diferidos, cárgalos antes: `ToolSearch select:mcp__episteme__search,mcp__episteme__read,mcp__episteme__remember,mcp__episteme__revise`. Si no existen en la sesión, dilo y no guardes el estado en otro sitio.

Si `$ARGUMENTS` empieza por `retomar`, ve a «Retomar». En cualquier otro caso, «Guardar».

## Guardar

1. **Pausa anterior**: `search(type="session", tags=["sesion/pausa"], zone="memory")`, sin `project`. Si hay una activa de la misma tarea, la nueva la reemplaza (`supersedes` en el paso 3). Si es de otra tarea, déjala.
2. **Redacta el estado** a partir de la conversación, para alguien que no la vio. Corto y concreto, con estas secciones:
   - `## Objetivo`: qué pidió la persona, con sus palabras si fueron precisas.
   - `## Hecho`: lo terminado, con rutas de archivos, rama y commits.
   - `## En curso`: lo que estaba a medias y en qué punto exacto quedó.
   - `## Falta`: los pasos siguientes, en orden.
   - `## Decisiones y restricciones`: lo acordado y lo descartado, con el porqué en una línea.
   - `## Comprobaciones`: qué se verificó, qué no, y los comandos para repetirlo.
   - `## Nota`: el texto de `$ARGUMENTS`, tal cual, si lo hay.

   Sin secretos (claves, tokens, contraseñas): di dónde están guardados. Las personas, por su apellido.
3. **Guarda** con `remember`:
   - `type="session"`, sin `project` (vale el del servidor, que es el de esta carpeta).
   - `title`: `Pausa: <la tarea en 4 a 6 palabras>`.
   - `tags=["sesion/pausa"]`, `priority=4` y `files` con los archivos en curso (rutas relativas al proyecto).
   - `valid_until`: 14 días después de hoy, para que no quede como memoria permanente.
   - `supersedes=<ruta>` si reemplaza una pausa del paso 1.
   - Si responde `created: false` por parecerse a otra, repite con `supersedes` de esa ruta; `force=true` solo si de verdad es otra tarea.
4. **Lo que deba durar** más que la tarea (una decisión cerrada, una lección, una corrección de la persona) va aparte, cada cosa en su memoria con su tipo. La pausa no las reemplaza.
5. **Responde** con una línea: la ruta creada y «ya puedes usar /clear». Sin resumen del contenido.

## Retomar

1. `search(type="session", tags=["sesion/pausa"], zone="memory")`. Si hay varias activas, muestra título y fecha y pregunta cuál; si hay una, sigue con esa. Si no hay ninguna, dilo y no inventes un estado.
2. Ábrela con `read`. Comprueba contra el repo lo que dice (rama, archivos, commits): pudo cambiar algo desde la pausa. Si algo no coincide, dilo antes de seguir.
3. Resume en pocas líneas dónde quedó y cuál es el siguiente paso, y continúa con «Falta» salvo que la persona diga otra cosa.
4. Cuando la tarea termine, archiva la pausa: `revise(note=<ruta>, action="archive")`.
