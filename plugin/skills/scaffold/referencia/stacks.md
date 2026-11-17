# Detección de stack

Una sola plantilla por archivo: el stack solo decide los comandos que se rellenan y los bloques de `.gitignore`. Si hay varias señales, se suman. Si no hay ninguna, se preguntan los comandos o se deja la sección fuera; **nunca se inventa un comando**.

| Señal | Stack | Comandos que rellena | Bloque de `.gitignore` |
| --- | --- | --- | --- |
| `pyproject.toml` + `uv.lock` | `python-uv` | `uv sync`; `uv run ruff check` y `uv run pytest` si están en el grupo `dev`; `uv run ty check` si está ty | `# stack: python-uv` |
| `package.json` (gestor por lockfile: `pnpm-lock.yaml` → pnpm, `bun.lock` → bun, `package-lock.json` → npm) | `node` | `<gestor> install` y los `scripts` de `package.json` que existan (`test`, `lint`, `build`) | `# stack: node` (`.astro/` solo si hay Astro) |
| `composer.json` | `php` | `composer install` y los `scripts` de `composer.json` | `# stack: php` |
| `wp-content/` | `wordpress` | los `scripts` de `composer.json`, si lo hay | `# stack: wordpress` |
| `mise.toml` con `[tasks]` | cualquiera | tiene preferencia sobre los anteriores (`mise run <tarea>`, p. ej. `mise run check`) | — |

## Cómo se detecta

En el inventario del paso 1, desde la raíz de git:

```sh
ls pyproject.toml uv.lock package.json pnpm-lock.yaml bun.lock package-lock.json composer.json mise.toml 2>/dev/null
test -d wp-content && echo wp-content
```

- `python-uv`: lee `[dependency-groups].dev` (o `[tool.uv].dev-dependencies`) de `pyproject.toml` para saber si están `ruff`, `pytest`, `ty`, `bandit`. `requires-python` da la versión mínima (`{{requires_python}}`, `{{python_min}}` de las reglas).
- `node`: lee `scripts` de `package.json`; el comando es `<gestor> run <script>` (`npm test` para `test`).
- `mise`: `mise tasks ls` lista las tareas; si hay una `check` o `test`, se usa.

## Placeholders que salen de aquí

| Placeholder | Valor |
| --- | --- |
| `{{instalar}}` | `uv sync`, `pnpm install`, `composer install`… |
| `{{lint}}` | `uv run ruff check`, `pnpm run lint`… |
| `{{tests}}` | `uv run pytest`, `pnpm test`… |
| `{{typecheck}}` | `uv run ty check` (solo Python) |
| `{{security_check}}` | `uv run bandit -c pyproject.toml -r <paquete> -q` si bandit está en `dev`; si no, se quita la línea |
| `{{comandos_check}}` | Los comandos que corre el CI (`.github/workflows/*.yml`), uno por línea; si no hay CI, `{{lint}}` y `{{tests}}` |
| `{{checks}}` | Los mismos, en una línea con backticks: `` `uv run ruff check` y `uv run pytest` `` |
| `{{gestor}}` | `uv` (`uv sync`, `uv add`), `pnpm`… |
| `{{src_glob}}` | El paquete principal: `src/**/*.py` si hay `src/`; si no, `<paquete>/**/*.py` |
