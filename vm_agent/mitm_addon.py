"""Mitmproxy addon that appends completed HTTP/HTTPS flows as JSON Lines."""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path

from mitmproxy import http

MAX_BODY_BYTES = 262_144
_LOCK = threading.Lock()
_FLOW_COUNTER = 0


def _flows_path() -> Path:
    raw = os.environ.get("VM_AGENT_FLOWS_FILE", "").strip()
    if raw:
        return Path(raw)
    return Path.cwd() / "flows.jsonl"


def _headers_dict(headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items(multi=True):
        key = str(k)
        if key in out:
            out[key] = f"{out[key]}, {v}"
        else:
            out[key] = str(v)
    return out


def _record(flow: http.HTTPFlow, error_text: str = "") -> None:
    global _FLOW_COUNTER
    req = flow.request
    resp = flow.response

    req_raw = req.raw_content or b""
    resp_raw = (resp.raw_content or b"") if resp else b""

    ts_start = getattr(req, "timestamp_start", None) or time.time()
    ts_end = getattr(resp, "timestamp_end", None) if resp else time.time()
    if not ts_end:
        ts_end = time.time()

    with _LOCK:
        _FLOW_COUNTER += 1
        fid = f"{int(ts_start * 1000)}_{_FLOW_COUNTER}"
        entry = {
            "id": fid,
            "ts": round(ts_start, 3),
            "method": req.method,
            "scheme": req.scheme,
            "host": req.pretty_host or req.host,
            "port": req.port,
            "path": req.path,
            "url": req.pretty_url,
            "status": resp.status_code if resp else 0,
            "reason": (resp.reason or "") if resp else error_text,
            "duration_ms": round(max(0.0, (ts_end - ts_start) * 1000.0), 1),
            "req_headers": _headers_dict(req.headers),
            "resp_headers": _headers_dict(resp.headers) if resp else {},
            "req_size": len(req_raw),
            "resp_size": len(resp_raw),
            "req_body_b64": base64.b64encode(req_raw[:MAX_BODY_BYTES]).decode("ascii"),
            "resp_body_b64": base64.b64encode(resp_raw[:MAX_BODY_BYTES]).decode("ascii"),
        }
        p = _flows_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def response(flow: http.HTTPFlow) -> None:
    _record(flow)


def error(flow: http.HTTPFlow) -> None:
    err_msg = str(flow.error.msg) if flow.error else "error"
    _record(flow, error_text=err_msg)
