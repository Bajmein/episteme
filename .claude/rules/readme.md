---
paths:
  - README.md
  - README.en.md
  - docs/**
  - static/**
---

# README y docs/

- `README.md` lo tiene que entender alguien no técnico: frases cortas, tablas y pocos tecnicismos. Estructura: qué es (con «Cómo funciona»), instalación, uso diario, límites, documentación y licencia. Parámetros, umbrales, la lista de tools y casos límite van en `docs/`. Sin barra de navegación: GitHub ya da el índice («Outline»).
- `README.en.md` es la traducción del `README.md` y cambia en el mismo PR. Sus enlaces a `docs/` apuntan a los documentos en español, con «(in Spanish)».
- Cabecera de los dos README: bloque centrado con el banner (`static/banner-episteme.jpg`), una fila de badges de shields.io en `style=for-the-badge` (versión, Python, licencia y, en vivo sobre `main`, CI con `github/actions/workflow/status` y cobertura con `codecov/c/github`), el título, el lema y el selector de idioma. Nada de badges de tecnologías ni de plataformas.
- Cada release cambia el badge de versión (estático) y la línea «**Versión actual: vX.Y.Z.**» («**Current version: vX.Y.Z.**» en inglés): conserva su forma exacta. El badge de cobertura no se toca.
- Diagramas en `static/diagrams/`: el HTML es la fuente (plugin diagram-design, variante oscura) y lo que se incrusta es el PNG exportado a 2x. Si cambia el HTML, vuelve a exportarlo.
