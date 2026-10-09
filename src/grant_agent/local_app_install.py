"""Reversible per-user installation of an App Factory Windows executable."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "neyvia.local-app-install.v1"


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LocalAppInstall:
    def __init__(self) -> None:
        if os.name != "nt" or not os.environ.get("LOCALAPPDATA") or not os.environ.get("APPDATA"):
            raise RuntimeError("Per-user App Factory installation is available on Windows only.")
        self.apps_root = (Path(os.environ["LOCALAPPDATA"]) / "Neyvia" / "Apps").resolve()
        self.shortcuts_root = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" /
                               "Start Menu" / "Programs" / "Neyvia Apps").resolve()

    def _paths(self, job: dict) -> tuple[Path, Path, Path]:
        job_id = str(job.get("jobId") or "")
        slug = str((job.get("spec") or {}).get("slug") or "")
        if not job_id.startswith("app-") or not all(c.isascii() and (c.isalnum() or c == "-") for c in job_id):
            raise ValueError("Invalid App Factory job identity for installation.")
        if not slug or not all(c.isascii() and (c.isalnum() or c == "-") for c in slug):
            raise ValueError("Invalid App Factory app slug for installation.")
        app_root = (self.apps_root / job_id).resolve()
        app_root.relative_to(self.apps_root)
        shortcut = (self.shortcuts_root / f"{slug}-{job_id}.lnk").resolve()
        shortcut.relative_to(self.shortcuts_root)
        return app_root, app_root / "installation.json", shortcut

    @staticmethod
    def _read(path: Path, job_id: str) -> dict:
        if not path.exists():
            return {"schema": SCHEMA, "jobId": job_id, "active": None, "previous": None}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("The existing installation manifest cannot be read.") from exc
        if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("jobId") != job_id:
            raise RuntimeError("The existing installation manifest belongs to another app or schema.")
        return value

    @staticmethod
    def _atomic_write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _valid_revision(app_root: Path, revision: object) -> bool:
        if not isinstance(revision, dict):
            return False
        path = Path(str(revision.get("path") or "")).resolve()
        try:
            path.relative_to(app_root)
        except ValueError:
            return False
        return path.is_file() and _sha256(path) == revision.get("sha256")

    @staticmethod
    def _write_shortcut(target: Path, shortcut: Path, name: str) -> None:
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise RuntimeError("Windows shortcut support (pywin32) is unavailable.") from exc
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        temporary = shortcut.with_name(shortcut.stem + "." + uuid.uuid4().hex + ".lnk")
        pythoncom.CoInitialize()
        shell = None
        link = None
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            link = shell.CreateShortcut(str(temporary))
            link.TargetPath = str(target)
            link.WorkingDirectory = str(target.parent)
            link.Description = name[:240]
            link.IconLocation = str(target)
            link.Save()
        finally:
            link = None
            shell = None
            pythoncom.CoUninitialize()
        if not temporary.is_file():
            raise RuntimeError("Windows did not create the app shortcut.")
        os.replace(temporary, shortcut)

    def state(self, job: dict) -> dict:
        app_root, manifest_path, shortcut = self._paths(job)
        manifest = self._read(manifest_path, job["jobId"])
        active = manifest.get("active")
        previous = manifest.get("previous")
        if active and not self._valid_revision(app_root, active):
            status = "broken"
        elif active:
            build = job.get("nativeBuild") or {}
            status = ("installed" if build.get("sourceSha256") == active.get("sourceSha256")
                      and build.get("sha256") == active.get("sha256") else "update_available")
        else:
            status = "not_installed"
        return {"state": status, "active": active, "previous": previous,
                "shortcutPath": str(shortcut) if shortcut.is_file() else "",
                "manifestPath": str(manifest_path) if manifest_path.is_file() else "",
                "rollbackAvailable": self._valid_revision(app_root, previous)}

    def install(self, job: dict) -> dict:
        build = job.get("nativeBuild") or {}
        verification = job.get("verification") or {}
        if build.get("state") != "ready" or not build.get("artifactPath"):
            raise RuntimeError("Compile the current Windows executable before installing it.")
        if verification.get("runtimeVerified") is not True or (
            (verification.get("runtimeProof") or {}).get("sourceSha256") != build.get("sourceSha256")
        ):
            raise RuntimeError("The current source needs a passing saved app journey before installation.")
        artifact = Path(str(build["artifactPath"])).resolve()
        if not artifact.is_file() or _sha256(artifact) != build.get("sha256"):
            raise RuntimeError("The compiled Windows executable is missing or changed.")
        app_root, manifest_path, shortcut = self._paths(job)
        manifest = self._read(manifest_path, job["jobId"])
        active = manifest.get("active")
        if active and not self._valid_revision(app_root, active):
            raise RuntimeError("The current installed app is damaged; repair it explicitly before updating.")
        if active and active.get("sha256") == build["sha256"]:
            return self.state(job)
        revision_dir = app_root / "versions" / build["sha256"][:24]
        revision_dir.mkdir(parents=True, exist_ok=True)
        installed = revision_dir / artifact.name
        if installed.exists() and _sha256(installed) != build["sha256"]:
            raise RuntimeError("An installed revision path already contains different bytes.")
        if not installed.exists():
            temporary = installed.with_name(installed.name + "." + uuid.uuid4().hex + ".tmp")
            shutil.copy2(artifact, temporary)
            if _sha256(temporary) != build["sha256"]:
                raise RuntimeError("The copied executable failed its hash check.")
            os.replace(temporary, installed)
        revision = {"path": str(installed), "sha256": build["sha256"],
                    "sourceSha256": build["sourceSha256"], "installedAt": _timestamp()}
        self._write_shortcut(installed, shortcut, str((job.get("spec") or {}).get("name") or "Neyvia app"))
        self._atomic_write(manifest_path, {"schema": SCHEMA, "jobId": job["jobId"],
            "appId": (job.get("spec") or {}).get("appId"), "name": (job.get("spec") or {}).get("name"),
            "active": revision, "previous": active, "shortcutPath": str(shortcut), "updatedAt": _timestamp()})
        return self.state(job)

    def rollback(self, job: dict) -> dict:
        app_root, manifest_path, shortcut = self._paths(job)
        manifest = self._read(manifest_path, job["jobId"])
        current, previous = manifest.get("active"), manifest.get("previous")
        if not self._valid_revision(app_root, previous):
            raise RuntimeError("No intact previous installed revision is available.")
        self._write_shortcut(Path(previous["path"]), shortcut,
                             str((job.get("spec") or {}).get("name") or "Neyvia app"))
        manifest.update(active=previous, previous=current, updatedAt=_timestamp())
        self._atomic_write(manifest_path, manifest)
        return self.state(job)
