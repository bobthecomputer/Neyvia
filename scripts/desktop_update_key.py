"""The desktop updater's signing key: where it lives and how its password is kept.

The private key (``neyvia-updater.key``) stays in ``%APPDATA%\\Neyvia\\updater`` on the PC that
publishes desktop updates. Its password is random and stored encrypted with Windows DPAPI for the
current Windows user, so publishing needs no typing and the password is never written in the clear.
The matching public key is built into the app; losing the private key means one manual reinstall.
"""
from __future__ import annotations

import ctypes
import os
import secrets
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Neyvia" / "updater"
KEY_FILE = KEY_DIR / "neyvia-updater.key"
PASSWORD_FILE = KEY_DIR / "neyvia-updater.password.dpapi"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.WinDLL("crypt32"), ctypes.WinDLL("kernel32")
    source = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise OSError("Windows could not " + ("protect" if protect else "unlock") + " the updater key password.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def password() -> str:
    return _dpapi(PASSWORD_FILE.read_bytes(), protect=False).decode("utf-8")


def public_key() -> str:
    return Path(str(KEY_FILE) + ".pub").read_text(encoding="utf-8").strip()


def private_key() -> str:
    return KEY_FILE.read_text(encoding="utf-8").strip()


def create() -> None:
    """Make the key pair once; refuses to replace an existing key (that would strand installed apps)."""
    if KEY_FILE.exists():
        raise SystemExit(f"A key already exists at {KEY_FILE}; keeping it.")
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(32)
    npx = "npx.cmd" if os.name == "nt" else "npx"
    done = subprocess.run([npx, "tauri", "signer", "generate", "--ci", "-w", str(KEY_FILE), "-p", secret],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode != 0 or not KEY_FILE.exists():
        raise SystemExit("Key generation failed:\n" + (done.stderr or done.stdout)[-2000:])
    PASSWORD_FILE.write_bytes(_dpapi(secret.encode("utf-8"), protect=True))
    print(f"Created {KEY_FILE} (+ .pub) and its protected password.")


def restore(folder: Path) -> None:
    """Bring back a key saved elsewhere (a backup holds the key, its .pub and password.txt)."""
    if KEY_FILE.exists():
        raise SystemExit(f"A key already exists at {KEY_FILE}; keeping it.")
    folder = Path(folder)
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("neyvia-updater.key", "neyvia-updater.key.pub"):
        (KEY_DIR / name).write_bytes((folder / name).read_bytes())
    secret = (folder / "neyvia-updater.password.txt").read_text(encoding="utf-8").strip()
    PASSWORD_FILE.write_bytes(_dpapi(secret.encode("utf-8"), protect=True))
    print(f"Restored the updater key into {KEY_DIR}.")


if __name__ == "__main__":
    if sys.argv[1:] == ["create"]:
        create()
    elif sys.argv[1:2] == ["restore"] and len(sys.argv) == 3:
        restore(Path(sys.argv[2]))
    elif sys.argv[1:] == ["public"]:
        print(public_key())
    else:
        raise SystemExit("usage: desktop_update_key.py create | public | restore <backup folder>")
