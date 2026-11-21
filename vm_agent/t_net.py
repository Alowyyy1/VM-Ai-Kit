"""HTTP/HTTPS traffic debugger tools backed by mitmproxy (mitmdump / mitmweb)."""
from __future__ import annotations

import asyncio
import base64
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import Config
from .util import AgentError, j

CREATE_NO_WINDOW = 0x08000000
_INTERNET_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _proxy_dir(cfg: Config) -> Path:
    p = cfg.work / "proxy"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _certs_dir(cfg: Config) -> Path:
    p = _proxy_dir(cfg) / "certs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _flows_file(cfg: Config) -> Path:
    return _proxy_dir(cfg) / "flows.jsonl"


def _state_file(cfg: Config) -> Path:
    return _proxy_dir(cfg) / "proxy_state.json"


def _backup_file(cfg: Config) -> Path:
    return _proxy_dir(cfg) / "proxy_backup.json"


def _resolve_mitm_exe(web_ui: bool = False) -> Path:
    name = "mitmweb.exe" if web_ui else "mitmdump.exe"
    py_dir = Path(sys.executable).resolve().parent
    cands = [
        py_dir / name,
        py_dir / "Scripts" / name,
    ]
    for c in cands:
        if c.is_file():
            return c
    found = shutil.which(name)
    if found:
        return Path(found)
    raise AgentError(f"{name} not found. Install mitmproxy in the agent venv: pip install mitmproxy")


def _refresh_wininet() -> None:
    if os.name != "nt":
        return
    try:
        wininet = ctypes.WinDLL("wininet", use_last_error=True)
        # INTERNET_OPTION_SETTINGS_CHANGED = 39, INTERNET_OPTION_REFRESH = 37
        wininet.InternetSetOptionW(None, 39, None, 0)
        wininet.InternetSetOptionW(None, 37, None, 0)
    except Exception:
        pass


def _read_wininet_proxy() -> dict[str, Any]:
    if os.name != "nt":
        return {"ProxyEnable": 0, "ProxyServer": "", "ProxyOverride": ""}
    import winreg

    out: dict[str, Any] = {"ProxyEnable": 0, "ProxyServer": "", "ProxyOverride": ""}
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _INTERNET_SUBKEY) as key:
        for field, default in (("ProxyEnable", 0), ("ProxyServer", ""), ("ProxyOverride", "")):
            try:
                val, _ = winreg.QueryValueEx(key, field)
                out[field] = val
            except FileNotFoundError:
                out[field] = default
    return out


def _write_wininet_proxy(enable: int, server: str = "", override: str = "<local>") -> None:
    if os.name != "nt":
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _INTERNET_SUBKEY) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(enable))
        if server is not None:
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, str(server))
        if override is not None:
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, str(override))
    _refresh_wininet()


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import psutil
        p = psutil.Process(int(pid))
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _load_state(cfg: Config) -> dict[str, Any]:
    sf = _state_file(cfg)
    if not sf.is_file():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(cfg: Config, state: dict[str, Any]) -> None:
    _state_file(cfg).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    else:
        import psutil
        psutil.Process(pid).kill()


def _decode_body(b64: str, max_bytes: int) -> dict[str, Any]:
    if not b64:
        return {"size": 0, "encoding": "empty", "text": ""}
    raw = base64.b64decode(b64)
    truncated = len(raw) > max_bytes
    sliced = raw[:max_bytes]
    try:
        text = sliced.decode("utf-8")
        return {"size": len(raw), "truncated": truncated, "encoding": "utf-8", "text": text}
    except UnicodeDecodeError:
        return {
            "size": len(raw),
            "truncated": truncated,
            "encoding": "base64",
            "base64": base64.b64encode(sliced).decode("ascii"),
        }


