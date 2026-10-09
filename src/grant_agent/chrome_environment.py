"""Chrome-only Windows metadata with explicit application-owned browser data.

Do not apply this environment to backend, provider or Node processes: their
isolated discovery homes must remain isolated. No operator profile is opened.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Mapping

_PRIVATE_ENV = re.compile(r"API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BASE.?URL|BROKER|CHROME_USER_DATA_DIR", re.I)


def chrome_environment(directory: str | Path, inherited: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a sanitized child environment, never changing the runner's homes."""
    source = dict(os.environ if inherited is None else inherited)
    env = {key: value for key, value in source.items() if not _PRIVATE_ENV.search(key)}
    temporary = Path(directory).resolve() / "temp"
    temporary.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    if os.name == "nt":
        drive, home = source.get("HOMEDRIVE", ""), source.get("HOMEPATH", "")
        profile = Path(drive + home)
        if not drive or not home or not profile.is_absolute():
            raise RuntimeError("Windows home path metadata unavailable; no Chrome profile fallback")
        env.update(USERPROFILE=str(profile), APPDATA=str(profile / "AppData/Roaming"),
                   LOCALAPPDATA=str(profile / "AppData/Local"))
    return env


def fresh_chrome_profile(root: str | Path, purpose: str) -> Path:
    """Create an empty profile under the selected root, without importing data."""
    if not re.fullmatch(r"[a-z0-9-]+", purpose):
        raise ValueError("Chrome profile purpose must be a simple directory label")
    # Native receipts can nest roots deeply. Leave room for Chrome's own
    # Default profile files on Windows, without using an external temp root.
    parent = Path(root).resolve() / ".chrome"
    parent.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="p-", dir=parent))
    if any(profile.iterdir()):
        raise RuntimeError("New owned Chrome profile was not empty")
    return profile


CHROME_AUTOMATION_ARGS = ["--disable-gpu", "--disable-background-networking",
    "--disable-component-update", "--disable-sync", "--no-first-run",
    "--no-default-browser-check", "--password-store=basic", "--disable-save-password-bubble"]


def chrome_executable(preflight: Mapping[str, object]) -> str:
    """Select installed Windows Chrome explicitly; never use a download cache."""
    if os.name == "nt":
        installed = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        if not installed.is_file():
            raise FileNotFoundError("Installed Google Chrome is unavailable")
        return str(installed)
    executable = str(preflight.get("chromeExecutable") or "").strip()
    if not executable:
        raise FileNotFoundError("Browser preflight did not select an executable")
    return executable
