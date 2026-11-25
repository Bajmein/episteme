<div align="center">

![episteme: Agentic Memory & Knowledge Vault. Persistent Knowledge Engine for AI Workflows.](static/banner-episteme.jpg)

<a href="https://github.com/Bajmein/episteme/tags"><img alt="Version" src="https://img.shields.io/badge/version-v0.23.0-8B5CF6?style=for-the-badge"></a>
<a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.14+-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54"></a>
<a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-yellow?style=for-the-badge"></a>
<a href="https://github.com/Bajmein/episteme/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Bajmein/episteme/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI"></a>
<a href="https://codecov.io/gh/Bajmein/episteme"><img alt="Coverage" src="https://img.shields.io/codecov/c/github/Bajmein/episteme/main?style=for-the-badge&logo=codecov&logoColor=white&label=coverage"></a>

# episteme

**One curated project memory for all your agents.**

<a href="README.md">Español</a> · <b>English</b>

</div>

---

> [!NOTE]
> This is the English translation of the [README in Spanish](README.md). The documents in `docs/` are in Spanish.

## What it is

An AI agent is like a brilliant colleague who arrives every morning remembering nothing about yesterday. **episteme gives it a memory that lasts**: a folder of Markdown notes (the *vault*) with the decisions, lessons and documentation of your projects. Claude Code, agy (Google Antigravity, with Gemini) and GitHub Copilot CLI share the same memories.

| | What it does for you |
| :-- | :-- |
| **Remembers** | Decisions, lessons, errors and preferences, by project |
| **Finds** | Searches the whole vault, ignoring case and accents |
| **Warns in time** | Shows a file's rules before it is edited |
| **Picks up** | Brings back what you were doing after compacting or `/clear` |
| **Saves your plans** | Copies every plan you approve |
| **Keeps things tidy** | Detects duplicates and expired memories; refuses passwords |

