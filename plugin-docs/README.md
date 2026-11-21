# episteme-docs

Plugin de Claude Code con la skill `/episteme-docs:docs`, que pone al día las suites de documentación de terceros guardadas en `docs/` del vault de episteme. Depende del plugin `episteme` (se instala solo) y del servidor de episteme con al menos una zona `mode = "docs"` en `episteme.toml`: sin ella, `docs_status` y `docs_write` no existen.

```bash
claude plugin install episteme-docs@episteme
```

Excepción de escritura: el script `skills/docs/scripts/docs_check.py` corre en la máquina de la persona (el servidor no tiene HTTP) y solo escribe en `.index/docs-inbox/<suite>/`, la ruta que devuelve `docs_status`. Todo lo demás del vault cambia solo con `docs_write`. Detalle en [docs/documentacion.md](../docs/documentacion.md).
