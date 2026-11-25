# GEMINI.md

Guía para agy (Google Antigravity CLI) y Gemini CLI en este repo.

## Lee primero `CLAUDE.md`

Las instrucciones del repo están en `CLAUDE.md`: qué es episteme, cómo se trabaja (uv, checks, CI, release), las convenciones y las pautas al cambiar código. Valen igual para ti. Léelo entero antes de la primera tarea. Aquí solo va lo que cambia en agy: agy suma todas las reglas que encuentra, así que este archivo no repite el texto de `CLAUDE.md`.

## Lo que en agy funciona distinto

- **Reglas por archivo.** `.claude/rules/*.md` guarda los invariantes de cada módulo. Claude Code las carga solo; agy no. Antes de tocar un archivo, mira si coincide con el `paths` del frontmatter de alguna regla y, si coincide, léela entera: `tools.md` (servidor, tools, engine, errores, prompting, activity), `vault.md` (vault, índice, `__main__`), `memory.md` (`memory/`, `migrate_omega.py`), `hookmode.md` (hookmode, worktree, session, plans) y `maintenance.md` (maintenance, backup).
- **episteme.** La regla del plugin (`plugin/rules/AGENTS.md`) explica cómo usar los tools. El repo no trae hooks de episteme para agy. Si tu config no los tiene, no hay bienvenida automática: al empezar, llama tú a `context(mode="task", task="…")` y, antes de decidir algo que quizá ya se decidió, a `search` con `project="episteme"`. El vault no se lee ni se edita con `read_file`, `write_file` ni comandos.
- **Lo que es solo de Claude Code.** No te aplica lo que `CLAUDE.md` dice de subagentes, plan mode, hooks de Claude Code ni del MCP de CodeScene si no lo tienes: en ese caso basta el check de CodeScene del PR.
- **Si cambias la regla de agy.** `plugin/rules/AGENTS.md` es la que reciben los usuarios de agy: no lleva frontmatter, y se revisa cada vez que cambia un tool que nombra.
