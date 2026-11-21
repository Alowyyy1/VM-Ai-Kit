"""Smoke test for a running AgentKit bridge.

Usage:
    python test_mcp.py --url http://127.0.0.1:37075/mcp --token <token>
    python test_mcp.py --url ... --token ... --full      # also screenshot + shell + pe_info
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(url: str, token: str, full: bool) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(url, headers=headers, timeout=30) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"server: {init.serverInfo.name} {init.serverInfo.version}")

            tools = (await session.list_tools()).tools
            print(f"tools: {len(tools)}")
            for tool in sorted(tools, key=lambda t: t.name):
                first = (tool.description or "").splitlines()[0][:90]
                print(f"  {tool.name:<28} {first}")

            async def call(name: str, args: dict | None = None) -> None:
                result = await session.call_tool(name, args or {})
                chunks = []
                for item in result.content:
                    text = getattr(item, "text", None)
                    chunks.append(text if text is not None else f"<{item.type}>")
                body = "\n".join(chunks)
                print(f"\n== {name} (isError={result.isError}) ==")
                print(body[:1200])

            await call("sys_info")
            await call("sys_exec", {"command": "echo agentkit-ok && ver", "shell": "cmd"})
            await call("fs_list", {"path": ".", "limit": 10})
            await call("agent_selftest")
            if full:
                await call("screen_capture", {"monitor": 0, "scale": 0.4})
                await call("pe_info", {"path": sys.executable})
            errors = [t for t in tools if not t.description]
            print(f"\nOK - {len(tools)} tools, {len(errors)} without description")
            return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:37075/mcp")
    parser.add_argument("--token", required=True)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.url, args.token, args.full))
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
