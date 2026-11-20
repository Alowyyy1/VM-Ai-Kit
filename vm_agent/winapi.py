"""Thin ctypes wrappers around the Win32 pieces the agent needs.

No pywin32/pyautogui dependency: input is injected through SendInput, which works
for both normal windows and most DirectInput games (as long as they run in the
interactive desktop session).
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Iterable, Sequence

from .util import AgentError

IS_WINDOWS = os.name == "nt"

user32 = ctypes.WinDLL("user32", use_last_error=True) if IS_WINDOWS else None
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if IS_WINDOWS else None

# --------------------------------------------------------------------------- dpi
def enable_dpi_awareness() -> None:
    """Make screen coordinates match physical pixels (call once at startup)."""
    if not IS_WINDOWS:
        return
    try:
        # PER_MONITOR_AWARE_V2
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# --------------------------------------------------------------------------- input
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

WHEEL_DELTA = 120

VK: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22, "end": 0x23, "home": 0x24, "left": 0x25,
    "up": 0x26, "right": 0x27, "down": 0x28, "printscreen": 0x2C, "prtsc": 0x2C,
    "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E, "win": 0x5B,
    "lwin": 0x5B, "rwin": 0x5C, "apps": 0x5D, "sleep": 0x5F,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D,
    "decimal": 0x6E, "divide": 0x6F, "numlock": 0x90, "scrolllock": 0x91,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5, "semicolon": 0xBA, "equals": 0xBB,
    "comma": 0xBC, "minus": 0xBD, "period": 0xBE, "slash": 0xBF,
    "grave": 0xC0, "lbracket": 0xDB, "backslash": 0xDC, "rbracket": 0xDD,
    "quote": 0xDE,
}

for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i

_SYMBOLS = {
    "-": "minus", "=": "equals", ",": "comma", ".": "period", "/": "slash",
    ";": "semicolon", "'": "quote", "[": "lbracket", "]": "rbracket",
    "\\": "backslash", "`": "grave",
}


def _key_inputs(vk: int, up: bool = False, scan: int = 0, unicode: bool = False) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_UNICODE if unicode else 0)
    item = INPUT(type=INPUT_KEYBOARD)
    item.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None)
    return item


def _send(*items: INPUT) -> None:
    if not IS_WINDOWS:
        raise AgentError("input injection is only supported on Windows")
    arr = (INPUT * len(items))(*items)
    sent = user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))
    if sent != len(items):
        err = ctypes.get_last_error()
        raise AgentError(f"SendInput failed (sent {sent}/{len(items)}, last_error={err})")


def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    item = INPUT(type=INPUT_MOUSE)
    item.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=None)
    return item


def virtual_screen() -> tuple[int, int, int, int]:
    """(left, top, width, height) of the whole virtual desktop."""
    gsm = user32.GetSystemMetrics
    return gsm(76), gsm(77), gsm(78), gsm(79)


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x: int, y: int) -> None:
    if not user32.SetCursorPos(int(x), int(y)):
        raise AgentError(f"SetCursorPos({x},{y}) failed: {ctypes.get_last_error()}")


def _absolute(x: int, y: int) -> tuple[int, int]:
    vx, vy, vw, vh = virtual_screen()
    if vw <= 1 or vh <= 1:
        raise AgentError("cannot read virtual screen metrics")
    nx = int(round((int(x) - vx) * 65535 / (vw - 1)))
    ny = int(round((int(y) - vy) * 65535 / (vh - 1)))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "x1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 1),
    "x2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 2),
}


def click(x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1,
          interval: float = 0.06) -> tuple[int, int]:
    if x is not None and y is not None:
        move_to(x, y)
        time.sleep(0.02)
    try:
        down, up, extra = _BUTTONS[button.lower()]
    except KeyError as exc:
        raise AgentError(f"unknown mouse button '{button}'") from exc
    for i in range(max(1, int(clicks))):
        _send(_mouse_input(down, data=extra), _mouse_input(up, data=extra))
        if i + 1 < clicks:
            time.sleep(max(0.01, interval))
    return cursor_pos()


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", duration: float = 0.3,
         steps: int = 24) -> None:
    down, up, extra = _BUTTONS[button.lower()]
    move_to(x1, y1)
    time.sleep(0.05)
    _send(_mouse_input(down, data=extra))
    steps = max(2, min(200, int(steps)))
    delay = max(0.0, float(duration)) / steps
    try:
        for i in range(1, steps + 1):
            move_to(int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
            if delay:
                time.sleep(delay)
    finally:
        _send(_mouse_input(up, data=extra))


def scroll(dy: int = -3, dx: int = 0) -> None:
    items = []
    if dy:
        items.append(_mouse_input(MOUSEEVENTF_WHEEL, data=int(dy) * WHEEL_DELTA))
    if dx:
        items.append(_mouse_input(MOUSEEVENTF_HWHEEL, data=int(dx) * WHEEL_DELTA))
    if items:
        _send(*items)


def _vk_for(token: str) -> int:
    key = token.strip().lower()
    if key in VK:
        return VK[key]
    if key in _SYMBOLS:
        return VK[_SYMBOLS[key]]
    if len(key) == 1:
        ch = key.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)
        # VkKeyScanW resolves layout-specific punctuation.
        scan = user32.VkKeyScanW(ctypes.c_wchar(key))
        if scan != -1:
            return scan & 0xFF
    raise AgentError(f"unknown key '{token}'")


def key_combo(combo: str) -> None:
    tokens = [t for t in combo.replace(" ", "").split("+") if t]
    if not tokens:
        raise AgentError("empty key combo")
    codes = [_vk_for(t) for t in tokens]
    items = [_key_inputs(vk) for vk in codes]
    items += [_key_inputs(vk, up=True) for vk in reversed(codes)]
    _send(*items)


def type_text(text: str, interval: float = 0.0) -> None:
    if not text:
        return
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:
            code -= 0x10000
            units = [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]
        else:
            units = [code]
        items = []
        for unit in units:
            if unit in (0x0A, 0x0D):
                items.append(_key_inputs(VK["enter"]))
                items.append(_key_inputs(VK["enter"], up=True))
            elif unit == 0x09:
                items.append(_key_inputs(VK["tab"]))
                items.append(_key_inputs(VK["tab"], up=True))
            else:
                items.append(_key_inputs(0, scan=unit, unicode=True))
                items.append(_key_inputs(0, up=True, scan=unit, unicode=True))
        _send(*items)
        if interval:
            time.sleep(interval)


# --------------------------------------------------------------------------- clipboard
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def _open_clipboard(retries: int = 10) -> None:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.03)
    raise AgentError("cannot open clipboard (another process is holding it)")


def clipboard_get() -> str:
    _open_clipboard()
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def clipboard_set(text: str) -> int:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    _open_clipboard()
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            raise AgentError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, size)
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise AgentError(f"SetClipboardData failed: {ctypes.get_last_error()}")
    finally:
        user32.CloseClipboard()
    return len(text)


# --------------------------------------------------------------------------- windows
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def list_windows(visible_only: bool = True, include_empty: bool = False) -> list[dict]:
    if not IS_WINDOWS:
        return []
    result: list[dict] = []

    def _cb(hwnd, _lparam):
        try:
            if visible_only and not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 2)
            user32.GetWindowTextW(hwnd, buf, length + 2)
            title = buf.value
            if not title and not include_empty:
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            result.append({
                "hwnd": int(hwnd),
                "title": title,
                "class": cls.value,
                "pid": int(pid.value),
                "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
                "minimized": bool(user32.IsIconic(hwnd)),
                "foreground": int(user32.GetForegroundWindow() or 0) == int(hwnd),
            })
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return result


def find_window(title: str | None = None, hwnd: int | None = None, exact: bool = False) -> int:
    if hwnd:
        return int(hwnd)
    if not title:
        raise AgentError("either hwnd or title is required")
    wanted = title.lower()
    for win in list_windows(visible_only=False):
        name = win["title"].lower()
        if (name == wanted) if exact else (wanted in name):
            return int(win["hwnd"])
    raise AgentError(f"window not found: {title!r}")


def focus_window(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.15)
    if user32.SetForegroundWindow(hwnd):
        return
    # Windows blocks SetForegroundWindow for background processes; a synthetic
    # ALT press lifts that restriction for the next call.
    _send(_key_inputs(VK["alt"]), _key_inputs(VK["alt"], up=True))
    time.sleep(0.05)
    if not user32.SetForegroundWindow(hwnd):
        raise AgentError("SetForegroundWindow failed (target may be elevated or on another desktop)")


def move_window(hwnd: int, x: int, y: int, width: int | None = None, height: int | None = None) -> None:
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = width if width is not None else rect.right - rect.left
    h = height if height is not None else rect.bottom - rect.top
    SWP_NOZORDER = 0x0004
    if not user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), SWP_NOZORDER):
        raise AgentError(f"SetWindowPos failed: {ctypes.get_last_error()}")


def close_window(hwnd: int) -> None:
    WM_CLOSE = 0x0010
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


# --------------------------------------------------------------------------- process modules
class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * 260),
    ]


TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def process_modules(pid: int) -> list[dict]:
    if not IS_WINDOWS:
        return []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, int(pid))
    if not snap or snap == INVALID_HANDLE_VALUE:
        raise AgentError(f"CreateToolhelp32Snapshot failed for pid {pid}: {ctypes.get_last_error()}")
    mods: list[dict] = []
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        ok = kernel32.Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            mods.append({
                "name": entry.szModule,
                "path": entry.szExePath,
                "base": int(entry.modBaseAddr or 0),
                "size": int(entry.modBaseSize),
                "base_hex": f"0x{int(entry.modBaseAddr or 0):X}",
            })
            ok = kernel32.Module32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return mods


def is_elevated() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def session_id() -> int:
    if not IS_WINDOWS:
        return 0
    pid = kernel32.GetCurrentProcessId()
    sid = wintypes.DWORD()
    kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid))
    return int(sid.value)


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buf, length + 2)
    return buf.value
