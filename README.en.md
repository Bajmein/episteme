<div align="center">

![episteme: Agentic Memory & Knowledge Vault. Persistent Knowledge Engine for AI Workflows.](static/banner-episteme.jpg)

<a href="https://github.com/Bajmein/episteme/tags"><img alt="Version" src="https://img.shields.io/badge/version-v0.22.1-8B5CF6?style=for-the-badge"></a>
<a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.14+-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54"></a>
<a href="https://docs.astral.sh/uv/"><img alt="uv" src="https://img.shields.io/badge/uv-DE5FE9?style=for-the-badge&logo=uv&logoColor=white"></a>
<a href="https://github.com/modelcontextprotocol/python-sdk"><img alt="MCP SDK" src="https://img.shields.io/badge/MCP_SDK-2.x-005571?style=for-the-badge&logo=modelcontextprotocol&logoColor=white"></a>
<a href="https://www.sqlite.org/fts5.html"><img alt="SQLite FTS5" src="https://img.shields.io/badge/sqlite-FTS5-07405e?style=for-the-badge&logo=sqlite&logoColor=white"></a>
<a href="https://obsidian.md/"><img alt="Obsidian" src="https://img.shields.io/badge/Obsidian-483699?style=for-the-badge&logo=obsidian&logoColor=white"></a>
<a href="https://www.markdownguide.org/"><img alt="Markdown" src="https://img.shields.io/badge/markdown-000000?style=for-the-badge&logo=markdown&logoColor=white"></a>
<a href="https://codescene.io/projects/87754"><img alt="CodeScene" src="https://img.shields.io/badge/CodeScene-analyzed-5F46EB?style=for-the-badge"></a>
<a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-yellow?style=for-the-badge"></a>
<br>
<a href="#installation"><img alt="Linux" src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black"></a>
<a href="#installation"><img alt="macOS" src="https://img.shields.io/badge/mac%20os-000000?style=for-the-badge&logo=macos&logoColor=F0F0F0"></a>
<a href="#installation"><img alt="Windows" src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge"></a>
<br>
<a href="https://github.com/Bajmein/episteme/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Bajmein/episteme/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI"></a>
<a href="https://codecov.io/gh/Bajmein/episteme"><img alt="Coverage" src="https://img.shields.io/codecov/c/github/Bajmein/episteme/main?style=for-the-badge&logo=codecov&logoColor=white&label=coverage"></a>

# episteme

**One curated project memory for all your agents.**

</div>

<p align="center">
  <a href="README.md">Español</a> · <b>English</b>
</p>

<p align="center">
  <a href="#what-it-is">What it is</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#daily-use">Daily use</a> ·
  <a href="#the-9-tools">Tools</a> ·
  <a href="#limits">Limits</a> ·
  <a href="#documentation">Documentation</a>
</p>

---

> [!NOTE]
> This is the English translation of the [README in Spanish](README.md). The documents in `docs/` are in Spanish.

## What it is

An AI agent is like a brilliant colleague who arrives every morning remembering nothing about yesterday. **episteme gives it a memory that lasts**: a folder of Markdown notes (the *vault*) that holds the decisions, lessons and documentation of your projects. Claude Code and agy (Google Antigravity, with Gemini) share the same memories, and each one records which agent saved it.

| | What it does for you |
| :-- | :-- |
| **Remembers** | Saves decisions, lessons, errors and preferences, by project |
| **Finds** | Searches the whole vault, in Spanish, ignoring case and accents |
| **Warns in time** | Shows a file's rules before it is edited |
| **Picks up where you left off** | Saves what you are working on and brings it back after compacting, `/clear` or when you continue |
| **Saves your plans** | Copies every plan you approve in plan mode |
| **Keeps the documentation current** | Updates third-party documentation with `/episteme-docs:docs` |
| **Keeps things tidy** | Detects duplicates, expired memories and broken links; refuses passwords and tokens |