**Your notes are your own Markdown files and never leave your machine** (open them with [Obsidian](https://obsidian.md/) or any editor). It only uses the network to install and with `/episteme-docs:docs`, if you use it.

> [!NOTE]
> **Current version: v0.23.0.** Works on Linux, macOS and Windows. What is new, in the [CHANGELOG](CHANGELOG.md) (in Spanish).

### How it works

<p align="center">
  <img src="static/diagrams/arquitectura.png" alt="Claude Code (the agent and its hooks) and, if you enable them, agy and Copilot CLI call the episteme server, which reads and writes the vault's Markdown notes (memories, documentation, sessions and plans) and keeps a search index; Obsidian can open the same vault. The text inside the diagram is in Spanish." width="880">
</p>

episteme is a small program that runs on your machine and is the only door to the vault: it validates what is saved and indexes it for fast search. Agents use it through its tools; in Claude Code, *hooks* also call it automatically at fixed moments, and in agy and Copilot CLI at start and on each message.

| | Claude Code | agy | Copilot CLI | Other MCP client |
| :-- | :-: | :-: | :-: | :-: |
| Tools (search, read, save) | Yes | Yes | Yes | Yes |
| Automations (hooks) | Yes | Partial: welcome and per-message context | Partial: welcome and per-message context | No |

<details>
<summary><b>Quick glossary</b></summary>

| Term | What it means |
| :-- | :-- |
| **Vault** | The folder with all the notes: memories, documentation, sessions and plans |
| **Memory** | A short note with something worth remembering |
| **Tool** | An action Claude asks episteme for: search, read, save |
| **Hook** | An automation of the agent (Claude Code, agy or Copilot CLI) that calls a tool without anyone asking |
| **MCP** | The protocol agents use to connect to programs like episteme |

</details>

## Installation

**You need** [uv](https://docs.astral.sh/uv/) and git. uv gets Python if it is missing.

### Option A · With the skill (recommended)

Once per machine (and per Claude Code account), the same on Linux, macOS and Windows ([more details](docs/instalacion.md#los-plugins), in Spanish):

```bash
claude plugin marketplace add Bajmein/episteme
claude plugin install episteme@episteme
```

Then, in each project:

1. Restart Claude Code and open it at the project root.
2. Type `/episteme:setup`.
3. Approve the changes: it registers the server, sets up hooks and permissions, and adds the rule to `CLAUDE.md`.

> [!TIP]
> `claude mcp list` should show `episteme` connected. The first time takes a while, because it downloads. To update, repeat the registration with the new tag.

<details>
<summary><b>Option B · By hand (without the skill)</b></summary>

A single command registers the server. Replace `<project>` with your project's name.

**Linux and macOS**

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+https://github.com/Bajmein/episteme@v0.23.0 episteme --project <project>
```

**Windows** (PowerShell, on a single line)

```powershell
claude mcp add --scope local episteme -- uvx --from git+https://github.com/Bajmein/episteme@v0.23.0 episteme --project <project>
```

The hooks, the permissions and the `CLAUDE.md` rule are still missing: they are in the [installation guide](docs/instalacion.md#después-de-registrar) (in Spanish).

</details>

## Daily use

There are no commands to learn: you use it by talking to Claude.

<p align="center">
  <img src="static/diagrams/ciclo-memoria.png" alt="Life cycle of a memory in episteme, around the vault: save with remember, find with search and read, warn in time with context, correct with revise and tidy up with /episteme:mantencion. The text inside the diagram is in Spanish." width="720">
</p>

| You | episteme |
| :-- | :-- |
| Start a session | Delivers the rules, the reminders and the key memories |
| Write a message | Suggests the memories that are relevant |
| Say «remember that…» | Saves a memory, unless an almost identical one exists |
| Ask «what did we decide about…?» | Claude searches the vault before answering |
| Claude is about to edit a file | Shows it that file's rules |
| Approve a plan | Saves a copy and says where it is after clearing the context |
| Compact or use `/clear` | Recovers the work state |

For some tasks there are shortcuts:

| Shortcut | What for |
| :-- | :-- |
| `/episteme:sesion` | Save where you are (`guardar`) and pick it up (`retomar`) |
| `/episteme:mantencion` | Review duplicates, contradictions and expired memories with you |
| `/episteme:reminder <text>` | Leave a reminder for each session |
| `/episteme:scaffold` | Create or review `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `.github/`, the rules and `.gitignore` |
| `/episteme:agy [task]` | Enable agy and hand it tasks |
| `/episteme:copilot` | Enable Copilot CLI in the project |
| `/episteme-docs:docs [suite]` | Update the third-party documentation (separate plugin: `claude plugin install episteme-docs@episteme`) |

The skills also load in agy. `/episteme:agy` and `/episteme:copilot` leave welcome and per-message context hooks in the project, without the other automations ([agy](docs/instalacion.md#agy-opcional), [Copilot CLI](docs/instalacion.md#copilot-cli-opcional), in Spanish).

Under the hood, Claude uses 9 tools: search, read, save, correct, review and others. Each memory has a type (decision, rule, lesson…) and a priority from 1 to 5; priority-5 memories are the rules Claude sees at the start. Detail in [Tools and memories](docs/tools.md#memorias) (in Spanish).

<details>
<summary><b>What the hooks do in each session</b></summary>

<p align="center">
  <img src="static/diagrams/hooks-sesion.png" alt="Sequence of the day-to-day: with each message, before and after using a file and when approving a plan, a Claude Code hook calls an episteme tool, which answers with the welcome, memories or rules, or saves a copy of the plan in the vault. The text inside the diagram is in Spanish." width="880">
</p>

Hooks never block Claude or decide for it: they only bring it context. Configuration in [Hooks](docs/hooks.md) (in Spanish).

<p align="center">
  <img src="static/diagrams/compactar-clear.png" alt="Sequence showing how the work state survives /compact and /clear: when compacting, the summary writes the state up to date and episteme saves it; it brings it back with the welcome when starting again, and after /clear the extractor agent updates it in the background. The text inside the diagram is in Spanish." width="880">
</p>

When compacting, episteme saves the work state; in a new session you pick it up with `/episteme:sesion retomar`. Detail in [Session state](docs/sesion.md) (in Spanish).

</details>

## Limits

- **It searches by words, not by meaning.** «marketing» does not find «mkt»: that is why each memory carries `keywords` with synonyms. With bge-m3 and 147 real queries, only 3 found anything new ([measurement](docs/desarrollo.md#medir-si-los-embeddings-aportan), in Spanish).
- **It warns, it does not force.** The rules arrive in time, but Claude can ignore them.
- **It does not tidy itself.** Merging and resolving contradictions is for you to approve, with `/episteme:mantencion` ([Maintenance](docs/mantencion.md), in Spanish).
- **The password filter is not perfect.** It knows the usual formats: do not dictate secrets.

## Documentation

All in Spanish.

| Document | Contents |
| :-- | :-- |
| [Installation](docs/instalacion.md) | By hand, the plugin, agy and Copilot CLI |
| [Configuration](docs/configuracion.md) | Arguments, variables and `episteme.toml` |
| [Tools and memories](docs/tools.md) | The tools, the memories and the errors |
| [Session state](docs/sesion.md) | Picking up the work after compacting or `/clear` |
| [Plans](docs/planes.md) | The copy of each plan |
| [Documentation suites](docs/documentacion.md) | Third-party documentation in the vault |
| [Hooks](docs/hooks.md) | Configuration and permissions |
| [Maintenance](docs/mantencion.md) | Archiving, backup and review |
| [OMEGA migration](docs/migracion-omega.md) | Bringing over the OMEGA memories |
| [Development](docs/desarrollo.md) | Tests, lint, CI and release |
| [CHANGELOG](CHANGELOG.md) | Changes in each version |

## License

[MIT](LICENSE), © 2026 Kenno ([benjamincriado.dev](https://benjamincriado.dev/episteme/)).
