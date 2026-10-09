#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_line(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def command_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or result.stderr or "").strip()


def probe() -> dict[str, Any]:
    macos_version = command_version(["sw_vers", "-productVersion"])
    xcode_version = command_version(["xcodebuild", "-version"])
    xcode_path = command_version(["xcode-select", "-p"])
    disk = shutil.disk_usage(Path.home())
    ready = platform.system() == "Darwin" and bool(xcode_version) and bool(shutil.which("python3"))
    summary = (
        f"macOS {macos_version or 'unknown'} · {xcode_version.replace(chr(10), ' · ') or 'Xcode missing'}"
        if ready
        else "This host is not a ready macOS Xcode builder."
    )
    return {
        "schema": "neyvia.ios_builder_probe.v1",
        "generatedAt": utc_now(),
        "ready": ready,
        "summary": summary,
        "host": platform.node(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "macosVersion": macos_version,
        "xcodeVersion": xcode_version,
        "xcodePath": xcode_path,
        "pythonVersion": platform.python_version(),
        "cocoaPodsVersion": command_version(["pod", "--version"]) if shutil.which("pod") else "",
        "freeDiskBytes": disk.free,
    }


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                raise RuntimeError(f"Build capsule contains a link and was rejected: {member.name}")
            member_path = (destination / member.name).resolve()
            try:
                member_path.relative_to(destination_root)
            except ValueError as exc:
                raise RuntimeError(f"Build capsule contains an unsafe path: {member.name}") from exc
        archive.extractall(destination)


class BuildLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def note(self, message: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{utc_now()}] {message}\n")

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int = 1800,
    ) -> subprocess.CompletedProcess[str]:
        self.note(f"$ {' '.join(command)}")
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self.note(f"Command timed out after {timeout}s")
            raise RuntimeError(f"{command[0]} timed out after {timeout}s") from exc
        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        with self.path.open("a", encoding="utf-8") as handle:
            if output:
                handle.write(output.rstrip() + "\n")
            handle.write(f"[return-code] {completed.returncode}\n")
        if completed.returncode != 0:
            detail = output.strip()[-1800:] or "Command failed without output."
            raise RuntimeError(f"{command[0]} failed: {detail}")
        return completed


def install_javascript_dependencies(project: Path, log: BuildLog, env: dict[str, str]) -> None:
    if (project / "pnpm-lock.yaml").exists():
        log.run(["corepack", "pnpm", "install", "--frozen-lockfile"], cwd=project, env=env)
        return
    if (project / "yarn.lock").exists():
        log.run(["corepack", "yarn", "install", "--immutable"], cwd=project, env=env)
        return
    if (project / "package-lock.json").exists():
        log.run(["npm", "ci"], cwd=project, env=env)
        return
    log.run(["npm", "install"], cwd=project, env=env)


