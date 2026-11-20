"""AgentKit VM bridge: one MCP server exposing system, files, screen, input, x64dbg and PE tools.

Run:
    python -m vm_agent.server --config C:\\AgentKit\\agent.json
"""
from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import t_agent, t_dbg, t_files, t_static, t_system, t_ui
from .config import AGENT_VERSION, Config, load_config
from .util import AgentError
from . import winapi

LOG = logging.getLogger("agentkit")

INSTRUCTIONS = """\
AgentKit - a Windows 10 VM driven over MCP. You are operating a real interactive desktop;
actions have real side effects.

Tool map:
  sys_*     shell, processes, network, modules        (sys_exec, sys_powershell, sys_processes, proc_modules)
  fs_*      files, chunked upload/download, zip, hash (fs_write_bytes mode=patch for chunks)
  screen_*  screenshots as inline PNG, pixels, monitors
  input_*   mouse/keyboard/clipboard injection
  win_*     window enumeration, focus, move, close
  dbg_*     x64dbg live debugging via the MCP plugin  (dbg_launch, dbg_set_breakpoint, dbg_run,
            dbg_read_memory, dbg_dump_module, dbg_hide_debugger, dbg_api for anything else)
  pe_*      static PE analysis (sections, imports, entropy, strings, AOB search, disassembly)
  tool_*    bundled CLI tools: DIE, capa, Sysinternals strings/procdump/handle

Start with agent_selftest() if the environment is unknown, and agent_guide() for workflows.
Prefer small steps and verify with a screenshot or a file hash. Large transfers use 3 MB
chunks. Never assume a GUI action landed - capture the screen afterwards.
"""


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self.token = token
        self.exempt = {"/healthz", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.exempt or request.method == "OPTIONS":
            return await call_next(request)
        supplied = ""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not supplied:
            supplied = request.headers.get("x-agent-token", "") or request.query_params.get("token", "")
        if not supplied or not hmac.compare_digest(supplied, self.token):
            return JSONResponse(
                {"error": "unauthorized", "hint": "send Authorization: Bearer <token>"},
                status_code=401,
            )
        return await call_next(request)


def _setup_logging(cfg: Config) -> None:
    level = getattr(logging, str(cfg.log_level).upper(), logging.INFO)
    log_path = cfg.work / "agent.log"
    handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)
    root.addHandler(stream)
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_app(cfg: Config) -> Starlette:
    mcp = FastMCP(
        "agentkit-vm",
        instructions=INSTRUCTIONS,
        host=cfg.host,
        port=cfg.port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=bool(cfg.stateless),
        max_request_body_size=16 * 1024 * 1024,
        session_idle_timeout=None,
        log_level=str(cfg.log_level).upper(),
    )

    t_system.register(mcp, cfg)
    t_files.register(mcp, cfg)
    t_ui.register(mcp, cfg)
    t_dbg.register(mcp, cfg)
    t_static.register(mcp, cfg)
    t_agent.register(mcp, cfg)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({
            "ok": True,
            "service": "agentkit-vm",
            "version": AGENT_VERSION,
            "hostname": socket.gethostname(),
            "user": os.environ.get("USERNAME"),
            "session": winapi.session_id(),
            "elevated": winapi.is_elevated(),
            "uptime_s": int(time.time() - _STARTED),
        })

    inner = mcp.streamable_http_app()
    app = Starlette(
        routes=inner.routes,
        middleware=[Middleware(TokenAuthMiddleware, token=cfg.token)],
        lifespan=inner.router.lifespan_context,
    )
    app.state.mcp = mcp
    return app


_STARTED = time.time()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentKit VM MCP bridge")
    parser.add_argument("--config", help="path to agent.json")
    parser.add_argument("--host", help="override listen address")
    parser.add_argument("--port", type=int, help="override listen port")
    parser.add_argument("--token", help="override auth token")
    parser.add_argument("--log-level", help="DEBUG/INFO/WARNING/ERROR")
    parser.add_argument("--show-config", action="store_true", help="print effective config and exit")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port
    if args.token:
        cfg.token = args.token
    if args.log_level:
        cfg.log_level = args.log_level
    cfg.validate()

    _setup_logging(cfg)
    winapi.enable_dpi_awareness()

    if args.show_config:
        print(json.dumps(cfg.public_dict(), indent=2))
        return 0

    app = build_app(cfg)
    LOG.info("AgentKit %s listening on http://%s:%s/mcp (token %s)",
             AGENT_VERSION, cfg.host, cfg.port, "set" if cfg.token else "MISSING")
    LOG.info("Health check: http://127.0.0.1:%s/healthz", cfg.port)
    LOG.info("Work dir: %s | tools: %s", cfg.work, cfg.tools_dir)
    try:
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_level=str(cfg.log_level).lower(),
                    access_log=False, timeout_keep_alive=75)
    except OSError as exc:
        LOG.error("cannot bind %s:%s - %s (is another agent already running?)",
                  cfg.host, cfg.port, exc)
        return 2
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
