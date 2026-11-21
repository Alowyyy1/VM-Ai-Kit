"""Static analysis tools: PE parsing, strings, AOB search, entropy, disassembly, external tools."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import pe
from .config import Config
from .util import AgentError, decode_bytes, human_size, j, norm_path

CREATE_NO_WINDOW = 0x08000000

# tool id -> (subdirectory under tools_dir, executable)
EXTERNAL_TOOLS = {
    "die": ("die", "diec.exe"),
    "die-gui": ("die", "die.exe"),
    "capa": ("capa", "capa.exe"),
    "strings": ("sysinternals", "strings64.exe"),
    "procdump": ("sysinternals", "procdump64.exe"),
    "handle": ("sysinternals", "handle64.exe"),
    "procexp": ("sysinternals", "procexp64.exe"),
    "pebear": ("pebear", "PE-bear.exe"),
    "dnspy": ("dnspy", "dnSpy.Console.exe"),
    "dnspy-gui": ("dnspy", "dnSpy.exe"),
    "pesieve": ("pesieve", "pe-sieve64.exe"),
    "hollowshunter": ("pesieve", "hollows_hunter64.exe"),
    "rizin": ("rizin/bin", "rizin.exe"),
    "rz-bin": ("rizin/bin", "rz-bin.exe"),
    "goresym": ("goresym", "GoReSym.exe"),
}


def _resolve_tool(cfg: Config, tool: str) -> Path:
    key = tool.lower()
    if key in EXTERNAL_TOOLS:
        sub, exe = EXTERNAL_TOOLS[key]
        path = Path(cfg.tools_dir) / sub / exe
        if not path.is_file():
            raise AgentError(
                f"tool '{key}' not found at {path}. Run install-vm.ps1 or fetch-tools.ps1."
            )
        return path
    candidate = norm_path(tool)
    tools_root = Path(cfg.tools_dir).resolve()
    if candidate.is_file() and str(candidate).lower().startswith(str(tools_root).lower()):
        return candidate
    raise AgentError(f"unknown tool '{tool}'. Known ids: {', '.join(sorted(EXTERNAL_TOOLS))}")


def _run_external(exe: Path, argv: list[str], timeout: float, cwd: Path | None = None) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        [str(exe)] + argv,
        cwd=str(cwd or exe.parent),
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    out = decode_bytes(proc.stdout)
    err = decode_bytes(proc.stderr)
    if len(out) > 200_000:
        out = out[:200_000] + f"\n... truncated ({len(out)} chars total)"
    return {
        "exe": str(exe),
        "argv": argv,
        "exit_code": proc.returncode,
        "duration_s": round(time.time() - started, 2),
        "stdout": out,
        "stderr": err[:20_000],
    }


def register(mcp, cfg: Config) -> None:
    @mcp.tool()
    def pe_info(path: str) -> str:
        """Deep PE inspection: headers, sections, entropy, imports/exports, TLS, resources,
        overlay, rich header, packer heuristics (VMProtect/UPX markers, RawSize=0 sections)."""
        return j(pe.pe_info(path))

    @mcp.tool()
    def pe_strings(path: str, min_length: int = 6, encoding: str = "ascii",
                   limit: int = 1000, search: str = "", offset: int = 0,
                   length: int = 0) -> str:
        """Extract ASCII or UTF-16LE strings from a file (offset/length page through big files)."""
        return j(pe.extract_strings(path, min_length=min_length, encoding=encoding,
                                    limit=limit, search=search or None,
                                    offset=offset, length=length or None))

    @mcp.tool()
    def pe_search(path: str, pattern: str, limit: int = 100, offset: int = 0,
                  length: int = 0) -> str:
        """Search file bytes: hex with wildcards ('E8 ?? ?? ?? ?? 48 89') or plain text."""
        return j(pe.search_bytes(path, pattern, limit=limit, offset=offset,
                                 length=length or None))

    @mcp.tool()
    def pe_disasm(path: str, offset: int = 0, rva: int = 0, count: int = 30,
                  bits: int = 64) -> str:
        """Disassemble a file at a raw offset or RVA (capstone, x86/x64)."""
        return j(pe.disasm(path, offset=offset or None, rva=rva or None,
                           count=count, bits=bits))

    @mcp.tool()
    def pe_entropy(path: str, offset: int = 0, length: int = 0) -> str:
        """Shannon entropy of a file or slice (>7.5 usually means compressed/encrypted)."""
        return j(pe.file_entropy(path, offset=offset, length=length or None))

    @mcp.tool()
    def pe_hexdump(path: str, offset: int = 0, length: int = 256) -> str:
        """Hex + ASCII dump of a file region."""
        return j(pe.hexdump(path, offset=offset, length=length))

    @mcp.tool()
    async def die_scan(path: str, deep: bool = True, show_entropy: bool = False, timeout: float = 60) -> str:
        """Scan a binary with Detect It Easy (DIE) to identify compiler, linker, packer, protector,
        language, libraries, and optionally section entropy."""
        import json
        exe = _resolve_tool(cfg, "die")
        target = norm_path(path)
        if not target.is_file():
            raise AgentError(f"file not found: {path}")
        argv = ["-j"]
        if deep:
            argv.append("-d")
        argv.append(str(target))
        res = await asyncio.to_thread(_run_external, exe, argv, timeout=timeout)
        parsed = {}
        try:
            parsed = json.loads(res["stdout"]) if res["stdout"].strip() else {}
        except Exception:
            parsed = {"raw": res["stdout"]}

        if show_entropy:
            ent_res = await asyncio.to_thread(_run_external, exe, ["-j", "-e", str(target)], timeout=timeout)
            try:
                parsed["entropy"] = json.loads(ent_res["stdout"])
            except Exception:
                parsed["entropy"] = ent_res["stdout"]
        return j({"path": str(target), "result": parsed, "exit_code": res["exit_code"]})

    @mcp.tool()
    async def capa_scan(path: str, timeout: float = 300, json_format: bool = True) -> str:
        """Analyze binary capabilities with Mandiant capa using bundled 1,000+ rules."""
        import json
        exe = _resolve_tool(cfg, "capa")
        target = norm_path(path)
        if not target.is_file():
            raise AgentError(f"file not found: {path}")
        argv = []
        rules = exe.parent / "rules"
        if rules.is_dir():
            argv += ["-r", str(rules)]
        if json_format:
            argv.append("-j")
        argv.append(str(target))
        res = await asyncio.to_thread(_run_external, exe, argv, timeout=timeout)
        parsed = None
        if json_format and res["stdout"].strip():
            try:
                parsed = json.loads(res["stdout"])
            except Exception:
                pass
        return j({
            "path": str(target),
            "result": parsed if parsed is not None else res["stdout"],
            "exit_code": res["exit_code"]
        })

    @mcp.tool()
    async def decompile_dotnet(path: str, type_name: str = "", output_dir: str = "", timeout: float = 180) -> str:
        """Decompile .NET assemblies (C#/VB/IL) to C# pseudocode using dnSpy.Console.
        Pass type_name to decompile a specific class to stdout, or output_dir to export the entire project."""
        exe = _resolve_tool(cfg, "dnspy")
        target = norm_path(path)
        if not target.is_file():
            raise AgentError(f"file not found: {path}")
        argv = []
        if output_dir:
            out_p = norm_path(output_dir)
            out_p.mkdir(parents=True, exist_ok=True)
            argv += ["-o", str(out_p)]
        if type_name:
            argv += ["-t", type_name]
        argv.append(str(target))
        res = await asyncio.to_thread(_run_external, exe, argv, timeout=timeout)
        return j({
            "path": str(target),
            "output_dir": output_dir or None,
            "type_name": type_name or None,
            "stdout": res["stdout"],
            "exit_code": res["exit_code"],
        })

    @mcp.tool()
    async def scan_memory_hollows(pid: int = 0, timeout: float = 120) -> str:
        """Scan running process memory for Process Hollowing, injected code, hooks, or unpacked payloads
        using pe-sieve (if pid specified) or hollows_hunter (all processes)."""
        if pid:
            exe = _resolve_tool(cfg, "pesieve")
            argv = ["/pid", str(pid), "/json"]
        else:
            exe = _resolve_tool(cfg, "hollowshunter")
            argv = ["/json"]
        res = await asyncio.to_thread(_run_external, exe, argv, timeout=timeout)
        return j({
            "target": f"PID {pid}" if pid else "all processes",
            "stdout": res["stdout"],
            "exit_code": res["exit_code"],
        })

    @mcp.tool()
    async def go_symbols(path: str, timeout: float = 60) -> str:
        """Extract Go language symbols, packages, functions, and types from stripped Go binaries using GoReSym."""
        exe = _resolve_tool(cfg, "goresym")
        target = norm_path(path)
        if not target.is_file():
            raise AgentError(f"file not found: {path}")
        res = await asyncio.to_thread(_run_external, exe, [str(target)], timeout=timeout)
        return j({
            "path": str(target),
            "stdout": res["stdout"],
            "exit_code": res["exit_code"],
        })

    @mcp.tool()
    def tool_list() -> str:
        """Bundled tools: x64dbg, ScyllaHide, Scylla, DIE, PE-bear, capa, Sysinternals + their state."""
        rows = []
        for tool, (sub, exe) in EXTERNAL_TOOLS.items():
            path = Path(cfg.tools_dir) / sub / exe
            rows.append({
                "id": tool,
                "path": str(path),
                "present": path.is_file(),
                "size": human_size(path.stat().st_size) if path.is_file() else None,
            })

        def _find_file(candidates: list[Path]) -> tuple[str, bool, str | None]:
            for p in candidates:
                if p.is_file():
                    return str(p), True, human_size(p.stat().st_size)
            return str(candidates[0]), False, None

        scylla_x64_p, scylla_x64_ok, scylla_x64_sz = _find_file([
            Path(cfg.x64dbg_dir) / "x64" / "plugins" / "ScyllaHideX64DBGPlugin.dp64",
            Path(cfg.x64dbg_dir) / "x64" / "plugins" / "ScyllaHide.dp64",
        ])
        scylla_x32_p, scylla_x32_ok, scylla_x32_sz = _find_file([
            Path(cfg.x64dbg_dir) / "x32" / "plugins" / "ScyllaHideX64DBGPlugin.dp32",
            Path(cfg.x64dbg_dir) / "x32" / "plugins" / "ScyllaHide.dp32",
        ])

        py_dir = Path(sys.executable).resolve().parent
        mitmdump_p, mitmdump_ok, mitmdump_sz = _find_file([py_dir / "mitmdump.exe", py_dir / "Scripts" / "mitmdump.exe"])
        mitmweb_p, mitmweb_ok, mitmweb_sz = _find_file([py_dir / "mitmweb.exe", py_dir / "Scripts" / "mitmweb.exe"])

        extra = [
            ("x64dbg x64", Path(cfg.x64dbg_dir) / "x64" / "x64dbg.exe"),
            ("x64dbg x32", Path(cfg.x64dbg_dir) / "x32" / "x32dbg.exe"),
            ("x64dbg_mcp dp64", Path(cfg.x64dbg_dir) / "x64" / "plugins" / "x64dbg_mcp.dp64"),
            ("x64dbg_mcp dp32", Path(cfg.x64dbg_dir) / "x32" / "plugins" / "x64dbg_mcp.dp32"),
            ("ScyllaHide x64", scylla_x64_p, scylla_x64_ok, scylla_x64_sz),
            ("ScyllaHide x32", scylla_x32_p, scylla_x32_ok, scylla_x32_sz),
            ("Scylla", Path(cfg.tools_dir) / "scylla" / "Scylla_x64.exe"),
            ("mitmdump", mitmdump_p, mitmdump_ok, mitmdump_sz),
            ("mitmweb", mitmweb_p, mitmweb_ok, mitmweb_sz),
        ]
        for item in extra:
            if len(item) == 4:
                name, p_str, ok, sz = item
                rows.append({"id": name, "path": p_str, "present": ok, "size": sz})
            else:
                name, path = item
                rows.append({"id": name, "path": str(path), "present": path.is_file(),
                             "size": human_size(path.stat().st_size) if path.is_file() else None})
        return j({"tools_dir": cfg.tools_dir, "tools": rows})

    @mcp.tool()
    async def tool_run(tool: str, args: list[str] | None = None, timeout: float = 300) -> str:
        """Run a bundled CLI tool (die, capa, strings, procdump, handle) with argument list.

        Example: tool_run("die", ["-j", "C:\\\\samples\\\\a.dll"])
                 tool_run("capa", ["C:\\\\samples\\\\a.dll"])
        """
        exe = _resolve_tool(cfg, tool)
        argv = [str(a) for a in (args or [])]
        rules = exe.parent / "rules"
        if exe.name.lower() == "capa.exe" and rules.is_dir() and "-r" not in argv \
                and "--rules" not in argv:
            argv = ["-r", str(rules)] + argv
        res = await asyncio.to_thread(_run_external, exe, argv, timeout=float(timeout))
        return j(res)

    @mcp.tool()
    def tool_gui(tool: str, args: list[str] | None = None) -> str:
        """Launch a bundled GUI tool detached (pebear, die-gui, procexp, scylla not included)."""
        exe = _resolve_tool(cfg, tool)
        proc = subprocess.Popen([str(exe)] + [str(a) for a in (args or [])],
                                cwd=str(exe.parent), creationflags=CREATE_NO_WINDOW)
        return j({"pid": proc.pid, "exe": str(exe)})
