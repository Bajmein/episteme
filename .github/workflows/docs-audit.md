---
# Auditoría semanal de documentación: compara lo mezclado en la última semana con los
# documentos que deberían haberlo seguido y abre un issue solo si hay discrepancias.
on:
  schedule: weekly on monday
  workflow_dispatch:

permissions:
  contents: read
  issues: read
  pull-requests: read

engine: copilot
timeout-minutes: 20

tools:
  github:
    toolsets: [repos, pull_requests, issues]

network: defaults

safe-outputs:
  create-issue:
    title-prefix: "docs: "
    labels: [docs-audit]
    max: 1
    close-older-issues: true
  noop:
---

# Weekly documentation audit

You audit the documentation of this repository (`episteme`, an MCP server in Python) against the
code changes merged to `main` in the last 7 days. You only read; your single possible write is one
issue through the safe output, or `noop` when everything is in order.

## Steps

1. List the pull requests merged into `main` in the last 7 days. If there are none, call `noop` and stop.
2. For each one, read its diff and decide which documents had to change with it:
   - A tool changed (signature, arguments, behaviour, errors; code in `src/episteme/tools/` or the
     modules they call): its docstring, `docs/tools.md`, the tools table of `README.md`, the
     `SKILL.md` files under `plugin/skills/` and `plugin-docs/skills/` that name the tool,
     `plugin/agents/extractor.md` and `plugin/rules/AGENTS.md`.
   - Hooks, installation or permissions changed: `docs/hooks.md`, `docs/instalacion.md`,
     `plugin/skills/setup/SKILL.md` and `plugin/skills/setup/settings.json`.
   - Configuration changed (`episteme.toml`, `src/episteme/vault.py`): `docs/configuracion.md`.
   - Anything a user of episteme notices (tools, hooks, skills, scripts, installation): an entry in
     the `## [Sin publicar]` section of `CHANGELOG.md`, unless the PR is itself a release.
   - CI or development workflow changed (`.github/workflows/`, `pyproject.toml` dev tooling):
     the CI paragraph of `CLAUDE.md` and `docs/desarrollo.md`.
3. Open each document that should have changed, on `main`, and check whether it now matches the code.
   Report only discrepancies you verified by reading both sides: a document that states something the
   code no longer does, a missing entry, a wrong name or argument. Do not report style, wording
   preferences or things you could not confirm.
4. If you found no verified discrepancy, call `noop` with a one-line reason and stop.
5. Otherwise create one issue, written in Spanish, titled `Auditoría de documentación YYYY-MM-DD`
   (today's date). For each discrepancy: the document as `path:line`, what it says, what the code
   does (`path:line`), and the PR that introduced the change (`#N`). Group by PR. End with the list
   of PRs reviewed.
