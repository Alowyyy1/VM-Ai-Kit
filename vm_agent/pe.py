"""Static PE inspection built on pefile + capstone (pure Python, no external tools)."""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import AgentError, human_size, norm_path

MACHINES = {
    0x014C: "i386", 0x8664: "AMD64", 0x01C0: "ARM", 0x01C4: "ARMv7",
    0xAA64: "ARM64", 0x0200: "IA64", 0x0EBC: "EBC",
}
SUBSYSTEMS = {
    1: "NATIVE", 2: "WINDOWS_GUI", 3: "WINDOWS_CUI", 5: "OS2_CUI",
    7: "POSIX_CUI", 9: "WINDOWS_CE_GUI", 10: "EFI_APPLICATION",
    11: "EFI_BOOT_SERVICE_DRIVER", 12: "EFI_RUNTIME_DRIVER", 13: "EFI_ROM",
    14: "XBOX", 16: "WINDOWS_BOOT_APPLICATION",
}
PACKER_HINTS = {
    ".vmp0": "VMProtect", ".vmp1": "VMProtect", ".vmp2": "VMProtect",
    "vmp": "VMProtect", ".themida": "Themida", ".winlice": "WinLicense",
    ".enigma1": "Enigma", ".enigma2": "Enigma", "upx0": "UPX", "upx1": "UPX",
    ".aspack": "ASPack", ".adata": "ASPack", ".mpress1": "MPRESS",
    ".petite": "Petite", ".packed": "generic packer",
}


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    total = len(data)
    ent = 0.0
    for count in counts:
        if count:
            p = count / total
            ent -= p * math.log2(p)
    return round(ent, 4)


def _flag(value: int, bit: int) -> bool:
    return bool(value & (1 << bit))


