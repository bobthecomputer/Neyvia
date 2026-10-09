"""Generated local mobile authoring, packaging and checked byte-transfer fixtures.

These exercise real production owners and inspect files independently. They do
not compile, sign, install, or contact a remote builder or device.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import tarfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TEXT = {"empty": "", "huge": "long " * 14000, "unicode": "雪🙂e\u0301 العربية"}


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def reject(call):
    try:
        call()
    except (RuntimeError, OSError, ValueError):
        return
    raise AssertionError("Invalid operation was admitted")


def _files(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _author(root, category):
    from . import ios_studio as ios
    text = TEXT.get(category, "Owned local author")
    if not text:
        reject(lambda: ios.create_ios_app(root, name=text, bundle_identifier="com.fixture.empty",
                                         directory="apps/empty", install_dependencies=False))
        require(not list(root.iterdir()), "Empty-name rejection wrote project state")
    name = text or "Empty input recovery"
    if category == "permissions":
        from .edge_fixture_c7d_local import _deny_child_creation
        with _deny_child_creation(root, root):
            reject(lambda: ios.create_ios_app(root, name=name, bundle_identifier="com.fixture.generated", directory="apps/generated", install_dependencies=False))
        require(not (root / "apps/generated").exists(), "OS-denied authoring generated a project")
    if category == "interrupted":
        original_write = Path.write_text
        interrupted = []
        def stop_source(path, *args, **kwargs):
            if path.name == "package.json" and root in path.resolve().parents:
                interrupted.append(str(path))
                raise KeyboardInterrupt("Owned source materialization interruption")
            return original_write(path, *args, **kwargs)
        Path.write_text = stop_source
        try:
            try:
                ios.create_ios_app(root, name=name, bundle_identifier="com.fixture.interrupted", directory="apps/interrupted", install_dependencies=False)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("Source author missed real file materialization interruption")
        finally:
            Path.write_text = original_write
        require(interrupted and not (root / "apps/interrupted/package.json").exists(), "Interrupted source publisher claimed complete dependency manifest")
    if category == "concurrency":
        from .edge_fixture_local import _parallel
        def create(index):
            try:
                return ios.create_ios_app(root, name="One writer", bundle_identifier="com.fixture.race", directory="apps/race", install_dependencies=False)
            except (RuntimeError, OSError, ValueError) as error:
                return {"ok": False, "type": type(error).__name__}
        competed = _parallel(create, range(8))
        winners = [row for row in competed if row.get("projectRoot")]
        require(len(winners) == 1 and json.loads((root / "apps/race/app.json").read_text(encoding="utf8"))["expo"]["ios"]["bundleIdentifier"] == "com.fixture.race", "Competing source authors lost single complete project winner")
    result = ios.create_ios_app(root, name=name, bundle_identifier="com.fixture.generated",
                                directory="apps/generated", install_dependencies=False)
    project = Path(result["projectRoot"])
    package = json.loads((project / "package.json").read_text(encoding="utf-8"))
    config = json.loads((project / "app.json").read_text(encoding="utf-8"))["expo"]
    require(config["name"] == name.strip() and config["ios"]["bundleIdentifier"] == "com.fixture.generated",
            "Generated project lost requested name or bundle identity")
    require(package["dependencies"]["expo"] == "~57.0.4" and package["dependencies"]["react-native"] == "0.86.0",
            "Starter dependency versions changed")
    before = _files(root)
    for directory, bundle in (("../escape", "com.fixture.generated"), ("apps/invalid", text or ""),
                              ("apps/generated", "com.fixture.occupied")):
        reject(lambda: ios.create_ios_app(root, name="Rejected", directory=directory,
                                         bundle_identifier=bundle, install_dependencies=False))
        require(_files(root) == before, "Rejected scope, identity or occupied project changed files")
    source = project / "generated-text.txt"
    source.write_text(text, encoding="utf-8")
    generated = project / "node_modules/generated.txt"
    generated.parent.mkdir()
    generated.write_text("excluded generated bytes", encoding="utf-8")
    if category == "stale":
        source.write_text("current authored source", encoding="utf8")
        text = "current authored source"
    if category == "permissions":
        from .edge_fixture_core import denied
        with denied(source):
            reject(lambda: ios.create_ios_build_capsule(project, job_id="denied-capsule", mode="simulator"))
        require(source.read_text(encoding="utf8") == text, "Denied capsule source observation changed authored bytes")
    if category == "concurrency":
        from .edge_fixture_local import _parallel
        raced = _parallel(lambda index: ios.create_ios_build_capsule(project, job_id=f"parallel-capsule-{index}", mode="simulator"), range(4))
        require(len({row["capsulePath"] for row in raced}) == 4, "Simultaneous capsule producers reused one archive identity")
        for row in raced:
            with tarfile.open(row["capsulePath"], "r:gz") as archive:
                require(archive.extractfile("project/generated-text.txt").read() == text.encode(), "Simultaneous capsule lost exact source bytes")
    if category == "interrupted":
        prior = _files(project)
        original_add = tarfile.TarFile.addfile
        reached = []
        def stop_archive(archive, member, *args, **kwargs):
            if member.name == "neyvia-build-manifest.json":
                reached.append(member.name)
                raise KeyboardInterrupt("Owned capsule manifest publication interruption")
            return original_add(archive, member, *args, **kwargs)
        tarfile.TarFile.addfile = stop_archive
        try:
            try:
                ios.create_ios_build_capsule(project, job_id="interrupted-capsule", mode="simulator")
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("Capsule missed actual archive manifest interruption")
        finally:
            tarfile.TarFile.addfile = original_add
        require(reached and all(_files(project).get(path) == digest for path, digest in prior.items()), "Interrupted capsule changed authored project sources")
    capsule = ios.create_ios_build_capsule(project, job_id="owned-capsule", mode="simulator")
    archive_path = Path(capsule["capsulePath"])
    with tarfile.open(archive_path, "r:gz") as archive:
        require(archive.extractfile("project/generated-text.txt").read() == text.encode(), "Capsule changed source bytes")
        require(not any("node_modules" in Path(m.name).parts or m.issym() or m.islnk() for m in archive.getmembers()),
                "Capsule retained generated content or links")
        manifest = json.load(archive.extractfile("neyvia-build-manifest.json"))
        require(manifest["bundleIdentifier"] == config["ios"]["bundleIdentifier"] and manifest["jobId"] == "owned-capsule",
                "Capsule embedded a different identity")
    require(hashlib.sha256(archive_path.read_bytes()).hexdigest() == capsule["capsuleSha256"], "Capsule digest differs")
    return {"project": str(project), "sourceBytes": source.stat().st_size, "capsuleSha256": capsule["capsuleSha256"],
            "observed": "Actual source authoring, invalid input preservation and independently opened source capsule"}


def _config(root, category):
    from . import ios_studio as ios, windows_ios_compiler as compiler
    text = TEXT.get(category, "owned reference")
    saved = ios.save_ios_builder(root, host="builder.example.invalid", user="fixture", port=48748,
                                 label=text, identity_file="reference-only/" + text)
    disk = json.loads((root / ios.IOS_STUDIO_CONFIG).read_text(encoding="utf-8"))
    require(disk == saved and ios.load_ios_studio_config(root)["builder"] == saved["builder"], "Builder reload differs from disk")
    config = compiler.save_windows_ios_config(root, minimum_ios="17.2", identity_file="reference-only/" + text)
    require(json.loads((root / compiler.WINDOWS_IOS_CONFIG).read_text(encoding="utf-8")) == config,
            "Compiler preferences differ from persisted bytes")
    require(compiler.load_windows_ios_config(root)["minimumIos"] == "17.2" and config["identityFile"] == ("reference-only/" + text).strip(),
            "Compiler reload lost references")
    before = _files(root)
    reject(lambda: ios.save_ios_builder(root, host="host;command", user="fixture", port=48748))
    reject(lambda: compiler.save_windows_ios_config(root, minimum_ios="latest"))
    require(_files(root) == before, "Invalid preference changed durable bytes")
    if category == "concurrency":
        from .edge_fixture_local import _parallel
        saves = _parallel(lambda index: ios.save_ios_builder(root, host="builder.example.invalid", user="fixture", port=48743, label=f"simultaneous-{index}"), range(8))
        actual = json.loads((root / ios.IOS_STUDIO_CONFIG).read_text(encoding="utf8"))
        require(actual in saves and actual["builder"]["label"] in {f"simultaneous-{index}" for index in range(8)}, "Concurrent builder save did not leave a complete winner payload")
        compiled = _parallel(lambda index: compiler.save_windows_ios_config(root, minimum_ios=f"17.{index}"), range(8))
        require(json.loads((root / compiler.WINDOWS_IOS_CONFIG).read_text(encoding="utf8")) in compiled, "Concurrent compiler save mixed preferences")
    if category in {"permissions", "interrupted"}:
        from .edge_fixture_core import denied
        original_replace = os.replace
        for target, operation in ((root / ios.IOS_STUDIO_CONFIG, lambda: ios.save_ios_builder(root, host="builder.example.invalid", user="fixture", port=48743, label="attempted replacement")),
                                  (root / compiler.WINDOWS_IOS_CONFIG, lambda: compiler.save_windows_ios_config(root, minimum_ios="18.1"))):
            original_bytes = target.read_bytes()
            if category == "permissions":
                with denied(target):
                    reject(operation)
            else:
                reached = []
                def interrupted(source, destination):
                    if Path(destination).resolve() == target.resolve():
                        reached.append(Path(source).stat().st_size)
                        raise KeyboardInterrupt("Owned config replacement interruption")
                    return original_replace(source, destination)
                os.replace = interrupted
                try:
                    try:
                        operation()
                    except KeyboardInterrupt:
                        pass
                    else:
                        raise AssertionError("Config writer missed actual atomic replacement boundary")
                finally:
                    os.replace = original_replace
                require(reached, "Config interruption occurred outside replacement boundary")
            require(target.read_bytes() == original_bytes, "OS-denied/interrupted preference replacement lost prior exact payload")
            operation()
            require(target.read_bytes() != original_bytes, "Config writer did not recover after denied/interrupted publication")
    if category == "stale":
        ios.save_ios_builder(root, host="new.example.invalid", user="newfixture", port=48743, label="current builder")
        compiler.save_windows_ios_config(root, minimum_ios="19.1")
        require(ios.load_ios_studio_config(root)["builder"]["host"] == "new.example.invalid" and compiler.load_windows_ios_config(root)["minimumIos"] == "19.1", "Fresh preference getter returned old persisted values")
    return {"labelCharacters": len(text), "configFiles": sorted(before), "credentialFilesRead": 0,
            "observed": "Production saves and fresh reloads, exact disk equality and invalid-input preservation"}


def _package(root, category):
    from . import windows_ios_compiler as compiler
    text = TEXT.get(category, "Owned package")
    project = root / "project"
    export = project / "dist"
    export.mkdir(parents=True)
    html = '<script src="/assets/app.js"></script><a href="//example.invalid">link</a>' + text
    (export / "index.html").write_text(html, encoding="utf-8")
    app = root / "Generated.app"
    app.mkdir()
    if category == "permissions":
        from .edge_fixture_c7d_local import _deny_child_creation
        with _deny_child_creation(app, root):
            reject(lambda: compiler._safe_copy_web_assets(project, root / "build", app))
        require(not (app / "www").exists() and (export / "index.html").read_text(encoding="utf8") == html, "Denied asset staging changed source/export state")
    if category == "interrupted":
        original_copytree = compiler.shutil.copytree
        reached = []
        def stop_copy(source, destination, *args, **kwargs):
            if Path(destination) == app / "www":
                reached.append(str(destination))
                raise KeyboardInterrupt("Owned staging interruption before directory copy")
            return original_copytree(source, destination, *args, **kwargs)
        compiler.shutil.copytree = stop_copy
        try:
            try:
                compiler._safe_copy_web_assets(project, root / "build", app)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("Asset staging missed actual copy boundary interruption")
        finally:
            compiler.shutil.copytree = original_copytree
        require(reached and not (app / "www").exists() and (export / "index.html").read_text(encoding="utf8") == html, "Interrupted asset staging fabricated state or modified source")
    destination = compiler._safe_copy_web_assets(project, root / "build", app)
    expected = html.replace('src="/assets/', 'src="./assets/')
    require((destination / "index.html").read_text(encoding="utf-8") == expected, "Staged links/text differ")
    path = compiler._write_info_plist(app, executable="NeyviaApp", app_name=text,
                                     bundle_identifier="com.fixture.generated", minimum_ios="17.2")
    plist = plistlib.loads(path.read_bytes())
    require(plist["CFBundleDisplayName"] == text and plist["CFBundleIdentifier"] == "com.fixture.generated"
            and plist["CFBundleSupportedPlatforms"] == ["iPhoneOS"] and plist["MinimumOSVersion"] == "17.2", "Plist identity changed")
    if category in {"permissions", "interrupted"}:
        from .edge_fixture_core import denied
        prior = path.read_bytes()
        if category == "permissions":
            with denied(path):
                reject(lambda: compiler._write_info_plist(app, executable="NeyviaApp", app_name="attempted replacement", bundle_identifier="com.fixture.generated", minimum_ios="17.2"))
        else:
            original_write = Path.write_bytes
            def stop_plist(target, value):
                if target == path:
                    raise KeyboardInterrupt("Owned binary plist publication interruption")
                return original_write(target, value)
            Path.write_bytes = stop_plist
            try:
                try:
                    compiler._write_info_plist(app, executable="NeyviaApp", app_name="attempted replacement", bundle_identifier="com.fixture.generated", minimum_ios="17.2")
                except KeyboardInterrupt:
                    pass
                else:
                    raise AssertionError("Metadata publication missed real binary write interruption")
            finally:
                Path.write_bytes = original_write
        require(path.read_bytes() == prior, "Denied/interrupted metadata publication corrupted prior binary identity")
    archive_path = root / "Generated.ipa"
    staged_before = _files(app)
    compiler._zip_payload(app, archive_path)
    if category == "permissions":
        from .edge_fixture_core import denied
        previous = archive_path.read_bytes()
        with denied(archive_path):
            reject(lambda: compiler._zip_payload(app, archive_path))
        require(archive_path.read_bytes() == previous, "OS-denied IPA rewrite corrupted prior complete archive")
    if category == "interrupted":
        original_write = zipfile.ZipFile.write
        reached = []
        def stop_zip(archive, path, *args, **kwargs):
            reached.append(str(path))
            raise KeyboardInterrupt("Owned IPA member publication interruption")
        zipfile.ZipFile.write = stop_zip
        try:
            try:
                compiler._zip_payload(app, root / "interrupted.ipa")
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("IPA archive missed actual member publication interruption")
        finally:
            zipfile.ZipFile.write = original_write
        require(reached and _files(app) == staged_before, "Interrupted archive changed staged sources")
        compiler._zip_payload(app, root / "recovered.ipa")
    if category == "concurrency":
        from .edge_fixture_local import _parallel
        parallel_apps = [root / f"Parallel-{index}.app" for index in range(4)]
        for candidate in parallel_apps:
            candidate.mkdir()
        staged = _parallel(lambda candidate: compiler._safe_copy_web_assets(project, root / "parallel-build", candidate), parallel_apps)
        require(all((directory / "index.html").read_text(encoding="utf8") == expected for directory in staged), "Simultaneous staging mixed readonly shared source bytes")
        metadata = _parallel(lambda index: compiler._write_info_plist(parallel_apps[index], executable="NeyviaApp", app_name=f"Parallel {index}", bundle_identifier=f"com.fixture.parallel{index}", minimum_ios="17.2"), range(4))
        require(all(plistlib.loads(target.read_bytes())["CFBundleIdentifier"] == f"com.fixture.parallel{index}" for index, target in enumerate(metadata)), "Simultaneous metadata writers mixed app identities")
        paths = [root / f"parallel-{index}.ipa" for index in range(4)]
        _parallel(lambda output: compiler._zip_payload(app, output), paths)
        for output in paths:
            with zipfile.ZipFile(output) as archive:
                require(archive.read("Payload/Generated.app/www/index.html") == expected.encode(), "Simultaneous IPA writer lost exact shared staged bytes")
    if category == "stale":
        (export / "index.html").write_text("current source", encoding="utf8")
        fresh_app = root / "Current.app"
        fresh_app.mkdir()
        fresh = compiler._safe_copy_web_assets(project, root / "fresh-build", fresh_app)
        require((fresh / "index.html").read_text(encoding="utf8") == "current source" and (destination / "index.html").read_text(encoding="utf8") == expected, "Fresh asset staging reused old source or changed previous build")
    files = _files(app)
    with zipfile.ZipFile(archive_path) as archive:
        require(set(archive.namelist()) == {"Payload/Generated.app/" + p for p in files}, "Package members differ")
        require(all(hashlib.sha256(archive.read("Payload/Generated.app/" + p)).hexdigest() == digest
                    for p, digest in files.items()), "Package changed staged bytes")
    before = _files(app)
    reject(lambda: compiler._safe_copy_web_assets(project, root / "build", app))
    require(_files(app) == before, "Repeated staging replaced existing app assets")
    return {"packageSha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(), "files": files,
            "observed": "Real asset staging, parsed binary plist and independently verified IPA bytes; no compilation or installation"}


def _download(root, category):
    from .windows_ios_compiler import _download_verified
    raw = TEXT.get(category, "verified bytes").encode()
    source = root / "public-bytes.bin"
    source.write_bytes(raw)
    target = root / "checked.bin"
    digest = hashlib.sha256(raw).hexdigest()
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda _: _download_verified(source.as_uri(), target, digest), range(4)))
        require(all(p == target for p in paths), "Concurrent transfers returned different destinations")
    else:
        _download_verified(source.as_uri(), target, digest)
    require(target.read_bytes() == raw, "Verified destination changed source bytes")
    if category == "offline":
        reject(lambda: _download_verified("http://127.0.0.1:48748/payload", target, "0" * 64))
    else:
        source.write_bytes(raw + b"changed")
        reject(lambda: _download_verified(source.as_uri(), target, "0" * 64))
    require(target.read_bytes() == raw and not list(root.glob("checked.bin.part-*")), "Failed transfer promoted or left a partial write")
    if category in {"interrupted", "permissions"}:
        latest = source.read_bytes()
        latest_digest = hashlib.sha256(latest).hexdigest()
        if category == "permissions":
            from .edge_fixture_missions import exclusive
            with exclusive(target):
                reject(lambda: _download_verified(source.as_uri(), target, latest_digest))
        else:
            original_replace = Path.replace
            observed = []
            def interrupt(path, destination):
                if path.name.startswith("checked.bin.part-"):
                    observed.append(path.name)
                    raise KeyboardInterrupt("Owned checked-byte promotion interruption")
                return original_replace(path, destination)
            Path.replace = interrupt
            try:
                try:
                    _download_verified(source.as_uri(), target, latest_digest)
                except KeyboardInterrupt:
                    pass
                else:
                    raise AssertionError("Transfer missed real promotion interruption")
            finally:
                Path.replace = original_replace
            require(observed, "No verified partial reached promotion")
        require(target.read_bytes() == raw and not list(root.glob("checked.bin.part-*")), "Denied/interrupted transfer changed prior bytes or retained partial")
        _download_verified(source.as_uri(), target, latest_digest)
        require(target.read_bytes() == latest, "Fresh transfer did not recover after denial/interruption")
    if category == "stale":
        latest = source.read_bytes()
        _download_verified(source.as_uri(), target, hashlib.sha256(latest).hexdigest())
        require(target.read_bytes() == latest, "Old cached destination defeated new expected digest")
    return {"bytes": len(raw), "digest": digest, "destinationSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "observed": "Actual urllib file transfer, checksum rejection with preserved destination and real partial cleanup"}


def _backend(root, category):
    from .web_backend import FluxioWebBackend
    from .windows_ios_compiler import WINDOWS_IOS_CONFIG, load_windows_ios_config
    from .edge_fixture_missions import exclusive
    backend = FluxioWebBackend(root, root)
    text = TEXT.get(category, "Owned backend author")
    command = "create_ios_app_command"
    payload = {"root": str(root), "name": text or "Empty name recovery", "directory": "apps/generated", "bundleIdentifier": "com.fixture.backend", "installDependencies": False}
    if category == "empty":
        reject(lambda: backend.dispatch(command, {**payload, "name": ""}))
        require(not (root / "apps/generated").exists(), "Empty backend authoring created a project")
    created = backend.dispatch(command, payload)
    project = Path(created["projectRoot"])
    observed = backend.dispatch("get_ios_studio_status_command", {"root": str(project)})
    require(observed["project"]["recognized"] and observed["project"]["bundleIdentifier"] == "com.fixture.backend" and json.loads((project / "app.json").read_text(encoding="utf8"))["expo"]["name"] == payload["name"].strip(), "Backend dispatch lost exact selected project identity/name")
    config_payload = {"root": str(project), "distro": "default", "minimumIos": "16.1"}
    saved = backend.dispatch("save_windows_ios_config_command", config_payload)
    path = project / WINDOWS_IOS_CONFIG
    require(saved["minimumIos"] == "16.1" and load_windows_ios_config(project)["minimumIos"] == "16.1", "Backend config dispatch lost durable preference")
    before = path.read_bytes()
    if category == "permissions":
        with exclusive(path):
            reject(lambda: backend.dispatch("save_windows_ios_config_command", {**config_payload, "minimumIos": "17.2"}))
        require(path.read_bytes() == before, "OS-denied backend config changed prior preference")
    if category == "interrupted":
        from .edge_fixture_local import replacement_fault
        from . import windows_ios_compiler
        with replacement_fault(windows_ios_compiler, path, KeyboardInterrupt) as interrupted:
            try:
                backend.dispatch("save_windows_ios_config_command", {**config_payload, "minimumIos": "17.2"})
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError("Backend config missed actual atomic replacement interruption")
        require(interrupted and path.read_bytes() == before, "Interrupted backend config changed durable prior preference")
    if category == "concurrency":
        from .edge_fixture_local import _parallel
        writes = _parallel(lambda i: backend.dispatch("save_windows_ios_config_command", {**config_payload, "minimumIos": "17." + str(i)}), range(8))
        require({row["minimumIos"] for row in writes} == {"17." + str(i) for i in range(8)} and load_windows_ios_config(project)["minimumIos"] in {row["minimumIos"] for row in writes}, "Concurrent backend dispatch lost accepted preference transaction")
    if category in {"stale", "permissions", "interrupted"}:
        recovered = backend.dispatch("save_windows_ios_config_command", {**config_payload, "minimumIos": "18.0"})
        require(recovered["minimumIos"] == load_windows_ios_config(project)["minimumIos"] == "18.0", "Fresh backend preference dispatch reused prior failed/stale value")
    return {"projectRoot": str(project), "bundleIdentifier": observed["project"]["bundleIdentifier"], "durableMinimumIos": load_windows_ios_config(project)["minimumIos"], "observed": "Actual backend dispatch authoring/status/preference route with durable readback; no build/toolchain/device launch"}


def _errors(root, category):
    from .windows_ios_compiler import _clean_error
    text = TEXT[category]
    actual = _clean_error("\x1b[31m" + text + "\x1b[0m", "explicit fallback")
    expected = text.strip()[-2400:] or "explicit fallback"
    require(actual == expected, "Error cleaning lost fallback, retained terminal codes or exceeded bound")
    return {"inputCharacters": len(text), "outputCharacters": len(actual), "outputSha256": hashlib.sha256(actual.encode()).hexdigest()}


FAMILIES = {
    "backend": (_backend, {"backend-wiring"}, set(TEXT) | {"concurrency", "permissions", "interrupted", "stale"}),
    "author": (_author, {"project", "scope", "bundle-id", "capsule"}, set(TEXT) | {"concurrency", "permissions", "interrupted", "stale"}),
    "config": (_config, {"builder-config", "compiler-config"}, set(TEXT) | {"concurrency", "permissions", "interrupted", "stale"}),
    "package": (_package, {"metadata", "package", "web-assets"}, set(TEXT) | {"concurrency", "permissions", "interrupted", "stale"}),
    "download": (_download, {"download-digest"}, {*TEXT, "concurrency", "stale", "offline", "interrupted", "permissions"}),
    "errors": (_errors, {"error-text"}, set(TEXT)),
}


def run(root, contracts, categories):
    rows = []
    for name, (builder, short_ids, supported) in FAMILIES.items():
        ids = sorted({"proofs-c.mobile." + i for i in short_ids} & contracts.keys())
        for category in categories:
            if not ids or category not in supported:
                continue
            scratch = root / f"mobile-{name}-{category}"
            scratch.mkdir(parents=True, exist_ok=False)
            row = {"id": f"mobile.{name}.{category}", "category": category, "contracts": ids,
                   "boundary": "Real local authoring/configuration/package/transfer owner; independent persisted-byte observations"}
            try:
                row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"error": str(error), "type": type(error).__name__, "scratch": str(scratch)})
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract["id"]
    for name, (_, ids, supported) in FAMILIES.items():
        if identity not in {"proofs-c.mobile." + i for i in ids} or category in supported:
            continue
        if category == "offline" and name != "download":
            return {"kind": "not_applicable", "reason": f"{identity} concerns local {name} files/transformations with dependency installation disabled; it has no network operation. Remote builds and signing are separate contracts."}
        if name == "errors" and category in {"concurrency", "interrupted", "stale", "permissions"}:
            return {"kind": "not_applicable", "reason": f"{identity} is an in-memory ANSI/bound transform; no worker, revision, grant or durable write exists for {category}."}
        return {"kind": "fixture_gap", "reason": f"{identity} still requires an actual {category} local {name} builder; ordinary successful packaging cannot prove that adverse boundary."}
    return None


def run_apple_artifacts(root: Path, project: Path):
    """C7 retained-artifact cases: fresh copies, actual hashes, no mock signer.

    This runner needs real completed Windows builds; it never fabricates a
    successful binary or runs a compiler/network/device. Originals stay sealed.
    """
    import shutil
    import re
    from .apple_targets import latest, verify
    rows = []
    from . import windows_ios_compiler as compiler
    toolchain = compiler._inspect_direct_windows_toolchain()
    source = compiler._runtime_source()
    for target, branch in (('arm64-apple-ios16.0', r'\bbl\s+_objc_msgSend\b'),
                           ('x86_64-apple-ios16.0-simulator', r'\bcallq\s+_objc_msgSend_stret\b')):
        output = root / (target+'.s')
        output.parent.mkdir(parents=True,exist_ok=True)
        built = compiler._run([toolchain['tools']['clang'], '-target',target,'-O2','-ffreestanding','-fno-stack-protector','-S',str(source),'-o',str(output)])
        require(built.returncode == 0 and re.search(branch, output.read_text(encoding='utf-8')), 'LLVM did not emit the required public Objective-C call ABI')
        rows.append({'id':'apple.runtime-abi.'+target,'category':'retained','contracts':['mobile-studio.apple-artifact-integrity'],
                     'status':'passed','boundary':'Actual LLVM compilation and emitted public-call ABI; no Apple-host execution',
                     'detail':{'compiler':toolchain['tools']['clangVersion'],'assemblySha256':hashlib.sha256(output.read_bytes()).hexdigest()}})
    for target in ('ios', 'ipados', 'macos'):
        original = latest(project, target)
        require(original.get('status') == 'completed', 'C7 Apple requires retained real artifact')
        job = Path(original['receiptPath']).parent
        for mutation in ('unchanged', 'web', 'metadata', 'code', 'archive'):
            scratch = root / target / mutation
            build = scratch / job.relative_to(project)
            shutil.copytree(job, build)
            receipt = dict(original)
            for key in ('receiptPath', 'appPath', 'executablePath', 'artifactPath'):
                if receipt.get(key): receipt[key] = str(scratch / Path(receipt[key]).relative_to(project))
            Path(receipt['receiptPath']).write_text(json.dumps(receipt), encoding='utf-8')
            executable = Path(receipt['executablePath'])
            contents = Path(receipt['appPath']) / 'Contents' if target == 'macos' else executable.parent
            web = contents / ('Resources/www' if target == 'macos' else 'www') / 'index.html'
            changed = {'web':web, 'metadata':contents/'Info.plist', 'code':executable, 'archive':Path(receipt['artifactPath'])}.get(mutation)
            if changed:
                data = bytearray(changed.read_bytes())
                if mutation in ('code','archive'): data[len(data)//2] ^= 1
                else: data.extend(b'\nmodified C7 bytes')
                changed.write_bytes(data)
            try:
                result = verify(scratch, target)
                require(mutation == 'unchanged' and result['ok'], 'Corrupted artifact was admitted')
                detail = {'artifactSha256':result['artifactSha256']}
            except (ValueError, OSError, plistlib.InvalidFileException, zipfile.BadZipFile) as exc:
                require(mutation != 'unchanged', 'Original retained artifact failed: '+str(exc))
                detail = {'rejected':str(exc)}
            rows.append({'id':f'apple.{target}.{mutation}', 'category':'stale' if changed else 'retained',
                         'contracts':['mobile-studio.apple-artifact-integrity'], 'status':'passed',
                         'boundary':'Real retained artifact bytes copied into owned scratch; no Apple-host execution', 'detail':detail})
        require(verify(project,target)['ok'], 'Original artifact changed during C7 copies')
    return rows


def run_apple_preview(project: Path, receipt_root: Path | None = None):
    """C7 rendered journey in an owned, authenticated headless runtime."""
    import sys, uuid, subprocess
    from PIL import Image
    from .windows_ios_compiler import _repo_root
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    repo, nonce = _repo_root(), uuid.uuid4().hex
    receipt_root=Path(receipt_root or repo/'.agent_control/apple/preview'/nonce).resolve()
    result = subprocess.run([sys.executable,str(repo/'scripts/apple/preview.py'),'--project',str(project),'--root',str(receipt_root)],
                  cwd=repo,timeout=300,env={**os.environ,'APPLE_PREVIEW_RUN_ID':nonce},capture_output=True,
                  text=True,encoding='utf-8',errors='replace',**hidden_windows_subprocess_kwargs())
    require(result.returncode == 0, 'Owned Apple rendered journey failed: '+result.stderr[-1800:])
    receipt = receipt_root/'receipt.json'
    outcome = json.loads(receipt.read_text(encoding='utf-8'))
    require(outcome.get('ok') and outcome.get('runId') == nonce and not outcome['errors'], 'Stale or failed C7 render receipt')
    captures = []
    for frame in outcome['frames']:
        path = Path(frame['screenshot'])
        with Image.open(path) as image:
            require(image.width > 250 and image.height > 250, 'Empty Apple frame capture')
            image.verify()
        captures.append({'device':frame['device'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'id':'apple.scroll-study.rendered','category':'rendered','contracts':['mobile-studio.apple-preview-rendered'],
            'status':'passed','boundary':'Actual authenticated running UI, Scroll Study frames and controls; browser emulation only',
            'detail':{'runId':nonce,'receiptSha256':hashlib.sha256(receipt.read_bytes()).hexdigest(),'captures':captures,
                      'persistenceVerified':outcome['behaviours']['persistenceVerified']}}
