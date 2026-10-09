"""Fast, offline proof of the real onboarding pack staging journey."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

CONTRACTS = ("p22.installer.local-pack-journey",)


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACTS[0]}: {detail}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_manifest(repo: Path, target: Path) -> tuple[Path, dict, dict[str, bytes]]:
    """Bind the generated creator SDK pack's real payloads to local file URLs."""
    path = repo / "config/onboarding_packs/pack.creator-sdk/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    bodies: dict[str, bytes] = {}
    for row in manifest["files"]:
        source = (repo / row["path"]).resolve()
        if row["path"] == "package.json":
            source = (repo / "config/onboarding_packs/pack.creator-sdk/package.json").resolve()
        source.relative_to(repo.resolve())
        body = source.read_bytes()
        # The checked-in generated manifest may lag this candidate's source edits.
        # Rebind the same declared component list to the current local bytes in
        # the disposable manifest; no repository-generated artifact is rewritten.
        row["size"] = len(body)
        row["sha256"] = _sha256(body)
        row["url"] = source.as_uri()
        bodies[row["path"]] = body
    # Put the largest actual component first so the production pause edge retains
    # a partial file rather than only a completed small component.
    manifest["files"].sort(key=lambda row: (-row["size"], row["path"]))
    manifest["totalSize"] = sum(row["size"] for row in manifest["files"])
    manifest["dev"] = {"throttleKbps": 1}
    require(manifest["totalSize"] < 200 * 1024 * 1024,
            "local generated pack exceeds the permitted proof payload size")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target, manifest, bodies