def pe_info(path: str | Path, *, scan_markers: bool = True) -> dict[str, Any]:
    import pefile

    p = norm_path(str(path))
    if not p.is_file():
        raise AgentError(f"file not found: {p}")
    data = p.read_bytes()
    try:
        pe = pefile.PE(data=data, fast_load=False)
    except pefile.PEFormatError as exc:
        raise AgentError(f"not a valid PE file: {exc}") from exc

    oh = pe.OPTIONAL_HEADER
    fh = pe.FILE_HEADER
    info: dict[str, Any] = {
        "file": str(p),
        "size": len(data),
        "size_human": human_size(len(data)),
        "sha256": hashlib.sha256(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),  # noqa: S324 - identification only
        "machine": MACHINES.get(fh.Machine, f"0x{fh.Machine:04X}"),
        "characteristics": [name for name in ("RELOCS_STRIPPED", "EXECUTABLE_IMAGE", "DLL",
                                              "LARGE_ADDRESS_AWARE")
                            if fh.Characteristics & getattr(pefile, f"IMAGE_FILE_{name}", 0)],
        "dll": bool(fh.Characteristics & 0x2000),
        "timestamp": int(fh.TimeDateStamp),
        "timestamp_iso": datetime.fromtimestamp(int(fh.TimeDateStamp), tz=timezone.utc).isoformat(),
        "subsystem": SUBSYSTEMS.get(oh.Subsystem, str(oh.Subsystem)),
        "image_base": oh.ImageBase,
        "entry_point_rva": oh.AddressOfEntryPoint,
        "entry_point_va": oh.ImageBase + oh.AddressOfEntryPoint,
        "size_of_image": oh.SizeOfImage,
        "size_of_headers": oh.SizeOfHeaders,
        "section_alignment": oh.SectionAlignment,
        "file_alignment": oh.FileAlignment,
        "checksum": int(oh.CheckSum),
        "os_version": f"{oh.MajorOperatingSystemVersion}.{oh.MinorOperatingSystemVersion}",
        "dotnet": False,
        "signed": False,
    }

    dirs = {entry.name: entry for entry in oh.DATA_DIRECTORY}
    if hasattr(pe, "NET_METADATA"):
        info["dotnet"] = True
    sec_dir = dirs.get("IMAGE_DIRECTORY_ENTRY_SECURITY")
    info["signed"] = bool(sec_dir and sec_dir.Size)

    # ------------------------------------------------------------------ sections
    sections = []
    max_end = 0
    for section in pe.sections:
        name = section.Name.rstrip(b"\x00").decode("latin-1")
        raw = section.PointerToRawData
        raw_size = section.SizeOfRawData
        chunk = data[raw:raw + raw_size] if raw_size else b""
        chars = section.Characteristics
        sections.append({
            "name": name,
            "va": section.VirtualAddress,
            "virtual_size": section.Misc_VirtualSize,
            "raw_offset": raw,
            "raw_size": raw_size,
            "entropy": _entropy(chunk),
            "readable": _flag(chars, 30) or True,
            "writable": _flag(chars, 31),
            "executable": _flag(chars, 29),
            "code": _flag(chars, 5),
            "initialized_data": _flag(chars, 6),
            "uninitialized_data": _flag(chars, 7),
        })
        if raw_size:
            max_end = max(max_end, raw + raw_size)
    info["sections"] = sections

    # ------------------------------------------------------------------ imports
    imports: dict[str, list[Any]] = {}
    import_totals: dict[str, int] = {}
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        dll = entry.dll.decode("latin-1") if isinstance(entry.dll, bytes) else str(entry.dll)
        funcs: list[Any] = []
        for imp in entry.imports:
            if imp.name:
                funcs.append(imp.name.decode("latin-1", "replace"))
            else:
                funcs.append(f"ord_{imp.ordinal}")
        import_totals[dll] = len(funcs)
        imports[dll] = funcs[:60]
    info["imports"] = imports
    info["imports_truncated_per_dll"] = 60
    info["imports_totals"] = import_totals
    info["imports_dll_count"] = len(imports)
    info["imports_func_count"] = sum(import_totals.values())

    # ------------------------------------------------------------------ exports
    exports = []
    export_dir = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if export_dir:
        for sym in export_dir.symbols:
            exports.append({
                "name": sym.name.decode("latin-1") if sym.name else None,
                "ordinal": sym.ordinal,
                "rva": sym.address,
                "forwarder": sym.forwarder.decode("latin-1") if sym.forwarder else None,
            })
    info["exports"] = exports[:1000]
    info["exports_truncated"] = len(exports) > 1000

    # ------------------------------------------------------------------ tls
    tls_callbacks: list[int] = []
    tls = getattr(pe, "DIRECTORY_ENTRY_TLS", None)
    if tls:
        info["tls"] = {
            "start": tls.struct.StartAddressOfRawData,
            "end": tls.struct.EndAddressOfRawData,
            "index": tls.struct.AddressOfIndex,
            "callbacks_va": tls.struct.AddressOfCallBacks,
        }
        try:
            ptr = tls.struct.AddressOfCallBacks
            rva = ptr - oh.ImageBase
            off = pe.get_offset_from_rva(rva)
            width = 8 if oh.Magic == 0x20B else 4
            for i in range(32):
                raw = data[off + i * width: off + (i + 1) * width]
                value = int.from_bytes(raw, "little")
                if not value:
                    break
                tls_callbacks.append(value)
        except Exception:
            pass
    info["tls_callbacks"] = tls_callbacks
    info["tls_callback_count"] = len(tls_callbacks)

    # ------------------------------------------------------------------ resources
    resource_types: list[str] = []
    res_dir = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    if res_dir:
        for entry in res_dir.entries:
            name = entry.name.string.decode("utf-8", "replace") if entry.name else str(entry.id)
            count = len(entry.directory.entries) if entry.directory else 0
            resource_types.append(f"{name}({count})")
    info["resources"] = resource_types

    # ------------------------------------------------------------------ overlay / rich
    overlay_size = len(data) - max_end
    info["overlay"] = {"offset": max_end, "size": max(0, overlay_size)} if overlay_size > 0 else None
    rich = getattr(pe, "RICH_HEADER", None)
    info["rich_header"] = bool(rich and getattr(rich, "values", None))

    # ------------------------------------------------------------------ heuristics
    marker_window = data[: 64 * 1024 * 1024]
    e9_zero = marker_window.count(b"\xE9\x00\x00\x00\x00")
    e8_zero = marker_window.count(b"\xE8\x00\x00\x00\x00")
    per_mb = round(e9_zero / max(1, len(marker_window) / (1024 * 1024)), 1)
    zero_raw = [s["name"] for s in sections if s["raw_size"] == 0 and s["virtual_size"] > 0x1000]
    vmp_sections = [s["name"] for s in sections
                    if any(hint in s["name"].lower() for hint in PACKER_HINTS)]
    high_entropy = [s["name"] for s in sections if s["raw_size"] > 0x1000 and s["entropy"] > 7.2]
    big_virtual = [s["name"] for s in sections
                   if s["raw_size"] and s["virtual_size"] / s["raw_size"] > 8]

    score = 0
    reasons: list[str] = []
    if high_entropy:
        score += 30
        reasons.append(f"high-entropy sections: {', '.join(high_entropy)}")
    if zero_raw:
        score += 20
        reasons.append(f"sections with RawSize=0 (restored at runtime): {', '.join(zero_raw)}")
    if e9_zero > 500:
        score += 20
        reasons.append(f"{e9_zero} 'E9 00 00 00 00' stubs ({per_mb}/MB)")
    if info["imports_func_count"] < 25:
        score += 10
        reasons.append(f"only {info['imports_func_count']} imports in {info['imports_dll_count']} DLLs")
    if big_virtual:
        score += 10
        reasons.append(f"VirtualSize >> RawSize: {', '.join(big_virtual)}")
    if vmp_sections:
        score += 10
        reasons.append(f"packer section names: {', '.join(vmp_sections)}")

    info["heuristics"] = {
        "packed_score": min(100, score),
        "reasons": reasons,
        "high_entropy_sections": high_entropy,
        "zero_raw_sections": zero_raw,
        "e9_00_stubs": e9_zero,
        "e8_00_stubs": e8_zero,
        "e9_00_per_mb": per_mb,
        "packer_section_hints": sorted({PACKER_HINTS[h] for s in sections
                                        for h in PACKER_HINTS if h in s["name"].lower()}),
        "size_of_image_hex": f"0x{oh.SizeOfImage:X}",
    }
    if not scan_markers:
        info["heuristics"].pop("e9_00_per_mb", None)
    pe.close()
    return info


