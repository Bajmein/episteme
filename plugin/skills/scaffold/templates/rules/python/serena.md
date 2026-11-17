---
paths:
  - "**/*.py"
  - "**/*.pyi"
---

# Python con Serena y ty

Para el código Python de este repo, la vía preferida es el MCP de Serena, con ty como servidor de lenguaje (`.serena/project.yml`, `python_ty`). Es el mismo ty de `uv run ty check`. Si las tools `mcp__serena__*` aparecen como diferidas, cárgalas con ToolSearch antes de usarlas. Si Serena no responde o el proyecto no está activo, llama a `activate_project` con la ruta del repo.

| Para | Usa |
|---|---|
| Ver la estructura de un archivo o una carpeta (clases, funciones, constantes) | `get_symbols_overview` |
| Leer una función, una clase o un método | `find_symbol` con `include_body=true` (`name_path` como `Clase/metodo`) |
| Buscar un símbolo por nombre sin saber dónde está | `find_symbol` con `substring_matching=true` y, si hace falta, `relative_path` de una carpeta |
| Ir a la definición o a las implementaciones | `find_declaration` y `find_implementations` |
| Quién usa un símbolo (impacto antes de cambiarlo) | `find_referencing_symbols` |
| Reemplazar una función o un método entero | `replace_symbol_body` |
| Agregar código antes o después de un símbolo (imports, funciones nuevas) | `insert_before_symbol` y `insert_after_symbol` |
| Cambiar unas líneas dentro de un cuerpo | `replace_content` (literal o regex) |
| Renombrar en todo el código | `rename_symbol` |
| Borrar un símbolo comprobando que nadie lo usa | `safe_delete_symbol` |
| Errores de tipos de un archivo o un símbolo | `get_diagnostics_for_file` y `get_diagnostics_for_symbol` |
| El LSP no ve cambios hechos fuera de Serena | `restart_language_server` |

- `Read` en un `.py` solo para unas pocas líneas cuando ya tienes el panorama (con `offset` y `limit`). `Grep` y `Glob` sirven para descubrir; para seguir, usa Serena.
- `Write` para crear un `.py` nuevo está bien: `create_text_file` no está disponible en el contexto `claude-code`.
- Después de editar Python, el hook PostToolUse (`.claude/hooks/python-serena.py post`) corre `uv run --frozen ty check` y avisa si hay errores. Antes del commit, además: `{{lint}}` y `{{tests}}`.
- Lo que no es Python (Markdown, TOML, YAML, JSON) se trabaja con las tools nativas.
