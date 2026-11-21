"""episteme: an MCP server over an Obsidian-compatible Markdown vault."""

from importlib.metadata import version

# Read from the installed package, so pyproject.toml stays the only place that sets it.
__version__ = version("episteme")
