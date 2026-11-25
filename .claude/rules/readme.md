---
paths:
  - README.md
  - README.en.md
  - docs/**
  - static/**
---

# README y docs/

- `README.md` lo tiene que entender alguien no técnico: frases cortas, tablas y pocos tecnicismos. Estructura: qué es, cómo funciona, instalación, uso diario, herramientas, límites y documentación. Parámetros, umbrales y casos límite van en `docs/`.
- `README.en.md` es la traducción del `README.md` y cambia en el mismo PR. Sus enlaces a `docs/` apuntan a los documentos en español, con «(in Spanish)».
- Cabecera de los dos README: bloque centrado con el banner (`static/banner-episteme.jpg`) y tres filas de badges de shields.io en `style=for-the-badge`:
  1. Tecnologías (estáticos, con CodeScene).
  2. Plataformas.
  3. Estado en vivo de la rama `main`: CI (`github/actions/workflow/status`) y cobertura de Codecov (`codecov/c/github`).
- Cada release cambia el badge de versión (estático) y la línea «**Versión actual: vX.Y.Z.**» («**Current version: vX.Y.Z.**» en inglés): conserva su forma exacta. El badge de cobertura no se toca.
- Diagramas en `static/diagrams/`: el HTML es la fuente (plugin diagram-design, variante oscura) y lo que se incrusta es el PNG exportado a 2x. Si cambia el HTML, vuelve a exportarlo.