def package_dependencies(project: Path) -> dict[str, Any]:
    try:
        package = json.loads((project / "package.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Build capsule does not contain a readable package.json.") from exc
    return {
        **(package.get("dependencies") if isinstance(package.get("dependencies"), dict) else {}),
        **(package.get("devDependencies") if isinstance(package.get("devDependencies"), dict) else {}),
    }


def prepare_native_project(project: Path, log: BuildLog, env: dict[str, str]) -> None:
    dependencies = package_dependencies(project)
    if not (project / "ios").is_dir():
        if "expo" not in dependencies:
            raise RuntimeError("React Native projects without an ios directory cannot be generated by this builder.")
        log.run(["npx", "expo", "prebuild", "--platform", "ios", "--no-install"], cwd=project, env=env)
    if not (project / "ios" / "Podfile").exists():
        raise RuntimeError("The generated iOS project does not contain a Podfile.")
    if (project / "Gemfile").exists() and shutil.which("bundle"):
        log.run(["bundle", "install"], cwd=project, env=env)
        log.run(["bundle", "exec", "pod", "install", "--project-directory=ios"], cwd=project, env=env)
    else:
        log.run(["npx", "pod-install", "ios"], cwd=project, env=env)


def xcode_container(project: Path) -> tuple[str, Path]:
    workspaces = sorted((project / "ios").glob("*.xcworkspace"))
    if workspaces:
        return "-workspace", workspaces[0]
    projects = [path for path in sorted((project / "ios").glob("*.xcodeproj")) if path.name != "Pods.xcodeproj"]
    if projects:
        return "-project", projects[0]
    raise RuntimeError("No Xcode workspace or project was generated.")


def shared_scheme(project: Path, container_kind: str, container: Path, log: BuildLog, env: dict[str, str]) -> str:
    result = log.run(
        ["xcodebuild", container_kind, str(container), "-list", "-json"],
        cwd=project,
        env=env,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("xcodebuild did not return a readable scheme list.") from exc
    container_payload = payload.get("workspace") or payload.get("project") or {}
    schemes = container_payload.get("schemes") if isinstance(container_payload, dict) else []
    candidates = [str(item) for item in schemes or [] if str(item).strip() and not str(item).lower().startswith("pods-")]
    if not candidates:
        raise RuntimeError("The Xcode project has no shared build scheme.")
    return candidates[0]


def export_method(mode: str) -> str:
    help_text = command_version(["xcodebuild", "-help"])
    if mode == "app-store":
        return "app-store-connect" if "app-store-connect" in help_text else "app-store"
    if mode == "development":
        return "debugging" if "debugging" in help_text else "development"
    raise RuntimeError(f"No export method exists for mode {mode}.")


def simulator_build(
    project: Path,
    container_kind: str,
    container: Path,
    scheme: str,
    job_dir: Path,
    log: BuildLog,
    env: dict[str, str],
) -> Path:
    derived_data = job_dir / "DerivedData"
    log.run(
        [
            "xcodebuild",
            container_kind,
            str(container),
            "-scheme",
            scheme,
            "-configuration",
            "Release",
            "-sdk",
            "iphonesimulator",
            "-derivedDataPath",
            str(derived_data),
            "CODE_SIGNING_ALLOWED=NO",
            "build",
        ],
        cwd=project,
        env=env,
    )
    apps = sorted((derived_data / "Build" / "Products").glob("Release-iphonesimulator/*.app"))
    if not apps:
        raise RuntimeError("Xcode completed but no Simulator .app was produced.")
    artifact = job_dir / f"{scheme}-simulator.app.zip"
    log.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(apps[0]), str(artifact)], cwd=project, env=env)
    return artifact


def signed_build(
    project: Path,
    container_kind: str,
    container: Path,
    scheme: str,
    job_dir: Path,
    mode: str,
    team_id: str,
    log: BuildLog,
    env: dict[str, str],
) -> Path:
    if not team_id:
        raise RuntimeError("A 10-character Apple Team ID is required for signed builds.")
    archive_path = job_dir / f"{scheme}.xcarchive"
    log.run(
        [
            "xcodebuild",
            container_kind,
            str(container),
            "-scheme",
            scheme,
            "-configuration",
            "Release",
            "-destination",
            "generic/platform=iOS",
            "-archivePath",
            str(archive_path),
            "-allowProvisioningUpdates",
            f"DEVELOPMENT_TEAM={team_id}",
            "CODE_SIGN_STYLE=Automatic",
            "archive",
        ],
        cwd=project,
        env=env,
    )
    export_path = job_dir / "export"
    export_path.mkdir(parents=True, exist_ok=True)
    options_path = job_dir / "ExportOptions.plist"
    options = {
        "method": export_method(mode),
        "destination": "export",
        "signingStyle": "automatic",
        "teamID": team_id,
        "stripSwiftSymbols": True,
    }
    with options_path.open("wb") as handle:
        plistlib.dump(options, handle)
    log.run(
        [
            "xcodebuild",
            "-exportArchive",
            "-archivePath",
            str(archive_path),
            "-exportPath",
            str(export_path),
            "-exportOptionsPlist",
            str(options_path),
            "-allowProvisioningUpdates",
        ],
        cwd=project,
        env=env,
    )
    ipas = sorted(export_path.glob("*.ipa"))
    if not ipas:
        raise RuntimeError("Xcode exported the archive but no .ipa was produced.")
    artifact = job_dir / ipas[0].name
    shutil.move(str(ipas[0]), artifact)
    return artifact


