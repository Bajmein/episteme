#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["mcp>=2.3,<3"]
# ///
"""Hook for agy and Copilot CLI: a one-shot MCP client that injects episteme's context.

Neither client has ``mcp_tool`` hooks, so this ``command`` hook starts the project's
episteme server (the command and args of ``.agents/mcp_config.json`` for agy, of
``.github/mcp.json`` for Copilot), calls ``context`` and prints the text in the client's
format.

- Session start: the welcome (``context(mode="welcome")``).
- Each user message (agy: only its first model call): the memories that match it
  (``context(mode="task")``). Every hook is a new process, so ``welcome`` with a prompt
  would repeat the welcome.

Usage: ``episteme-hook.py --client agy|copilot --event <event>``, with the hook's JSON on
stdin. It never blocks the client: on any failure it prints ``{}`` and one line on stderr.
``/episteme:agy`` and ``/episteme:copilot`` copy it into each project.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

TIMEOUT = 20  # seconds; the hook has 30 in its config
TASK_BUDGET = 800  # tokens of the per-message context
MIN_PROMPT = 15  # a «yes» or a «go on» is not worth a search
TASK_CHARS = 500  # of the message, sent as the task
CONFIG = {"agy": ".agents/mcp_config.json", "copilot": ".github/mcp.json"}
WELCOME_EVENTS = {"SessionStart", "sessionStart"}
TASK_EVENTS = {"PreInvocation", "userPromptSubmitted"}


def project_root(client: str, data: dict[str, Any]) -> Path | None:
    """The project folder: agy's first workspace, or Copilot's project dir or cwd."""
    if client == "agy":
        paths = data.get("workspacePaths") or []
        return Path(paths[0]) if paths else None
    root = os.environ.get("COPILOT_PROJECT_DIR") or data.get("cwd")
    return Path(root) if root else None


def server_params(client: str, root: Path) -> StdioServerParameters | None:
    """The episteme server of the project's MCP config, or None if there is none."""
    path = root / CONFIG[client]
    if not path.is_file():
        return None
    server = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {}).get("episteme")
    if not server:
        return None
    # The full environment: agy's `uv run episteme` needs the user's PATH, and the cwd.
    return StdioServerParameters(
        command=server["command"], args=server.get("args", []), cwd=root, env=dict(os.environ)
    )


def user_prompt(client: str, data: dict[str, Any]) -> str:
    """The user's message without a leading /command."""
    prompt = (data.get("lastUserInput" if client == "agy" else "prompt") or "").strip()
    if prompt.startswith("/"):  # «/plan revisa…»: drop the command
        prompt = prompt.partition(" ")[2].strip()
    return prompt


def arguments(client: str, event: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """The arguments of ``context`` for this event, or None when there is nothing to call."""
    session = data.get("conversationId" if client == "agy" else "sessionId")
    if event in WELCOME_EVENTS:
        return {"mode": "welcome", "session": session}
    if event not in TASK_EVENTS or data.get("invocationNum", 0) != 0:
        return None
    prompt = user_prompt(client, data)
    if len(prompt) < MIN_PROMPT:
        return None
    return {
        "mode": "task",
        "task": prompt[:TASK_CHARS],
        "budget_tokens": TASK_BUDGET,
        "session": session,
    }


async def call_context(params: StdioServerParameters, args: dict[str, Any]) -> str:
    """Call ``context`` once and return its text, empty when it found nothing."""
    with open(os.devnull, "w", encoding="utf-8") as errlog:  # server notices, not errors
        async with (
            stdio_client(params, errlog=errlog) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("context", args)
    if result.is_error or not result.content:
        raise RuntimeError(str(result.content)[:300])
    payload = json.loads(getattr(result.content[0], "text", ""))
    found = payload.get("entries") or args["mode"] == "welcome"
    return payload.get("text", "") if found else ""


def output(client: str, text: str) -> dict[str, Any]:
    """The hook's answer in the client's format."""
    if client == "agy":  # agy wants a nested object: {"systemMessage": {"systemMessage": …}}
        return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}
    return {"additionalContext": text}


def run(client: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
    root = project_root(client, data)
    params = server_params(client, root) if root else None
    args = arguments(client, data.get("hookEventName") or event, data)
    if not params or not args:
        return {}
    text = asyncio.run(asyncio.wait_for(call_context(params, args), TIMEOUT))
    return output(client, f"episteme · {args['mode']}\n{text}") if text else {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--client", choices=sorted(CONFIG), required=True)
    parser.add_argument("--event", default="")
    opts = parser.parse_args()
    out: dict[str, Any] = {}
    try:
        out = run(opts.client, opts.event, json.load(sys.stdin))
    except Exception as exc:  # a broken hook must not stop the client
        print(f"episteme-hook: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
