Si los tools de episteme no están disponibles en este workspace, ignora esta regla.

# episteme: memoria y documentación del proyecto

episteme es el vault de memoria y documentación del proyecto. Úsalo solo con sus tools.

- Al empezar una tarea, llama a `context(mode="task", task="<lo que vas a hacer>")`.
- Antes de decidir algo que quizá ya se decidió, usa `search` y lee los mejores resultados con `read(notes=[…])`.
- Pide lecturas acotadas: `read` con `heading` o `lines` y pocas notas por llamada. Una respuesta de más de ~10 KB llega truncada.
- Guarda con `remember` cuando se cierra una decisión o aprendes una lección. Si una memoria está mal o quedó reemplazada, corrígela con `revise`; nunca guardes una memoria que la contradiga. Al guardar, añade `description` (una línea) y `link=true` para que quede enlazada.
- Para seguir el grafo de enlaces de una nota, `read(note="…", links="out"|"in"|"both")`.
- Guarda el estado de la sesión con `session(action="save")`, siguiendo `session(action="template")`, al acordar un plan, al cerrar una fase y cuando te lo pidan.
- No leas ni edites el vault con `read_file`, `write_file` ni comandos.
- Si los tools de episteme no aparecen cuando los necesitas, dilo antes de seguir.