def build(args: argparse.Namespace) -> dict[str, Any]:
    remote_root = Path(args.remote_root).expanduser().resolve()
    job_dir = remote_root / "jobs" / args.job_id
    project = job_dir / "source" / "project"
    log = BuildLog(job_dir / "build.log")
    receipt_path = job_dir / "receipt.json"
    receipt: dict[str, Any] = {
        "schema": "neyvia.ios_builder_receipt.v1",
        "jobId": args.job_id,
        "mode": args.mode,
        "status": "running",
        "createdAt": utc_now(),
        "updatedAt": utc_now(),
        "jobDir": str(job_dir),
        "logPath": str(log.path),
        "receiptPath": str(receipt_path),
    }
    job_dir.mkdir(parents=True, exist_ok=True)
    write_json(receipt_path, receipt)
    try:
        capsule = Path(args.capsule).expanduser().resolve()
        if not capsule.exists():
            raise RuntimeError(f"Build capsule does not exist: {capsule}")
        log.note(f"Neyvia iOS build {args.job_id} started in {args.mode} mode.")
        safe_extract(capsule, job_dir / "source")
        manifest_path = job_dir / "source" / "neyvia-build-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("jobId") != args.job_id or manifest.get("mode") != args.mode:
            raise RuntimeError("Build capsule manifest does not match the requested job.")

        environment = dict(os.environ)
        environment.update({"CI": "1", "LANG": environment.get("LANG") or "en_US.UTF-8"})
        install_javascript_dependencies(project, log, environment)
        prepare_native_project(project, log, environment)
        container_kind, container = xcode_container(project)
        scheme = shared_scheme(project, container_kind, container, log, environment)
        log.note(f"Selected scheme {scheme} from {container.name}.")
        if args.mode == "simulator":
            artifact = simulator_build(project, container_kind, container, scheme, job_dir, log, environment)
        else:
            artifact = signed_build(
                project,
                container_kind,
                container,
                scheme,
                job_dir,
                args.mode,
                args.team_id,
                log,
                environment,
            )
        receipt.update(
            {
                "status": "completed",
                "updatedAt": utc_now(),
                "artifactPath": str(artifact),
                "artifactBytes": artifact.stat().st_size,
                "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "scheme": scheme,
                "container": str(container),
                "xcodeVersion": command_version(["xcodebuild", "-version"]),
                "manifest": manifest,
            }
        )
    except Exception as exc:
        log.note(f"Build failed: {exc}")
        receipt.update({"status": "failed", "updatedAt": utc_now(), "error": str(exc)})
    write_json(receipt_path, receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Neyvia private macOS iOS build runner")
    subparsers = root.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe", help="Report macOS and Xcode readiness")
    build_parser = subparsers.add_parser("build", help="Compile one Neyvia source capsule")
    build_parser.add_argument("--capsule", required=True)
    build_parser.add_argument("--job-id", required=True)
    build_parser.add_argument("--mode", choices=["simulator", "development", "app-store"], required=True)
    build_parser.add_argument("--remote-root", default="~/NeyviaBuilds")
    build_parser.add_argument("--team-id", default="")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "probe":
        payload = probe()
        json_line(payload)
        return 0 if payload["ready"] else 1
    receipt = build(args)
    json_line(receipt)
    return 0 if receipt.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
