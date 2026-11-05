import ctypes
import os
import subprocess
import sys
from pathlib import Path


def get_default_video_folder():
    """Return the user's actual Windows Videos folder, including OneDrive redirects."""
    if os.name == "nt":
        try:
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", ctypes.c_ulong),
                    ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            videos_guid = GUID()
            values = "18989B1D99B5455B841CAB7C74E4DDFC"
            videos_guid.Data1 = int(values[0:8], 16)
            videos_guid.Data2 = int(values[8:12], 16)
            videos_guid.Data3 = int(values[12:16], 16)
            videos_guid.Data4[:] = bytes.fromhex(values[16:])

            path_pointer = ctypes.c_wchar_p()
            result = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(videos_guid), 0, None, ctypes.byref(path_pointer)
            )
            if result == 0 and path_pointer.value:
                videos_folder = Path(path_pointer.value)
                ctypes.windll.ole32.CoTaskMemFree(path_pointer)
                return videos_folder
        except Exception:
            pass

    return Path.home() / "Videos"


def hidden_subprocess_kwargs():
    """Prevent Windows console windows from appearing for helper processes."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def resource_path(relative_path):
    """Resolve bundled resources both from source and from PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent.parent / relative_path
