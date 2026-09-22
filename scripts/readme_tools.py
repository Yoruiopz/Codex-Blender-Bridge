"""Generate or check the README's complete MCP tool inventory (no Blender needed)."""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp_server.tools import catalog

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- BEGIN GENERATED MCP TOOLS -->"
END = "<!-- END GENERATED MCP TOOLS -->"


def render_inventory() -> str:
    definitions = list(catalog.CORE_DEFINITIONS)
    for name in sorted(catalog.__all__):
        if name.startswith("load_"):
            definitions.extend(getattr(catalog, name)())
    names = [tool.name for tool in definitions]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate tool in inventory")
    lines = [START, f"Current development registry: **{len(names)} MCP tools**.", ""]
    groups = sorted({tool.toolset for tool in definitions}, key=lambda name: (name != "core", name))
    for group in groups:
        tools = sorted((tool for tool in definitions if tool.toolset == group), key=lambda tool: tool.name)
        lines.extend(["<details>", f"<summary>{group} — {len(tools)} tools</summary>", "",
                      "| Tool | What it does |", "| --- | --- |"])
        for tool in tools:
            description = tool.description.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{tool.name}` | {description} |")
        lines.extend(["", "</details>", ""])
    return "\n".join([*lines, END])


def updated_readme(text: str) -> str:
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("README must contain exactly one inventory marker pair")
    before, rest = text.split(START)
    _, after = rest.split(END)
    return before + render_inventory() + after


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed inventory is stale")
    args = parser.parse_args()
    path = ROOT / "README.md"
    current = path.read_text(encoding="utf-8")
    updated = updated_readme(current)
    if args.check:
        if current != updated:
            parser.exit(1, "README tool inventory is stale; run python scripts/readme_tools.py\n")
    else:
        path.write_text(updated, encoding="utf-8")
