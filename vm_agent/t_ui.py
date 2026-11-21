"""Screen capture, mouse/keyboard injection, clipboard and window management."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Image

from . import winapi
from .config import Config
from .util import AgentError, b64e, j


def _parse_region(region: str) -> tuple[int, int, int, int] | None:
    if not region:
        return None
    parts = [p.strip() for p in region.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 4:
        raise AgentError("region must be 'x,y,width,height'")
    try:
        x, y, w, h = (int(p, 0) for p in parts)
    except ValueError as exc:
        raise AgentError(f"region values must be integers: {exc}") from exc
    if w <= 0 or h <= 0:
        raise AgentError("region width/height must be positive")
    return x, y, w, h


def _draw_grid(img, step: int, box: dict[str, Any], scale: float):
    from PIL import Image as PILImage, ImageDraw, ImageFont

    step = max(25, int(step or 100))
    base = img.convert("RGBA")
    overlay = PILImage.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()

    origin_x = int(box.get("left", 0))
    origin_y = int(box.get("top", 0))
    orig_w = int(box.get("width", int(img.width / scale)))
    orig_h = int(box.get("height", int(img.height / scale)))

    for ox in range(0, orig_w, step):
        px = int(ox * scale)
        if px >= base.width:
            break
        draw.line([(px, 0), (px, base.height)], fill=(255, 220, 40, 120), width=1)
        if ox > 0:
            label = str(origin_x + ox)
            draw.rectangle([(px + 2, 2), (px + 2 + len(label) * 6 + 4, 15)], fill=(0, 0, 0, 180))
            draw.text((px + 4, 3), label, fill=(255, 235, 80, 240), font=font)

    for oy in range(0, orig_h, step):
        py = int(oy * scale)
        if py >= base.height:
            break
        draw.line([(0, py), (base.width, py)], fill=(255, 220, 40, 120), width=1)
        if oy > 0:
            label = str(origin_y + oy)
            draw.rectangle([(2, py + 2), (2 + len(label) * 6 + 4, py + 15)], fill=(0, 0, 0, 180))
            draw.text((4, py + 3), label, fill=(255, 235, 80, 240), font=font)

    return PILImage.alpha_composite(base, overlay).convert("RGB")


def _grab(cfg: Config, monitor: int, region: str, scale: float, grid: bool = False, grid_step: int = 100):
    import mss
    from PIL import Image as PILImage

    with mss.mss() as sct:
        monitors = sct.monitors
        index = int(monitor)
        if index < 0 or index >= len(monitors):
            raise AgentError(
                f"monitor {index} does not exist; available indexes: 0..{len(monitors) - 1} "
                "(0 = all monitors combined)"
            )
        box = monitors[index]
        if region:
            rx, ry, rw, rh = _parse_region(region)
            box = {"left": box["left"] + rx, "top": box["top"] + ry, "width": rw, "height": rh}
        shot = sct.grab(box)
        img = PILImage.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    scale = float(scale or 1.0)
    if scale <= 0:
        raise AgentError("scale must be > 0")
    if abs(scale - 1.0) > 0.001:
        width = max(1, int(img.width * scale))
        height = max(1, int(img.height * scale))
        img = img.resize((width, height), PILImage.LANCZOS)
    if grid:
        img = _draw_grid(img, step=grid_step, box=box, scale=scale)
    return img, box


def _save(cfg: Config, img) -> Path:
    name = f"shot_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.png"
    path = cfg.shots / name
    img.save(path, format="PNG", optimize=True)
    shots = sorted(cfg.shots.glob("shot_*.png"))
    for old in shots[:-300]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def register(mcp, cfg: Config) -> None:
    # ---------------------------------------------------------------- screen
    @mcp.tool()
    def screen_info() -> str:
        """Monitors, virtual-desktop bounds, cursor position and foreground window."""
        import mss

        with mss.mss() as sct:
            monitors = [{
                "index": i,
                "left": m["left"], "top": m["top"],
                "width": m["width"], "height": m["height"],
            } for i, m in enumerate(sct.monitors)]
        vx, vy, vw, vh = winapi.virtual_screen()
        return j({
            "monitors": monitors,
            "virtual_screen": {"left": vx, "top": vy, "width": vw, "height": vh},
            "primary_size": list(winapi.screen_size()),
            "cursor": list(winapi.cursor_pos()),
            "foreground_window": winapi.foreground_title(),
            "dpi_aware": True,
            "note": "monitor 0 = all monitors; coordinates are physical pixels",
        })

    @mcp.tool()
    def screen_capture(monitor: int = 0, region: str = "", scale: float = 1.0,
                       grid: bool = False, grid_step: int = 100) -> Image:
        """Grab the screen as a PNG image (returned inline to the client).

        monitor: 0 = all monitors, 1..N = one monitor (see screen_info).
        region:  optional 'x,y,width,height' relative to the chosen monitor.
        scale:   0.5 halves the resolution (fewer tokens), 2.0 zooms in.
        grid:    overlay a coordinate grid with physical pixel labels (step=grid_step).
        """
        img, box = _grab(cfg, monitor, region, scale, grid=grid, grid_step=grid_step)
        path = _save(cfg, img)
        return Image(path=str(path))

    @mcp.tool()
    def screen_capture_data(monitor: int = 0, region: str = "", scale: float = 1.0,
                            include_base64: bool = True,
                            grid: bool = False, grid_step: int = 100) -> str:
        """Same as screen_capture but returns JSON (saved path, size, base64) - use for automation."""
        img, box = _grab(cfg, monitor, region, scale, grid=grid, grid_step=grid_step)
        path = _save(cfg, img)
        result: dict[str, Any] = {
            "path": str(path),
            "width": img.width,
            "height": img.height,
            "box": box,
            "bytes": path.stat().st_size,
        }
        if include_base64:
            result["base64"] = b64e(path.read_bytes())
        return j(result)

    @mcp.tool()
    def screen_pixel(x: int, y: int) -> str:
        """Read the RGB color of one screen pixel."""
        import mss

        with mss.mss() as sct:
            shot = sct.grab({"left": int(x), "top": int(y), "width": 1, "height": 1})
            b, g, r = shot.pixel(0, 0)[:3]
        return j({"x": x, "y": y, "rgb": [r, g, b], "hex": f"#{r:02X}{g:02X}{b:02X}"})

    # ---------------------------------------------------------------- input
    @mcp.tool()
    def input_mouse_move(x: int, y: int) -> str:
        """Move the mouse cursor to absolute screen coordinates (physical pixels)."""
        winapi.move_to(x, y)
        time.sleep(0.02)
        return j({"cursor": list(winapi.cursor_pos())})

    @mcp.tool()
    def input_click(x: int | None = None, y: int | None = None, button: str = "left",
                    clicks: int = 1, interval: float = 0.06) -> str:
        """Click a mouse button, optionally moving to (x, y) first. button: left|right|middle|x1|x2."""
        pos = winapi.click(x, y, button=button, clicks=clicks, interval=interval)
        return j({"clicked": button, "clicks": clicks, "cursor": list(pos)})

    @mcp.tool()
    def input_drag(x1: int, y1: int, x2: int, y2: int, button: str = "left",
                   duration: float = 0.3) -> str:
        """Press, move and release the mouse (drag & drop)."""
        winapi.drag(x1, y1, x2, y2, button=button, duration=duration)
        return j({"from": [x1, y1], "to": [x2, y2], "button": button})

    @mcp.tool()
    def input_scroll(dy: int = -3, dx: int = 0) -> str:
        """Scroll the wheel at the current cursor position (positive dy = up)."""
        winapi.scroll(dy=dy, dx=dx)
        return j({"dy": dy, "dx": dx})

    @mcp.tool()
    def input_type(text: str, interval: float = 0.0) -> str:
        """Type text as Unicode keystrokes into the focused window (works with any layout)."""
        winapi.type_text(text, interval=interval)
        return j({"typed_chars": len(text)})

    @mcp.tool()
    def input_key(combo: str) -> str:
        """Press a key or chord: 'enter', 'esc', 'ctrl+shift+esc', 'alt+f4', 'win+r'."""
        winapi.key_combo(combo)
        return j({"pressed": combo})

    @mcp.tool()
    def clipboard_get() -> str:
        """Read the clipboard text."""
        text = winapi.clipboard_get()
        return j({"length": len(text), "text": text})

    @mcp.tool()
    def clipboard_set(text: str) -> str:
        """Write text to the clipboard."""
        length = winapi.clipboard_set(text)
        return j({"chars": length})

    # ---------------------------------------------------------------- windows
    @mcp.tool()
    def win_list(filter: str = "", visible_only: bool = True, include_empty: bool = False) -> str:
        """List top-level windows (hwnd, title, class, pid, rect) - use with win_focus/input_*."""
        windows = winapi.list_windows(visible_only=visible_only, include_empty=include_empty)
        if filter:
            needle = filter.lower()
            windows = [w for w in windows if needle in w["title"].lower() or needle in w["class"].lower()]
        return j({"count": len(windows), "windows": windows[:400]})

    @mcp.tool()
    def win_focus(hwnd: int = 0, title: str = "", exact: bool = False) -> str:
        """Bring a window to the foreground by hwnd or (partial) title."""
        handle = winapi.find_window(title=title or None, hwnd=hwnd or None, exact=exact)
        winapi.focus_window(handle)
        time.sleep(0.1)
        return j({"hwnd": handle, "foreground": winapi.foreground_title()})

    @mcp.tool()
    def win_move(hwnd: int, x: int, y: int, width: int | None = None,
                 height: int | None = None) -> str:
        """Move/resize a window (keeps current size when width/height are omitted)."""
        winapi.move_window(hwnd, x, y, width, height)
        return j({"hwnd": hwnd, "x": x, "y": y, "width": width, "height": height})

    @mcp.tool()
    def win_close(hwnd: int) -> str:
        """Post WM_CLOSE to a window (graceful close)."""
        winapi.close_window(hwnd)
        return j({"hwnd": hwnd, "close_sent": True})

    @mcp.tool()
    def ui_desktop_icons(filter: str = "") -> str:
        """List desktop icons with exact screen coordinates (pos + clickable icon center)."""
        import ctypes
        import ctypes.wintypes as w

        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        lv = 0
        pm = u32.FindWindowW("Progman", None)
        sv = u32.FindWindowExW(pm, 0, "SHELLDLL_DefView", None)
        if sv:
            lv = u32.FindWindowExW(sv, 0, "SysListView32", None)
        if not lv:
            @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
            def _cb(h, _lp):
                nonlocal lv
                s = u32.FindWindowExW(h, 0, "SHELLDLL_DefView", None)
                if s:
                    lv = u32.FindWindowExW(s, 0, "SysListView32", None)
                    return False
                return True
            u32.EnumWindows(_cb, 0)
        if not lv:
            raise AgentError("Desktop SysListView32 window not found")

        cnt = u32.SendMessageW(lv, 0x1004, 0, 0)  # LVM_GETITEMCOUNT
        pid = w.DWORD()
        u32.GetWindowThreadProcessId(lv, ctypes.byref(pid))
        hp = k32.OpenProcess(0x001F0FFF, False, pid.value)
        if not hp:
            raise AgentError("Failed to open explorer.exe process for desktop icon coordinates")

        class _LVITEMW(ctypes.Structure):
            _fields_ = [
                ("mask", w.UINT), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
                ("state", w.UINT), ("stateMask", w.UINT), ("pszText", ctypes.c_void_p),
                ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int), ("lParam", w.LPARAM),
            ]

        buf = k32.VirtualAllocEx(hp, 0, 4096, 0x3000, 0x04)
        icons = []
        try:
            pt = w.POINT()
            needle = (filter or "").lower()
            for i in range(cnt):
                u32.SendMessageW(lv, 0x1010, i, buf)  # LVM_GETITEMPOSITION
                k32.ReadProcessMemory(hp, buf, ctypes.byref(pt), ctypes.sizeof(pt), None)
                lvi = _LVITEMW(mask=1, iItem=i, pszText=buf + 256, cchTextMax=260)
                k32.WriteProcessMemory(hp, buf + 64, ctypes.byref(lvi), ctypes.sizeof(lvi), None)
                u32.SendMessageW(lv, 0x104B, i, buf + 64)  # LVM_GETITEMTEXTW
                txt = ctypes.create_unicode_buffer(260)
                k32.ReadProcessMemory(hp, buf + 256, txt, 520, None)
                name = txt.value
                if needle and needle not in name.lower():
                    continue
                icons.append({
                    "index": i,
                    "name": name,
                    "pos": [int(pt.x), int(pt.y)],
                    "center": [int(pt.x) + 24, int(pt.y) + 24],
                })
        finally:
            k32.VirtualFreeEx(hp, buf, 0, 0x8000)
            k32.CloseHandle(hp)
        return j({"count": len(icons), "icons": icons})
