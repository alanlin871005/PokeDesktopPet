"""
Windows 桌面視窗偵測與標題列棲息輔助模組
- 使用 Win32 EnumWindows + DwmGetWindowAttribute 取得可見且未遮蔽視窗之精準邊框
- 自動過濾隱藏 UWP 視窗、最小化視窗、最大化視窗與本程式自身視窗
- 提供 Z-order 遮擋判斷，讓桌寵只會站上真正露出的視窗標題列上緣
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except Exception:
    dwmapi = None

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
if dwmapi is not None:
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

SKIP_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Progman",
    "WorkerW",
    "NotifyIconOverflowWindow",
    "TaskListThumbnailWnd",
    "Windows.UI.Core.CoreWindow",
    "ForegroundStaging",
    "MultitaskingViewFrame",
    "TopLevelWindowForOverflowXamlIsland",
}


@dataclass(frozen=True)
class WindowRect:
    hwnd: int
    left: int
    top: int
    right: int
    bottom: int
    title: str = ""

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def get_work_area() -> tuple[int, int, int, int]:
    """Return Windows primary monitor work area (left, top, right, bottom) excluding taskbar."""
    rect = RECT()
    SPI_GETWORKAREA = 0x0030
    if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, 1920, 1040


def _is_window_cloaked(hwnd: int) -> bool:
    if dwmapi is None:
        return False
    cloaked = wintypes.DWORD(0)
    hr = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_CLOAKED),
        ctypes.byref(cloaked),
        ctypes.sizeof(cloaked),
    )
    return hr == 0 and cloaked.value != 0


def _read_visible_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = RECT()
    if dwmapi is not None:
        hr = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if hr == 0:
            return rect.left, rect.top, rect.right, rect.bottom
    if user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 128)
    return buf.value


def _get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(min(length + 1, 160))
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, len(buf))
    return buf.value


def _is_candidate_window(hwnd: int, exclude_pid: int) -> bool:
    if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
        return False
    if user32.IsIconic(wintypes.HWND(hwnd)):
        return False

    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    if pid.value == exclude_pid:
        return False

    if _is_window_cloaked(hwnd):
        return False

    cls = _get_class_name(hwnd)
    if cls in SKIP_CLASSES:
        return False

    ex_style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    if ex_style & WS_EX_TOOLWINDOW:
        return False

    return True


def get_perchable_windows(exclude_pid: int, work_area: tuple[int, int, int, int] | None = None) -> list[WindowRect]:
    """Enumerate visible top-level windows in Z-order (front to back) suitable for perching."""
    if work_area is None:
        work_area = get_work_area()
    w_left, w_top, w_right, w_bottom = work_area

    results: list[WindowRect] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            if not _is_candidate_window(hwnd, exclude_pid):
                return True
            bounds = _read_visible_rect(hwnd)
            if not bounds:
                return True
            left, top, right, bottom = bounds
            width = right - left
            height = bottom - top
            if width < 180 or height < 80:
                return True
            if right <= w_left + 30 or left >= w_right - 30:
                return True
            if bottom <= w_top + 60 or top >= w_bottom - 30:
                return True

            title = _get_window_title(hwnd)
            if not title:
                return True
            results.append(WindowRect(hwnd=int(hwnd), left=left, top=top, right=right, bottom=bottom, title=title))
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return results


def get_window_rect_if_alive(
    hwnd: int,
    exclude_pid: int,
    work_area: tuple[int, int, int, int] | None = None,
) -> WindowRect | None:
    """Fast single-window check for the window a pet is currently perched on."""
    if not hwnd or not user32.IsWindow(wintypes.HWND(hwnd)):
        return None
    if not user32.IsWindowVisible(wintypes.HWND(hwnd)) or user32.IsIconic(wintypes.HWND(hwnd)):
        return None
    if user32.IsZoomed(wintypes.HWND(hwnd)) or _is_window_cloaked(hwnd):
        return None
    bounds = _read_visible_rect(hwnd)
    if not bounds:
        return None
    if work_area is None:
        work_area = get_work_area()
    w_left, w_top, w_right, w_bottom = work_area
    left, top, right, bottom = bounds
    if (right - left) < 180 or (bottom - top) < 80:
        return None
    if top < w_top + 36 or top >= w_bottom - 30:
        return None
    if right <= w_left + 30 or left >= w_right - 30:
        return None
    return WindowRect(hwnd=hwnd, left=left, top=top, right=right, bottom=bottom)


def find_landing_window(
    windows_z_order: list[WindowRect],
    center_x: float,
    prev_bottom: float,
    next_bottom: float,
    work_top: int,
    margin: int = 18,
) -> WindowRect | None:
    """Find the topmost unoccluded window top edge crossed by a falling entity."""
    for win in windows_z_order:
        if not (win.left + margin <= center_x <= win.right - margin):
            continue
        # Only perch when window top has room above it for the pet sprite
        if win.top >= work_top + 36 and (prev_bottom - 8 <= win.top <= next_bottom + 4):
            return win
        # If a higher-Z window covers this (x, y) region, deeper windows behind it are occluded
        if win.top < prev_bottom - 8 < win.bottom:
            return None
    return None


def is_perch_spot_occluded(
    windows_z_order: list[WindowRect],
    target_hwnd: int,
    center_x: float,
    perch_y: float,
) -> bool:
    """Return True if another window higher in Z-order covers the pet's perch spot."""
    for win in windows_z_order:
        if win.hwnd == target_hwnd:
            return False
        if win.left <= center_x <= win.right and win.top <= perch_y <= win.bottom:
            return True
    return False
