"""Optional Windows DuckStation hotkey handoff for its *configured* next-disc key.

The user must bind F8 to 'Switch to Next Disc' in DuckStation. We do not inject
inputs into arbitrary processes or claim that a simulated key proves a swap.
"""
from __future__ import annotations
import os


def send_duckstation_next_disc(process_ids: set[int], *, api=None) -> tuple[bool,str]:
    """Focus a window of the running emulator and tap F8, best effort.

    Uses Windows user32 keybd_event for broad compatibility, but deliberately
    only if a foreground-able window belongs to a PID tracked at launch.
    """
    if os.name!='nt' and api is None:
        return False, 'Automatic hotkey dispatch requires Windows.'
    if not process_ids:
        return False, 'No tracked emulator process is running.'
    if api is not None:
        return api(set(process_ids))
    try:
        import ctypes
        user32=ctypes.windll.user32
        import ctypes.wintypes as wt
        handles=[]
        CALLBACK=ctypes.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
        # Explicit 64-bit HWND signatures; ctypes' default integer result can
        # truncate handles on 64-bit Windows and make focus detection fail.
        user32.EnumWindows.argtypes=(CALLBACK,wt.LPARAM)
        user32.EnumWindows.restype=wt.BOOL
        user32.GetWindowThreadProcessId.argtypes=(wt.HWND,ctypes.POINTER(wt.DWORD))
        user32.GetWindowThreadProcessId.restype=wt.DWORD
        user32.GetWindow.argtypes=(wt.HWND,wt.UINT)
        user32.GetWindow.restype=wt.HWND
        user32.IsWindowVisible.argtypes=(wt.HWND,)
        user32.IsWindowVisible.restype=wt.BOOL
        user32.GetForegroundWindow.restype=wt.HWND
        user32.SetForegroundWindow.argtypes=(wt.HWND,)
        user32.SetForegroundWindow.restype=wt.BOOL
        user32.ShowWindow.argtypes=(wt.HWND,ctypes.c_int)
        user32.keybd_event.argtypes=(wt.BYTE,wt.BYTE,wt.DWORD,ctypes.c_void_p)
        def window(hwnd,_):
            pid=wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value in process_ids and user32.IsWindowVisible(hwnd) and user32.GetWindow(hwnd,4)==0:
                handles.append(hwnd)
            return True
        cb=CALLBACK(window)
        user32.EnumWindows(cb,0)
        if not handles:
            return False, 'Could not locate a window belonging to that emulator.'
        hwnd=handles[0]
        user32.ShowWindow(hwnd,9)
        user32.SetForegroundWindow(hwnd)
        if user32.GetForegroundWindow()!=hwnd:
            return False, 'Windows did not allow GameShelf to focus the emulator. Switch to the emulator and use its disc hotkey.'
        VK_F8=0x77
        KEYUP=0x0002
        user32.keybd_event(VK_F8,0,0,0)
        user32.keybd_event(VK_F8,0,KEYUP,0)
        return True, 'Sent F8 to DuckStation; confirm the disc changed in the emulator.'
    except (OSError,AttributeError,ValueError) as exc:
        return False, f'Could not send the DuckStation hotkey: {exc}'
