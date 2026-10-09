"""Universal AppKit/WKWebView web-export bundle, compiled on Windows."""
from __future__ import annotations
import plistlib
import re
import struct
import uuid
import zipfile
from pathlib import Path
from . import windows_ios_compiler as ios
from .apple_bundle import seal_resources, sign_macos_slice, universal, verify_bundle

BUILDS = Path(".agent_control/windows_macos_builds")


def _icon(resources: Path, project: Path) -> None:
    # A project can supply a complete Apple icon set. Fallback uses the existing
    # Neyvia authoring icon, never silently claims to be the project's artwork.
    supplied = project / "native/AppIcon.icns"
    if supplied.is_file():
        (resources / "AppIcon.icns").write_bytes(supplied.read_bytes())
        return
    png = (ios._repo_root() / "web/public/icons/neyvia-512.png").read_bytes()
    chunk = b"ic09" + struct.pack(">I", len(png) + 8) + png
    (resources / "AppIcon.icns").write_bytes(b"icns" + struct.pack(">I", len(chunk) + 8) + chunk)


def package_macos(app: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob("*")):
            if path.is_symlink():
                raise ValueError("Refusing linked bundle member")
            if not path.is_file():
                continue
            member = zipfile.ZipInfo(path.relative_to(app.parent).as_posix())
            member.create_system = 3
            mode = 0o100755 if path.parent.name == "MacOS" else 0o100644
            member.external_attr = mode << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, path.read_bytes())


def build_windows_macos_app(root: str | Path, *, minimum_macos: str = "12.0") -> dict:
    project = Path(root).resolve()
    if not ios._VERSION_PATTERN.fullmatch(minimum_macos):
        raise ValueError("Minimum macOS must look like 12.0")
    tools = ios._inspect_direct_windows_toolchain()
    if not tools["ready"]:
        raise RuntimeError("Direct Windows LLVM compiler/linker/objdump are required; no WSL or VM fallback")
    name, identifier = ios._resolve_project_metadata(project)
    build = project / BUILDS / ("win_mac_" + uuid.uuid4().hex[:12])
    app = build / ((re.sub(r"[^A-Za-z0-9]", "", name)[:32] or "NeyviaApp") + ".app")
    contents = app / "Contents"
    resources, macos = contents / "Resources", contents / "MacOS"
    resources.mkdir(parents=True); macos.mkdir()
    receipt_path = build / "receipt.json"
    receipt = {"schema": "neyvia.windows_apple_build.v1", "platform": "macos", "jobId": build.name,
               "status": "running", "host": "windows-native", "engine": "win32", "nativeProcess": True,
               "wslInvoked": False, "createdAt": ios._utc_now(), "projectRoot": str(project),
               "receiptPath": str(receipt_path), "compiler": tools["tools"].get("clangVersion"),
               "appPath": str(app), "signatureKind": "adhoc", "notarized": False,
               "nativeExecutionVerified": False, "iconSource": "project native/AppIcon.icns" if (project / "native/AppIcon.icns").is_file() else "Neyvia authoring icon"}
    ios._write_json(receipt_path, receipt)
    try:
        ios._safe_copy_web_assets(project, build, resources)
        _icon(resources, project)
        info = {"CFBundleName": name, "CFBundleDisplayName": name, "CFBundleExecutable": "NeyviaApp",
                "CFBundleIdentifier": identifier, "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0", "CFBundleSupportedPlatforms": ["MacOSX"],
                "LSMinimumSystemVersion": minimum_macos, "NSHighResolutionCapable": True, "CFBundleIconFile": "AppIcon",
                "NSPrincipalClass": "NSApplication"}
        info_bytes = plistlib.dumps(info, fmt=plistlib.FMT_BINARY)
        (contents / "Info.plist").write_bytes(info_bytes)
        (contents / "PkgInfo").write_bytes(b"APPL????")
        resource_bytes = seal_resources(contents)
        (contents / "_CodeSignature").mkdir()
        (contents / "_CodeSignature/CodeResources").write_bytes(resource_bytes)
        thin, log = [], []
        source = ios._repo_root() / "native/macos/neyvia_runtime.c"
        stubs = source.parent / "stubs"
        for arch in ("arm64", "x86_64"):
            object_path, executable = build / (arch + ".o"), build / (arch + ".macho")
            compile_command = [tools["tools"]["clang"], "-target", f"{arch}-apple-macos{minimum_macos}",
                               "-O2", "-ffreestanding", "-fno-stack-protector", "-fno-builtin", "-c", str(source), "-o", str(object_path)]
            link_command = [tools["tools"]["linker"], "-arch", arch, "-platform_version", "macos", minimum_macos, "15.0",
                            "-o", str(executable), str(object_path), "-L", str(stubs), "-lSystem", "-lobjc",
                            "-e", "_main", "-dead_strip", "-adhoc_codesign"]
            for command in (compile_command, link_command):
                result = ios._run(command, timeout=300, check=False)
                log.append({"command": command, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
                ios._write_json(build / "compile.json", log)
                if result.returncode:
                    raise RuntimeError(ios._clean_error(result.stderr, "Mac compilation failed"))
            sign_macos_slice(executable, identifier, info_bytes, resource_bytes)
            thin.append(executable)
        output = macos / "NeyviaApp"
        universal(thin, output)
        outcome = verify_bundle(app, "macos")
        ios._write_json(build / "outcome.json", outcome)
        archive = build / (app.stem + "-macos-universal.zip")
        package_macos(app, archive)
        inspection = ios._run([tools["tools"]["objdump"], "--macho", "--universal-headers", "--private-headers", str(output)])
        (build / "macho-inspection.txt").write_text(inspection.stdout, encoding="utf-8")
        receipt.update(status="completed", artifactPath=str(archive), artifactSha256=ios._file_sha256(archive),
                       artifactBytes=archive.stat().st_size, executablePath=str(output), executableSha256=ios._file_sha256(output),
                       architectures=["arm64", "x86_64"], verification=outcome, outcomePath=str(build / "outcome.json"))
    except Exception as exc:
        receipt.update(status="failed", error=str(exc))
    receipt["updatedAt"] = ios._utc_now()
    ios._write_json(receipt_path, receipt)
    return receipt