# --------------------------------------------------------------------------- strings
def _printable(ch: str) -> bool:
    return 0x20 <= ord(ch) <= 0x7E


def extract_strings(path: str | Path, min_length: int = 6, encoding: str = "ascii",
                    limit: int = 2000, search: str | None = None,
                    offset: int = 0, length: int | None = None) -> dict[str, Any]:
    p = norm_path(str(path))
    if not p.is_file():
        raise AgentError(f"file not found: {p}")
    size = p.stat().st_size
    start = max(0, int(offset))
    with p.open("rb") as fh:
        fh.seek(start)
        data = fh.read(length if length else size - start)
    base = start

    pattern = re.compile(rb"[\x20-\x7e]{%d,}" % max(1, int(min_length)))
    encoding = (encoding or "ascii").lower()
    found: list[dict[str, Any]] = []
    needle = search.lower() if search else None

    if encoding in ("ascii", "ansi", "utf8", "utf-8"):
        for match in pattern.finditer(data):
            text = match.group().decode("latin-1")
            if needle and needle not in text.lower():
                continue
            found.append({"offset": base + match.start(), "encoding": "ascii", "text": text})
            if len(found) >= limit:
                break
    elif encoding in ("utf16", "unicode", "utf-16", "utf-16le"):
        wide = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % max(1, int(min_length)))
        for match in wide.finditer(data):
            text = match.group().decode("utf-16le", "replace")
            if needle and needle not in text.lower():
                continue
            found.append({"offset": base + match.start(), "encoding": "utf-16le", "text": text})
            if len(found) >= limit:
                break
    else:
        raise AgentError("encoding must be ascii or utf16")

    return {
        "file": str(p),
        "encoding": encoding,
        "min_length": min_length,
        "scanned_bytes": len(data),
        "count": len(found),
        "truncated": len(found) >= limit,
        "strings": found,
    }


