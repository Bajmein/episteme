---
paths:
  - "**/*.py"
  - "**/*.pyi"
---

# Estilo de Python en {{proyecto}}

Regla local de desarrollo (módulo `reglas-python` de `/episteme:scaffold`). Si choca con una regla de `.claude/rules/` versionada o con `CLAUDE.md`, mandan esas.

## Versión del lenguaje

El paquete pide `{{requires_python}}` (`requires-python` de `pyproject.toml`). Todo lo que entra tiene que correr en la versión mínima: ruff (`target-version`) y ty (`python-version`) revisan contra ella, pero un nombre nuevo de la biblioteca estándar no siempre lo detectan.

- Nada de `return`, `break` ni `continue` dentro de un `finally` (PEP 765).
- `encoding="utf-8"` siempre en las lecturas y `newline=""` en las escrituras: en Windows el valor por defecto no es UTF-8.
- Para comprobar algo en la versión mínima: `uv run --python {{python_min}} --no-project python archivo.py`.

## Herramientas

- Lint: `{{lint}}`. Si el repo no está formateado con `ruff format`, no lo corras: tocaría archivos enteros. Sigue el formato del archivo que editas.
- Tipos: `{{typecheck}}`.
- Si borras código o tocas dependencias, corre también los analizadores de código muerto y de dependencias del proyecto, si los tiene.

## Tipos y datos

- Anotaciones en todas las firmas, también el retorno. `Any` solo para datos que llegan de fuera (JSON, YAML).
- Valores que se pasan entre funciones: `@dataclass(frozen=True)` o `NamedTuple`. No cambies los argumentos que recibes (listas, dicts): devuelve uno nuevo.
- El estado que cambia es explícito y está acotado: un `@dataclass` mutable con dueño claro o un dict de módulo con tope y comentario. No añadas estado global sin tope.
- `Protocol` solo cuando haya dos implementaciones reales (o una real y un doble en los tests).
- Recursos (archivos, conexiones, bloqueos) con `with`. Generadores para recorrer colecciones grandes.

## Nombres

- `snake_case` en funciones y variables, `PascalCase` en clases, `UPPER_SNAKE_CASE` en constantes de módulo, `_prefijo` en lo privado del módulo.
- Los booleanos se leen como una afirmación (`created`, `truncated`, `is_…`, `has_…`).
- Umbrales, topes y plazos van en constantes con nombre al inicio del módulo, nunca sueltos en el código. Si cambia uno, cambia también su mención en `docs/`.

## Errores y salida

- Se valida en el borde (argumentos, archivos de config, rutas) y se falla pronto. Dentro, las funciones confían en lo ya validado.
- Los mensajes de error dicen qué falló y qué hacer.
- Un `except Exception: pass` solo donde fallar rompería algo peor (un hook, un registro) y siempre con `# nosec B110` y el motivo. En el resto, deja subir el error.

## Tamaño y forma

- Funciones cortas (hasta unas 50 líneas) y retornos anticipados en vez de anidar más de 3 o 4 niveles.
- Módulos de 200 a 400 líneas, con 800 como techo.
- KISS, DRY y YAGNI: la solución más simple que funcione; extrae cuando la repetición ya existe, no por si acaso.
- Docstrings en inglés, de una línea salvo que haya un contrato que explicar.
- Rutas con `pathlib` u `os.path`, nunca comparando contra `"/"`.

## Antes de dar algo por terminado

- [ ] `{{lint}}` y `{{tests}}` en verde; `{{typecheck}}` si tocaste tipos.
- [ ] Corre en la versión mínima de `requires-python`.
- [ ] Sin números sueltos ni argumentos mutados.
- [ ] Docstring, `docs/` y `CHANGELOG.md` al día si cambió algo que se nota desde fuera.
