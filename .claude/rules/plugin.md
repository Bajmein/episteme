---
paths:
  - plugin/**
  - plugin-docs/**
  - .claude-plugin/**
  - src/episteme/docs/hashing.py
---

# Plugins

- El repo es un marketplace (`.claude-plugin/marketplace.json`) con dos plugins: `episteme` (`plugin/`) y `episteme-docs` (`plugin-docs/`, opcional, depende de `episteme`). Ninguno trae el servidor. Instalación: «Los plugins» en `docs/instalacion.md`.
- Skills de `plugin/skills/`: `sesion`, `mantencion`, `reminder`, `scaffold`, `agy` y `setup`. Solo `setup` (`/episteme:setup`) conecta un proyecto: registro con `claude mcp add`, permisos, hooks y regla del `CLAUDE.md`, en Linux, macOS y Windows. Si cambian la instalación, los hooks, los permisos o los tools, actualiza a la vez `README.md`, su documento de `docs/`, el `SKILL.md` de `setup` y su `settings.json`.
- `reminder`, `mantencion` y `sesion` sirven igual en Claude Code y en agy: la carga con `ToolSearch` va precedida de «En Claude Code».
- Si cambia un tool que nombran (`context`, `read`, `remember`, `revise`, `review`, `search`, `session`, `docs`), revisa los `SKILL.md` (también `plugin-docs/skills/docs/SKILL.md`), el agente y `plugin/rules/AGENTS.md`.
- El agente `plugin/agents/extractor.md` pone al día el estado de la sesión con el transcript tras `/clear`, tras un `/compact` sin bloque de estado y al retomar. Su script, `plugin/skills/sesion/scripts/transcript_digest.py`, lee el transcript en la máquina de la persona: el servidor no lee fuera del vault ni lanza procesos.
- Hooks `command` de `plugin/hooks/`:
  - `SessionStart` (`clear`): `extract-wake.py` despierta al modelo para lanzar el extractor.
  - `PreToolUse` (`Bash`): `digest-allow.py` aprueba solo el comando exacto del script del extractor. Es el único hook de episteme que devuelve `permissionDecision`: siempre `allow`, nunca `deny`.
- agy lee el plugin: el manifiesto en `plugin/.antigravity-plugin/`, la regla siempre activa `plugin/rules/AGENTS.md` (sin frontmatter) y las skills.
- `plugin-docs/skills/docs/scripts/docs_check.py` es de la skill `/episteme-docs:docs`, no del servidor: descarga las páginas en la máquina de la persona (el servidor no tiene HTTP). Su `body_hash` es copia del de `src/episteme/docs/hashing.py`: si cambia uno, cambia el otro.
- La `version` de los tres `plugin.json` es la de `pyproject.toml` (`tests/test_plugin.py`): sin ese cambio, las skills no se actualizan.