**Your notes are your own Markdown files and never leave your machine** (open them with [Obsidian](https://obsidian.md/) or any editor). The only network use is the installation, from GitHub, and `/episteme-docs:docs`, if you use it.

> [!NOTE]
> **Current version: v0.22.1.** Works on Linux, macOS and Windows. What is new in each version is in the [CHANGELOG](CHANGELOG.md) (in Spanish).

## How it works

<p align="center">
  <img src="static/diagrams/arquitectura.png" alt="Claude Code (the agent and its hooks) and, if you enable it, agy call the episteme server, which reads and writes the vault's Markdown notes (memories, documentation, sessions and plans) and keeps a search index; Obsidian can open the same vault. The text inside the diagram is in Spanish." width="880">
</p>

1. **Claude Code** uses episteme's tools when it needs them, and its *hooks* call them automatically at fixed moments of the session. **agy** uses the same tools, without hooks.
2. **episteme** is a small program that runs on your machine. It is the only door to the vault: it validates what is saved and keeps an index for fast search.
3. **The vault** is a folder of Markdown notes, by default `~/.episteme`. You can read and edit it with Obsidian.

<details>
<summary><b>Quick glossary</b></summary>

| Term | What it means |
| :-- | :-- |
| **Vault** | The folder with all the notes. It is split into zones: memories, documentation, session state and plans |
| **Memory** | A short note with something worth remembering: a decision, a lesson, a reminder |
| **Tool** | An action Claude can ask episteme for: search, read, save |
| **Hook** | A Claude Code automation that calls a tool without anyone asking |
| **MCP** | The standard protocol Claude Code uses to connect to programs like episteme |

</details>

### Which agents it works with

| | Claude Code | agy | Other MCP client |
| :-- | :-: | :-: | :-: |
| Tools (search, read, save) | Yes | Yes | Yes |
| Automations: welcome, suggestions with each message, rules and notices when touching files, continuity after `/compact` and `/clear`, copy of plans | Yes | No | No |

In agy and other clients, the agent uses the tools when you ask or when a rule tells it to.

## Installation

**You need** [uv](https://docs.astral.sh/uv/) and git. uv gets Python for you if it is missing.

### Option A · With the skill (recommended)

Once per machine, the same on Linux, macOS and Windows ([more details](docs/instalacion.md#los-plugins), in Spanish):

```bash
claude plugin marketplace add Bajmein/episteme
claude plugin install episteme@episteme
```

Then, in each project you want to connect:

1. Restart Claude Code and open it at the project root.
2. Type `/episteme:setup`.
3. Approve the changes it shows you: it registers the server, sets up hooks and permissions, and adds the rule to `CLAUDE.md`.

| Skill | What for |
| :-- | :-- |
| `/episteme:setup` | Connect the project: server, hooks, permissions and the `CLAUDE.md` rule |
| `/episteme:sesion` | Save where you are (`guardar`) and pick it up (`retomar`) |
| `/episteme:mantencion` | Review memories with you; `corta` does a quick round and `huerfanas` links the loose ones |
| `/episteme:reminder <text>` | Leave a reminder that appears at the start of each session |
| `/episteme:scaffold` | Create or review `README.md`, `CLAUDE.md`, `CHANGELOG.md` and `.gitignore`; with `auditar` it only reviews |
| `/episteme:agy [task]` | Enable agy in the project and hand it tasks |
| `/episteme-docs:docs [suite]` | Update the third-party documentation. Separate, optional plugin: `claude plugin install episteme-docs@episteme` |

The skills also load in agy, including `/episteme-docs:docs`, but without hooks or an automatic welcome (see «agy» in [Installation](docs/instalacion.md#agy-opcional), in Spanish).

<details>
<summary><b>Option B · By hand (without the skill)</b></summary>

A single command registers the server. Replace `<project>` with your project's name.

**Linux and macOS**

```bash
claude mcp add --scope local episteme -- \
  uvx --from git+https://github.com/Bajmein/episteme@v0.22.1 episteme --project <project>
```

**Windows** (PowerShell, on a single line)

```powershell
claude mcp add --scope local episteme -- uvx --from git+https://github.com/Bajmein/episteme@v0.22.1 episteme --project <project>
```

The hooks, the permissions and the `CLAUDE.md` rule are still missing: they are in the [installation guide](docs/instalacion.md#después-de-registrar) (in Spanish).

</details>

> [!TIP]
> To check it, `claude mcp list` should show `episteme` connected. The first time takes a while, because it downloads. To update, repeat the registration with the new tag.

## Daily use

There are no commands to learn: you use it by talking to Claude.

<p align="center">
  <img src="static/diagrams/ciclo-memoria.png" alt="Life cycle of a memory in episteme, around the vault: save with remember, find with search and read, warn in time with context, correct with revise and tidy up with /episteme:mantencion. The text inside the diagram is in Spanish." width="720">
</p>

| You | episteme |
| :-- | :-- |
| Start a session | Delivers the rules, the due reminders and the most important memories |
| Write a message | Suggests the memories that are relevant |
| Say «remember that…» | Saves a new memory, unless an almost identical one exists |
| Ask «what did we decide about…?» | Claude searches the vault before answering |
| Claude is about to edit a file | Shows it that file's rules |
| Approve a plan in plan mode | Saves a copy and, if you clear the context, says where it is |
| Compact or use `/clear` | Recovers the work state and updates it in the background |
| Ask for `/episteme:mantencion` | Reviews duplicates, contradictions and expired memories with you |

<details>
<summary><b>What the hooks do in each session</b></summary>

<p align="center">
  <img src="static/diagrams/hooks-sesion.png" alt="Sequence of the day-to-day: with each message, before and after using a file and when approving a plan, a Claude Code hook calls an episteme tool, which answers with the welcome, memories or rules, or saves a copy of the plan in the vault. The text inside the diagram is in Spanish." width="880">
</p>

Hooks never block Claude or decide for it: they only bring it context. Configuration in [Hooks](docs/hooks.md) (in Spanish).

<p align="center">
  <img src="static/diagrams/compactar-clear.png" alt="Sequence showing how the work state survives /compact and /clear: when compacting, the summary writes the state up to date and episteme saves it; it brings it back with the welcome when starting again, and after /clear the extractor agent updates it in the background. The text inside the diagram is in Spanish." width="880">
</p>

When compacting you do not have to do anything: episteme saves the work state. A new session tells you it exists and you pick it up with `/episteme:sesion retomar`. Detail in [Session state](docs/sesion.md) (in Spanish).

</details>

## The 9 tools

| Tool | What it is for | Writes |
| :-- | :-- | :-: |
| `search` | Search the notes and memories | |
| `read` | Read notes and see which other notes link to them | |
| `context` | Give the welcome, gather what is relevant for a task and show a file's rules | ● |
| `remember` | Save a new memory, linked to similar ones | ● |
| `revise` | Correct, replace or archive a note without losing changes | ● |
| `review` | Review the vault: duplicates, expired, broken links and loose memories | |
| `session` | Save and pick up the session state | ● |
| `plan` | Save a copy of each plan-mode plan (the hooks use it) | ● |
| `docs` | See the documentation suites and save a page (used by `/episteme-docs:docs`) | ● |

`docs` only appears if the vault has documentation suites; without them there are 8. Each memory has a type (decision, rule, lesson, error, preference, finding or reminder) and a priority from 1 to 5: priority-5 memories are the rules Claude sees at the start. Detail in [Tools and memories](docs/tools.md#memorias) (in Spanish).

## Limits

- **Search by keywords, not by embeddings.** «marketing» does not find «mkt»: that is why each memory carries `keywords` with synonyms. With bge-m3 and 147 real queries, only 3 found anything new ([measurement](docs/desarrollo.md#medir-si-los-embeddings-aportan), in Spanish).
- **It warns, it does not force.** The rules reach Claude in time, but nothing stops it from ignoring them.
- **It does not tidy itself.** Merging and resolving contradictions is for you to approve, with `/episteme:mantencion`. It is worth enabling `archive_expired = true` ([Maintenance](docs/mantencion.md), in Spanish).
- **The password filter knows the usual formats.** An unusual key may get through: do not dictate secrets.

## Documentation

| Document | Contents |
| :-- | :-- |
| [Installation](docs/instalacion.md) (in Spanish) | Manual steps on Linux, macOS and Windows, and the plugin |
| [Configuration](docs/configuracion.md) (in Spanish) | Arguments, variables, `episteme.toml` and the activity log |
| [Tools and memories](docs/tools.md) (in Spanish) | The 9 tools, the memory schema and the errors |
| [Session state](docs/sesion.md) (in Spanish) | The live note of each thread of work in `sesiones/` |
| [Plans](docs/planes.md) (in Spanish) | The copy of each plan and how it is recovered after «clear context» |
| [Documentation suites](docs/documentacion.md) (in Spanish) | Third-party documentation in the vault and `/episteme-docs:docs` |
| [Hooks](docs/hooks.md) (in Spanish) | The block for `settings.json` and the recommended permissions |
| [Maintenance](docs/mantencion.md) (in Spanish) | Warnings, archiving, backup and the review cycle |
| [OMEGA migration](docs/migracion-omega.md) (in Spanish) | How to bring over the OMEGA memories |
| [Development](docs/desarrollo.md) (in Spanish) | Tests, lint, code health and measurement scripts |
| [CHANGELOG](CHANGELOG.md) (in Spanish) | Changes in each version |

Want to contribute? Tests and lint in [Development](docs/desarrollo.md) (in Spanish); the agents already have their instructions in [`CLAUDE.md`](CLAUDE.md) (Claude Code) and [`GEMINI.md`](GEMINI.md) (agy), in Spanish.

## License

[MIT](LICENSE), © 2026 Kenno ([benjamincriado.dev](https://benjamincriado.dev/episteme/)).
