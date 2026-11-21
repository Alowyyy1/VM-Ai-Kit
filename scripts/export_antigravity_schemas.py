"""Export Antigravity MCP tool schemas and instructions.md from vm_agent.server."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vm_agent.config import Config  # noqa: E402
from vm_agent.server import INSTRUCTIONS, build_app  # noqa: E402


async def export() -> int:
    cfg = Config(token="schema_export_dummy_token_0123456789")
    app = build_app(cfg)
    mcp = app.state.mcp
    tools = await mcp.list_tools()

    out_dir = ROOT / "host" / "antigravity_schemas"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale json schemas that no longer exist
    expected = {f"{t.name}.json" for t in tools}
    for old in out_dir.glob("*.json"):
        if old.name not in expected:
            old.unlink()

    for tool in sorted(tools, key=lambda t: t.name):
        schema = tool.inputSchema or {"type": "object", "properties": {}}
        if "title" not in schema:
            schema["title"] = f"{tool.name}Arguments"
        payload = {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": schema,
        }
        (out_dir / f"{tool.name}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    (out_dir / "instructions.md").write_text(INSTRUCTIONS, encoding="utf-8")
    print(f"Exported {len(tools)} schemas and instructions.md to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(export()))
