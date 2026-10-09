"""Create checked-in license evidence from already-resolved local metadata.

This collector performs no network access. Cargo metadata JSON must have been
captured for the intended target, and the Python environment must already have
been synchronized from uv.lock. The release inventory consumes only the
resulting checked-in JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from email.parser import Parser
from pathlib import Path
from typing import Any

from packaging.markers import Marker, default_environment


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _cargo_evidence(
    metadata_path: Path, lock_path: Path, *, component: str, target: str
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    locked = {
        (
            str(item["name"]),
            str(item["version"]),
            str(item.get("source") or ""),
        ): item
        for item in lock["package"]
    }
    packages = []
    for item in metadata["packages"]:
        source = str(item.get("source") or "")
        key = (str(item["name"]), str(item["version"]), source)
        locked_item = locked.get(key)
        if locked_item is None:
            raise ValueError(f"cargo metadata identity is not locked: {key}")
        license_value = item.get("license")
        if not license_value:
            raise ValueError(f"cargo metadata lacks a license: {key}")
        packages.append(
            {
                "name": key[0],
                "version": key[1],
                "source": key[2],
                "checksum": locked_item.get("checksum"),
                "license": license_value,
            }
        )
    return {
        "component": component,
        "target": target,
        "lockSha256": _sha256(lock_path),
        "metadataCaptureSha256": _sha256(metadata_path),
        "packages": sorted(
            packages,
            key=lambda item: (item["name"], item["version"], item["source"]),
        ),
    }


def _requirements(requirements_path: Path) -> set[tuple[str, str]]:
    selected: set[tuple[str, str]] = set()
    environment = default_environment()
    environment.update(
        {
            "implementation_name": "cpython",
            "platform_python_implementation": "CPython",
            "python_full_version": "3.12.11",
            "python_version": "3.12",
        }
    )
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        match = re.match(
            r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)(?:\s*;\s*(.*?))?\s*\\?$",
            line,
        )
        if match and (
            not match.group(3) or Marker(match.group(3)).evaluate(environment)
        ):
            selected.add((match.group(1).lower().replace("_", "-"), match.group(2)))
    if not selected:
        raise ValueError("Python export contains no pinned packages")
    return selected


def _python_evidence(
    site_packages: Path,
    requirements_path: Path,
    uv_lock_path: Path,
    *,
    target: str,
) -> dict[str, Any]:
    selected = _requirements(requirements_path)
    lock = tomllib.loads(uv_lock_path.read_text(encoding="utf-8"))
    locked = {
        (str(item["name"]).lower().replace("_", "-"), str(item["version"])): item
        for item in lock["package"]
    }
    metadata_by_identity: dict[tuple[str, str], tuple[Path, Any]] = {}
    for path in site_packages.glob("*.dist-info/METADATA"):
        message = Parser().parsestr(path.read_text(encoding="utf-8"))
        key = (
            str(message["Name"]).lower().replace("_", "-"),
            str(message["Version"]),
        )
        metadata_by_identity[key] = (path, message)
    packages = []
    for key in sorted(selected):
        if key not in locked:
            raise ValueError(f"Python export identity is not in uv.lock: {key}")
        metadata_entry = metadata_by_identity.get(key)
        if metadata_entry is None:
            raise ValueError(f"Python metadata is unavailable for exact identity: {key}")
        path, message = metadata_entry
        expression = message.get("License-Expression")
        raw_license = message.get("License")
        classifiers = sorted(
            value
            for value in message.get_all("Classifier", [])
            if value.startswith("License ::")
        )
        if expression:
            declaration: dict[str, Any] = {"expression": expression}
        elif raw_license and raw_license.strip() not in {"", "UNKNOWN"} and len(raw_license) <= 200:
            declaration = {"declaredText": raw_license.strip()}
        elif classifiers:
            declaration = {"classifiers": classifiers}
        else:
            raise ValueError(f"Python metadata lacks license evidence: {key}")
        packages.append(
            {
                "name": key[0],
                "version": key[1],
                "source": locked[key].get("source") or {},
                "license": declaration,
                "metadataSha256": _sha256(path),
            }
        )
    return {
        "target": target,
        "uvLockSha256": _sha256(uv_lock_path),
        "requirementsCaptureSha256": _sha256(requirements_path),
        "packages": packages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--desktop-cargo-metadata", required=True)
    parser.add_argument("--cache-cargo-metadata", required=True)
    parser.add_argument("--python-requirements", required=True)
    parser.add_argument("--python-site-packages", required=True)
    parser.add_argument(
        "--target",
        default="windows-x86_64-msvc-python312",
    )
    parser.add_argument(
        "--output",
        default="config/neyvia_dependency_license_evidence.json",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    payload = {
        "schema": "neyvia.dependency-license-evidence/v1",
        "offlineInventoryInput": True,
        "target": args.target,
        "workspaceOverrides": [
            {
                "id": "npm:workspace",
                "license": "MIT",
                "evidence": [
                    "pyproject.toml project.license",
                    "src-tauri/Cargo.toml package.license",
                ],
            }
        ],
        "cargo": [
            _cargo_evidence(
                Path(args.desktop_cargo_metadata),
                root / "src-tauri/Cargo.lock",
                component="desktop-rust",
                target="x86_64-pc-windows-msvc",
            ),
            _cargo_evidence(
                Path(args.cache_cargo_metadata),
                root / "tools/neyvia-iroh-cache/Cargo.lock",
                component="iroh-cache-rust",
                target="x86_64-pc-windows-msvc",
            ),
        ],
        "python": _python_evidence(
            Path(args.python_site_packages),
            Path(args.python_requirements),
            root / "uv.lock",
            target="cpython-3.12-windows-x86_64",
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(hashlib.sha256(output.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
