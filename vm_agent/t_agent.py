"""Agent self-checks, configuration view, log access and a built-in workflow cheat-sheet."""
from __future__ import annotations

import importlib
import os
import socket
import sys
from pathlib import Path

from . import winapi
from .config import AGENT_VERSION, Config
from .util import AgentError, human_size, j
from .x64dbg import X64Dbg

REQUIRED_MODULES = ["mcp", "mss", "PIL", "psutil", "pefile", "capstone"]


def register(mcp, cfg: Config) -> None:
    @mcp.tool()
    def agent_selftest() -> str:
        """Verify the installation end-to-end: deps, permissions, tools, screenshot, clipboard, debugger."""
        checks: list[dict] = []

        def add(name: str, ok: bool, detail: str = "", level: str = "error") -> None:
            checks.append({"check": name, "ok": ok,
                           "level": "ok" if ok else level, "detail": detail})

        add("windows", os.name == "nt", sys.platform)
        add("python", sys.version_info >= (3, 10), sys.version.split()[0])
        for name in REQUIRED_MODULES:
            try:
                module = importlib.import_module(name)
                add(f"module:{name}", True, getattr(module, "__version__", "ok"))
            except Exception as exc:
                add(f"module:{name}", False, str(exc))

        add("admin", winapi.is_elevated(),
            "running elevated" if winapi.is_elevated() else "not elevated (some operations will fail)",
            level="warn")
        add("interactive_session", winapi.session_id() != 0, f"session {winapi.session_id()}")

        work = cfg.work
        try:
            probe = work / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            add("work_dir_writable", True, str(work))
        except Exception as exc:
            add("work_dir_writable", False, f"{work}: {exc}")

        try:
            import mss

            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
                add("screen_capture", shot.width > 0 and shot.height > 0,
                    f"{shot.width}x{shot.height}")
        except Exception as exc:
            add("screen_capture", False, str(exc))

        try:
            winapi.clipboard_set("agentkit-selftest")
            value = winapi.clipboard_get()
            add("clipboard", value == "agentkit-selftest", value[:40])
        except Exception as exc:
            add("clipboard", False, str(exc))

        dbg = X64Dbg(cfg)
        try:
            exe = dbg.exe(False)
            add("x64dbg_x64", True, str(exe))
        except AgentError as exc:
            add("x64dbg_x64", False, str(exc))
        try:
            exe32 = dbg.exe(True)
            add("x64dbg_x32", True, str(exe32))
        except AgentError as exc:
            add("x64dbg_x32", False, str(exc))

        scylla_x64 = next(
            (p for p in (
                Path(cfg.x64dbg_dir) / "x64" / "plugins" / "ScyllaHideX64DBGPlugin.dp64",
                Path(cfg.x64dbg_dir) / "x64" / "plugins" / "ScyllaHide.dp64",
            ) if p.is_file()),
            Path(cfg.x64dbg_dir) / "x64" / "plugins" / "ScyllaHideX64DBGPlugin.dp64",
        )
        scylla_x32 = next(
            (p for p in (
                Path(cfg.x64dbg_dir) / "x32" / "plugins" / "ScyllaHideX64DBGPlugin.dp32",
                Path(cfg.x64dbg_dir) / "x32" / "plugins" / "ScyllaHide.dp32",
            ) if p.is_file()),
            Path(cfg.x64dbg_dir) / "x32" / "plugins" / "ScyllaHideX64DBGPlugin.dp32",
        )
        py_dir = Path(sys.executable).resolve().parent
        mitmdump_exe = next(
            (p for p in (py_dir / "mitmdump.exe", py_dir / "Scripts" / "mitmdump.exe") if p.is_file()),
            py_dir / "mitmdump.exe",
        )

        for label, path in [
            ("plugin_dp64", Path(cfg.x64dbg_dir) / "x64" / "plugins" / "x64dbg_mcp.dp64"),
            ("plugin_dp32", Path(cfg.x64dbg_dir) / "x32" / "plugins" / "x64dbg_mcp.dp32"),
            ("scyllahide_x64", scylla_x64),
            ("scyllahide_x32", scylla_x32),
            ("die", Path(cfg.tools_dir) / "die" / "diec.exe"),
            ("capa", Path(cfg.tools_dir) / "capa" / "capa.exe"),
            ("pebear", Path(cfg.tools_dir) / "pebear" / "PE-bear.exe"),
            ("scylla", Path(cfg.tools_dir) / "scylla" / "Scylla_x64.exe"),
            ("pesieve", Path(cfg.tools_dir) / "pesieve" / "pe-sieve64.exe"),
            ("hollowshunter", Path(cfg.tools_dir) / "pesieve" / "hollows_hunter64.exe"),
            ("dnspy", Path(cfg.tools_dir) / "dnspy" / "dnSpy.Console.exe"),
            ("rizin", Path(cfg.tools_dir) / "rizin" / "bin" / "rizin.exe"),
            ("goresym", Path(cfg.tools_dir) / "goresym" / "GoReSym.exe"),
            ("sysinternals", Path(cfg.tools_dir) / "sysinternals" / "strings64.exe"),
            ("mitmdump", mitmdump_exe),
            ("vc_redist", Path(r"C:\Windows\System32\vcruntime140.dll")),
        ]:
            add(label, path.is_file(), str(path), level="warn")

        health = dbg.health()
        add("x64dbg_plugin", bool(health.get("reachable")),
            f"running: {len(dbg.running())} instance(s); {health.get('error') or 'reachable'}",
            level="warn")

        try:
            import psutil

            usage = psutil.disk_usage(str(work.anchor))
            add("disk_free", usage.free > 2 * 1024**3, human_size(usage.free), level="warn")
        except Exception:
            pass

        add("token", len(cfg.token) >= 16, f"{len(cfg.token)} chars")
        add("listen", True, f"http://{cfg.host}:{cfg.port}/mcp")

        failed = [c for c in checks if not c["ok"] and c["level"] == "error"]
        warned = [c for c in checks if not c["ok"] and c["level"] == "warn"]
        return j({
            "agent_version": AGENT_VERSION,
            "hostname": socket.gethostname(),
            "result": "fail" if failed else ("warn" if warned else "ok"),
            "errors": len(failed),
            "warnings": len(warned),
            "checks": checks,
        })

    @mcp.tool()
    def agent_config() -> str:
        """Active agent configuration with secrets redacted."""
        return j(cfg.public_dict())

    @mcp.tool()
    def agent_logs(lines: int = 100, level: str = "") -> str:
        """Tail the agent log (work_dir/agent.log). level filters by substring, e.g. ERROR."""
        path = cfg.work / "agent.log"
        if not path.is_file():
            return j({"path": str(path), "lines": []})
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if level:
            content = [line for line in content if level.upper() in line.upper()]
        tail = content[-max(1, min(2000, int(lines))):]
        return j({"path": str(path), "count": len(tail), "lines": tail})

    @mcp.tool()
    def agent_guide(topic: str = "overview") -> str:
        """Cheat-sheet for driving this VM: overview | unpack | dota | traffic | transfer | screen."""
        topic = (topic or "overview").lower()
        guides = {
            "overview": [
                "Files: fs_* or direct HTTP GET /files/download?path=... and POST /files/upload?path=...",
                "Shell: sys_exec(shell=cmd|powershell); long jobs -> sys_start(detached=true) or sys_exec with big timeout.",
                "Screen: screen_capture (inline PNG) + input_click/input_type/input_key; win_list/win_focus to target windows.",
                "Processes: sys_processes, proc_modules(pid) (module base addresses), sys_connections (phone-home).",
                "Traffic: net_proxy_install_cert -> net_proxy_start -> net_proxy_flows -> net_proxy_flow_detail -> net_proxy_stop.",
                "Debug: dbg_launch(target) -> dbg_status -> dbg_set_breakpoint -> dbg_run -> dbg_read_memory/dbg_dump_module.",
                "Static: pe_info, pe_strings, pe_search, pe_disasm, die_scan, capa_scan, decompile_dotnet, go_symbols.",
                "Anything not covered by the wrappers: dbg_api(method, path, body).",
            ],
            "unpack": [
                "1. dbg_launch(target) and let the packer run (VMProtect decrypts sections on the fly).",
                "2. Static first: pe_info shows RawSize=0 sections + entropy; note SizeOfImage and section RVAs.",
                "3. Find OEP: breakpoint on VirtualProtect (or on the last section's entry), run, then inspect memmap for RWX->RX transitions.",
                "4. Once the real .text is restored and you are at OEP: dbg_dump_module(module, out, fix_iat=true, oep=<oep>).",
                "5. Re-run pe_info on the dump; compare section entropy and imports with the packed file.",
                "6. ScyllaHide is installed in x64dbg: Plugins -> ScyllaHide, or dbg_hide_debugger for the PEB flags.",
            ],
            "dota": [
                "Target process is usually 'Dota2.exe'; the cheat expects to be injected via LoadLibrary.",
                "proc_modules(pid) gives the module list + bases after injection; look for localHero.dll.",
                "To follow VMProtect code: dbg_attach(pid), then use dbg_memmap, dbg_sections(address), dbg_disasm.",
                "The packer restores pages at runtime: dump after the module's entry point has executed.",
                "Keep the VM isolated (host-only network) - the sample may phone home.",
            ],
            "traffic": [
                "1. First time on a clean system: net_proxy_install_cert() installs the mitmproxy Root CA into Trusted Root.",
                "2. Start capture: net_proxy_start(port=8080, web_ui=False, set_system_proxy=True) sets WinINET proxy automatically.",
                "3. Run the sample or make requests; use net_proxy_flows(limit=50, host_filter=...) to inspect captured traffic.",
                "4. Inspect headers and payload: net_proxy_flow_detail(flow_id) decodes UTF-8 or returns base64.",
                "5. Always finish with net_proxy_stop(restore_system_proxy=True) to cleanly disable the Windows proxy.",
            ],
            "transfer": [
                "Fast HTTP upload: POST http://<vm>:37075/files/upload?path=C:\\temp\\file.bin (raw body + Bearer token).",
                "Fast HTTP download: GET http://<vm>:37075/files/download?path=C:\\temp\\dump.dll (Bearer token).",
                "MCP chunked upload: fs_write_bytes(path, chunk_b64, mode='patch', offset=N) in <=3 MB chunks; pass expect_sha256.",
                "MCP chunked download: fs_read_bytes(path, offset, length<=4MB, format='base64') until next_offset is null.",
                "Always verify with fs_hash(path,'sha256') on both sides.",
            ],
            "screen": [
                "screen_info tells you monitor indexes and physical pixel bounds.",
                "screen_capture(monitor=0, scale=0.5) keeps images small enough for the model.",
                "Focus first: win_focus(title='Dota 2'), then input_click / input_key / input_type.",
                "DirectX fullscreen games may capture black - use borderless/windowed mode in the VM.",
            ],
        }
        if topic not in guides:
            raise AgentError(f"unknown topic '{topic}'; available: {', '.join(guides)}")
        return j({"topic": topic, "steps": guides[topic]})
