#!/bin/bash
# Serena's language server (python_ty): the ty pinned in the dev group of pyproject.toml, the
# same one `uv run ty check` runs. Serena passes `server` as an argument; it is ignored.
cd "$(dirname "$0")/.." && exec uv run --frozen ty server
