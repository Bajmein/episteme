# GEMINI.md

Guía para agy (Google Antigravity CLI) en este repo.

## Lee primero `CLAUDE.md`

Las instrucciones del repo están en `CLAUDE.md` y valen igual para ti: léelo entero antes de la primera tarea. Aquí solo va lo que cambia en agy, sin repetir `CLAUDE.md`, porque agy suma todas las reglas que encuentra.

## Lo que en agy funciona distinto

- **Reglas por archivo.** `.claude/rules/*.md` (`hookmode`, `maintenance`, `memory`, `tools`, `vault`) guarda los invariantes de cada módulo. Claude Code las carga solo; agy no: antes de tocar un archivo, lee las que coincidan con su `paths`.
- **episteme.** La regla del plugin (`plugin/rules/AGENTS.md`) explica cómo usar los tools. agy no tiene hooks de episteme ni bienvenida automática: al empezar, llama tú a `context(mode="task", task="…")` y, antes de decidir algo que quizá ya se decidió, a `search` con `project="episteme"`. El vault no se lee ni se edita con `read_file`, `write_file` ni comandos.
- **Solo de Claude Code.** No te aplica lo que `CLAUDE.md` dice de subagentes, plan mode, hooks, `CLAUDE.local.md` ni del MCP de CodeScene (sin él, basta el check del PR).
- **Si cambias la regla de agy.** `plugin/rules/AGENTS.md` es la que reciben los usuarios de agy: sin frontmatter, y se revisa cuando cambia un tool que nombra.
