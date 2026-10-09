"""Onboarding semantic contracts and real disposable staging procedures.

No mock transport, suite import, protected credentials or global configuration.
The local HTTP fixture binds only the assigned PROOFS-d port 48496.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import base64
import hashlib
import json
import os
import re
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

CONTRACTS = (
    "onboarding.manifest-safety", "onboarding.signature-authority", "onboarding.verified-staging",
    "onboarding.resume-reuse", "onboarding.pause", "onboarding.addon-isolation",
    "onboarding.addon-recovery", "onboarding.catalog-integrity", "onboarding.ordered-recommendations",
    "onboarding.choices-durable",
)
COVERAGE = {
    "test_resumes_a_partial_file_with_a_range_request": ["onboarding.resume-reuse", "onboarding.verified-staging"],
    "test_second_run_skips_verified_files": ["onboarding.resume-reuse"],
    "test_wrong_checksum_fails_and_keeps_nothing": ["onboarding.verified-staging"],
    "test_pause_stops_and_resume_finishes": ["onboarding.pause", "onboarding.resume-reuse"],
    "test_manifest_rejects_unsafe_paths_and_sources": ["onboarding.manifest-safety"],
    "test_bundled_test_manifest_is_valid": ["onboarding.manifest-safety"],
    "test_add_on_worker_installs_local_manifest_on_separate_state": ["onboarding.addon-isolation", "onboarding.verified-staging"],
    "test_add_on_rejects_unavailable_and_mismatched_manifests": ["onboarding.addon-recovery", "onboarding.manifest-safety"],
    "test_download_handles_empty_files_and_rejects_oversized_sources": ["onboarding.verified-staging"],
    "test_signed_remote_manifest_rejects_tampering_and_unknown_or_unprovisioned_keys": ["onboarding.signature-authority"],
    "test_unsigned_manifest_allows_only_test_or_local_sources": ["onboarding.signature-authority"],
    "test_tiers_preselect_and_filter_the_tour": ["onboarding.ordered-recommendations"],
    "test_catalog_only_names_real_apps_and_packs": ["onboarding.catalog-integrity"],
    "test_save_validates_and_persists": ["onboarding.choices-durable"],
}


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_manifest(manifest):
    """Guard even direct downloader callers carrying a normalized manifest."""
    contract = "onboarding.manifest-safety"
    require(manifest.get("schema") == "neyvia.base-pack/v1", contract, "manifest schema")
    for field in ("packId", "version"):
        require(isinstance(manifest.get(field), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", manifest[field]), contract, "plain pack/version id")
    files = manifest.get("files")
    require(isinstance(files, list) and 0 < len(files) <= 20000, contract, "bounded nonempty file list")
    seen, total = set(), 0
    for row in files:
        path = row.get("path", "")
        require(isinstance(path, str) and path and ":" not in path and "\\" not in path and all(part not in {"", ".", ".."} for part in path.split("/")) and not path.endswith(".part"), contract, "safe relative path")
        require(path.casefold() not in seen, contract, "unique path")
        seen.add(path.casefold())
        require(type(row.get("size")) is int and 0 <= row["size"] <= 4 * 1024 ** 3, contract, "bounded byte size")
        require(isinstance(row.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]), contract, "SHA256")
        parsed = urlparse(row.get("url", ""))
        require(parsed.scheme in {"https", "file"} or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}), contract, "HTTPS or local source")
        total += row["size"]
    require(manifest.get("totalSize") == total, contract, "exact aggregate bytes")
    if manifest.get("throttleKbps") is not None:
        require(all(urlparse(row["url"]).scheme == "file" or urlparse(row["url"]).hostname in {"localhost", "127.0.0.1", "::1"} for row in files), contract, "throttle is local only")


def safe_destination(target, relative):
    target = Path(target).resolve()
    destination = target / relative
    require(destination.resolve().is_relative_to(target), "onboarding.manifest-safety", "staged path escapes through a link")
    return destination


def check_staged_file(destination, entry):
    require(Path(destination).is_file() and Path(destination).stat().st_size == entry["size"] and _digest(destination) == entry["sha256"],
            "onboarding.verified-staging", "committed bytes differ from declared size/hash")
    require(not Path(str(destination) + ".part").exists(), "onboarding.verified-staging", "committed file retains a partial")


def check_download_result(pack, target, manifest, status):
    persisted = json.loads((Path(pack) / "status.json").read_text(encoding="utf-8"))
    require(persisted == status, "onboarding.verified-staging", "status was not durably reported")
    if status["state"] == "done":
        for row in manifest["files"]:
            check_staged_file(safe_destination(target, row["path"]), row)
        require(status["doneBytes"] == manifest["totalSize"] and status["files"] == {"done": len(manifest["files"]), "total": len(manifest["files"])}, "onboarding.verified-staging", "completion counters")
        receipt = json.loads((Path(target) / "installed.json").read_text(encoding="utf-8"))
        expected = [{key: row[key] for key in ("path", "size", "sha256")} for row in manifest["files"]]
        require(receipt["files"] == expected and receipt["packId"] == manifest["packId"] and receipt["version"] == manifest["version"] and receipt["target"] == str(target), "onboarding.verified-staging", "receipt differs from installed payload")
    elif status["state"] == "paused":
        require(not (Path(pack) / "pause").exists(), "onboarding.pause", "pause request was not consumed")
    else:
        require(status["state"] == "failed" and bool(status.get("error")), "onboarding.verified-staging", "terminal error missing")


def check_pack_status(root, packs):
    from . import neyvia_onboarding as host
    for row in packs:
        require(row["stagedOnly"] is True, "onboarding.addon-isolation", "add-on status must disclose staging")
        if row["state"] == "installed":
            target = Path(row["target"]).resolve()
            require(target.is_relative_to(host._pack_dir(root, row["packId"]).resolve()) and Path(row["receipt"]).is_file(), "onboarding.addon-isolation", "add-on receipt outside separate state")
        if row["state"] in {"failed", "unavailable"}:
            require(bool(row["error"]), "onboarding.addon-recovery", "unavailable/failed pack must explain why")


def check_staging_scope(root, pack_id=None):
    from . import neyvia_onboarding as host
    pack = host._pack_dir(root, pack_id).resolve()
    require(pack.is_relative_to(Path(root).resolve()), "onboarding.manifest-safety", "staging folder escapes selected root")
    if pack_id:
        require(not pack.is_relative_to(host._pack_dir(root).resolve()), "onboarding.addon-isolation", "add-on staging aliases base-pack state")


def check_catalog(catalog, apps, packs):
    for row in catalog["interests"]:
        require(not (set(row["apps"]) - set(apps)) and not (set(row["packs"]) - set(packs)), "onboarding.catalog-integrity", "interest names missing app/pack")


def check_recommendation(catalog, chosen, result):
    selected = [row for row in catalog["interests"] if row["id"] in chosen]
    require(result["interests"] == [row["id"] for row in selected], "onboarding.ordered-recommendations", "catalog order")
    for key in ("apps", "packs", "runtimes"):
        require(result[key] == list(dict.fromkeys(value for row in selected for value in row.get(key, []))), "onboarding.ordered-recommendations", "ordered unique selections")
    wanted = {value for row in selected for value in row.get("chapters", [])}
    expected = [row for row in catalog["tutorial"]["chapters"] if not row["interests"] or row["id"] in wanted]
    require(result["chapters"] == [row["id"] for row in expected], "onboarding.ordered-recommendations", "filtered tour")
    require(result["tourSeconds"] == (round(min(90, max(60, sum(row["durationMs"] for row in expected) / 1000))) if expected else 0), "onboarding.ordered-recommendations", "tour duration")


def check_saved(root, stored):
    from . import neyvia_onboarding as host
    actual = json.loads((host._dir(root) / "state.json").read_text(encoding="utf-8"))
    require(actual == stored and host.read_state(root) == {**stored, "firstRun": False}, "onboarding.choices-durable", "saved setup differs from returned state")


def self_check(root):
    """Exercise real action paths against small disposable files and a loopback CDN."""
    from . import neyvia_onboarding as host
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    started = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    served = root / "cdn"
    served.mkdir(exist_ok=True)
    files = {"shell/app.bin": bytes(range(256)) * 900, "web/index.html": b"<!doctype html>proof"}
    for name, body in files.items():
        path = served / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    requests, cases, observations = [], [], []

    class CDN(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = Path(self.translate_path(self.path))
            header = self.headers.get("Range", "")
            requests.append({"path": self.path, "range": header})
            if not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            offset = int(header.split("=")[1].split("-")[0]) if header else 0
            self.send_response(206 if header else 200)
            self.send_header("Content-Length", str(len(body) - offset))
            self.end_headers()
            try:
                self.wfile.write(body[offset:])
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48496)), partial(CDN, directory=str(served)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = proof_text("http://127.0.0.1:48496/")

    def manifest(payload=None, **extra):
        payload = files if payload is None else payload
        return {"schema": host.MANIFEST_SCHEMA, "packId": "base", "version": "1.0.0", "baseUrl": base,
                "files": [{"path": name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()} for name, body in payload.items()], **extra}

    def parsed(payload=None, **extra):
        return host.parse_manifest(json.dumps(manifest(payload, **extra)), base + "manifest.json")

    def record(name, action):
        begin = time.perf_counter()
        row = {"case": name, "contracts": COVERAGE.get(name, list(CONTRACTS))}
        try:
            action()
            row["ok"] = True
        except Exception as exc:
            row.update(ok=False, error=str(exc))
        row["durationMs"] = round((time.perf_counter() - begin) * 1000, 3)
        cases.append(row)

    def rejects(action, fragment=""):
        try:
            action()
        except ValueError as exc:
            require(fragment in str(exc), "onboarding.manifest-safety", "rejection reason missing: " + fragment)
        else:
            raise ValueError("Adverse action accepted")

    def download():
        stage_root = root / "resume"
        target = host._pack_dir(stage_root) / "base/1.0.0"
        partial_path = target / "shell/app.bin.part"
        partial_path.parent.mkdir(parents=True)
        partial_path.write_bytes(files["shell/app.bin"][:5000])
        status = host.run_download(stage_root, parsed())
        require(status["state"] == "done" and status["resumedBytes"] == 5000 and any(row["range"] == "bytes=5000-" for row in requests), "onboarding.resume-reuse", "HTTP range resume failed")
        require((target / "shell/app.bin").read_bytes() == files["shell/app.bin"], "onboarding.verified-staging", "resumed bytes")
        require(len(json.loads((target / "installed.json").read_text())["files"]) == 2, "onboarding.verified-staging", "receipt list")
        observations.append({"procedure": "resume", "state": status["state"], "resumedBytes": status["resumedBytes"], "receipt": status["receipt"]})

    def reuse():
        count = len(requests)
        status = host.run_download(root / "resume", parsed())
        require(status["state"] == "done" and len(requests) == count, "onboarding.resume-reuse", "verified files re-downloaded")
        # A forged unchanged timestamp cannot turn corrupt bytes into verified data.
        path = Path(status["target"]) / "shell/app.bin"
        stamp = path.stat()
        path.write_bytes(b"!" * len(files["shell/app.bin"]))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        repaired = host.run_download(root / "resume", parsed())
        require(repaired["state"] == "done" and path.read_bytes() == files["shell/app.bin"] and len(requests) > count, "onboarding.resume-reuse", "corrupted cache reused")

    def corrupt():
        bad = manifest()
        bad["files"][1]["sha256"] = "0" * 64
        status = host.run_download(root / "corrupt", host.parse_manifest(json.dumps(bad), base))
        require(status["state"] == "failed" and "checksum" in status["error"] and status["retries"] == 1, "onboarding.verified-staging", "checksum failure did not retry once")
        require(list((Path(status["target"]) / "web").iterdir()) == [], "onboarding.verified-staging", "corrupt payload retained")

    def pause():
        stage_root = root / "pause"
        signal = host._pack_dir(stage_root) / "pause"
        signal.parent.mkdir(parents=True)
        signal.write_text("pause", encoding="utf-8")
        status = host.run_download(stage_root, parsed())
        require(status["state"] == "paused" and not signal.exists(), "onboarding.pause", "pause request not consumed")
        require(host.run_download(stage_root, parsed())["state"] == "done", "onboarding.pause", "resume after pause failed")

    def unsafe():
        for path in ("../escape.txt", "C:/Windows/x", "/abs", "a/./b"):
            rejects(lambda path=path: parsed({path: b"x"}))
        rejects(lambda: parsed(baseUrl="http://example.com/"))
        rejects(lambda: parsed(totalSize=1))
        remote = parsed(baseUrl="https://example.com/", channel="test", dev={"throttleKbps": 5})
        require(remote["throttleKbps"] is None, "onboarding.manifest-safety", "remote source throttled")

    def bundled():
        data = host.load_manifest(str(host.TEST_MANIFEST))
        require(data["totalSize"] > 0 and all(row["url"].startswith("file:") for row in data["files"]), "onboarding.manifest-safety", "bundled local manifest")

    def empty_oversize():
        (served / "empty").write_bytes(b"")
        require(host.run_download(root / "empty", parsed({"empty": b""}))["state"] == "done", "onboarding.verified-staging", "empty source")
        bad = manifest()
        bad["files"][0]["size"] = 1
        status = host.run_download(root / "oversize", host.parse_manifest(json.dumps(bad), base))
        require(status["state"] == "failed" and "declared size" in status["error"], "onboarding.verified-staging", "oversize source accepted")

    def signatures():
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes_raw()
        data = manifest({"hello.txt": b"hello"}, baseUrl="https://example.com/", channel="stable", description="Édition")
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        data["signature"] = {"keyId": "proof-fixture", "ed25519": base64.b64encode(private.sign(canonical)).decode()}
        key = {"provisioned": True, "publicKeyBase64": base64.b64encode(public).decode(), "fingerprintSha256": hashlib.sha256(public).hexdigest()}
        policy = root / "fixture-public-trust.json"

        def write(value):
            policy.write_text(json.dumps({"signing": {"trustedKeys": {"proof-fixture": value}}}), encoding="utf-8")

        def parse(value):
            return host.parse_manifest(json.dumps(value, indent=4), "https://example.com/manifest.json", trusted_policy=policy)

        write(key)
        require(parse(data)["packId"] == "base", "onboarding.signature-authority", "valid Unicode canonical signature rejected")
        for changed in ({**data, "version": "2"}, {**data, "signature": {**data["signature"], "keyId": "unknown"}}, {**data, "signature": {**data["signature"], "ed25519": "invalid"}}):
            rejects(lambda changed=changed: parse(changed), "signature")
        write({**key, "provisioned": False})
        rejects(lambda: parse(data), "provisioned")
        write({**key, "fingerprintSha256": "0" * 64})
        rejects(lambda: parse(data), "signature")

    def unsigned():
        data = manifest({"hello.txt": b"hello"}, baseUrl="https://example.com/", channel="stable")
        for source in ("https://example.com/manifest.json", str(root / "manifest.json")):
            rejects(lambda source=source: host.parse_manifest(json.dumps(data), source), "signature")
        require(host.parse_manifest(json.dumps({**data, "channel": "test"}), "https://example.com/manifest.json")["channel"] == "test", "onboarding.signature-authority", "test channel rejected")
        local = {**data, "baseUrl": base}
        require(host.parse_manifest(json.dumps(local), base + "manifest.json")["channel"] == "stable", "onboarding.signature-authority", "local stable source rejected")
        rejects(lambda: host.parse_manifest(json.dumps(local), "https://example.com/manifest.json"), "signature")

    def addons():
        identity = "pack.ocr-local"
        source = served / "addon.json"
        source.write_text(json.dumps(manifest(baseUrl=served.as_uri() + "/", packId=identity, channel="test")), encoding="utf-8")
        addon_root = root / "addons"
        previous = os.environ.get("NEYVIA_ONBOARDING_PACK_MANIFESTS")
        try:
            os.environ["NEYVIA_ONBOARDING_PACK_MANIFESTS"] = json.dumps({identity: str(source)})
            require(host.handle(addon_root, "onboarding_pack_status_command", {"packId": identity})["packs"][0]["state"] == "not-installed", "onboarding.addon-isolation", "unexpected initial add-on state")
            first = host.handle(addon_root, "onboarding_pack_install_command", {"packId": identity})["packs"][0]
            require(first["state"] in {"queued", "installing", "installed"}, "onboarding.addon-isolation", "worker did not start")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                row = host.call_tool(addon_root, "pack", {"action": "status", "packId": identity})["packs"][0]
                if row["state"] in {"installed", "failed"}:
                    break
                time.sleep(0.05)
            require(row["state"] == "installed" and row["stagedOnly"] and Path(row["receipt"]).is_file(), "onboarding.addon-isolation", "detached worker did not install: " + row.get("error", ""))
            require((Path(row["target"]) / "shell/app.bin").read_bytes() == files["shell/app.bin"] and host.base_pack_status(addon_root)["state"] == "idle", "onboarding.addon-isolation", "worker payload or base isolation")
            require(host.install_pack(addon_root, identity)["packs"][0]["state"] == "installed", "onboarding.addon-isolation", "installed pack not reused")
            observations.append({"procedure": "detached-addon-worker", "state": row["state"], "receipt": row["receipt"], "stagedOnly": row["stagedOnly"]})
        finally:
            if previous is None:
                os.environ.pop("NEYVIA_ONBOARDING_PACK_MANIFESTS", None)
            else:
                os.environ["NEYVIA_ONBOARDING_PACK_MANIFESTS"] = previous

    def addon_recovery():
        addon_root = root / "addon-recovery"
        unavailable = host.install_pack(addon_root, "pack.documents-office")["packs"][0]
        require(unavailable["state"] == "unavailable" and "grammar" in unavailable["error"], "onboarding.addon-recovery", "missing office grammar not disclosed")
        rejects(lambda: host.install_pack(addon_root, "../../outside"))
        identity = "pack.ocr-local"
        source = served / "recover-addon.json"
        source.write_text(json.dumps(manifest()), encoding="utf-8")
        previous = os.environ.get("NEYVIA_ONBOARDING_PACK_MANIFESTS")
        try:
            os.environ["NEYVIA_ONBOARDING_PACK_MANIFESTS"] = json.dumps({identity: str(source)})
            row = host.install_pack(addon_root, identity, spawn=False)["packs"][0]
            require(row["state"] == "failed" and "packId" in row["error"] and "target" not in row, "onboarding.addon-recovery", "wrong add-on identity")
            source.write_text("{broken", encoding="utf-8")
            require(host.pack_status(addon_root, identity)["packs"][0]["state"] == "failed", "onboarding.addon-recovery", "broken manifest accepted")
            source.unlink()
            require(host.pack_status(addon_root, identity)["packs"][0]["state"] == "failed", "onboarding.addon-recovery", "missing manifest accepted")
            source.write_text(json.dumps(manifest(packId=identity)), encoding="utf-8")
            row = host.install_pack(addon_root, identity, spawn=False)["packs"][0]
            require(row["state"] == "queued" and row["error"] == "", "onboarding.addon-recovery", "repaired manifest cannot retry")
            # Complete the queued action so no scratch job is abandoned.
            require(host.run_download(addon_root, pack_id=identity)["state"] == "done", "onboarding.addon-recovery", "retry did not finish")
        finally:
            if previous is None:
                os.environ.pop("NEYVIA_ONBOARDING_PACK_MANIFESTS", None)
            else:
                os.environ["NEYVIA_ONBOARDING_PACK_MANIFESTS"] = previous

    def tiers():
        catalog = host.load_catalog()
        beginner = host.recommend(catalog, tier="beginner")
        advanced = host.recommend(catalog, tier="advanced")
        require(len(beginner["apps"]) < len(advanced["apps"]) and beginner["chapters"][0] == "basics" and beginner["chapters"][-1] == "help" and "missions" not in beginner["chapters"] and "missions" in advanced["chapters"], "onboarding.ordered-recommendations", "tier selection/tour")
        require(all(60 <= row["tourSeconds"] <= 90 for row in (beginner, advanced)), "onboarding.ordered-recommendations", "tour outside 60–90 seconds")

    def choices():
        choice_root = root / "choices"
        require(host.read_state(choice_root)["firstRun"], "onboarding.choices-durable", "first run missing")
        rejects(lambda: host.save_state(choice_root, {"apps": ["not-an-app"]}))
        require(not (host._dir(choice_root) / "state.json").exists(), "onboarding.choices-durable", "invalid choice changed disk")
        host.save_state(choice_root, {"interests": ["coding"], "apps": ["pdf"], "packs": ["pack.ocr-local"], "completed": True})
        state = host.read_state(choice_root)
        require(not state["firstRun"] and (state["interests"], state["apps"], state["completed"]) == (["coding"], ["pdf"], True), "onboarding.choices-durable", "choices not persisted")
        before = (host._dir(choice_root) / "state.json").read_bytes()
        rejects(lambda: host.save_state(choice_root, {"apps": ["not-an-app"]}))
        require((host._dir(choice_root) / "state.json").read_bytes() == before, "onboarding.choices-durable", "rejected save modified existing choices")

    def grounded_manual():
        from .native_tools import NativeToolRegistry
        from .neyvia_workspace_tools import workspace_for
        from . import neyvia_manuals
        manual_root = root / "manual-procedure"
        service, registry = workspace_for(manual_root), NativeToolRegistry(manual_root)

        def dispatch(tool, args, action_id=""):
            require(tool in {"neyvia.onboarding.save", "neyvia.onboarding.state", "neyvia.onboarding.base_pack"}, "onboarding.choices-durable", "manual fixture requested an out-of-area action")
            return host.call_tool(manual_root, tool.rsplit(".", 1)[-1], args)

        for observer in ("base-staging", "choices"):
            result = neyvia_manuals.call(service, "manual.observe", {"id": "onboarding", "chapter": "proofs-d-downloader", "state": observer, "inputs": {}}, dispatcher=dispatch, registry=registry)
            require(result.get("ok"), "onboarding.choices-durable", "grounded observer failed")
            observations.append({"manual": "onboarding", "observer": observer, "ok": True})
        result = neyvia_manuals.run(service, {"id": "onboarding", "chapter": "proofs-d-downloader", "procedure": "save-and-observe", "inputs": {"interests": ["coding"], "completed": True}}, registry, dispatch)
        require(result.get("ok") and result["status"] == "completed" and all(check["passed"] for check in result["checks"]), "onboarding.choices-durable", "grounded procedure failed")
        observations.append({"manual": "onboarding", "procedure": "save-and-observe", "runId": result["runId"], "checks": len(result["checks"]), "ok": True})

    try:
        for name, action in (
            ("test_resumes_a_partial_file_with_a_range_request", download),
            ("test_second_run_skips_verified_files", reuse),
            ("test_wrong_checksum_fails_and_keeps_nothing", corrupt),
            ("test_pause_stops_and_resume_finishes", pause),
            ("test_manifest_rejects_unsafe_paths_and_sources", unsafe),
            ("test_bundled_test_manifest_is_valid", bundled),
            ("test_add_on_worker_installs_local_manifest_on_separate_state", addons),
            ("test_add_on_rejects_unavailable_and_mismatched_manifests", addon_recovery),
            ("test_download_handles_empty_files_and_rejects_oversized_sources", empty_oversize),
            ("test_signed_remote_manifest_rejects_tampering_and_unknown_or_unprovisioned_keys", signatures),
            ("test_unsigned_manifest_allows_only_test_or_local_sources", unsigned),
            ("test_tiers_preselect_and_filter_the_tour", tiers),
            ("test_catalog_only_names_real_apps_and_packs", host.load_catalog),
            ("test_save_validates_and_persists", choices),
            ("grounded_manual_observers_and_procedure", grounded_manual),
        ):
            record(name, action)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return {"ok": all(row["ok"] for row in cases), "contracts": list(CONTRACTS), "cases": cases,
            "failures": [row for row in cases if not row["ok"]], "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "scratchRoot": str(root), "observers": ["onboarding.pack.status", "onboarding.state", "onboarding.base_pack.status"],
            "procedures": ["resume-and-verify", "pause-and-resume", "stage-detached-addon", "reject-and-repair-addon", "signed-manifest-admission", "save-setup-choices"],
            "httpRequests": requests, "actionReceipts": observations, "bytesPerFile": {name: len(body) for name, body in files.items()}}
