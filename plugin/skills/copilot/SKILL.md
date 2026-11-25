---
name: copilot
description: Activa GitHub Copilot CLI con episteme en el proyecto actual (MCP, hooks de bienvenida y contexto por mensaje, y regla). Úsala con /episteme:copilot, o cuando la persona pida que Copilot CLI use episteme.
---

# /episteme:copilot: Copilot CLI con episteme

Trabaja desde la raíz del proyecto (`<proyecto>`). No toques nada fuera del proyecto sin la aprobación de la persona.

En Copilot CLI hay hooks de bienvenida (`sessionStart`) y de contexto por mensaje (`userPromptSubmitted`). No hay `surface`, `constraints`, extractor, copia de planes ni estado al compactar: Copilot no tiene hooks `mcp_tool`, ni `postCompact`, ni un `sessionStart` tras `/clear`.

## Activar

1. **Precondiciones.**
   - `copilot --version` responde. Si no, dilo y detente: no lo instales sin permiso.
   - El proyecto ya está conectado con `/episteme:setup`: `claude mcp get episteme` muestra el registro. Si no, pide correr `/episteme:setup` primero y detente. Anota su `command` y sus `args` tal cual, también `--directory` si lo lleva: Copilot lanza el servidor con esos `args`. No los inventes ni cambies el tag.
2. **MCP del proyecto.** Escribe `<proyecto>/.github/mcp.json`. Si existe, léelo y fusiona: conserva los demás servidores y reemplaza solo `episteme`. Copilot solo lo carga si la carpeta es de confianza.

   ```json
   {
     "mcpServers": {
       "episteme": {
         "type": "local",
         "command": "<command del registro>",
         "args": ["<args del registro, en el mismo orden>"],
         "tools": ["*"]
       }
     }
   }
   ```

3. **Hook.**
   - Copia `${CLAUDE_SKILL_DIR}/../../hooks/episteme-hook.py` a `<proyecto>/.github/hooks/episteme-hook.py`. Para actualizarlo, vuelve a correr esta skill: la copia sale de la versión instalada del plugin.
   - Escribe `<proyecto>/.github/hooks/episteme.json`:

     ```json
     {
       "version": 1,
       "hooks": {
         "sessionStart": [
           {
             "type": "command",
             "bash": "uv run --quiet --script \"$COPILOT_PROJECT_DIR/.github/hooks/episteme-hook.py\" --client copilot --event sessionStart",
             "timeoutSec": 30
           }
         ],
         "userPromptSubmitted": [
           {
             "type": "command",
             "bash": "uv run --quiet --script \"$COPILOT_PROJECT_DIR/.github/hooks/episteme-hook.py\" --client copilot --event userPromptSubmitted",
             "timeoutSec": 30
           }
         ]
       }
     }
     ```

   El script lee `.github/mcp.json`, lanza el servidor, llama a `context` y devuelve `additionalContext`. Ante cualquier fallo devuelve `{}` y no frena a Copilot.
4. **Regla.** Escribe `<proyecto>/.github/instructions/episteme.instructions.md` con este frontmatter y, debajo, el cuerpo de `${CLAUDE_SKILL_DIR}/../../rules/AGENTS.md` tal cual:

   ```markdown
   ---
   applyTo: "**"
   ---
   ```

5. **Git.** Pregunta si añadir a `.git/info/exclude` `.github/mcp.json`, `.github/hooks/episteme*` y `.github/instructions/episteme.instructions.md` (la config es de la máquina, como `.mcp.json` en `setup`). Solo con un sí.
6. **Aviso esperado.** Si el proyecto tiene hooks de Claude Code con `"type": "mcp_tool"` (en `.claude/settings.local.json` o `.claude/settings.json`), Copilot lee ese archivo como «repository settings» y lo descarta entero con `Invalid hook type`: Copilot no tiene `mcp_tool`. Explícalo a la persona: los hooks de Claude Code siguen igual y Copilot usa los suyos de `.github/hooks/`. No lo intentes arreglar.
7. **Comprobación.**
   - `copilot mcp list` muestra `episteme` (workspace).
   - Pide a la persona abrir `copilot` en el proyecto: `/env` lista `episteme.json` y el primer mensaje trae «episteme · welcome».
   - El primer uso de un tool pide aprobar `episteme(*)`: que elija «siempre».
8. **Plugin (opcional, global).** Para tener las skills en Copilot: `copilot plugin marketplace add Bajmein/episteme` y `copilot plugin install episteme@episteme`. Solo con la aprobación de la persona. Si Copilot avisa por `hooks/hooks.json` (son los hooks de Claude Code), anótalo en el informe sin intentar arreglarlo.
9. **Informe.** Di qué escribiste y dónde, y qué propuestas quedaron sin aprobar.
