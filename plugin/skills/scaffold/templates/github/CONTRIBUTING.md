# Contribuir a {{nombre}}

<!-- guía: un párrafo sobre cómo se reciben los PR (plazo de revisión, abrir antes un issue para un cambio grande). Si es un repo solo de uso interno, bórralo. -->
{{como_se_reciben}}

## Entorno

```sh
{{instalar}}
git config commit.template .github/.gitmessage
```

## Antes de abrir un PR

Los mismos comandos que corre el CI, todos en verde:

```sh
{{comandos_check}}
```

## Commits y ramas

- Ramas `<tipo>/<tema-en-kebab>`, por ejemplo `fix/search-empty-query`. Una rama y un PR por tema, sin mezclar.
- Commits en inglés, con [Conventional Commits](https://www.conventionalcommits.org/) y en imperativo: `feat(search): …`, `fix: …`, `docs: …`. La primera línea, de 72 caracteres o menos; el cuerpo explica el porqué. La plantilla `.github/.gitmessage` lista los tipos.
- Commits atómicos: un cambio lógico por commit, con los identificadores literales (funciones, archivos) para encontrarlo con `git log --grep` y `-S`.
- Los archivos se añaden por ruta (`git add <ruta>`), nunca con `git add -A`. Antes del push, nada fuera del stage: `git status` limpio.
- Si el commit lo hace Claude, lleva el trailer `Co-Authored-By`.

## Pull requests

- El cuerpo sigue la plantilla (`.github/pull_request_template.md`); `Closes #N` si cierra un issue.
- Se mezcla con squash: `gh pr merge --squash --delete-branch`. El título del PR es el mensaje del commit final, así que lleva el formato de Conventional Commits.

## Documentación y registro de cambios

- Un cambio que nota quien usa el proyecto se anota en `CHANGELOG.md`, en «Sin publicar», en el mismo PR.
- Release: {{release}}. «Sin publicar» pasa a ser la versión con su fecha.
- Redacción y nombres: [`ESTILO.md`](ESTILO.md).

<!-- guía: «Licencia» solo si hay LICENSE. -->
## Licencia

Las contribuciones entran bajo la licencia {{licencia}} del proyecto.
