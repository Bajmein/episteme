---
title: Índice del vault de prueba
description: Mapa de contenido (MOC) de la bóveda: qué nota consultar según el objetivo y la categoría.
aliases:
  - Índice
  - MOC
  - Mapa de contenido
tags:
  - claude-code/index
  - moc
type: index
status: stable
lang: es
created: 2026-10-18
updated: 2026-10-18
---
# Índice del vault de prueba

> **Guía de lectura rápida:** Este archivo sirve como mapa de navegación del repositorio. Consulta esta tabla o sus categorías temáticas para saber exactamente qué documento revisar según tus necesidades u objetivos.

---

## 🗺️ Mapa Rápido por Objetivos

| ¿Qué buscas hacer o entender? | Archivos recomendados |
| :--- | :--- |
| **Primeros pasos y mejores prácticas generales** | [[docs/claude-code/best-practices\|best-practices]], [[goal]], [[checkpointing]] |
| **Crear y optimizar Skills (`SKILL.md`)** | [[skills]], [[agent-skills-best-practices]], [[docs/claude-code/agent-skill-open-standard-doc-reference/quickstart|quickstart]], [[docs/claude-code/agent-skill-open-standard-doc-reference/best-practices|open-standard/best-practices]], [[optimizing-descriptions]], [[evaluating-skills]], [[using-scripts]], [[skill-md\|others/skill-md]] |
| **Diseñar tu `CLAUDE.md` de proyecto** | [[reglas-base\|others/reglas-base]], [[reglas-comunidad\|others/reglas-comunidad]], [[claudemd-guia-breve\|others/claudemd-guia-breve]] |
| **Paralelismo, Subagentes y Workflows** | [[sub-agents]], [[agents]], [[agent-teams]], [[workflows]], [[worktrees]] |
| **Automatización (Hooks, Rutinas, Tareas)** | [[hooks-guide]], [[hooks-reference]], [[routines]], [[scheduled-tasks]] |
| **Comandos, CLI y Configuración** | [[cli-reference]], [[commands]], [[settings-reference]], [[env-vars]] |
| **Costos, Tokens y Contexto** | [[context-window]], [[prompt-caching]], [[costs]], [[monitoring-usage]] |
| **Web legible por LLMs (`llms.txt`)** | [[llms-txt\|others/llms-txt]] |

---

## 📂 Directorio Raíz (`/`)

### 1. Flujo de Trabajo y Mejores Prácticas
* [[docs/claude-code/best-practices|best-practices]]: Filosofía central de trabajo con Claude Code como agente interactivo (no un chatbot pasivo), ciclos iterativos y verificación.
* [[goal]]: Cómo mantener a Claude trabajando de forma autónoma hacia una meta definida sin interrupciones mediante el comando `/goal`.
* [[checkpointing]]: Historial automático de modificaciones en archivos para auditar o deshacer cambios de forma segura (`/rewind`).
* [[worktrees]]: Uso de `git worktree` para ejecutar sesiones de Claude concurrentes en ramas aisladas sin conflictos de código.

### 2. Agentes, Subagentes y Concurrencia
* [[agents]]: Comparativa de los 5 métodos de paralelización en Claude Code (subagentes, sesiones paralelas, worktrees, etc.).
* [[sub-agents]]: Definición, configuración (`agent.json`) y despliegue de subagentes especializados para tareas concretas.
* [[agent-teams]]: Orquestación de múltiples sesiones coordinadas de Claude trabajando como equipo en un mismo proyecto.
* [[workflows]]: Construcción de flujos de trabajo dinámicos y escalables para orquestar subagentes mediante código.
* [[cross-session-messaging]]: Comunicación e intercambio de mensajes entre distintas sesiones activas de Claude Code.

### 3. Habilidades de Agente (*Skills*)
* [[skills]]: Introducción a la extensión de Claude mediante archivos `SKILL.md` (descubrimiento, activación y uso de herramientas).
* [[agent-skills-best-practices]]: Directrices de ejemplo para redactar skills robustas, concisas y efectivas.

### 4. Automatización: Hooks, Rutinas y Canales
* [[hooks-guide]]: Guía práctica para ejecutar comandos de shell automáticos antes o después de llamadas a herramientas o eventos del ciclo de vida.
* [[hooks-reference]]: Referencia completa de eventos, argumentos, formatos JSON y variables de entorno para hooks.
* [[routines]]: Configuración de rutinas reutilizables para automatizar tareas repetitivas en el entorno de desarrollo.
* [[scheduled-tasks]]: Ejecución periódica y desatendida de prompts a intervalos definidos (cron-like polling).
* [[channels]]: Inyección de eventos y flujos de datos externos en tiempo real directamente en una sesión en marcha.

### 5. CLI, Comandos y Configuración
* [[cli-reference]]: Guía de comandos del binario `claude` (flags para tuberías stdin, reanudación de sesiones, modo no interactivo).
* [[commands]]: Catálogo de slash commands internos ejecutables dentro de una sesión interactiva (`/model`, `/cost`, `/review`, etc.).
* [[settings-reference]]: Diccionario exhaustivo de claves y valores para los archivos `settings.json`.
* [[settings-example]]: Plantillas comentadas de `settings.json` para niveles de usuario, proyecto y local.
* [[env-vars]]: Variables de entorno que alteran el comportamiento del motor (modelos, límites de tokens, telemetría).
* [[model-config]]: Selección y ajuste de modelos (Claude 3.7 Sonnet, Haiku, Opus, reasoning/thinking budgets).
* [[claude-directory]]: Estructura y propósito de la carpeta oculta `.claude/` (reglas, memoria persistente, logs, cache).

### 6. Contexto, Eficiencia y Monitoreo
* [[context-window]]: Dinámica de la ventana de contexto, compactación de historial y prevención de saturación.
* [[prompt-caching]]: Explicación técnica de cómo el caché de prompts ahorra tiempo de latencia y hasta un 90% en costos de tokens.
* [[costs]]: Modelos de tarificación, consumo por herramienta y estrategias para optimizar el gasto de API.
* [[monitoring-usage]]: Telemetría, trazabilidad de actividad y exportación de métricas de uso a nivel individual o de equipo.

### 7. Herramientas, Entorno y Personalización
* [[tools-reference]]: Especificación de las herramientas integradas que usa Claude (FileEdit, RunBash, Grep, ViewFile, etc.).
* [[statusline]]: Cómo personalizar la barra de estado inferior en la terminal mediante scripts shell propios.
* [[output-styles]]: Ajuste del tono, formato y estilo de respuesta del agente (roles técnicos, concisión, verbosidad).
* [[cloud-environments]]: Configuración de Claude Code en Docker, contenedores de desarrollo y máquinas virtuales remotas.
* [[claude-code-in-the-web]]: Uso de Claude Code en entornos web hospedados en la nube.

---

## 📁 Subdirectorio: `agent-skill-open-standard-doc-reference/`
Documentación de referencia del estándar abierto de skills:

* [[quickstart]]: Tutorial introductorio paso a paso para crear tu primera skill funcional con scripts.
* [[docs/claude-code/agent-skill-open-standard-doc-reference/best-practices|best-practices]]: Principios de diseño para creadores de skills (evitar alucinaciones y sobredependencia de prompts extensos).
* [[optimizing-descriptions]]: Cómo afinar el campo `description` en YAML para asegurar que el agente la invoque en el momento correcto.
* [[evaluating-skills]]: Métodos para probar y validar sistemáticamente la calidad y consistencia de una skill.
* [[using-scripts]]: Cómo incluir y ejecutar scripts ejecutables (`scripts/`) dentro de una skill para evitar reescribir código en el contexto.

---

## 📁 Subdirectorio: `others/`
Reglas de oro, especificaciones estándar y guías de la comunidad externa:

* [[claudemd-guia-breve]]: Guías de comportamiento de un autor de ejemplo para mitigar fallos frecuentes en código asistido por LLMs (pensamiento previo, simplicidad, modificaciones quirúrgicas).
* [[reglas-base]]: Recomendaciones de ejemplo para redactar archivos `CLAUDE.md` concisos y orientados a comandos.
* [[reglas-comunidad]]: Reglas de oro recopiladas de la comunidad (límites de líneas, reglas negativas > positivas, documentar errores pasados).
* [[skill-buenas-practicas]]: Compendio de mejores prácticas de ejemplo (divulgación progresiva, bucles de validación, seguridad y mínimo privilegio).
* [[skill-md]]: Especificación técnica completa del estándar `SKILL.md` (esquema YAML, modelo de carga en 3 fases, comparativa con `AGENTS.md` y `.cursorrules`).
* [[llms-txt]]: Especificación técnica de `llms.txt` para estructurar sitios web y documentación para el consumo eficiente de modelos de IA.
* [[guia-larga]]: Guía avanzada de ejemplo: economía de tokens, persistencia de memoria, bucles de verificación, paralelización con worktrees y orquestación de subagentes.
