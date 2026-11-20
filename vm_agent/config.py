"""Agent kit configuration.

Resolution order:
  1. $env:AGENTKIT_CONFIG
  2. <kit>\\config\\agent.json          (portable / dev layout)
  3. C:\\AgentKit\\agent.json           (installed layout)
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

AGENT_VERSION = "1.0.0"


def _kit_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_paths() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("AGENTKIT_CONFIG")
    if env:
        out.append(Path(env))
    out.append(_kit_root() / "config" / "agent.json")
    out.append(Path(r"C:\AgentKit\agent.json"))
    return out


def _default_work_dir() -> str:
    if (Path(r"C:\AgentKit")).exists() or os.name == "nt":
        return r"C:\AgentKit\work"
    return str(_kit_root() / "work")


@dataclass
class Config:
    # network
    host: str = "0.0.0.0"
    port: int = 37075
    token: str = ""
    stateless: bool = True
    # layout
    work_dir: str = field(default_factory=_default_work_dir)
    tools_dir: str = r"C:\AgentKit\tools\bin"
    x64dbg_dir: str = r"C:\AgentKit\tools\bin\x64dbg"
    # x64dbg automation plugin (REST API bound to loopback inside the VM)
    x64dbg_host: str = "127.0.0.1"
    x64dbg_port: int = 27042
    x64dbg_token: str = ""
    # safety
    allow_roots: list[str] = field(default_factory=list)
    protected_paths: list[str] = field(
        default_factory=lambda: [r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)"]
    )
    allow_protected_writes: bool = False
    read_only: bool = False
    # limits
    max_chunk_bytes: int = 3 * 1024 * 1024
    max_read_bytes: int = 4 * 1024 * 1024
    exec_timeout_default: int = 60
    exec_timeout_max: int = 1800
    debug_timeout: int = 600
    log_level: str = "INFO"
    log_keep_days: int = 7

    # ------------------------------------------------------------------
    @property
    def work(self) -> Path:
        p = Path(self.work_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def shots(self) -> Path:
        p = self.work / "shots"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads(self) -> Path:
        p = self.work / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def public_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["token"] = "<set>" if self.token else "<empty>"
        data["x64dbg_token"] = "<set>" if self.x64dbg_token else "<empty>"
        data["agent_version"] = AGENT_VERSION
        return data

    def validate(self) -> None:
        loopback = self.host in ("127.0.0.1", "localhost", "::1")
        if not loopback and not self.token:
            raise SystemExit(
                "Refusing to listen on a non-loopback address without a token. "
                "Set 'token' in agent.json (the installer generates one)."
            )
        if len(self.token) < 16 and self.token:
            print("[warn] agent token is shorter than 16 characters", file=sys.stderr)


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    cfg_path = Path(path) if path else next((p for p in _candidate_paths() if p.exists()), None)
    data: dict[str, Any] = {}
    if cfg_path and cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # pragma: no cover - config errors are fatal
            raise SystemExit(f"Cannot read config {cfg_path}: {exc}") from exc

    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        print(f"[warn] ignoring unknown config keys: {', '.join(sorted(unknown))}", file=sys.stderr)

    cfg = Config(**{k: v for k, v in data.items() if k in known})
    if not cfg.token:
        cfg.token = secrets.token_urlsafe(24)
        print("[warn] no token in config, generated an ephemeral one (clients must use it this run)", file=sys.stderr)
    cfg.validate()
    return cfg
