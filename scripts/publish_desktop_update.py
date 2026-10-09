"""Build, sign and publish a desktop update to the PC service's feed.

    python scripts/publish_desktop_update.py [--tree PATH] [--bump] [--notes TEXT]

Only changes to the desktop shell itself (``src-tauri``: tray, window, updater, native
commands) need this. The interface and the Python side reach the desktop app without a
new build: its loader takes the interface from the PC service, and the service's code
is promoted in place.

Steps: optionally bump the patch version (tauri.conf.json, Cargo.toml, package.json);
run ``npm run tauri build`` with the signing key from ``desktop_update_key``; copy the
NSIS installer and its signature into ``<state root>/.agent_control/desktop-updates``;
write ``latest.json`` there, which installed apps poll; keep the three newest builds.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop_update_key  # noqa: E402

FEED_URL = "http://127.0.0.1:47881/updates/desktop"
KEEP = 3


def _version(tree: Path) -> str:
    return json.loads((tree / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]


def bump(tree: Path) -> str:
    current = _version(tree)
    major, minor, patch = (int(part) for part in current.split("."))
    new = f"{major}.{minor}.{patch + 1}"
    for relative, pattern in (("src-tauri/tauri.conf.json", r'"version": "{0}"'), ("src-tauri/Cargo.toml", r'(?m)^version = "{0}"'),
                              ("package.json", r'"version": "{0}"')):
        path = tree / relative
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(pattern.format(re.escape(current)), lambda match: match.group(0).replace(current, new), text, count=1)
        if count != 1:
            raise SystemExit(f"Could not find version {current} in {relative}.")
        path.write_text(updated, encoding="utf-8")
    return new


def build(tree: Path) -> None:
    env = {**os.environ, "TAURI_SIGNING_PRIVATE_KEY": desktop_update_key.private_key(),
           "TAURI_SIGNING_PRIVATE_KEY_PASSWORD": desktop_update_key.password()}
    npm = "npm.cmd" if os.name == "nt" else "npm"
    done = subprocess.run([npm, "run", "tauri", "build"], cwd=tree, env=env, check=False)
    if done.returncode != 0:
        raise SystemExit(f"The desktop build failed (exit {done.returncode}).")


def publish(tree: Path, state_root: Path, notes: str) -> dict:
    version = _version(tree)
    bundle = tree / "src-tauri" / "target" / "release" / "bundle" / "nsis"
    installer = bundle / f"Neyvia_{version}_x64-setup.exe"
    signature = Path(str(installer) + ".sig")
    if not installer.is_file() or not signature.is_file():
        raise SystemExit(f"No signed installer for {version} in {bundle}. Build it first.")
    feed = state_root / ".agent_control" / "desktop-updates"
    feed.mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer, feed / installer.name)
    shutil.copy2(signature, feed / signature.name)
    latest = {
        "version": version,
        "notes": notes or f"Neyvia {version}",
        "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {"windows-x86_64": {"signature": signature.read_text(encoding="utf-8").strip(),
                                         "url": f"{FEED_URL}/{installer.name}"}},
    }
    temp = feed / "latest.json.tmp"
    temp.write_text(json.dumps(latest, indent=2) + "\n", encoding="utf-8")
    temp.replace(feed / "latest.json")
    builds = sorted(feed.glob("Neyvia_*_x64-setup.exe"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in builds[KEEP:]:
        old.unlink(missing_ok=True)
        Path(str(old) + ".sig").unlink(missing_ok=True)
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tree", default=str(Path(__file__).resolve().parents[1]), help="checkout to build (default: this one)")
    parser.add_argument("--state-root", default=r"C:\Users\user\Projects\Neyvia", help="the PC service's state root")
    parser.add_argument("--bump", action="store_true", help="raise the patch version first")
    parser.add_argument("--no-build", action="store_true", help="publish the installer already built")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    tree = Path(args.tree).resolve()
    if args.bump:
        print("version", bump(tree))
    if not args.no_build:
        build(tree)
    latest = publish(tree, Path(args.state_root), args.notes)
    print(f"Published Neyvia {latest['version']} to {FEED_URL}/latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
