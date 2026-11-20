"""Runtime debugging through x64dbg + the MCP automation plugin."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .config import Config
from .util import AgentError, j, norm_path
from .x64dbg import ENDPOINTS, X64Dbg


def register(mcp, cfg: Config) -> None:
    dbg = X64Dbg(cfg)

    # ---------------------------------------------------------------- session
    @mcp.tool()
    def dbg_status() -> str:
        """Is x64dbg running, is the plugin reachable, what is the debugger state, which target is loaded."""
        procs = dbg.running()
        health = dbg.health()
        state: Any = None
        modules: Any = None
        if health.get("reachable"):
            try:
                state = dbg.call("GET", "/api/debug/state", timeout=5)
                modules = dbg.call("GET", "/api/modules/list", timeout=5)
            except AgentError as exc:
                state = {"error": str(exc)}
        return j({
            "x64dbg_processes": procs,
            "plugin": health,
            "state": state,
            "modules": modules,
            "x64dbg_dir": cfg.x64dbg_dir,
            "plugin_endpoint": f"http://{cfg.x64dbg_host}:{cfg.x64dbg_port}",
        })

    @mcp.tool()
    def dbg_launch(target: str, args: str = "", x32: bool = False,
                   wait_seconds: float = 45) -> str:
        """Start x64dbg with a target file loaded and wait for the automation plugin.

        Fails if x64dbg is already running - use dbg_attach or close it first.
        """
        return j(dbg.launch(target, args=args, x32=x32, wait_seconds=wait_seconds))

    @mcp.tool()
    def dbg_attach(pid: int) -> str:
        """Attach the running debugger to a live process id."""
        return j(dbg.call("POST", "/api/command/exec", body={"command": f"attach {int(pid)}"},
                          timeout=120))

    @mcp.tool()
    def dbg_detach() -> str:
        """Detach from the current target (leaves the process running)."""
        return j(dbg.call("POST", "/api/command/exec", body={"command": "detach"}, timeout=60))

    @mcp.tool()
    def dbg_close() -> str:
        """Close x64dbg (all instances)."""
        import psutil

        closed = []
        for proc in psutil.process_iter(["pid", "name"]):
            if (proc.info.get("name") or "").lower() in ("x64dbg.exe", "x32dbg.exe"):
                try:
                    proc.terminate()
                    closed.append(proc.info["pid"])
                except Exception:
                    pass
        return j({"closed": closed})

    # ---------------------------------------------------------------- execution
    @mcp.tool()
    def dbg_command(command: str, timeout: float = 120) -> str:
        """Run any x64dbg command, e.g. 'bp MessageBoxW', 'run', 'dump rax', 'log "hi"'."""
        return j(dbg.call("POST", "/api/command/exec", body={"command": command},
                          timeout=timeout))

    @mcp.tool()
    def dbg_script(path: str) -> str:
        """Execute an x64dbg script file (.txt/.x64dbg script) as a batch of commands."""
        p = norm_path(path)
        if not p.is_file():
            raise AgentError(f"script not found: {p}")
        commands: list[str] = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("//") or line.startswith(";"):
                continue
            commands.append(line)
        if not commands:
            raise AgentError("script contains no commands")
        return j(dbg.call("POST", "/api/command/script", body={"commands": commands},
                          timeout=max(120.0, len(commands) * 5.0)))

    @mcp.tool()
    def dbg_run(timeout: float = 0) -> str:
        """Continue execution. Blocks until a debug event or the timeout; timeout=0 uses the default."""
        limit = float(timeout) if timeout and timeout > 0 else float(cfg.debug_timeout)
        result = dbg.call("POST", "/api/debug/run", timeout=limit)
        return j({"run": result, "state": dbg.state()})

    @mcp.tool()
    def dbg_pause() -> str:
        """Break into the debugger."""
        return j({"pause": dbg.call("POST", "/api/debug/pause", timeout=30), "state": dbg.state()})

    @mcp.tool()
    def dbg_step(kind: str = "into") -> str:
        """Single step: kind = into | over | out."""
        kind = (kind or "into").lower()
        routes = {"into": "/api/debug/step_into", "over": "/api/debug/step_over",
                  "out": "/api/debug/step_out", "step": "/api/debug/step_into"}
        if kind not in routes:
            raise AgentError("kind must be into, over or out")
        return j({"step": dbg.call("POST", routes[kind], timeout=120), "state": dbg.state()})

    @mcp.tool()
    def dbg_run_to(address: str, timeout: float = 300) -> str:
        """Run until the given address (hex or expression)."""
        return j({"run_to": dbg.call("POST", "/api/debug/run_to", body={"address": address},
                                     timeout=timeout), "state": dbg.state()})

    @mcp.tool()
    def dbg_state() -> str:
        """Current debugger state (paused/running, cip, last event, thread)."""
        return j(dbg.state())

    @mcp.tool()
    def dbg_registers() -> str:
        """All CPU registers and flags for the current thread."""
        return j(dbg.call("GET", "/api/registers/all", timeout=30))

    @mcp.tool()
    def dbg_events(limit: int = 30) -> str:
        """Recent debugger log events (breakpoint hits, exceptions, module loads)."""
        data = dbg.call("GET", "/api/command/events", timeout=30)
        if isinstance(data, list):
            data = data[-max(1, int(limit)):]
        return j(data)

    # ---------------------------------------------------------------- memory
    @mcp.tool()
    def dbg_read_memory(address: str, size: int = 256) -> str:
        """Read target memory at an address/expression (returns the plugin's hex/ascii dump)."""
        return j(dbg.call("GET", "/api/memory/read",
                          {"address": address, "size": str(int(size))}, timeout=60))

    @mcp.tool()
    def dbg_write_memory(address: str, bytes_hex: str, verify: bool = True) -> str:
        """Write hex bytes to target memory, e.g. address='0x401000', bytes_hex='90 90'."""
        return j(dbg.call("POST", "/api/memory/write",
                          body={"address": address, "bytes": bytes_hex, "verify": verify},
                          timeout=60))

    @mcp.tool()
    def dbg_memmap(address: str = "") -> str:
        """Memory map of the target, or the region containing a specific address."""
        if address:
            return j(dbg.call("GET", "/api/memmap/at", {"address": address}, timeout=30))
        return j(dbg.call("GET", "/api/memmap/list", timeout=60))

    @mcp.tool()
    def dbg_sections(address: str) -> str:
        """Module/section info for the module containing an address."""
        return j(dbg.call("GET", "/api/modules/section", {"address": address}, timeout=30))

    # ---------------------------------------------------------------- breakpoints
    @mcp.tool()
    def dbg_set_breakpoint(address: str, kind: str = "software", condition: str = "",
                           log_text: str = "", singleshot: bool = False,
                           hw_type: str = "x", hw_size: str = "1") -> str:
        """Set a breakpoint on an address or symbol (MessageBoxW, 0x401000).

        kind: software | hardware | memory. condition: x64dbg expression (e.g. 'eax==0').
        log_text: when set the breakpoint logs instead of pausing.
        """
        kind = (kind or "software").lower()
        out: dict[str, Any] = {}
        if kind == "software":
            out["set"] = dbg.call("POST", "/api/breakpoints/set",
                                  body={"address": address, "singleshot": bool(singleshot)},
                                  timeout=60)
        elif kind == "hardware":
            out["set"] = dbg.call("POST", "/api/breakpoints/set_hardware",
                                  body={"address": address, "type": hw_type, "size": str(hw_size)},
                                  timeout=60)
        elif kind == "memory":
            out["set"] = dbg.call("POST", "/api/breakpoints/set_memory",
                                  body={"address": address, "type": hw_type or "a"}, timeout=60)
        else:
            raise AgentError("kind must be software, hardware or memory")
        if condition:
            out["condition"] = dbg.call("POST", "/api/breakpoints/set_condition",
                                        body={"address": address, "condition": condition}, timeout=30)
        if log_text:
            out["log"] = dbg.call("POST", "/api/breakpoints/set_log",
                                  body={"address": address, "text": log_text}, timeout=30)
        out["breakpoints"] = dbg.call("GET", "/api/breakpoints/list", timeout=30)
        return j(out)

    @mcp.tool()
    def dbg_delete_breakpoint(address: str, kind: str = "") -> str:
        """Delete a breakpoint by address (optionally restrict to software/hardware/memory)."""
        body: dict[str, Any] = {"address": address}
        if kind:
            body["type"] = kind.lower()
        return j(dbg.call("POST", "/api/breakpoints/delete", body=body, timeout=30))

    @mcp.tool()
    def dbg_breakpoints() -> str:
        """List all breakpoints with hit counts."""
        return j(dbg.call("GET", "/api/breakpoints/list", timeout=30))

    # ---------------------------------------------------------------- analysis
    @mcp.tool()
    def dbg_disasm(address: str = "cip", count: int = 20) -> str:
        """Disassemble instructions at an address/expression."""
        return j(dbg.call("GET", "/api/disasm/at",
                          {"address": address, "count": str(int(count))}, timeout=60))

    @mcp.tool()
    def dbg_callstack() -> str:
        """Call stack of the current thread."""
        return j(dbg.call("GET", "/api/stack/callstack_thread", timeout=30))

    @mcp.tool()
    def dbg_modules() -> str:
        """Modules loaded in the debuggee (name, base, size, path)."""
        return j(dbg.call("GET", "/api/modules/list", timeout=30))

    @mcp.tool()
    def dbg_threads() -> str:
        """Threads of the debuggee."""
        return j(dbg.call("GET", "/api/threads/list", timeout=30))

    @mcp.tool()
    def dbg_search_pattern(pattern: str, address: str = "", size: str = "",
                           max_results: int = 100) -> str:
        """Search target memory for a byte pattern with wildcards, e.g. '48 8B ?? 48 85 C0'."""
        body: dict[str, Any] = {"pattern": pattern, "max_results": int(max_results)}
        if address:
            body["address"] = address
        if size:
            body["size"] = str(size)
        return j(dbg.call("POST", "/api/search/pattern", body=body, timeout=180))

    @mcp.tool()
    def dbg_search_string(text: str, module: str = "", encoding: str = "utf8") -> str:
        """Search for a text string in target memory (encoding: utf8|ascii|unicode)."""
        return j(dbg.call("POST", "/api/search/string",
                          body={"text": text, "module": module, "encoding": encoding},
                          timeout=120))

    # ---------------------------------------------------------------- patching / dumping
    @mcp.tool()
    def dbg_patch(address: str, bytes_hex: str) -> str:
        """Apply a permanent in-memory patch (tracked by x64dbg so it can be restored)."""
        return j(dbg.call("POST", "/api/patches/apply",
                          body={"address": address, "bytes": bytes_hex}, timeout=60))

    @mcp.tool()
    def dbg_patches() -> str:
        """List applied patches."""
        return j(dbg.call("GET", "/api/patches/list", timeout=30))

    @mcp.tool()
    def dbg_dump_module(module: str, out_file: str, fix_iat: bool = False,
                        oep: str = "") -> str:
        """Dump a loaded module to disk (unpacking) and optionally rebuild the IAT.

        Run it while the process is paused after the packer restored the original
        sections. For VMProtect targets: break at OEP, then dump + fix_iat.
        """
        return j(dbg.dump_module(module, out_file, fix_iat=fix_iat, oep=oep or None))

    @mcp.tool()
    def dbg_hide_debugger() -> str:
        """Ask the plugin to hide the debugger (PEB BeingDebugged, NtGlobalFlag, heap flags)."""
        return j(dbg.call("POST", "/api/antidebug/hide_debugger", timeout=60))

    @mcp.tool()
    def dbg_peb(pid: str = "") -> str:
        """Read the debuggee PEB (anti-debug relevant fields)."""
        return j(dbg.call("GET", "/api/antidebug/peb", {"pid": pid}, timeout=30))

    @mcp.tool()
    def dbg_imports(module: str = "") -> str:
        """Import table of a module as seen by the debugger."""
        return j(dbg.call("GET", "/api/dump/imports", {"module": module}, timeout=60))

    @mcp.tool()
    def dbg_sections_info(module: str = "") -> str:
        """Section table of a module as seen by the debugger (RVA/size/flags)."""
        return j(dbg.call("GET", "/api/dump/sections", {"module": module}, timeout=60))

    # ---------------------------------------------------------------- raw api
    @mcp.tool()
    def dbg_api(method: str, path: str, params: dict[str, Any] | None = None,
                body: Any = None, timeout: float = 120) -> str:
        """Raw passthrough to any x64dbg MCP plugin endpoint, e.g. GET /api/analysis/xrefs_to.

        Call dbg_endpoints() for the full catalog. This unlocks anything without a wrapper.
        """
        if not path.startswith("/api/"):
            raise AgentError("path must start with /api/")
        return j(dbg.call(method.upper(), path, params=params, body=body, timeout=timeout))

    @mcp.tool()
    def dbg_endpoints() -> str:
        """Catalog of the plugin's REST endpoints by area."""
        flat = sorted({path for paths in ENDPOINTS.values() for path in paths})
        return j({"areas": ENDPOINTS, "count": len(flat), "endpoints": flat})
