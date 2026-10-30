"""Read-only host facts for comparing confinement feasibility reports.

This is discovery, not a sandbox test. Executable paths can contain the user's
name; credentials, the environment block and command output are not collected.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import struct
import sys
from typing import Any


def _windows_update_revision() -> int | None:
    """Windows API build numbers omit the revision needed for MXC eligibility."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            revision, _ = winreg.QueryValueEx(key, "UBR")
        return revision if isinstance(revision, int) else None
    except (ImportError, OSError):
        return None


def _windows_privileges() -> dict[str, Any]:
    """Read the current process token without requesting any privilege change."""
    from ctypes import wintypes

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
    except (AttributeError, OSError):
        return {"status": "unknown", "method": "windows_token_elevation",
                "reason": "token_api_unavailable"}

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008,
                                    ctypes.byref(token)):
        return {"status": "unknown", "method": "windows_token_elevation",
                "reason": "open_token_failed", "error_code": ctypes.get_last_error()}

    try:
        elevated = wintypes.DWORD()
        returned_length = wintypes.DWORD()
        # TokenElevation (20) returns a TOKEN_ELEVATION containing one DWORD.
        if not advapi32.GetTokenInformation(
            token, 20, ctypes.byref(elevated), ctypes.sizeof(elevated),
            ctypes.byref(returned_length),
        ):
            return {"status": "unknown", "method": "windows_token_elevation",
                    "reason": "query_token_failed",
                    "error_code": ctypes.get_last_error()}
        if returned_length.value != ctypes.sizeof(elevated):
            return {"status": "unknown", "method": "windows_token_elevation",
                    "reason": "unexpected_token_result_size"}
        return {
            "status": "elevated" if elevated.value else "non_elevated",
            "method": "windows_token_elevation",
        }
    finally:
        kernel32.CloseHandle(token)


def _privileges(system: str) -> dict[str, Any]:
    if system == "Windows":
        return _windows_privileges()
    if system == "Darwin":
        try:
            effective_uid = os.geteuid()
        except (AttributeError, OSError):
            return {"status": "unknown", "method": "effective_uid",
                    "reason": "uid_unavailable"}
        return {
            "status": "elevated" if effective_uid == 0 else "non_elevated",
            "method": "effective_uid",
            "effective_uid": effective_uid,
        }
    return {"status": "unknown", "method": None,
            "reason": "unsupported_platform"}


def collect_environment() -> dict[str, Any]:
    """Return JSON-compatible observations without launching tools or probing writes.

    ``reported_machine`` is Python's platform observation, not a claim that the
    interpreter is native: Windows and macOS may run it under emulation.
    ``non_elevated`` describes the process token/UID only; it is not confinement.
    """
    system = platform.system()
    os_report: dict[str, Any] = {
        "system": system,
        "release": platform.release(),
        "version": platform.version(),
        "reported_machine": platform.machine(),
    }
    if system == "Darwin":
        os_report["macos_version"] = platform.mac_ver()[0]
    if system == "Windows" and hasattr(sys, "getwindowsversion"):
        version = sys.getwindowsversion()
        os_report["windows_version"] = {
            "major": version.major,
            "minor": version.minor,
            "build": version.build,
            "update_build_revision": _windows_update_revision(),
        }

    commands = {}
    for name in ("powershell", "pwsh", "node", "git"):
        executable = shutil.which(name)
        commands[name] = {"available": executable is not None, "path": executable}

    return {
        "schema_version": 1,
        "os": os_report,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "pointer_bits": struct.calcsize("P") * 8,
        },
        "privileges": _privileges(system),
        "commands": commands,
    }
