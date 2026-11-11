"""Phase 0 headless monitor layout probe (ctypes, Per-Monitor-V2 DPI aware). Prints physical bounds.

Usage: .venv\\Scripts\\python.exe scripts\\monitor_probe.py
"""
from __future__ import annotations

import ctypes
import json
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shcore = ctypes.WinDLL("shcore")

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
MONITORINFOF_PRIMARY = 1
MDT_EFFECTIVE_DPI = 0
ENUM_CURRENT_SETTINGS = -1


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
                ("rest", ctypes.c_byte * 64)]


def rect(r: wintypes.RECT) -> list[int]:
    return [r.left, r.top, r.right, r.bottom]


def main() -> None:
    user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    monitors = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def cb(hmon, _hdc, _rc, _lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        dx, dy = wintypes.UINT(), wintypes.UINT()
        shcore.GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy))
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        user32.EnumDisplayDevicesW(mi.szDevice, 0, ctypes.byref(dd), 0)  # monitor attached to adapter
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(dm)
        user32.EnumDisplaySettingsW(mi.szDevice, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
        monitors.append({
            "device": mi.szDevice,
            "monitor_name": dd.DeviceString,
            "primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY),
            "bounds_ltrb": rect(mi.rcMonitor),
            "work_area_ltrb": rect(mi.rcWork),
            "size": f"{mi.rcMonitor.right - mi.rcMonitor.left}x{mi.rcMonitor.bottom - mi.rcMonitor.top}",
            "refresh_hz": dm.dmDisplayFrequency,
            "dpi": dx.value,
            "scale_percent": round(dx.value / 96 * 100),
        })
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    print(json.dumps({"virtual_desktop_ltwh": [vx, vy, vw, vh], "monitors": monitors}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
