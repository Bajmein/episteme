<!-- doc-review: {{fecha}} {{sha}} -->
<div align="center">

# {{nombre}}

**{{frase}}**

<!-- guía: badges solo de lo que el repo tiene. CI: el badge nativo de GitHub (https://github.com/<dueño>/<repo>/actions/workflows/<archivo>.yml/badge.svg) si hay workflows. Versión: solo si hay tags, con el último. Si no hay ninguno, borra esta línea. -->
{{badges}}

<!-- guía: barra de navegación solo si hay más de 4 secciones; si no, bórrala. -->
[Qué es](#qué-es) · [Instalación](#instalación) · [Uso](#uso) · [Documentación](#documentación) · [Desarrollo](#desarrollo)

</div>

## Qué es

<!-- guía: un párrafo para alguien no técnico: qué es y para quién. Sin parámetros, umbrales ni casos límite: eso va a docs/. -->
{{que_es}}

| Qué hace por ti | Cómo |
| :-- | :-- |
| {{beneficio}} | {{como}} |

<!-- guía: «Cómo funciona» es opcional: 3 pasos numerados. Bórrala si no aporta. -->
## Cómo funciona

1. {{paso_1}}
2. {{paso_2}}
3. {{paso_3}}

## Instalación

<!-- guía: la versión y el tag de los ejemplos son los del último tag. -->
{{instalacion}}

## Uso

{{uso}}

<!-- guía: «Límites» es opcional: lo que no hace, en frases cortas. -->
## Límites

- {{limite}}

<!-- guía: «Documentación» solo si existe docs/: una fila por documento, con enlace relativo. -->
## Documentación

| Documento | Para qué |
| :-- | :-- |
| [{{doc}}](docs/{{doc_archivo}}) | {{doc_para_que}} |

## Desarrollo

<!-- guía: los tres comandos detectados (referencia/stacks.md); nunca uno inventado. -->
```sh
{{instalar}}
{{lint}}
{{tests}}
```

Las convenciones de commits, ramas y PR están en [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).

<!-- guía: «Licencia» solo si hay LICENSE. -->
## Licencia

[{{licencia}}](LICENSE)
