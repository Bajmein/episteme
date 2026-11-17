---
paths:
  - "README.md"
  - "CLAUDE.md"
  - "CHANGELOG.md"
  - "docs/**"
  - ".github/**"
---

# Documentación

- La redacción y los nombres siguen `.github/ESTILO.md`: frases cortas, tildes completas, backticks para código y rutas, enlaces relativos, rutas de ejemplo neutras (`/home/ana/…`) y fechas ISO.
- `README.md` lo entiende alguien no técnico: frases cortas, tablas y tecnicismos al mínimo. Los parámetros, los umbrales y los casos límite van en `docs/`.
- `README.md` y `docs/` van en español; el código, los identificadores y los commits, en inglés.
- Un cambio que nota quien usa el proyecto se anota en `CHANGELOG.md`, en «Sin publicar», en el mismo PR. Formato Keep a Changelog; orden de secciones: Añadido, Cambiado, Obsoleto, Eliminado, Corregido, Seguridad.
- En un release, «Sin publicar» pasa a ser la versión con su fecha (la del tag) y se añade su enlace de comparación al pie; se actualizan también la versión de los ejemplos de instalación y el badge de versión, si lo hay.
- Al revisar entero `README.md` o `CLAUDE.md`, actualiza su línea `<!-- doc-review: AAAA-MM-DD <sha> -->` (fecha de hoy y `git rev-parse --short HEAD`); una corrección puntual no la toca.
- `CLAUDE.md` no copia el árbol del repo: una lista de archivos o módulos se queda vieja. Si la hay, se comprueba contra `git ls-files`.
