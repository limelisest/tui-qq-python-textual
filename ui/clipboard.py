"""System clipboard access.

Currently Windows-only via PowerShell; on other platforms the helpers degrade
to no-ops so the rest of the app keeps working. The interface is intentionally
narrow (get/set) so platform-specific backends can be added later (macOS
``pbcopy``/``pbpaste``, wl-clipboard on Linux, etc.) without touching callers.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Optional

from ui.theme import CLIPBOARD_TIMEOUT


def _run_powershell(command: str, input_text: Optional[str] = None):
    """Run a PowerShell command, returning the completed process or ``None``.

    Returns ``None`` on any OS/subprocess error so callers can treat "not
    available" uniformly instead of distinguishing error kinds.
    """
    if platform.system() != "Windows":
        return None
    try:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLIPBOARD_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def set_system_clipboard(text: str) -> bool:
    """Write ``text`` to the OS clipboard. Returns ``True`` on success."""
    command = (
        "[Console]::InputEncoding=[Text.Encoding]::UTF8; "
        "$text=[Console]::In.ReadToEnd(); Set-Clipboard -Value $text"
    )
    result = _run_powershell(command, text)
    return result is not None and result.returncode == 0


def get_system_clipboard() -> str:
    """Read the OS clipboard; returns ``''`` when unavailable or on error."""
    command = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-Clipboard -Raw"
    )
    result = _run_powershell(command)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout
