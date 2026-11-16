---
title: Referencia de hooks
description: Nota sintética del vault de prueba sobre «Referencia de hooks».
summary: Referencia completa de eventos, argumentos, formatos JSON y variables de entorno para hooks.
aliases:
- Referencia de hooks
tags:
- claude-code/automation
- hooks
type: reference
category: automation
status: stable
lang: en
created: 2026-10-18
updated: 2026-10-18
up: '[[README.index]]'
related:
- '[[settings-reference]]'
- '[[tools-reference]]'
- '[[sub-agents]]'
- '[[agent-teams]]'
- '[[env-vars]]'
- '[[model-config]]'
---
# Referencia de hooks

> Synthetic reference for the lifecycle events of a coding agent. The text is written for the episteme test vault.

See [[hooks-guide|the hooks guide]] for a short walkthrough.

## Hook lifecycle

A hook is a command that runs when an event fires. The agent sends a JSON document on stdin and reads the exit code and an optional JSON answer back.

## Hook events

### SessionStart

Fires when a session begins. The input carries the session id and the working directory.

### UserPromptSubmit

Fires when the user sends a prompt, before the agent reads it.

### PreToolUse

Fires before a tool call runs. A hook for **PreToolUse** can allow, deny or ask. The decision is read from the exit code or from the JSON output.

#### PreToolUse input

The input has the tool name and the tool arguments. A matcher selects which tools the hook sees.

#### PreToolUse output

A deny decision carries a reason that the agent reads and acts on.

### PermissionRequest

Fires when a tool call needs a permission decision. It is a separate event from the one above and has its own output format.

### PostToolUse

Fires after a tool call finishes. The input adds the tool result.

## Exit codes

| Code | Meaning |
| :- | :- |
| 0 | Success; the standard output is read as JSON when it parses |
| 2 | Blocking error; the standard error goes back to the agent |
| other | Non-blocking error; the first line is shown to the user |

## Configuración

Los hooks se declaran en el archivo de configuración, dentro de la clave `hooks`, con un matcher y la lista de comandos.

## Example: a guard hook

A guard hook can inspect a shell command and block it when it runs `cd` outside the project. The hook prints a short reason and exits with code 2.

%% nav:start %%

---

## Navegación

- **Índice:** [[README.index|Índice de documentación]] › [[README.index#4. Automatización Hooks, Rutinas y Canales|4. Automatización: Hooks, Rutinas y Canales]]
- **Anterior / siguiente:** ← [[hooks-guide|Guía rápida de hooks]] · [[routines|Routines, trabajo que corre solo]] →
- **Relacionadas:** [[settings-reference|Referencia de settings]] · [[tools-reference|Referencia de tools]] · [[sub-agents|Subagents propios]] · [[agent-teams|Equipos de sesiones coordinadas]] · [[env-vars|Variables de entorno]] · [[model-config|Elegir y configurar el modelo]]

%% nav:end %%