# --------------------------------------------------------------------------- search
def search_bytes(path: str | Path, pattern: str, limit: int = 100,
                 offset: int = 0, length: int | None = None) -> dict[str, Any]:
    """Byte/AOB search. Accepts 'DE AD ?? EF', 'dead??ef' or plain text."""
    p = norm_path(str(path))
    if not p.is_file():
        raise AgentError(f"file not found: {p}")
    raw = pattern.strip()
    compact = re.sub(r"[\s,\-]", "", raw)
    is_hex = bool(compact) and len(compact) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F?]+", compact) is not None
    if is_hex:
        parts = [compact[i:i + 2] for i in range(0, len(compact), 2)]
        regex = b"".join(b"." if part in ("??", "?") else re.escape(bytes.fromhex(part))
                         for part in parts)
        label = compact
    else:
        regex = re.escape(raw.encode("utf-8"))
        label = raw

    size = p.stat().st_size
    start = max(0, int(offset))
    with p.open("rb") as fh:
        fh.seek(start)
        data = fh.read(length if length else size - start)

    compiled = re.compile(b"(?=(" + regex + b"))", re.DOTALL)
    hits: list[dict[str, Any]] = []
    for match in compiled.finditer(data):
        pos = start + match.start()
        hits.append({"offset": pos, "offset_hex": f"0x{pos:X}",
                     "context": data[match.start():match.start() + 32].hex(" ")})
        if len(hits) >= limit:
            break
    return {"file": str(p), "pattern": label, "scanned_bytes": len(data),
            "count": len(hits), "hits": hits}


# --------------------------------------------------------------------------- disasm
def disasm(path: str | Path, offset: int | None = None, rva: int | None = None,
           count: int = 20, bits: int = 64) -> dict[str, Any]:
    try:
        import capstone
    except ImportError as exc:  # pragma: no cover
        raise AgentError("capstone is not installed (pip install capstone)") from exc

    p = norm_path(str(path))
    if not p.is_file():
        raise AgentError(f"file not found: {p}")
    data = p.read_bytes()
    if rva is not None:
        import pefile

        pe = pefile.PE(data=data, fast_load=True)
        offset = pe.get_offset_from_rva(int(rva))
        pe.close()
    start = int(offset or 0)
    mode = capstone.CS_MODE_64 if bits == 64 else capstone.CS_MODE_32
    cs = capstone.Cs(capstone.CS_ARCH_X86, mode)
    cs.detail = False
    out = []
    va_base = int(rva or start)
    for insn in cs.disasm(data[start:start + 16 * max(1, count)], va_base):
        out.append({
            "address": f"0x{insn.address:X}",
            "bytes": insn.bytes.hex(" "),
            "mnemonic": insn.mnemonic,
            "op_str": insn.op_str,
        })
        if len(out) >= count:
            break
    return {"file": str(p), "offset": start, "bits": bits, "count": len(out), "instructions": out}


def file_entropy(path: str | Path, offset: int = 0, length: int | None = None) -> dict[str, Any]:
    p = norm_path(str(path))
    if not p.is_file():
        raise AgentError(f"file not found: {p}")
    size = p.stat().st_size
    start = max(0, int(offset))
    with p.open("rb") as fh:
        fh.seek(start)
        data = fh.read(length if length else size - start)
    return {"file": str(p), "offset": start, "length": len(data),
            "entropy": _entropy(data), "size_human": human_size(len(data))}


def hexdump(path: str | Path, offset: int = 0, length: int = 256) -> dict[str, Any]:
    p = norm_path(str(path))
    if not p.is_file():
        raise AgentError(f"file not found: {p}")
    length = max(1, min(65536, int(length)))
    with p.open("rb") as fh:
        fh.seek(max(0, int(offset)))
        data = fh.read(length)
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02X}" for b in chunk)
        text = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
        lines.append(f"{offset + i:08X}  {hexpart:<47}  {text}")
    return {"file": str(p), "offset": offset, "length": len(data), "lines": lines}
