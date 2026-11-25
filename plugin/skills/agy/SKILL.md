---
name: agy
description: Activa agy (Google Antigravity CLI) con episteme en el proyecto actual y le delega tareas en modo headless. Úsala con /episteme:agy para activarlo, con /episteme:agy <tarea>, o cuando la persona pida «pásale esto a agy» o «que lo haga agy».
argument-hint: "[tarea a delegar]"
---

# /episteme:agy: agy como agente secundario

Tarea: $ARGUMENTS

Sin tarea, ve a «Activar». Con tarea, ve a «Delegar»; si falta `<ws>/.agents/mcp_config.json` con `episteme`, dilo y ofrece «Activar» antes: no lo actives sin que la persona lo pida.

Trabaja desde la raíz del proyecto (`<ws>`). Con «Activar», agy tiene hooks de bienvenida (`SessionStart`) y de contexto por mensaje (`PreInvocation`), más la regla del plugin (`rules/AGENTS.md`, siempre activa). No hay los modos `surface` y `constraints` de `context`, extractor ni copia de planes.

## Activar

1. **Precondiciones.**
   - `agy --version` responde. Si no, indica el instalador (`curl -fsSL https://antigravity.google/cli/install.sh | bash`) y detente: no lo instales sin permiso.
   - El proyecto ya está conectado con `/episteme:setup`: `claude mcp get episteme` muestra el registro. Si no, pide correr `/episteme:setup` primero y detente. Anota su `command` y sus `args` tal cual (p. ej. `uvx --from git+https://github.com/Bajmein/episteme@<tag> episteme --project <p>`, o `git+ssh://…` si el registro usa SSH). No los inventes ni cambies el tag. Única excepción: si los `args` llevan `--directory <raíz del proyecto>` (`uv run --directory … episteme`, el servidor desde una copia local), quita `--directory` y su ruta. agy no expande variables (`${workspaceFolder}`, `${HOME}`) en `mcp_config.json` y lanza el servidor en la carpeta desde donde corre, la raíz del proyecto, donde `uv run` encuentra el `pyproject.toml` (comprobado con agy 1.5.16). Si `--directory` apunta a otra carpeta, déjalo tal cual.
2. **Plugin de agy** (es global). `agy plugin list`: si sale `episteme`, sigue. Si no, propón `agy plugin install ${CLAUDE_SKILL_DIR}/../..` (la copia del plugin que tiene Claude Code, de la misma versión) o `agy plugin install https://github.com/Bajmein/episteme`, e instálalo solo si la persona lo aprueba. `agy plugin validate` da 1 error esperado: agy salta el agente `extractor` (`model: sonnet` no es un tier de agy) y el resto carga. También sale 1 aviso esperado, `hooks/hooks.json: never loaded`: son los hooks de Claude Code, y agy solo lee `hooks.json` en la raíz del plugin. Si `agy plugin install` falla por ese error, dilo y detente, sin intentar arreglarlo.
3. **MCP del proyecto.** `agy mcp add` solo escribe en global, así que escribe a mano `<ws>/.agents/mcp_config.json`. Si existe, léelo y fusiona: conserva los demás servidores y reemplaza solo `episteme`.

   ```json
   {
     "mcpServers": {
       "episteme": {
         "command": "<command del registro>",
         "args": ["<args del registro, en el mismo orden, sin --directory si apunta a la raíz>"],
         "tools": {
           "context": { "eager": true },
           "search": { "eager": true },
           "read": { "eager": true },
           "remember": { "eager": true },
           "revise": { "eager": true }
         }
       }
     }
   }
   ```

   `eager` hace que agy muestre esos tools al modelo desde el principio; no evita el truncado de las respuestas largas.
4. **Hook del proyecto.**
   - Copia `${CLAUDE_SKILL_DIR}/../../hooks/episteme-hook.py` a `<ws>/.agents/hooks/episteme-hook.py`. Para actualizarlo, vuelve a correr «Activar»: la copia sale de la versión instalada del plugin.
   - Escribe `<ws>/.agents/hooks.json`. Si existe, léelo y fusiona: conserva los demás hooks y reemplaza solo `episteme`. La ruta es relativa porque agy corre el hook en `.agents/`.

     ```json
     {
       "episteme": {
         "SessionStart": [
           { "type": "command", "command": "uv run --quiet --script hooks/episteme-hook.py --client agy --event SessionStart", "timeout": 30 }
         ],
         "PreInvocation": [
           { "type": "command", "command": "uv run --quiet --script hooks/episteme-hook.py --client agy --event PreInvocation", "timeout": 30 }
         ]
       }
     }
     ```

   - El script lee `.agents/mcp_config.json`, lanza el servidor, llama a `context` y devuelve `injectSteps`. Ante cualquier fallo devuelve `{}` y no frena a agy.
   - Lee `~/.gemini/config/hooks.json`. Si trae un hook `episteme`, duplicaría la bienvenida y el contexto por mensaje. Propón quitar esa entrada (con un respaldo antes del archivo) y hazlo solo con la aprobación de la persona.
