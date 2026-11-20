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


def _grab(cfg: Config, monitor: int, region: str, scale: float):
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
    def screen_capture(monitor: int = 0, region: str = "", scale: float = 1.0) -> Image:
        """Grab the screen as a PNG image (returned inline to the client).

        monitor: 0 = all monitors, 1..N = one monitor (see screen_info).
        region:  optional 'x,y,width,height' relative to the chosen monitor.
        scale:   0.5 halves the resolution (fewer tokens), 2.0 zooms in.
        """
        img, box = _grab(cfg, monitor, region, scale)
        path = _save(cfg, img)
        return Image(path=str(path))

    @mcp.tool()
    def screen_capture_data(monitor: int = 0, region: str = "", scale: float = 1.0,
                            include_base64: bool = True) -> str:
        """Same as screen_capture but returns JSON (saved path, size, base64) - use for automation."""
        img, box = _grab(cfg, monitor, region, scale)
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
