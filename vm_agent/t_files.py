"""File system tools: browse, read/write (text + binary chunks), search, pack, hash."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from .config import Config
from .util import (AgentError, b64d, b64e, guard_path, human_size, j, truncate)

_TEXT_LIMIT = 200_000


def _entry(p: Path, root: Path) -> dict[str, Any]:
    try:
        st = p.stat()
        size = st.st_size
        mtime = st.st_mtime
        is_dir = p.is_dir()
    except OSError:
        size, mtime, is_dir = 0, 0, False
    return {
        "name": p.name,
        "path": str(p),
        "rel": str(p.relative_to(root)) if p != root else ".",
        "dir": is_dir,
        "size": None if is_dir else size,
        "size_human": None if is_dir else human_size(size),
        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)) if mtime else None,
    }


def _sha(path: Path, algo: str = "sha256") -> str:
    try:
        h = hashlib.new(algo)
    except ValueError as exc:
        raise AgentError(f"unsupported hash algorithm: {algo}") from exc
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def register(mcp, cfg: Config) -> None:
    @mcp.tool()
    def fs_list(path: str = ".", pattern: str = "*", recursive: bool = False,
                include_dirs: bool = True, limit: int = 500) -> str:
        """List a directory (glob filter, optional recursion), dirs first."""
        root = guard_path(cfg, path)
        if not root.exists():
            raise AgentError(f"path not found: {root}")
        if root.is_file():
            return j({"path": str(root), "entries": [_entry(root, root.parent)]})
        limit = max(1, min(5000, int(limit)))
        entries: list[dict[str, Any]] = []
        iterator = root.rglob("*") if recursive else root.iterdir()
        for item in iterator:
            if not fnmatch.fnmatch(item.name.lower(), pattern.lower() if os.name == "nt" else pattern):
                continue
            is_dir = item.is_dir()
            if is_dir and not include_dirs:
                continue
            entries.append(_entry(item, root))
            if len(entries) >= limit:
                break
        entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
        return j({"path": str(root), "count": len(entries),
                  "truncated": len(entries) >= limit, "entries": entries})

    @mcp.tool()
    def fs_stat(path: str) -> str:
        """File/directory metadata: size, timestamps, attributes, sha256 for files."""
        p = guard_path(cfg, path)
        if not p.exists():
            raise AgentError(f"path not found: {p}")
        st = p.stat()
        info = {
            "path": str(p),
            "dir": p.is_dir(),
            "size": st.st_size,
            "size_human": human_size(st.st_size),
            "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_ctime)),
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "readonly": not os.access(p, os.W_OK),
        }
        if p.is_file():
            info["sha256"] = _sha(p)
            info["extension"] = p.suffix.lower()
        else:
            info["children"] = len(list(p.iterdir())) if p.is_dir() else 0
        return j(info)

    @mcp.tool()
    def fs_read_text(path: str, offset: int = 0, max_bytes: int = _TEXT_LIMIT,
                     encoding: str = "utf-8") -> str:
        """Read a text file (or slice of it). Use offset to page through large files."""
        p = guard_path(cfg, path)
        if not p.is_file():
            raise AgentError(f"not a file: {p}")
        max_bytes = max(1, min(int(max_bytes), cfg.max_read_bytes))
        with p.open("rb") as fh:
            fh.seek(max(0, int(offset)))
            raw = fh.read(max_bytes + 1)
        more = len(raw) > max_bytes
        raw = raw[:max_bytes]
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            text = raw.decode(encoding, errors="replace")
        text, cut = truncate(text, _TEXT_LIMIT)
        return j({"path": str(p), "offset": offset, "encoding": encoding,
                  "bytes_read": len(raw), "next_offset": int(offset) + len(raw) if more else None,
                  "truncated": cut, "text": text})

    @mcp.tool()
    def fs_write_text(path: str, content: str, append: bool = False,
                      encoding: str = "utf-8", create_dirs: bool = True) -> str:
        """Write or append a text file (creates parent directories)."""
        p = guard_path(cfg, path, write=True)
        if create_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a" if append else "w", encoding=encoding, newline="") as fh:
            fh.write(content)
        return j({"path": str(p), "bytes": p.stat().st_size, "mode": "append" if append else "overwrite"})

    @mcp.tool()
    def fs_replace_text(path: str, old: str, new: str, count: int = 0,
                        encoding: str = "utf-8") -> str:
        """Exact substring replacement in a text file (count=0 replaces all)."""
        p = guard_path(cfg, path, write=True)
        if not p.is_file():
            raise AgentError(f"not a file: {p}")
        text = p.read_text(encoding=encoding)
        limit = -1 if not count else int(count)
        occurrences = text.count(old)
        if occurrences == 0:
            return j({"path": str(p), "replacements": 0, "message": "pattern not found"})
        updated = text.replace(old, new, limit)
        p.write_text(updated, encoding=encoding, newline="")
        return j({"path": str(p), "replacements": min(occurrences, limit) if limit > 0 else occurrences,
                  "bytes": len(updated.encode(encoding))})

    @mcp.tool()
    def fs_read_bytes(path: str, offset: int = 0, length: int = 262_144,
                      format: str = "base64") -> str:
        """Read raw bytes. format: base64 (default) | hex | text. Chunk large files with offset."""
        p = guard_path(cfg, path)
        if not p.is_file():
            raise AgentError(f"not a file: {p}")
        length = max(1, min(int(length), cfg.max_read_bytes))
        size = p.stat().st_size
        with p.open("rb") as fh:
            fh.seek(max(0, int(offset)))
            data = fh.read(length)
        fmt = (format or "base64").lower()
        if fmt in ("base64", "b64"):
            payload: Any = b64e(data)
        elif fmt == "hex":
            payload = data.hex(" ")
        elif fmt == "text":
            payload = data.decode("utf-8", "replace")
        else:
            raise AgentError("format must be base64, hex or text")
        end = int(offset) + len(data)
        return j({"path": str(p), "offset": offset, "length": len(data), "file_size": size,
                  "next_offset": end if end < size else None, "eof": end >= size,
                  "sha256_of_chunk": hashlib.sha256(data).hexdigest(), "format": fmt, "data": payload})

    @mcp.tool()
    def fs_write_bytes(path: str, data: str, format: str = "base64", mode: str = "overwrite",
                       offset: int = 0, create_dirs: bool = True,
                       expect_sha256: str | None = None) -> str:
        """Write raw bytes (or a chunk). modes: overwrite | append | patch (patch uses offset).

        Chunked upload: call with mode="patch", increasing offset, ~3 MB per call; pass
        expect_sha256 on the final call to verify the assembled file.
        """
        if cfg.read_only:
            raise AgentError("agent is in read-only mode")
        p = guard_path(cfg, path, write=True)
        fmt = (format or "base64").lower()
        try:
            if fmt in ("base64", "b64"):
                raw = b64d(data)
            elif fmt == "hex":
                raw = bytes.fromhex(data.replace(" ", "").replace("\n", ""))
            elif fmt == "text":
                raw = data.encode("utf-8")
            else:
                raise AgentError("format must be base64, hex or text")
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(f"cannot decode payload: {exc}") from exc

        if len(raw) > cfg.max_chunk_bytes:
            raise AgentError(f"chunk too large ({len(raw)} > {cfg.max_chunk_bytes} bytes); split it")

        if create_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)

        mode = (mode or "overwrite").lower()
        if mode == "overwrite":
            p.write_bytes(raw)
        elif mode == "append":
            with p.open("ab") as fh:
                fh.write(raw)
        elif mode == "patch":
            offset = int(offset)
            if offset < 0:
                raise AgentError("offset must be >= 0")
            existing = p.stat().st_size if p.exists() else 0
            if offset > existing:
                raise AgentError(f"patch offset {offset} is past EOF ({existing})")
            with p.open("r+b" if p.exists() else "w+b") as fh:
                fh.seek(offset)
                fh.write(raw)
        else:
            raise AgentError("mode must be overwrite, append or patch")

        size = p.stat().st_size
        result = {"path": str(p), "mode": mode, "bytes_written": len(raw), "file_size": size}
        if expect_sha256:
            actual = _sha(p)
            result["sha256"] = actual
            result["sha256_match"] = actual.lower() == expect_sha256.strip().lower()
            if not result["sha256_match"]:
                raise AgentError(f"sha256 mismatch: expected {expect_sha256}, got {actual}")
        return j(result)

    @mcp.tool()
    def fs_mkdir(path: str) -> str:
        """Create a directory (parents included)."""
        p = guard_path(cfg, path, write=True)
        p.mkdir(parents=True, exist_ok=True)
        return j({"path": str(p), "created": True})

    @mcp.tool()
    def fs_delete(path: str, recursive: bool = False) -> str:
        """Delete a file, or a directory with recursive=true."""
        p = guard_path(cfg, path, write=True)
        if not p.exists():
            raise AgentError(f"path not found: {p}")
        if p.is_dir():
            if not recursive:
                raise AgentError("directory delete requires recursive=true")
            if p.parent == p:
                raise AgentError("refusing to delete a drive root")
            shutil.rmtree(p)
        else:
            p.unlink()
        return j({"path": str(p), "deleted": True})

    @mcp.tool()
    def fs_copy(src: str, dst: str, overwrite: bool = False) -> str:
        """Copy a file or directory tree."""
        s = guard_path(cfg, src)
        d = guard_path(cfg, dst, write=True)
        if not s.exists():
            raise AgentError(f"source not found: {s}")
        if d.exists() and not overwrite:
            raise AgentError(f"destination exists: {d} (set overwrite=true)")
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
        return j({"src": str(s), "dst": str(d), "size": d.stat().st_size if d.is_file() else None})

    @mcp.tool()
    def fs_move(src: str, dst: str, overwrite: bool = False) -> str:
        """Move/rename a file or directory."""
        s = guard_path(cfg, src, write=True)
        d = guard_path(cfg, dst, write=True)
        if not s.exists():
            raise AgentError(f"source not found: {s}")
        if d.exists() and not overwrite:
            raise AgentError(f"destination exists: {d} (set overwrite=true)")
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            shutil.rmtree(d) if d.is_dir() else d.unlink()
        shutil.move(str(s), str(d))
        return j({"src": str(s), "dst": str(d), "moved": True})

    @mcp.tool()
    def fs_hash(path: str, algo: str = "sha256") -> str:
        """Hash a file: sha256 (default), sha1, md5, ..."""
        p = guard_path(cfg, path)
        if not p.is_file():
            raise AgentError(f"not a file: {p}")
        return j({"path": str(p), "algo": algo, "hash": _sha(p, algo), "size": p.stat().st_size})

    @mcp.tool()
    def fs_zip(src: str, dst: str, include_root: bool = False) -> str:
        """Create a .zip from a file or directory."""
        s = guard_path(cfg, src)
        d = guard_path(cfg, dst, write=True)
        if not s.exists():
            raise AgentError(f"source not found: {s}")
        if d.suffix.lower() != ".zip":
            d = d.with_suffix(".zip")
        d.parent.mkdir(parents=True, exist_ok=True)
        base = s.parent if not include_root else s.parent.parent
        count = 0
        with zipfile.ZipFile(d, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            if s.is_file():
                zf.write(s, s.name)
                count = 1
            else:
                for root, _dirs, files in os.walk(s):
                    for name in files:
                        full = Path(root) / name
                        if full == d:
                            continue
                        zf.write(full, str(full.relative_to(base)))
                        count += 1
        return j({"zip": str(d), "entries": count, "size": d.stat().st_size})

    @mcp.tool()
    def fs_unzip(src: str, dst: str, overwrite: bool = True) -> str:
        """Extract a .zip (protects against path traversal)."""
        s = guard_path(cfg, src)
        d = guard_path(cfg, dst, write=True)
        if not s.is_file():
            raise AgentError(f"not a file: {s}")
        d.mkdir(parents=True, exist_ok=True)
        extracted = 0
        with zipfile.ZipFile(s) as zf:
            for member in zf.infolist():
                target = (d / member.filename).resolve()
                if not str(target).startswith(str(d)):
                    raise AgentError(f"unsafe path in archive: {member.filename}")
                if target.exists() and not overwrite:
                    continue
                zf.extract(member, d)
                extracted += 1
        return j({"zip": str(s), "dst": str(d), "extracted": extracted})

    @mcp.tool()
    def fs_search(root: str, name_pattern: str = "*", content: str | None = None,
                  max_results: int = 200, max_file_mb: int = 16) -> str:
        """Find files by name glob and/or text content under a root directory."""
        base = guard_path(cfg, root)
        if not base.is_dir():
            raise AgentError(f"not a directory: {base}")
        max_results = max(1, min(2000, int(max_results)))
        hits: list[dict[str, Any]] = []
        scanned = 0
        for dirpath, _dirs, files in os.walk(base):
            for fname in files:
                if not fnmatch.fnmatch(fname.lower(), name_pattern.lower()):
                    continue
                full = Path(dirpath) / fname
                entry = {"path": str(full), "size": None, "match": "name"}
                if content:
                    try:
                        if full.stat().st_size > max_file_mb * 1024 * 1024:
                            continue
                        raw = full.read_bytes()
                        if content.encode("utf-8") not in raw and content.lower().encode("utf-8") not in raw.lower():
                            continue
                        entry["match"] = "content"
                    except Exception:
                        continue
                entry["size"] = full.stat().st_size
                hits.append(entry)
                scanned += 1
                if len(hits) >= max_results:
                    return j({"root": str(base), "count": len(hits), "truncated": True, "hits": hits})
        return j({"root": str(base), "count": len(hits), "truncated": False, "hits": hits})

    @mcp.tool()
    def fs_drives() -> str:
        """List mounted drives with free space."""
        import psutil

        rows = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                rows.append({"drive": part.device, "fstype": part.fstype,
                             "total_gb": round(usage.total / 1073741824, 1),
                             "free_gb": round(usage.free / 1073741824, 1)})
            except Exception:
                continue
        return j({"drives": rows})