5. **Entrada global.** Lee `~/.gemini/config/mcp_config.json`. Si trae un servidor `episteme` (p. ej. `~/.local/bin/episteme` sin `--project`), agy usa ese e ignora el del proyecto sin avisar (comprobado con agy 1.5.16), y sin `--project` escribe en otro proyecto. La activación no queda hecha mientras siga ahí. Propón quitarlo (`agy mcp remove episteme`, con un respaldo antes del archivo) y hazlo solo con la aprobación de la persona. Si no lo aprueba, sigue con el paso 6, salta la comprobación del paso 7 y di en el informe que la activación quedó incompleta y por qué.
6. **Git.** Pregunta si añadir `.agents/` a `.git/info/exclude` (la config es de la máquina, como `.mcp.json` en `setup`). Solo con un sí.
7. **Comprobación.** `agy mcp list` no muestra el MCP de proyecto; usa una ejecución corta desde `<ws>`:

   ```bash
   agy -p 'Di qué tools del servidor MCP episteme tienes como Eager y llama a context(mode="welcome") de episteme sin pasar project; responde solo con la lista de tools Eager y el número de normas' \
     --output-format json --mode plan --settings '{"permissions":{"allow":["mcp(episteme/*)"]}}'
   ```

   Vale si la lista trae `context`, `search`, `read`, `remember` y `revise` (solo el servidor del proyecto los tiene como `eager`), `response` trae un número y el `stderr` no avisa de ningún permiso negado. Si `context` falla con `no project given`, respondió el global: vuelve al paso 5. Si no, muestra la salida y el `stderr`.

   Para los hooks, pide a la persona abrir `agy` en el proyecto: `/hooks` muestra `episteme` (de `.agents/hooks.json`) y la bienvenida llega una sola vez.
8. **Informe.** Di qué escribiste y dónde, qué propuestas quedaron sin aprobar, y muestra las reglas que la persona puede poner en el `settings.json` global de agy para no pasar `--settings` (los permisos de proyecto no se aplican en agy). No lo toques:

   ```json
   { "permissions": { "allow": ["mcp(episteme/*)"] } }
   ```

## Delegar

1. **Comando**, con Bash en segundo plano (`run_in_background`) y desde la raíz del proyecto:

   ```bash
   agy -p '<prompt>' --output-format json --mode plan --print-timeout 15m \
     --settings '{"permissions":{"allow":["mcp(episteme/*)"]}}'
   ```

   - `--mode plan` por defecto. `--mode accept-edits` solo si la persona pidió cambios en el proyecto.
   - `--model` solo si la persona lo pide.
   - Nunca `--dangerously-skip-permissions`.
2. **Prompt.** La tarea, el proyecto `<p>` y estas instrucciones:

   > Proyecto de episteme: `<p>`. Llama a `context(mode="task", task=…)` de episteme al empezar. No uses `remember` ni `revise`. Termina con tres secciones: «Resultado», «Memorias propuestas» (tipo, título y cuerpo de cada una) y «Tools de episteme usados».

3. **Lectura** del JSON: `status`, `finished_reason`, `response`, `denied_actions` y `conversation_id`.
   - Un permiso denegado no da error: la salida es 0, `status: "SUCCESS"`, y agy avisa en `stderr` qué tool negó y cómo permitirlo; `response` puede llegar vacío. Revisa siempre el `stderr` (y `denied_actions`, si viene en el JSON) y di qué se negó.
   - Una salida distinta de 0 o un `status` distinto de `SUCCESS`: informa con el `stderr` (`AGY_ERROR`).
   - Si «Tools de episteme usados» sale vacía, avisa de que agy pudo no tener acceso al vault.
4. **Seguir.** Para continuar la misma conversación, repite el comando con `--conversation <conversation_id>`.
5. **Memorias.** Revisa las «Memorias propuestas» y guarda con `remember` solo lo que valga (busca antes con `search` para no duplicar), anotando «propuesto por agy» en el cuerpo. Di cuáles guardaste y cuáles descartaste.
