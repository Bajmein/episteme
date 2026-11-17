---
paths:
  - "tests/**/*.py"
  - "{{src_glob}}"
---

# Pruebas en {{proyecto}}

Regla local de desarrollo (módulo `reglas-python` de `/episteme:scaffold`). Si choca con una regla de `.claude/rules/` versionada o con `CLAUDE.md`, mandan esas.

## Flujo: la prueba primero

1. Escribe la prueba del comportamiento nuevo o del bug y córrela: tiene que **fallar** por el motivo esperado.
2. Implementa lo mínimo para que pase.
3. Refactoriza con la prueba en verde.
4. Al final, la suite completa: `{{tests}}`.

Si una prueba falla, se corrige el código, no la prueba, salvo que la prueba esté mal; en ese caso, di por qué.

## Cómo correrlas

- Mientras trabajas, corre solo lo tuyo: `{{tests}} tests/test_x.py -q` o `-k nombre`.
- Framework: pytest.
- Para mirar la cobertura de un módulo sin tocar `pyproject.toml`: `uv run --with pytest-cov pytest --cov=<paquete> --cov-report=term-missing tests/test_x.py`.

## Reglas

- Los fixtures de datos no se modifican: el test que escribe los copia a `tmp_path`.
- Cada test se vale solo: sin orden entre tests ni estado compartido. El estado de módulo se limpia con `monkeypatch`.
- La fecha y la hora se fijan; nunca se depende de la fecha real.
- Nombre: `test_<qué hace>_<cuándo>` en inglés, que se entienda sin abrir el test.
- Estructura preparar, actuar y comprobar, separada por líneas en blanco, sin comentarios `# Arrange`.
- Varios casos del mismo comportamiento: `@pytest.mark.parametrize`.
- Dobles (`SimpleNamespace`, clases `Fake…`) solo para lo que no se puede usar de verdad.
- Portabilidad: lo que solo vale en POSIX lleva `skipif(sys.platform == "win32", reason=…)`. Los subprocesos heredan `os.environ`.
- Un bug corregido deja su test de regresión.
