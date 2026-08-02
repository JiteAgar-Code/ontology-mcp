"""
tool_meta.py — loads config/tool_descriptions.yaml and exposes helper functions.

All MCP server files call tool_meta.get() to obtain tool descriptions.
No description strings are written inline in server.py or diagnostic_server.py.
"""

from __future__ import annotations

from pathlib import Path
import yaml

_CONFIG_PATH = (
    Path(__file__).parent.parent.parent / "config" / "tool_descriptions.yaml"
)

def _load() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)

_DATA: dict = _load()


def get(server: str, tool: str) -> str:
    """
    Return the description string for the named tool on the named server.

    Args:
        server: top-level key in tool_descriptions.yaml
                ("ontology_mcp" or "data_mcp")
        tool:   tool name key under that server's `tools` section
    """
    try:
        return _DATA[server]["tools"][tool]["description"].strip()
    except KeyError as exc:
        raise KeyError(
            f"tool_meta: no description found for server='{server}' tool='{tool}'. "
            f"Add it to config/tool_descriptions.yaml."
        ) from exc


def server_description(server: str) -> str:
    """Return the server-level description string."""
    try:
        return _DATA[server]["server"]["description"].strip()
    except KeyError as exc:
        raise KeyError(
            f"tool_meta: no server description found for '{server}'. "
            f"Add it to config/tool_descriptions.yaml."
        ) from exc