def register(mcp, cfg: Config) -> None:
    @mcp.tool()
    async def net_proxy_install_cert() -> str:
        """Generate mitmproxy CA certificate into work/proxy/certs (ASCII-safe) and install it into Windows Trusted Root."""
        def _do_install() -> dict[str, Any]:
            certs = _certs_dir(cfg)
            cer_path = certs / "mitmproxy-ca-cert.cer"
            if not cer_path.is_file():
                exe = _resolve_mitm_exe(web_ui=False)
                # Launch mitmdump briefly on a free ephemeral port just to generate CA certs in confdir
                proc = subprocess.Popen(
                    [str(exe), "--listen-host", "127.0.0.1", "--listen-port", "0",
                     "--set", f"confdir={certs}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
                deadline = time.time() + 10.0
                while time.time() < deadline and not cer_path.is_file():
                    time.sleep(0.25)
                _kill_pid(proc.pid)

            if not cer_path.is_file():
                raise AgentError(f"mitmproxy CA certificate was not generated in {certs}")

            res = subprocess.run(
                ["certutil", "-user", "-addstore", "Root", str(cer_path)],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            # Also attempt LocalMachine store (agent runs elevated) so system services/WinHTTP trust it
            res_lm = subprocess.run(
                ["certutil", "-addstore", "Root", str(cer_path)],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            return {
                "cert_path": str(cer_path),
                "user_store_exit": res.returncode,
                "machine_store_exit": res_lm.returncode,
                "installed": (res.returncode == 0 or res_lm.returncode == 0),
            }

        res_dict = await asyncio.to_thread(_do_install)
        return j(res_dict)

    @mcp.tool()
    async def net_proxy_start(
        port: int = 8080,
        web_ui: bool = False,
        web_port: int = 8081,
        set_system_proxy: bool = True,
        upstream: str = "",
    ) -> str:
        """Start HTTP/HTTPS MITM traffic debugger (mitmdump/mitmweb) and optionally set Windows system proxy."""
        state = _load_state(cfg)
        if state.get("pid") and _pid_alive(int(state["pid"])):
            return j({"already_running": True, **state})

        exe = _resolve_mitm_exe(web_ui=web_ui)
        certs = _certs_dir(cfg)
        flows = _flows_file(cfg)
        addon = Path(__file__).resolve().parent / "mitm_addon.py"
        if not addon.is_file():
            raise AgentError(f"mitm_addon.py not found at {addon}")

        argv = [
            str(exe),
            "--listen-host", "127.0.0.1",
            "--listen-port", str(int(port)),
            "--set", f"confdir={certs}",
            "-s", str(addon),
        ]
        if web_ui:
            argv += ["--web-host", "127.0.0.1", "--web-port", str(int(web_port)), "--no-web-open-browser"]
        if upstream:
            argv += ["--mode", f"upstream:{upstream}"]

        env = os.environ.copy()
        env["VM_AGENT_FLOWS_FILE"] = str(flows)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        log_path = _proxy_dir(cfg) / "mitmproxy.log"
        log_fh = log_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(
            argv,
            cwd=str(_proxy_dir(cfg)),
            env=env,
            stdout=log_fh,
            stderr=log_fh,
            creationflags=CREATE_NO_WINDOW,
        )
        await asyncio.sleep(1.5)
        if proc.poll() is not None:
            log_fh.close()
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-1000:]
            raise AgentError(f"mitmproxy exited immediately (code {proc.returncode}): {tail}")

        if set_system_proxy:
            bak = _backup_file(cfg)
            if not bak.is_file():
                bak.write_text(json.dumps(_read_wininet_proxy(), indent=2), encoding="utf-8")
            _write_wininet_proxy(1, f"127.0.0.1:{int(port)}", "<local>")

        new_state = {
            "pid": proc.pid,
            "port": int(port),
            "web_ui": bool(web_ui),
            "web_url": f"http://127.0.0.1:{int(web_port)}" if web_ui else None,
            "system_proxy_set": bool(set_system_proxy),
            "flows_file": str(flows),
            "certs_dir": str(certs),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_state(cfg, new_state)
        return j({"started": True, **new_state})

    @mcp.tool()
    def net_proxy_stop(restore_system_proxy: bool = True) -> str:
        """Stop the MITM traffic debugger and restore Windows system proxy settings."""
        state = _load_state(cfg)
        pid = int(state.get("pid") or 0)
        stopped = False
        if pid and _pid_alive(pid):
            _kill_pid(pid)
            stopped = True

        restored = False
        if restore_system_proxy:
            bak = _backup_file(cfg)
            if bak.is_file():
                try:
                    orig = json.loads(bak.read_text(encoding="utf-8"))
                    _write_wininet_proxy(
                        int(orig.get("ProxyEnable", 0)),
                        str(orig.get("ProxyServer", "")),
                        str(orig.get("ProxyOverride", "<local>")),
                    )
                    bak.unlink(missing_ok=True)
                    restored = True
                except Exception:
                    _write_wininet_proxy(0, "")
                    restored = True
            else:
                _write_wininet_proxy(0, "")
                restored = True

        _state_file(cfg).unlink(missing_ok=True)
        return j({"stopped": stopped, "pid": pid or None, "system_proxy_restored": restored,
                  "wininet": _read_wininet_proxy()})

    @mcp.tool()
    def net_proxy_status() -> str:
        """Return status of MITM proxy, captured flow count, CA cert path, and Windows WinINET proxy state."""
        state = _load_state(cfg)
        pid = int(state.get("pid") or 0)
        running = _pid_alive(pid) if pid else False
        flows = _flows_file(cfg)
        flow_count = 0
        if flows.is_file():
            with flows.open("r", encoding="utf-8", errors="replace") as fh:
                flow_count = sum(1 for _ in fh)
        cer = _certs_dir(cfg) / "mitmproxy-ca-cert.cer"
        return j({
            "running": running,
            "pid": pid if running else None,
            "port": state.get("port"),
            "web_url": state.get("web_url"),
            "flows_file": str(flows),
            "flow_count": flow_count,
            "cert_path": str(cer),
            "cert_exists": cer.is_file(),
            "wininet_proxy": _read_wininet_proxy(),
        })

    @mcp.tool()
    def net_proxy_flows(
        limit: int = 50,
        host_filter: str = "",
        method: str = "",
        status_code: int = 0,
        search: str = "",
    ) -> str:
        """List recent captured HTTP/HTTPS flows with optional host, method, status, or substring filter."""
        flows = _flows_file(cfg)
        if not flows.is_file():
            return j({"count": 0, "flows": []})
        limit = max(1, min(500, int(limit)))
        hf = host_filter.strip().lower()
        mf = method.strip().upper()
        sf = search.strip().lower()
        items: list[dict[str, Any]] = []
        with flows.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if hf and hf not in str(row.get("host", "")).lower():
                    continue
                if mf and mf != str(row.get("method", "")).upper():
                    continue
                if status_code and int(row.get("status", 0)) != int(status_code):
                    continue
                if sf:
                    hay = (str(row.get("url", "")) + " " + json.dumps(row.get("req_headers", {}))).lower()
                    if sf not in hay:
                        continue
                items.append({
                    "id": row.get("id"),
                    "ts": row.get("ts"),
                    "method": row.get("method"),
                    "url": row.get("url"),
                    "status": row.get("status"),
                    "duration_ms": row.get("duration_ms"),
                    "req_size": row.get("req_size"),
                    "resp_size": row.get("resp_size"),
                })
        recent = items[-limit:]
        return j({"total_matched": len(items), "count": len(recent), "flows": recent})

    @mcp.tool()
    def net_proxy_flow_detail(
        flow_id: str,
        include_body: bool = True,
        max_body_bytes: int = 16384,
    ) -> str:
        """Inspect full request/response headers and decoded body for a specific captured flow_id."""
        flows = _flows_file(cfg)
        if not flows.is_file():
            raise AgentError("no flows captured yet")
        max_b = max(256, min(262_144, int(max_body_bytes)))
        with flows.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if str(row.get("id")) == str(flow_id):
                    out = {
                        "id": row.get("id"),
                        "ts": row.get("ts"),
                        "method": row.get("method"),
                        "url": row.get("url"),
                        "status": row.get("status"),
                        "reason": row.get("reason"),
                        "duration_ms": row.get("duration_ms"),
                        "req_headers": row.get("req_headers"),
                        "resp_headers": row.get("resp_headers"),
                        "req_size": row.get("req_size"),
                        "resp_size": row.get("resp_size"),
                    }
                    if include_body:
                        out["req_body"] = _decode_body(row.get("req_body_b64", ""), max_b)
                        out["resp_body"] = _decode_body(row.get("resp_body_b64", ""), max_b)
                    return j(out)
        raise AgentError(f"flow_id not found: {flow_id}")

    @mcp.tool()
    def net_proxy_clear() -> str:
        """Clear all captured HTTP/HTTPS flows from work/proxy/flows.jsonl."""
        flows = _flows_file(cfg)
        if flows.is_file():
            flows.unlink()
        return j({"cleared": True, "flows_file": str(flows)})
