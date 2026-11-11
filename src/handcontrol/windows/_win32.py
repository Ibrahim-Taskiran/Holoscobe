"""Explicit Win32 ABI definitions; DLL loading is lazy."""
from __future__ import annotations

import ctypes as C
import os
from functools import lru_cache

BOOL = C.c_int32
DWORD = UINT = C.c_uint32
LONG = C.c_int32
WORD = C.c_uint16
HANDLE = C.c_void_p
ULONG_PTR = C.c_size_t
LRESULT = LPARAM = C.c_ssize_t
WPARAM = C.c_size_t
WINFUNCTYPE = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)


class POINT(C.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class RECT(C.Structure):
    _fields_ = [(n, LONG) for n in ("left", "top", "right", "bottom")]


class MONITORINFO(C.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD)]


class WINDOWPLACEMENT(C.Structure):
    _fields_ = [("length", UINT), ("flags", UINT), ("showCmd", UINT),
                ("ptMinPosition", POINT), ("ptMaxPosition", POINT), ("rcNormalPosition", RECT)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", DWORD), ("data", INPUTUNION)]


MONITORENUMPROC = WINFUNCTYPE(BOOL, HANDLE, HANDLE, C.POINTER(RECT), LPARAM)
WNDPROC = WINFUNCTYPE(LRESULT, HANDLE, UINT, WPARAM, LPARAM)


class WNDCLASSW(C.Structure):
    _fields_ = [("style", UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", HANDLE), ("hIcon", HANDLE),
                ("hCursor", HANDLE), ("hbrBackground", HANDLE),
                ("lpszMenuName", C.c_wchar_p), ("lpszClassName", C.c_wchar_p)]


class MSG(C.Structure):
    _fields_ = [("hwnd", HANDLE), ("message", UINT), ("wParam", WPARAM),
                ("lParam", LPARAM), ("time", DWORD), ("pt", POINT), ("lPrivate", DWORD)]


def bind(dll: object, name: str, restype: object, *argtypes: object):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = restype, list(argtypes)
    return fn


@lru_cache(maxsize=1)
def user32():
    if os.name != "nt":
        raise OSError("Windows adapters require Windows")
    dll = C.WinDLL("user32", use_last_error=True)
    signatures = {
        "SetProcessDpiAwarenessContext": (BOOL, HANDLE),
        "GetThreadDpiAwarenessContext": (HANDLE,),
        "AreDpiAwarenessContextsEqual": (BOOL, HANDLE, HANDLE),
        "EnumDisplayMonitors": (BOOL, HANDLE, C.POINTER(RECT), MONITORENUMPROC, LPARAM),
        "GetMonitorInfoW": (BOOL, HANDLE, C.POINTER(MONITORINFO)),
        "SendInput": (UINT, UINT, C.POINTER(INPUT), C.c_int),
        "GetAsyncKeyState": (C.c_int16, C.c_int),
        "WindowFromPoint": (HANDLE, POINT), "GetAncestor": (HANDLE, HANDLE, UINT),
        "GetForegroundWindow": (HANDLE,), "GetDesktopWindow": (HANDLE,),
        "GetCursorPos": (BOOL, C.POINTER(POINT)),
        "GetShellWindow": (HANDLE,), "IsWindow": (BOOL, HANDLE),
        "IsWindowVisible": (BOOL, HANDLE), "IsIconic": (BOOL, HANDLE),
        "IsZoomed": (BOOL, HANDLE),
        "GetWindowThreadProcessId": (DWORD, HANDLE, C.POINTER(DWORD)),
        "GetClassNameW": (C.c_int, HANDLE, C.c_wchar_p, C.c_int),
        "GetWindow": (HANDLE, HANDLE, UINT),
        "GetWindowRect": (BOOL, HANDLE, C.POINTER(RECT)),
        "GetWindowPlacement": (BOOL, HANDLE, C.POINTER(WINDOWPLACEMENT)),
        "SetWindowPos": (BOOL, HANDLE, HANDLE, C.c_int, C.c_int, C.c_int, C.c_int, UINT),
        "ShowWindowAsync": (BOOL, HANDLE, C.c_int),
        "PostMessageW": (BOOL, HANDLE, UINT, WPARAM, LPARAM),
        "RegisterClassW": (WORD, C.POINTER(WNDCLASSW)),
        "UnregisterClassW": (BOOL, C.c_wchar_p, HANDLE),
        "CreateWindowExW": (HANDLE, DWORD, C.c_wchar_p, C.c_wchar_p, DWORD,
                            C.c_int, C.c_int, C.c_int, C.c_int, HANDLE, HANDLE, HANDLE, HANDLE),
        "DestroyWindow": (BOOL, HANDLE), "DefWindowProcW": (LRESULT, HANDLE, UINT, WPARAM, LPARAM),
        "GetMessageW": (BOOL, C.POINTER(MSG), HANDLE, UINT, UINT),
        "TranslateMessage": (BOOL, C.POINTER(MSG)),
        "DispatchMessageW": (LRESULT, C.POINTER(MSG)), "PostQuitMessage": (None, C.c_int),
        "RegisterHotKey": (BOOL, HANDLE, C.c_int, UINT, UINT),
        "UnregisterHotKey": (BOOL, HANDLE, C.c_int),
    }
    for name, signature in signatures.items():
        bind(dll, name, *signature)
    name = "GetWindowLongPtrW" if C.sizeof(HANDLE) == 8 else "GetWindowLongW"
    dll.window_style = bind(dll, name, C.c_ssize_t, HANDLE, C.c_int)
    return dll


def last_error() -> int:
    return getattr(C, "get_last_error", lambda: 0)()
