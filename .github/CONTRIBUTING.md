# Contribuir a episteme

episteme es un proyecto personal. Los PR se agradecen, pero no hay compromiso de plazo de revisión. Para un cambio grande, abre antes un issue y lo hablamos.

## Entorno

Hace falta [uv](https://docs.astral.sh/uv/). El paquete pide Python 3.14 o superior; el repo se desarrolla con 3.15 (`.python-version`).

```sh
uv sync
git config commit.template .github/.gitmessage
```

## Antes de abrir un PR

Los mismos comandos que corre el CI, todos en verde:

```sh
uv run ruff check
uv run ty check
uv run pytest
uv run bandit -c pyproject.toml -r src scripts plugin plugin-docs -q
uv run vulture
uv run deptry .
uv run zizmor .github/workflows
```

CodeScene revisa además cada PR. El check de CodeScene del PR (quality gate «The Bare Minimum») tiene que pasar. La meta es 9 o más por archivo de `src/` y `scripts/`; un archivo nuevo o tocado no baja de 9 ni baja su code health. `@CodeScene(disable:"<regla>")` solo con una línea que diga por qué.

## Commits y ramas

- Commits en inglés, con [Conventional Commits](https://www.conventionalcommits.org/): `feat(search): …`, `fix(memory): …`, `docs: …`. La plantilla `.github/.gitmessage` lista los tipos y los alcances en uso.
- Ramas con la forma `tipo/descripcion`, por ejemplo `fix/search-empty-query`.
- Un PR por cambio, sin mezclar temas.

## Tests

- `tests/fixtures/vault/` no se modifica: los tests lo copian a `tmp_path` antes de escribir.
- Rutas con `pathlib` u `os.path`, nunca comparando contra `"/"` fijo (el CI corre también en Windows).
- Lecturas con `encoding="utf-8"` y escrituras con `newline=""`.
- Un test que solo tiene sentido en POSIX lleva `skipif(sys.platform == "win32", reason=…)`.

## Documentación y registro de cambios

- Un cambio que note quien usa episteme (tools, hooks, skills, scripts, instalación) se anota en `CHANGELOG.md`, en «Sin publicar».
- Si cambia un tool, revisa también `README.md`, `docs/`, los `SKILL.md` de los dos plugins (`plugin/` y `plugin-docs/`), el agente (`plugin/agents/extractor.md`) y `plugin/rules/AGENTS.md`. Si cambian los hooks o los permisos, también `plugin/skills/setup/settings.json`.
- `README.md` y `docs/` van en español; el código, los docstrings y los commits, en inglés.

## Licencia

Las contribuciones entran bajo la licencia MIT del proyecto.