def self_check(root=None):
    """Pause and resume the actual onboarding downloader using local pack bytes only."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    repo = Path(__file__).resolve().parents[2]
    state_root = repo / ".agent_control" / "p22" / "installer-journey" / uuid.uuid4().hex
    state_root.mkdir(parents=True, exist_ok=False)
    manifest_path, raw_manifest, bodies = _local_manifest(
        repo, state_root / "source" / "local-components-manifest.json")
    identity = raw_manifest["packId"]
    source_bindings = {row["path"]: row["sha256"] for row in raw_manifest["files"]}
    total = int(raw_manifest["totalSize"])
    case_id = "installer.local-pack-journey"

    from . import neyvia_onboarding as onboarding

    previous = os.environ.get("NEYVIA_BASE_PACK_MANIFEST")
    os.environ["NEYVIA_BASE_PACK_MANIFEST"] = str(manifest_path)
    worker_result: dict = {}
    worker_error: list[str] = []
    worker_done = threading.Event()
    try:
        # The standard first-run start command validates the manifest before it reports
        # a queued state. Spawn is disabled so the harness owns and joins the worker.
        queued = onboarding.start_base_pack(state_root, spawn=False)
        require(queued.get("state") == "starting" and queued.get("packId") == identity
                and queued.get("doneBytes") == 0 and queued.get("totalBytes") == total,
                "start did not report the selected local pack and initial progress")

        manifest = onboarding.load_manifest()
        require(all(row["url"].startswith("file:") for row in manifest["files"])
                and manifest["totalSize"] == total,
                "proof manifest resolved a source outside local files")
        pack_dir = onboarding._pack_dir(state_root)
        pause_path = pack_dir / "pause"

        def wait_until_paused(_delay: float) -> None:
            deadline = time.monotonic() + 5
            while not pause_path.exists() and time.monotonic() < deadline:
                time.sleep(0.005)

        def download_to_pause() -> None:
            try:
                worker_result.update(onboarding.run_download(
                    state_root, manifest, sleep=wait_until_paused))
            except Exception as exc:  # expose thread failures through the contract
                worker_error.append(str(exc))
            finally:
                worker_done.set()

        worker = threading.Thread(target=download_to_pause, name="p22-local-pack-download", daemon=True)
        worker.start()
        progress_deadline = time.monotonic() + 4
        progress = onboarding.base_pack_status(state_root)
        while time.monotonic() < progress_deadline:
            progress = onboarding.base_pack_status(state_root)
            if progress.get("state") == "running" and int(progress.get("doneBytes") or 0) > 0:
                break
            if worker_done.is_set():
                break
            time.sleep(0.01)
        require(progress.get("state") == "running" and int(progress.get("doneBytes") or 0) > 0,
                "downloader never exposed real byte progress before pause")

        paused = onboarding.pause_base_pack(state_root)
        worker.join(timeout=5)
        require(not worker.is_alive() and not worker_error and worker_done.is_set(),
                "pause did not stop the owned downloader promptly")
        require(paused.get("state") == "paused" and worker_result.get("state") == "paused"
                and not pause_path.exists(),
                "pause command did not persist paused state and consume the request")
        paused_status = onboarding.base_pack_status(state_root)
        require(paused_status.get("state") == "paused"
                and 0 < int(paused_status.get("doneBytes") or 0) < total,
                "paused state must retain nonzero partial progress below the total")
        partial_rows = []
        for row in manifest["files"]:
            partial = onboarding._pack_dir(state_root) / identity / manifest["version"] / (row["path"] + ".part")
            if partial.exists():
                body = partial.read_bytes()
                source = bodies[row["path"]]
                require(body == source[:len(body)] and len(body) <= row["size"],
                        f"partial payload differs from its local source bytes: {row['path']}")
                partial_rows.append((row["path"], len(body)))
        require(partial_rows and sum(size for _, size in partial_rows) == paused_status["doneBytes"],
                "durable progress does not equal the actual retained partial bytes")

        # Resume through the same production downloader. No URL leaves the filesystem.
        resumed = onboarding.run_download(state_root, manifest, sleep=lambda _delay: None)
        require(resumed.get("state") == "done" and resumed.get("doneBytes") == total
                and resumed.get("files") == {"done": len(manifest["files"]), "total": len(manifest["files"])}
                and int(resumed.get("resumedBytes") or 0) > 0,
                "resume did not finish the local pack from the retained bytes")
        target = Path(resumed["target"])
        receipt = json.loads((target / "installed.json").read_text(encoding="utf-8"))
        require(receipt.get("packId") == identity and receipt.get("version") == manifest["version"]
                and receipt.get("files") == [
                    {"path": row["path"], "size": row["size"], "sha256": row["sha256"]}
                    for row in manifest["files"]
                ], "installed receipt changed the generated pack's component inventory")
        staged = {}
        for row in manifest["files"]:
            body = (target / row["path"]).read_bytes()
            require(body == bodies[row["path"]] and _sha256(body) == source_bindings[row["path"]],
                    f"staged component differs from source bytes: {row['path']}")
            staged[row["path"]] = {"bytes": len(body), "sha256": _sha256(body)}
        complete = onboarding.base_pack_status(state_root)
        require(complete.get("state") == "done" and complete.get("doneBytes") == total
                and complete.get("receipt") == str(target / "installed.json"),
                "status observer did not reopen the durable completed receipt")

        # A fresh unsafe request is refused before it can overwrite the completed result.
        unsafe = json.loads(json.dumps(raw_manifest))
        unsafe["files"][0]["path"] = "../escape.py"
        unsafe_path = state_root / "source" / "unsafe-manifest.json"
        unsafe_path.write_text(json.dumps(unsafe), encoding="utf-8")
        escaped = state_root.parent / "escape.py"
        require(not escaped.exists(), "unsafe-path sentinel unexpectedly existed before refusal")
        os.environ["NEYVIA_BASE_PACK_MANIFEST"] = str(unsafe_path)
        try:
            onboarding.start_base_pack(state_root, spawn=False)
        except ValueError as exc:
            require("Unsafe manifest path" in str(exc), "manifest refusal did not explain unsafe path")
        else:
            raise ValueError(f"Contract {CONTRACTS[0]}: unsafe manifest path was accepted")
        require(not escaped.exists() and onboarding.base_pack_status(state_root).get("state") == "done"
                and all((target / name).read_bytes() == bodies[name] for name in bodies),
                "unsafe manifest refusal changed installed bytes or wrote outside staging")

        case = {
            "id": case_id,
            "contracts": list(CONTRACTS),
            "ok": True,
            "packId": identity,
            "stagedFiles": staged,
            "pauseState": paused_status["state"],
            "pausedBytes": paused_status["doneBytes"],
            "resumedBytes": resumed["resumedBytes"],
            "finalBytes": resumed["doneBytes"],
            "unsafePathRefused": True,
            "stagingOnly": True,
        }
        return {
            "ok": True,
            "contracts": list(CONTRACTS),
            "outcomes": [{"id": identity, "status": "PASS"} for identity in CONTRACTS],
            "cases": [case],
            "failures": [],
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "stateRoot": str(state_root),
            "frontier": "Runs the production first-run staging, progress, pause, resume, receipt and manifest refusal paths over generated local component files. The pack remains staged and is never activated or installed system-wide.",
        }
    except Exception as error:
        return {
            "ok": False,
            "contracts": list(CONTRACTS),
            "outcomes": [{"id": identity, "status": "FAIL"} for identity in CONTRACTS],
            "cases": [{"id": case_id, "contracts": list(CONTRACTS), "ok": False, "error": str(error)}],
            "failures": [str(error)],
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "stateRoot": str(state_root),
        }
    finally:
        if previous is None:
            os.environ.pop("NEYVIA_BASE_PACK_MANIFEST", None)
        else:
            os.environ["NEYVIA_BASE_PACK_MANIFEST"] = previous
