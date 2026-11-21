---
name: sesion
description: Guarda, retoma o muestra el estado de la sesión en episteme (la nota viva de la tarea en sesiones/<proyecto>/). Úsala con /episteme:sesion, cuando pidan «guarda el estado de la sesión», «retoma donde quedé» o «¿en qué estábamos?», y cuando un aviso de episteme diga que el estado no se guarda o nombre el estado de una sesión anterior.
argument-hint: "[guardar [nota] | retomar | plantilla [tipo]]"
---

# /episteme:sesion: el estado de la sesión

Argumentos: $ARGUMENTS (en agy, lo que se escribió después del comando)

El estado de la sesión es una nota por línea de trabajo en `sesiones/<proyecto>/` del vault, que solo cambia el tool `session`. Sobrevive a `/compact` y `/clear`. Al compactar, el propio resumen escribe el estado al día y episteme lo guarda. El hook `SessionStart` lo devuelve al contexto. El agente `episteme:extractor` lo pone al día con el transcript en tres casos: tras `/clear`, tras una compactación cuyo resumen no trajo el estado y al retomar el estado de otra sesión. Una sesión nueva no lo carga: su bienvenida solo lo nombra.

Solo se usan los tools de episteme. En Claude Code, si salen como diferidos, cárgalos con `ToolSearch select:mcp__episteme__session,mcp__episteme__search,mcp__episteme__remember`. Si no aparecen ni diferidos, dilo y detente: no guardes el estado en otro sitio.

Según el primer argumento: `retomar` va a «Retomar», `plantilla` a «Plantilla» y cualquier otro caso (también sin argumentos) a «Guardar».

## Guardar

1. `session(action="template")` para tener el esqueleto, y `session(action="show")` para ver si ya hay un estado en uso.
2. **Redacta el estado entero** a partir de la conversación, para alguien que no la vio, con las secciones de la plantilla. Si había estado, conserva lo vigente y corrige lo que cambió: `body` reemplaza el cuerpo entero.
   - En «Hecho (con evidencia)», rutas, rama, commits y comandos que lo prueban.
   - En «Lo que no funcionó», cada intento fallido con el error exacto.
   - En «Siguiente paso», una sola acción concreta.
   - Si hay texto después de `guardar`, va tal cual en «Pendiente» como nota para quien retome.
   - Sin secretos (claves, tokens, contraseñas): di dónde están guardados. Las personas, por su apellido.
3. **Guarda** con `session(action="save", title=<la tarea en pocas palabras>, body=<el estado>, files=[…])`. Sin `note` se reescribe el estado en uso; si no hay, se crea uno (por eso pide `title`). Para empezar otra línea de trabajo, archiva antes el estado en uso (ver «Al terminar»).
4. Si la respuesta trae `missing_sections` o `template_hint`, completa lo que falte solo si tienes con qué; nunca inventes.
5. Lo que deba durar más que la tarea (una decisión cerrada, una lección, una corrección de la persona) va aparte, con `remember` y su tipo, y pasa `description` (una línea, hasta 160 caracteres). El estado no lo reemplaza.
6. **Responde** con una línea: la ruta y si se creó o se reescribió.

## Retomar

1. `session(action="restore")`. Si `found` es falso, dilo y no inventes un estado. Si la respuesta trae `extract` (el estado lo guardó otra sesión y quedó parte de su transcript sin leer), lanza en segundo plano el agente `episteme:extractor` con ese encargo y sigue sin esperarlo.
2. Comprueba contra el repo lo que dice (rama, archivos, commits): pudo cambiar desde que se guardó. Si algo no coincide, dilo antes de seguir.
3. Resume en pocas líneas dónde quedó y sigue por «Siguiente paso», salvo que la persona diga otra cosa.

## Plantilla

`session(action="template", type=<tipo>)`, con el tipo del segundo argumento (`session` si no hay). Muestra el esqueleto tal cual.

## Al terminar la tarea

Archiva el estado con `session(action="archive")` (o `note=<ruta>`). No se borra: queda con `status: archived` y deja de salir en `show` y `restore`. `revise` no sirve aquí: rechaza las notas de `sesiones/`.
