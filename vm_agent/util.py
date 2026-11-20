"""Small shared helpers: paths, encodings, JSON shaping."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .config import Config


class AgentError(RuntimeError):
    """Error that is reported back to the MCP client as-is."""


# --------------------------------------------------------------------------- json
def j(data: Any, **kwargs: Any) -> str:
    """Compact JSON for tool results."""
    payload = data if not kwargs else {"data": data, **kwargs}
    return json.dumps(payload, ensure_ascii=False, indent=1, default=str)


def ok(**kwargs: Any) -> str:
    return json.dumps({"ok": True, **kwargs}, ensure_ascii=False, indent=1, default=str)


# --------------------------------------------------------------------------- text
def decode_bytes(data: bytes) -> str:
    """Decode console output, trying UTF-8 first and falling back to cp1251."""
    for enc in ("utf-8", "cp1251", "cp866"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        # Reject decodings that produced a lot of replacement characters.
        return text
    return data.decode("utf-8", errors="replace")


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n... <{len(text) - limit} chars truncated> ...\n{text[-tail:]}", True


def human_size(n: int) -> str:
    step = 1024.0
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < step or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= step
    return f"{n} B"


# --------------------------------------------------------------------------- paths
_DRIVE = re.compile(r"^[a-zA-Z]:")


def norm_path(path: str) -> Path:
    if not path or not str(path).strip():
        raise AgentError("path is empty")
    raw = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def guard_path(cfg: Config, path: str, *, write: bool = False) -> Path:
    """Validate a client-supplied path against the configured safety policy."""
    p = norm_path(path)

    if cfg.allow_roots:
        roots = [norm_path(r) for r in cfg.allow_roots]
        if not any(_is_under(p, r) for r in roots):
            raise AgentError(
                f"path '{p}' is outside allow_roots ({', '.join(str(r) for r in roots)})"
            )

    if write:
        if cfg.read_only:
            raise AgentError("agent is in read-only mode")
        if not cfg.allow_protected_writes:
            for prot in cfg.protected_paths:
                try:
                    prot_p = norm_path(prot)
                except AgentError:
                    continue
                if _is_under(p, prot_p):
                    raise AgentError(
                        f"refusing to modify protected path '{p}'. "
                        "Set allow_protected_writes=true in agent.json to override."
                    )
    return p


# --------------------------------------------------------------------------- misc
def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except Exception as exc:
        raise AgentError(f"invalid base64 payload: {exc}") from exc


def from_hex_or_text(value: str) -> bytes:
    """Accept 'AA BB CC', 'aabbcc' or raw text."""
    compact = re.sub(r"[\s,\-]", "", value)
    if compact and len(compact) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", compact):
        return bytes.fromhex(compact)
    return value.encode("utf-8")
