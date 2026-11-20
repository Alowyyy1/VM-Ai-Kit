"""System, shell and process tools."""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import winapi
from .config import AGENT_VERSION, Config
from .util import AgentError, decode_bytes, human_size, j, norm_path, truncate

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
STARTF_USESHOWWINDOW = 0x00000001


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)


def _run(command: str, *, shell: str, cwd: str | None, timeout: float,
         stdin: str | None, env: dict[str, str] | None) -> dict[str, Any]:
    workdir = None
    if cwd:
        workdir = str(norm_path(cwd))
        if not Path(workdir).is_dir():
            raise AgentError(f"cwd does not exist: {workdir}")

    shell = (shell or "cmd").lower()
    merged_env = _base_env()
    if env:
        merged_env.update({str(k): str(v) for k, v in env.items()})

    started = time.time()
    if shell in ("cmd", "cmd.exe", "batch"):
        full = "chcp 65001>nul & " + command
        argv: Any = full
        use_shell = True
    elif shell in ("powershell", "pwsh", "ps"):
        exe = shutil_which("pwsh.exe") or "powershell.exe"
        prelude = ("$ErrorActionPreference='Continue';"
                   "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                   "$OutputEncoding=[Text.Encoding]::UTF8;")
        argv = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", prelude + command]
        use_shell = False
    else:
        raise AgentError("shell must be 'cmd' or 'powershell'")

    proc = subprocess.Popen(
        argv,
        shell=use_shell,
        cwd=workdir,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
        creationflags=CREATE_NO_WINDOW,
    )
    timed_out = False
    try:
        out, err = proc.communicate(input=stdin.encode("utf-8") if stdin is not None else None,
                                    timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    duration = round(time.time() - started, 3)

    stdout, cut_out = truncate(decode_bytes(out), 120_000)
    stderr, cut_err = truncate(decode_bytes(err), 40_000)
    return {
        "command": command,
        "shell": shell,
        "cwd": workdir or os.getcwd(),
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "duration_s": duration,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": cut_out,
        "stderr_truncated": cut_err,
    }


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def register(mcp, cfg: Config) -> None:
    # ---------------------------------------------------------------- info
    @mcp.tool()
    def sys_info() -> str:
        """Host overview: OS build, CPU, RAM, disks, user/session, privileges, Python and agent version."""
        import psutil

        vm = psutil.virtual_memory()
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            disks.append({
                "drive": part.device,
                "fstype": part.fstype,
                "total": human_size(usage.total),
                "free": human_size(usage.free),
                "used_pct": usage.percent,
            })
        net = []
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    net.append({"adapter": name, "ipv4": addr.address, "netmask": addr.netmask})
        return j({
            "agent_version": AGENT_VERSION,
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()} ({platform.version()})",
            "architecture": platform.machine(),
            "cpu": {"model": platform.processor() or "unknown", "cores": psutil.cpu_count(logical=True),
                    "usage_pct": psutil.cpu_percent(interval=0.3)},
            "memory": {"total": human_size(vm.total), "available": human_size(vm.available),
                       "used_pct": vm.percent},
            "disks": disks,
            "network": net,
            "user": os.environ.get("USERNAME"),
            "domain": os.environ.get("USERDOMAIN"),
            "elevated": winapi.is_elevated(),
            "session_id": winapi.session_id(),
            "interactive_desktop": winapi.session_id() != 0,
            "python": sys.version.split()[0],
            "python_exe": sys.executable,
            "cwd": os.getcwd(),
            "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 2),
            "monitors": list(winapi.screen_size()),
            "foreground_window": winapi.foreground_title(),
        })

    @mcp.tool()
    def sys_env(name: str | None = None, filter: str | None = None) -> str:
        """Read environment variables. `name` returns one value; `filter` is a case-insensitive substring."""
        if name:
            return j({"name": name, "value": os.environ.get(name), "exists": name in os.environ})
        items = dict(sorted(os.environ.items()))
        if filter:
            needle = filter.lower()
            items = {k: v for k, v in items.items() if needle in k.lower() or needle in v.lower()}
        return j({"count": len(items), "variables": items})

    # ---------------------------------------------------------------- exec
    @mcp.tool()
    def sys_exec(command: str, shell: str = "cmd", cwd: str | None = None,
                 timeout: int = 120, stdin: str | None = None,
                 env: dict[str, str] | None = None) -> str:
        """Run a command and capture stdout/stderr/exit code.

        shell: "cmd" (default) or "powershell". timeout is seconds; on timeout the whole
        process tree is killed and timed_out=true is returned.
        """
        timeout = max(1, min(int(timeout or cfg.exec_timeout_default), cfg.exec_timeout_max))
        return j(_run(command, shell=shell, cwd=cwd, timeout=timeout, stdin=stdin, env=env))

    @mcp.tool()
    def sys_powershell(script: str, cwd: str | None = None, timeout: int = 300) -> str:
        """Run a PowerShell script (multi-line is fine) with UTF-8 output."""
        timeout = max(1, min(int(timeout or cfg.exec_timeout_default), cfg.exec_timeout_max))
        return j(_run(script, shell="powershell", cwd=cwd, timeout=timeout, stdin=None, env=None))

    @mcp.tool()
    def sys_start(path: str, args: str = "", cwd: str | None = None, hidden: bool = False,
                  detached: bool = False, wait_seconds: float = 2.0) -> str:
        """Launch an executable. Returns pid; with detached=true the agent does not track it."""
        target = norm_path(path)
        if not target.is_file():
            raise AgentError(f"executable not found: {target}")
        argv = [str(target)] + shlex.split(args or "")
        flags = 0
        startup = None
        if hidden:
            flags |= CREATE_NO_WINDOW
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
        if detached:
            flags |= DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(argv, cwd=str(norm_path(cwd)) if cwd else str(target.parent),
                                creationflags=flags, startupinfo=startup, close_fds=True)
        info: dict[str, Any] = {"pid": proc.pid, "exe": str(target), "args": argv[1:]}
        if wait_seconds > 0 and not detached:
            time.sleep(min(10.0, float(wait_seconds)))
            info["running"] = proc.poll() is None
            if proc.poll() is not None:
                info["exit_code"] = proc.returncode
        return j(info)

    @mcp.tool()
    def sys_processes(filter: str | None = None, sort_by: str = "cpu", limit: int = 60,
                      with_paths: bool = True) -> str:
        """List processes (pid, name, cpu%, rss, path, user) sorted by cpu/mem/pid/name."""
        import psutil

        rows = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "username", "exe"]):
            try:
                info = proc.info
                name = info.get("name") or ""
                if filter and filter.lower() not in name.lower() and filter not in str(info.get("pid")):
                    continue
                mem = info.get("memory_info")
                rows.append({
                    "pid": info["pid"],
                    "name": name,
                    "cpu": info.get("cpu_percent") or 0.0,
                    "rss_mb": round(mem.rss / 1048576, 1) if mem else 0,
                    "user": info.get("username"),
                    "path": info.get("exe") if with_paths else None,
                })
            except Exception:
                continue
        key = {"cpu": lambda r: r["cpu"], "mem": lambda r: r["rss_mb"],
               "pid": lambda r: r["pid"], "name": lambda r: r["name"].lower()}.get(sort_by)
        if key:
            rows.sort(key=key, reverse=sort_by != "name")
        return j({"count": len(rows), "processes": rows[: max(1, int(limit))]})

    @mcp.tool()
    def sys_kill(pid: int | None = None, name: str | None = None, force: bool = True) -> str:
        """Terminate by pid or image name (all matches)."""
        import psutil

        killed = []
        if pid:
            targets = [psutil.Process(int(pid))]
        elif name:
            targets = []
            for proc in psutil.process_iter(["name"]):
                if (proc.info.get("name") or "").lower() == name.lower():
                    targets.append(proc)
        else:
            raise AgentError("provide pid or name")
        for proc in targets:
            try:
                if force:
                    for child in proc.children(recursive=True):
                        try:
                            child.kill()
                        except Exception:
                            pass
                proc.kill() if force else proc.terminate()
                killed.append(proc.pid)
            except Exception as exc:
                killed.append({"pid": getattr(proc, "pid", None), "error": str(exc)})
        return j({"killed": killed, "count": len(killed)})

    @mcp.tool()
    def sys_connections(limit: int = 200, listening_only: bool = False) -> str:
        """TCP/UDP endpoints with owning process (useful to spot C2 / phone-home traffic)."""
        import psutil

        rows = []
        for conn in psutil.net_connections(kind="inet"):
            if listening_only and conn.status != psutil.CONN_LISTEN:
                continue
            try:
                pname = psutil.Process(conn.pid).name() if conn.pid else None
            except Exception:
                pname = None
            rows.append({
                "proto": "tcp" if conn.type == socket.SOCK_STREAM else "udp",
                "local": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "",
                "remote": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "",
                "status": conn.status,
                "pid": conn.pid,
                "process": pname,
            })
        return j({"count": len(rows), "connections": rows[: max(1, int(limit))]})

    @mcp.tool()
    def proc_modules(pid: int | None = None, name: str | None = None) -> str:
        """List modules (DLLs) loaded in a process with base addresses - essential for unpacking."""
        import psutil

        if not pid and name:
            for proc in psutil.process_iter(["pid", "name"]):
                if (proc.info.get("name") or "").lower() == name.lower():
                    pid = proc.info["pid"]
                    break
        if not pid:
            raise AgentError("process not found; pass pid or exact image name")
        mods = winapi.process_modules(int(pid))
        return j({"pid": pid, "count": len(mods),
                  "modules": [m for m in mods if not m["path"].lower().startswith(r"c:\windows")],
                  "system_modules": len([m for m in mods if m["path"].lower().startswith(r"c:\windows")])})
