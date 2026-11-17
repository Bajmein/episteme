# Estilo de {{nombre}}

Cómo se escribe y cómo se nombra en este repo. Las convenciones de commits, ramas y PR están en [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Redacción

- Frases cortas, una idea por frase, voz activa y en presente. Sin relleno.
- Tildes completas.
- Código, rutas y comandos en backticks; «comillas latinas» para citar mensajes o texto de la interfaz.
- Coma decimal en español (0,15).
- Tablas para comparar y listas para pasos.
- Encabezados con mayúscula solo inicial.
- Enlaces relativos dentro del repo.

## Nombres

- Archivos de `docs/` en kebab-case y sin tildes (`guia-instalacion.md`).
- Identificadores en inglés, con la convención del lenguaje.
- Tags `vX.Y.Z`; ramas como en `CONTRIBUTING.md`.

## Ejemplos

- Rutas neutras: `/home/ana/src/<proyecto>` o `${HOME}`, nunca las de la máquina de nadie.
- Fechas ISO (`2026-11-16`) en metadatos y en el CHANGELOG.

<!-- guía: «Errores» solo si el proyecto expone errores a un agente (tools, CLI). Si no, borra la sección. -->
## Errores

- Formato `<código>: <qué falló>. <qué hacer>`, por ejemplo: `not_found: note "x" does not exist. Check the name with search.`
