"""Local authoring and package contracts; never claim a compiler/device journey."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text
import hashlib
import json
import plistlib
import tarfile
import zipfile
from pathlib import Path

CONTRACTS = ["proofs-c.mobile.project", "proofs-c.mobile.scope", "proofs-c.mobile.bundle-id",
             "proofs-c.mobile.capsule", "proofs-c.mobile.builder-config", "proofs-c.mobile.compiler-config",
             "proofs-c.mobile.download-digest", "proofs-c.mobile.metadata", "proofs-c.mobile.package",
             "proofs-c.mobile.web-assets", "proofs-c.mobile.error-text", "proofs-c.mobile.backend-wiring"]


def check_backend(command, payload, root, result):
    identity = "proofs-c.mobile.backend-wiring"
    if command == "create_ios_app_command":
        bundle = str(payload.get("bundleIdentifier") or payload.get("bundle_identifier") or "").strip()
        target = Path(result["projectRoot"]).resolve()
        require(target.is_relative_to(root.resolve()) and result["bundleIdentifier"] == bundle
                and result["status"]["project"]["recognized"]
                and result["status"]["project"]["bundleIdentifier"] == bundle,
                identity, "create command lost selected root, identity or fresh project recognition")
    elif command == "get_ios_studio_status_command":
        from .ios_studio import _package_metadata
        current = _package_metadata(root)
        require(result["project"]["bundleIdentifier"] == current["bundleIdentifier"]
                and result["project"]["framework"] == current["framework"]
                and result["buildModes"][0]["id"] == "windows-native",
                identity, "status command does not describe selected root")
    else:
        wanted = str(payload.get("minimumIos") or payload.get("minimum_ios") or "16.0").strip()
        require(result["minimumIos"] == wanted and result["distro"] == str(payload.get("distro") or "default").strip(),
                identity, "compiler configuration command lost requested preferences")
    return result


def require(condition, identity, detail):
    if not condition:
        raise ValueError(f"{identity}: {detail}")


def check_project(target, package, config, files):
    require(all((target / name).read_text(encoding="utf-8") == text for name, text in files.items()),
            "proofs-c.mobile.project", "created project differs from requested authoring files")
    require(json.loads((target / "package.json").read_text(encoding="utf-8")) == package
            and package["dependencies"].get("expo") == "~57.0.4"
            and package["dependencies"].get("react-native") == "0.86.0"
            and config["expo"]["ios"]["bundleIdentifier"],
            "proofs-c.mobile.project", "starter dependencies or app identity lost")


def check_config(path, payload, identity):
    require(json.loads(path.read_text(encoding="utf-8")) == payload, identity, "configuration is not durable")
    allowed = ({"schema", "updatedAt", "builder"} if identity.endswith("builder-config") else
               {"schema", "engine", "distro", "minimumIos", "identityFile", "certificateFile", "provisioningProfile", "updatedAt"})
    require(set(payload) <= allowed and not any("password" in key.lower() for key in payload),
            identity, "configuration must store references, never signing passwords")
    if "builder" in payload:
        require(set(payload["builder"]) <= {"label", "host", "user", "port", "remoteRoot", "identityFile",
                "appleTeamId", "knownHostsPolicy", "lastProbe", "lastProbeAt"}, identity, "unexpected builder field")


def check_capsule(path, manifest):
    from .ios_studio import _CAPSULE_EXCLUDED_PARTS, _SECRET_SUFFIXES
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = {item.name for item in members}
        require("project" in names and "neyvia-build-manifest.json" in names,
                "proofs-c.mobile.capsule", "capsule lost source or build manifest")
        for item in members:
            parts = Path(item.name).parts
            name = parts[-1]
            require(not (item.issym() or item.islnk()) and not (set(parts[1:]) & _CAPSULE_EXCLUDED_PARTS)
                    and not (name == ".env" or name.startswith(".env.") or Path(name).suffix.lower() in _SECRET_SUFFIXES),
                    "proofs-c.mobile.capsule", "capsule includes generated or confidential content")
        require(json.load(archive.extractfile("neyvia-build-manifest.json")) == manifest,
                "proofs-c.mobile.capsule", "embedded manifest differs from receipt")


def check_plist(path, payload):
    saved = plistlib.loads(path.read_bytes())
    require(saved == payload and saved["CFBundlePackageType"] == "APPL"
            and saved["CFBundleSupportedPlatforms"] == ["iPhoneOS"],
            "proofs-c.mobile.metadata", "iOS metadata differs from requested identity/platform")


def check_package(app_dir, ipa_path):
    expected = {"Payload/" + app_dir.name + "/" + path.relative_to(app_dir).as_posix(): path
                for path in app_dir.rglob("*") if path.is_file() and not path.is_symlink()}
    with zipfile.ZipFile(ipa_path) as archive:
        require(set(archive.namelist()) == set(expected), "proofs-c.mobile.package", "package files/layout differ from app bundle")
        for name, path in expected.items():
            require(archive.read(name) == path.read_bytes(), "proofs-c.mobile.package", "package changed staged bytes")


def check_web_assets(destination, source_text):
    import re
    expected = re.sub(r'''(?P<attr>\b(?:src|href)=['"])/(?!/)''', r"\g<attr>./", source_text)
    bundle_root = destination.parent
    if bundle_root.name == "Resources" and bundle_root.parent.name == "Contents":
        bundle_root = bundle_root.parent.parent
    require(destination.name == "www" and bundle_root.name.endswith(".app")
            and (destination / "index.html").read_text(encoding="utf-8") == expected,
            "proofs-c.mobile.web-assets", "web export escaped bundle or asset links changed")


def self_check(root):
    from . import ios_studio as ios, windows_ios_compiler as compiler
    base = Path(root)
    result = ios.create_ios_app(base, name="Contract Journey", directory="apps/journey",
                               bundle_identifier="com.neyvia.journey", install_dependencies=False)
    project = Path(result["projectRoot"])
    require(result["status"]["project"]["recognized"] and result["status"]["project"]["framework"] == "expo",
            "proofs-c.mobile.project", "real observer cannot recognize the created project")
    cases = [{"id": "create-observe-local-project", "ok": True}]
    for directory, bundle in [("../escape", "com.neyvia.journey"), ("apps/bad", "invalid"),
                              ("apps/bad", "com two.parts"), ("apps/bad", "1com.neyvia.app")]:
        before = sorted(str(p.relative_to(base)) for p in base.rglob("*"))
        try:
            ios.create_ios_app(base, name="Invalid Journey", directory=directory, bundle_identifier=bundle)
        except RuntimeError:
            require(sorted(str(p.relative_to(base)) for p in base.rglob("*")) == before,
                    "proofs-c.mobile.scope", "rejected input wrote authoring state")
        else:
            raise ValueError("Invalid project input accepted")
    cases.append({"id": "invalid-input-preserves-workspace", "ok": True})
    saved = ios.save_ios_builder(project, host="builder.example.invalid", user="builder", port=proof_port(48489),
                                apple_team_id="A1B2C3D4E5")
    require(ios.inspect_ios_studio(project)["builder"] == saved["builder"],
            "proofs-c.mobile.builder-config", "fresh observer lost saved builder metadata")
    saved = compiler.save_windows_ios_config(project, minimum_ios="17.2", distro="default")
    require(compiler.load_windows_ios_config(project)["minimumIos"] == "17.2",
            "proofs-c.mobile.compiler-config", "compiler preference does not survive reload")
    for patch in [{"minimum_ios": "latest"}, {"distro": "bad; command"}, {"engine": "pretend-native"}]:
        path = project / compiler.WINDOWS_IOS_CONFIG
        previous = path.read_bytes()
        try:
            compiler.save_windows_ios_config(project, **patch)
        except RuntimeError:
            require(path.read_bytes() == previous, "proofs-c.mobile.compiler-config", "invalid preference changed durable state")
        else:
            raise ValueError("Invalid compiler preference accepted")
    generated = project / "node_modules" / "generated.js"
    generated.parent.mkdir()
    generated.write_text("generated disposable content", encoding="utf-8")
    capsule = ios.create_ios_build_capsule(project, job_id="local-proof", mode="simulator")
    require(hashlib.sha256(Path(capsule["capsulePath"]).read_bytes()).hexdigest() == capsule["capsuleSha256"],
            "proofs-c.mobile.capsule", "capsule hash differs from actual archive")
    # Confidential-name rejection is exercised without opening any credential file.
    filter_member = ios._capsule_filter(project)
    for name in ["project/.env.production", "project/signing.p12", "project/.git/config"]:
        require(filter_member(tarfile.TarInfo(name)) is None, "proofs-c.mobile.capsule", "excluded name accepted")
    source = base / "release-bytes.bin"
    source.write_bytes(b"local non-network toolchain receipt")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = base / "downloads" / "checked.bin"
    compiler._download_verified(source.as_uri(), destination, digest)
    require(destination.read_bytes() == source.read_bytes(), "proofs-c.mobile.download-digest", "verified bytes differ")
    source.write_bytes(b"changed")
    try:
        compiler._download_verified(source.as_uri(), base / "downloads" / "rejected.bin", digest)
    except RuntimeError:
        require(not (base / "downloads" / "rejected.bin").exists(), "proofs-c.mobile.download-digest", "bad digest promoted")
    else:
        raise ValueError("Changed release bytes accepted")
    export = project / "dist"
    export.mkdir()
    (export / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    app = base / "staging" / "Journey.app"
    app.mkdir(parents=True)
    compiler._safe_copy_web_assets(project, base / "build", app)
    compiler._write_info_plist(app, executable="NeyviaApp", app_name="Contract Journey",
                               bundle_identifier="com.neyvia.journey", minimum_ios="17.2")
    compiler._zip_payload(app, base / "Journey.ipa")
    require(compiler._clean_error("\x1b[31mLocal failure\x1b[0m", "fallback") == "Local failure",
            "proofs-c.mobile.error-text", "receipt error includes terminal control codes")
    cases.append({"id": "author-configure-package-reload-reject", "ok": True})
    from .web_backend import FluxioWebBackend
    host_root = base / "backend-host"
    host_root.mkdir()
    backend = FluxioWebBackend(host_root, host_root)
    created = backend.dispatch("create_ios_app_command", {"root": str(host_root), "name": "Backend Journey",
        "directory": "apps/backend", "bundleIdentifier": "com.neyvia.backend", "installDependencies": False})
    observed = backend.dispatch("get_ios_studio_status_command", {"root": created["projectRoot"]})
    saved = backend.dispatch("save_windows_ios_config_command", {"root": created["projectRoot"], "distro": "default", "minimumIos": "16.1"})
    require(observed["project"]["recognized"] and observed["readiness"]["windowsPreview"]
            and saved["distro"] == "default" and saved["minimumIos"] == "16.1",
            "proofs-c.mobile.backend-wiring", "real backend authoring/status/preferences journey diverged")
    cases.append({"id": "actual-backend-dispatch-author-observe-configure", "ok": True})
    return {"ok": True, "contracts": CONTRACTS, "cases": cases, "scratchRoot": str(base),
            "frontier": ["Native compilation/signing and remote builder deployment require their real hosts."]}
