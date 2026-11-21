#!/usr/bin/env python3
"""Stdio-to-HTTP MCP Bridge for VM Agent Kit.

Translates stdio JSON-RPC into HTTP FastMCP calls to the VM.
Allows legacy stdio-only MCP clients to interact with the remote VM agent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

def load_config() -> dict:
    cfg_file = Path(__file__).resolve().parent / "host_config.json"
    if cfg_file.is_file():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "vm_ip": os.environ.get("VM_AGENT_HOST", "127.0.0.1"),
        "vm_port": int(os.environ.get("VM_AGENT_PORT", "37075")),
        "token": os.environ.get("VM_AGENT_TOKEN", ""),
    }

def main():
    parser = argparse.ArgumentParser(description="VM Agent Stdio Bridge")
    parser.add_argument("--url", help="Override VM MCP URL")
    parser.add_argument("--token", help="Override auth token")
    args = parser.parse_args()

    cfg = load_config()
    vm_url = args.url or f"http://{cfg.get('vm_ip', '127.0.0.1')}:{cfg.get('vm_port', 37075)}/mcp"
    token = args.token or cfg.get("token", "")

    # Check connection
    health_url = vm_url.replace("/mcp", "/healthz")
    try:
        req = urllib.request.Request(health_url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            pass
    except Exception as e:
        sys.stderr.write(f"[bridge warn] cannot connect to VM agent at {health_url}: {e}\n")

    # Stdio loop
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = urllib.request.Request(vm_url, data=line.encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = resp.read().decode("utf-8")
                sys.stdout.write(out + "\n")
                sys.stdout.flush()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            sys.stderr.write(f"[bridge error] HTTP {e.code}: {err_body}\n")
            err_resp = {"jsonrpc": "2.0", "error": {"code": -32603, "message": f"HTTP {e.code}: {err_body}"}, "id": None}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stderr.write(f"[bridge error] {e}\n")
            err_resp = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": None}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
