"""Client for the x64dbg MCP automation plugin (x64dbg_mcp.dp64 / .dp32).

The plugin exposes ~150 REST endpoints on 127.0.0.1:27042 inside the VM. We talk to
it directly instead of spawning a Node MCP server: one less moving part, and the
whole API surface is reachable through the `dbg_api` passthrough.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import Config
from .util import AgentError, norm_path


class X64Dbg:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------------ paths
    def exe(self, x32: bool = False) -> Path:
        root = Path(self.cfg.x64dbg_dir)
        name = "x32dbg.exe" if x32 else "x64dbg.exe"
        candidates = [
            root / ("x32" if x32 else "x64") / name,
            root / "release" / ("x32" if x32 else "x64") / name,
            root / name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise AgentError(
            f"{name} not found under {root}. Run install-vm.ps1 (or fetch-tools.ps1) first."
        )

    def running(self) -> list[dict]:
        import psutil

        out = []
        for proc in psutil.process_iter(["pid", "name", "exe", "create_time"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in ("x64dbg.exe", "x32dbg.exe"):
                    out.append({
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "exe": proc.info.get("exe"),
                        "started": proc.info.get("create_time"),
                    })
            except Exception:
                continue
        return out

    # ------------------------------------------------------------------ http
    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        if not path.startswith("/api/"):
            raise AgentError("plugin path must start with /api/")
        url = f"http://{self.cfg.x64dbg_host}:{self.cfg.x64dbg_port}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, "")}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        return url

    def call(self, method: str, path: str, params: dict[str, Any] | None = None,
             body: Any = None, timeout: float | None = None) -> Any:
        url = self._url(path, params)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.cfg.x64dbg_token:
            headers["Authorization"] = f"Bearer {self.cfg.x64dbg_token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        limit = float(timeout if timeout is not None else self.cfg.debug_timeout)
        status = 200
        try:
            with urllib.request.urlopen(req, timeout=limit) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        except urllib.error.URLError as exc:
            raise AgentError(
                f"x64dbg plugin is not reachable at {self.cfg.x64dbg_host}:{self.cfg.x64dbg_port} "
                f"({exc.reason}). Start x64dbg with a target loaded and check that "
                f"x64dbg_mcp.dp64 is in x64\\plugins."
            ) from exc
        except TimeoutError as exc:
            raise AgentError(
                f"x64dbg request timed out after {limit:.0f}s; the debugger may be running "
                f"or waiting for an event. Use dbg_pause or increase the timeout."
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError as exc:
            raise AgentError(
                f"plugin returned non-JSON (HTTP {status}): {raw[:400]!r}"
            ) from exc

        if isinstance(payload, dict) and "success" in payload:
            if not payload.get("success"):
                err = payload.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise AgentError(f"x64dbg plugin error: {msg or payload}")
            return payload.get("data")
        if status >= 400:
            raise AgentError(f"x64dbg plugin HTTP {status}: {payload}")
        return payload

    def health(self, timeout: float = 2.0) -> dict:
        try:
            data = self.call("GET", "/api/health", timeout=timeout)
            return {"reachable": True, "data": data}
        except AgentError as exc:
            return {"reachable": False, "error": str(exc)}

    def wait_ready(self, timeout: float = 45.0) -> dict:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.health()
            if last["reachable"]:
                return last
            time.sleep(3 if (deadline - time.time()) < 15 else 1)
        raise AgentError(
            f"x64dbg plugin did not come online within {timeout:.0f}s: "
            f"{last.get('error') if last else 'no response'}"
        )

    # ------------------------------------------------------------------ control
    def launch(self, target: str, args: str = "", x32: bool = False,
               wait_seconds: float = 45.0) -> dict:
        exe = self.exe(x32)
        target_path = norm_path(target)
        if not target_path.is_file():
            raise AgentError(f"target not found: {target_path}")
        existing = self.running()
        if existing:
            raise AgentError(
                "x64dbg is already running (pids: "
                + ", ".join(str(p["pid"]) for p in existing)
                + "). Use dbg_open or close it first."
            )
        argv = [str(exe), str(target_path)] + shlex.split(args or "")
        proc = subprocess.Popen(argv, cwd=str(exe.parent))
        ready = self.wait_ready(wait_seconds)
        return {
            "pid": proc.pid,
            "exe": str(exe),
            "target": str(target_path),
            "plugin": ready,
            "state": self.state(),
        }

    def state(self) -> dict:
        try:
            return self.call("GET", "/api/debug/state", timeout=10)
        except AgentError:
            return {"unknown": True}

    def module_base(self, module: str) -> int:
        data = self.call("GET", "/api/modules/base", {"name": module}, timeout=15)
        if isinstance(data, dict):
            for key in ("base", "address", "value"):
                if key in data:
                    return int(str(data[key]), 0)
        if isinstance(data, (int, str)):
            return int(str(data), 0)
        raise AgentError(f"unexpected /api/modules/base response: {data!r}")

    def dump_module(self, module: str, out_file: str, fix_iat: bool = False,
                    oep: str | None = None) -> dict:
        out_path = norm_path(out_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {"module": module, "file": str(out_path)}
        result["dump"] = self.call("POST", "/api/dump/module",
                                   body={"module": module, "file": str(out_path)},
                                   timeout=300)
        if fix_iat:
            target_oep = oep or self._entry_point(module)
            result["oep"] = target_oep
            result["fix_iat"] = self.call("POST", "/api/dump/fix_iat", body={"oep": target_oep},
                                          timeout=300)
        if out_path.is_file():
            result["size"] = out_path.stat().st_size
            result["sha256"] = __import__("hashlib").sha256(out_path.read_bytes()).hexdigest()
        return result

    def _entry_point(self, module: str) -> str:
        data = self.call("GET", "/api/dump/entry_point", {"module": module}, timeout=20)
        if isinstance(data, dict):
            for key in ("entry_point", "address", "va", "value"):
                if key in data:
                    return str(data[key])
        return str(data)


# Full REST surface of x64dbg_mcp v2.3.0, kept for `dbg_endpoints` discovery.
ENDPOINTS: dict[str, list[str]] = {
    "control": ["/api/debug/run", "/api/debug/pause", "/api/debug/force_pause",
                "/api/debug/step_into", "/api/debug/step_over", "/api/debug/step_out",
                "/api/debug/run_to", "/api/debug/stop", "/api/debug/restart",
                "/api/debug/state"],
    "command": ["/api/command/exec", "/api/command/script", "/api/command/eval",
                "/api/command/format", "/api/command/events", "/api/command/hash",
                "/api/command/init_script"],
    "breakpoints": ["/api/breakpoints/set", "/api/breakpoints/set_hardware",
                    "/api/breakpoints/set_memory", "/api/breakpoints/set_condition",
                    "/api/breakpoints/set_log", "/api/breakpoints/configure",
                    "/api/breakpoints/configure_batch", "/api/breakpoints/list",
                    "/api/breakpoints/get", "/api/breakpoints/delete",
                    "/api/breakpoints/enable", "/api/breakpoints/disable",
                    "/api/breakpoints/toggle", "/api/breakpoints/reset_hit_count"],
    "memory": ["/api/memory/read", "/api/memory/write", "/api/memory/allocate",
               "/api/memory/free", "/api/memory/protect", "/api/memory/page_info",
               "/api/memory/is_valid", "/api/memory/is_code", "/api/memory/update_map",
               "/api/memmap/list", "/api/memmap/at"],
    "registers": ["/api/registers/all", "/api/registers/get", "/api/registers/set",
                  "/api/registers/flags", "/api/registers/avx512"],
    "disassembly": ["/api/disasm/at", "/api/disasm/basic", "/api/disasm/function",
                    "/api/disasm/assemble"],
    "analysis": ["/api/analysis/function", "/api/analysis/basic_blocks",
                 "/api/analysis/xrefs_to", "/api/analysis/xrefs_from",
                 "/api/analysis/strings", "/api/analysis/constants",
                 "/api/analysis/structs", "/api/analysis/watch",
                 "/api/analysis/va_to_file", "/api/analysis/file_to_va",
                 "/api/analysis/mnemonic_brief", "/api/analysis/error_codes",
                 "/api/analysis/source"],
    "modules": ["/api/modules/list", "/api/modules/get", "/api/modules/base",
                "/api/modules/section", "/api/modules/party"],
    "dumping": ["/api/dump/module", "/api/dump/pe_header", "/api/dump/sections",
                "/api/dump/imports", "/api/dump/exports", "/api/dump/entry_point",
                "/api/dump/relocations", "/api/dump/fix_iat"],
    "patches": ["/api/patches/apply", "/api/patches/list", "/api/patches/restore",
                "/api/patches/export", "/api/patches/export_file"],
    "search": ["/api/search/pattern", "/api/search/string", "/api/search/string_at",
               "/api/search/encode_type", "/api/search/auto_complete"],
    "process": ["/api/process/info", "/api/process/details", "/api/process/pid",
                "/api/process/cmdline", "/api/process/set_cmdline",
                "/api/process/dbversion", "/api/process/elevated"],
    "threads": ["/api/threads/list", "/api/threads/count", "/api/threads/current",
                "/api/threads/get"],
    "stack": ["/api/stack/callstack_thread", "/api/stack/read", "/api/stack/pointers",
              "/api/stack/return_address", "/api/stack/seh_chain", "/api/stack/trace",
              "/api/stack/comment"],
    "handles": ["/api/handles/list", "/api/handles/get", "/api/handles/close",
                "/api/handles/tcp", "/api/handles/windows", "/api/handles/heaps"],
    "tracing": ["/api/trace/into", "/api/trace/over", "/api/trace/run",
                "/api/trace/conditional_run", "/api/trace/log", "/api/trace/animate",
                "/api/trace/status", "/api/trace/stop", "/api/trace/record/set_type",
                "/api/trace/record/type", "/api/trace/record/hitcount"],
    "symbols": ["/api/symbols/list", "/api/symbols/at", "/api/symbols/resolve",
                "/api/symbols/search", "/api/labels/set", "/api/labels/get",
                "/api/comments/set", "/api/comments/get", "/api/bookmarks/set"],
    "antidebug": ["/api/antidebug/hide_debugger", "/api/antidebug/peb",
                  "/api/antidebug/teb", "/api/antidebug/dep_status"],
    "exceptions": ["/api/exceptions/list_codes", "/api/exceptions/list_bps",
                   "/api/exceptions/set_bp", "/api/exceptions/delete_bp",
                   "/api/exceptions/skip"],
    "cfg": ["/api/cfg/function", "/api/cfg/loops", "/api/cfg/branch_dest",
            "/api/cfg/is_jump_taken", "/api/cfg/func_type", "/api/cfg/add_function",
            "/api/cfg/delete_function"],
}
