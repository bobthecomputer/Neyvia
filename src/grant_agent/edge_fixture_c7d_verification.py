"""Production local verification, measurement and artifact fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = {"empty": "", "huge": "owned supplied argument " * 2048, "unicode": "雪 café e\u0301 العربية"}
IDS = {"sv.verification.discovery", "sv.verification.result", "sv.ladder.receipt", "sv.performance.fail-closed", "sv.suite.artifacts", "sv.video.metadata", "sv.video.digest", "sv.video.route"}
PURE = {"sv.video.route"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def deny(action, types=(OSError, ValueError, RuntimeError)):
    try:
        action()
    except types as error:
        return type(error).__name__
    raise AssertionError("Actual refusal was required")


def _suite(root, category):
    from .suite_report import build_suite_summary, write_suite_artifacts
    text = TEXT.get(category, "Actual durable writer")
    results = [{"preset": text or "owned", "training_comparison": {"score_delta": 2}, "probe": {"status": "pass", "resistance_score": 4}}]
    def write(index):
        rows = [{**results[0], "preset": "writer-" + str(index)}]
        return write_suite_artifacts(root, "owned", rows, build_suite_summary(rows))
    if category == "concurrency":
        gate = threading.Barrier(8)
        def race(index):
            gate.wait(timeout=10)
            return write(index)
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(race, range(8)))
        final = json.loads((root / "owned.json").read_bytes())
        markdown = (root / "owned.md").read_text(encoding="utf-8")
        require(len(values) == 8 and final["results"][0]["preset"] in markdown and
                final["summary"]["presets"] == [final["results"][0]["preset"]], "Concurrent JSON/Markdown suite pair disagrees")
        return {"sameRootWriters": 8, "independentFinalPairAgrees": True}
    first = write_suite_artifacts(root, "owned", results, build_suite_summary(results))
    before = [(root / name).read_bytes() for name in ("owned.json", "owned.md")]
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with _deny_read(root / "owned.json"):
            deny(lambda: write(1))
        require(before == [(root / name).read_bytes() for name in ("owned.json", "owned.md")], "Denied suite replacement altered keepers")
    elif category == "stale":
        write(1)
        final = json.loads((root / "owned.json").read_bytes())
        require(final["results"][0]["preset"] == "writer-1" and "writer-1" in (root / "owned.md").read_text(encoding="utf-8"), "Explicit later suite write lost current pair")
    elif category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        code = "import os,sys;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.suite_report import build_suite_summary,write_suite_artifacts;rows=[{'preset':'completed-before-exit'}];write_suite_artifacts(r,'owned',rows,build_suite_summary(rows));os._exit(23)"
        child = subprocess.run([sys.executable, "-c", code, str(root)], capture_output=True, timeout=30,
                    env={**os.environ, "PYTHONPATH": str(REPO / "src")}, **hidden_windows_subprocess_kwargs())
        require(child.returncode == 23, "Owned suite child never completed durable write")
        require(json.loads((root / "owned.json").read_bytes())["results"] == [{"preset": "completed-before-exit"}] and
                "completed-before-exit" in (root / "owned.md").read_text(encoding="utf-8"), "Completed suite pair disappeared after abrupt exit")
    else:
        require(json.loads(Path(first["suite_json_path"]).read_bytes())["results"] == results, "Suite output changed actual row inputs")
    return {"independentJsonAndMarkdownReadback": True, "noTrainingExecuted": True}


def _discovery(root, category):
    from .verification import detect_default_verification_commands
    require(detect_default_verification_commands(root, pytest_python=sys.executable) == [], "Empty project invented default commands")
    (root / "pyproject.toml").write_text("[project]\nname='owned'\nversion='0'\n")
    (root / "src").mkdir()
    package = root / "package.json"
    text = TEXT.get(category, "owned")
    package.write_text(json.dumps({"description": text, "scripts": {"frontend:build": "Owned metadata only", "build": "Must not override"}}), encoding="utf-8")
    def observe():
        return detect_default_verification_commands(root, pytest_python=sys.executable)
    require(observe() == ["python -m compileall -q src", "npm run frontend:build"], "Discovery did not preserve actual project metadata precedence")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = package.read_bytes()
        with _deny_read(package):
            deny(observe, (OSError,))
        require(package.read_bytes() == before, "Denied package discovery altered bytes")
    if category == "stale":
        package.write_text(json.dumps({"scripts": {"build": "Metadata only"}}))
        require(observe()[-1] == "npm run build", "Discovery reused stale package scripts")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: observe(), range(16)))
        require(all(value == values[0] for value in values), "Stable concurrent metadata discovery diverged")
    return {"generatedCommandsNeverExecuted": True, "actualProjectMetadataRead": True, "pytestTestsExecuted": 0}


def _runner(root, category):
    from .verification import VerificationRunner
    script = root / "owned.cjs"
    text = TEXT.get(category, "owned")
    script.write_text("process.stdout.write(" + json.dumps(text or "empty input accepted") + ");", encoding="utf-8")
    runner = VerificationRunner(default_timeout_seconds=2)
    command = 'node "' + str(script) + '"'
    if category == "empty":
        require(runner.run([], root) == [], "Empty command list invented verification results")
    def observe():
        result = runner.run([command], root)[0]
        require(result.status == "executed" and result.return_code == 0 and result.stdout == (text.strip() or "empty input accepted"), "Actual Node stdout/exit receipt disagrees: " + str(result))
        return result
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with _deny_read(script):
            result = runner.run([command], root)[0]
        require(result.status == "executed" and result.return_code != 0 and result.stderr, "Denied Node source read acquired a passed receipt")
        return {"actualNodeReadDenied": True, "nonzeroOutcomePreserved": True}
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: observe(), range(8)))
        return {"realParallelNodeExecutions": len(values), "pytestTestsExecuted": 0}
    if category == "stale":
        observe(); script.write_text("process.stdout.write('fresh current bytes');")
        result = runner.run([command], root)[0]
        require(result.stdout == "fresh current bytes", "Explicit rerun reused old script bytes")
    elif category == "interrupted":
        pidfile = root / "owned-node-pid.json"
        script.write_text("require('node:fs').writeFileSync(" + json.dumps(str(pidfile)) + ",String(process.pid));setTimeout(()=>{},10000)")
        try:
            result = VerificationRunner(default_timeout_seconds=1).run([command], root)[0]
            require(result.status == "timeout" and result.return_code == 124 and "timed out" in result.stderr.lower(), "Actual deadline was not retained in result: " + str(result))
        finally:
            if pidfile.exists():
                import psutil
                try:
                    child = psutil.Process(int(pidfile.read_text(encoding="utf-8"))); child.kill(); child.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
        return {"realNodeDeadline": True, "ownedTimedOutNodeClosed": True, "pytestTestsExecuted": 0}
    else:
        observe()
    blocked = runner.run(["rm -rf /owned-c7d-never-executed"], root)[0]
    require(blocked.status == "blocked" and blocked.return_code == 126, "High-risk supplied command escaped real safety refusal")
    return {"actualNodeStdoutReadback": True, "highRiskCommandNotExecuted": True, "pytestTestsExecuted": 0}


def _ladder(root, category):
    from .verification_ladder import build_syntax_import_receipt, build_changed_file_targeted_receipt, build_backend_command_smoke_receipt, build_ui_button_smoke_receipt
    text = TEXT.get(category, "owned")
    missing = ["missing.py", "missing.py", "README.md"] if category != "empty" else []
    syntax = build_syntax_import_receipt(mission_id=text, workspace=root, changed_files=missing)
    require(syntax["status"] == ("failed" if missing else "passed") and syntax["missingFiles"] == (["missing.py"] if missing else []), "Missing source/empty syntax state fabricated compiler execution")
    targeted = build_changed_file_targeted_receipt(mission_id=text, workspace=root, changed_files=["test_missing.py"])
    require(targeted["status"] == "failed" and not targeted["targetedTestFiles"] and not targeted["command"], "Absent test target claimed pytest execution")
    script = root / "smoke.cjs"; script.write_text("process.stdout.write('actual Node command');")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with _deny_read(script):
            denied = build_backend_command_smoke_receipt(mission_id=text, workspace=root, commands=[["node", str(script)]])
        require(denied["status"] == "failed" and denied["commands"][0]["exitCode"] != 0, "Denied smoke source read acquired passing evidence")
        return {"actualNodeSourceSharingDenied": True, "failedReceiptRetained": True, "pytestTestsExecuted": 0}
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: build_backend_command_smoke_receipt(mission_id=text, workspace=root, commands=[["node", str(script)]]), range(8)))
        require(all(row["status"] == "passed" and row["commands"][0]["stdoutSummary"] == "actual Node command" for row in values), "Parallel actual smoke receipts lost measured stdout")
        return {"parallelActualNodeCommands": 8, "independentReceipts": 8, "pytestTestsExecuted": 0}
    if category == "stale":
        build_backend_command_smoke_receipt(mission_id=text, workspace=root, commands=[["node", str(script)]])
        script.write_text("process.stdout.write('fresh current smoke bytes');")
        fresh = build_backend_command_smoke_receipt(mission_id=text, workspace=root, commands=[["node", str(script)]])
        require(fresh["commands"][0]["stdoutSummary"] == "fresh current smoke bytes", "Explicit smoke rerun ignored current script bytes")
        return {"currentScriptReopened": True, "pytestTestsExecuted": 0}
    if category == "interrupted":
        pidfile = root / "owned-node-pid.json"
        script.write_text("require('node:fs').writeFileSync(" + json.dumps(str(pidfile)) + ",String(process.pid));setTimeout(()=>{},10000)")
        try:
            result = None
            try:
                result = build_backend_command_smoke_receipt(mission_id=text, workspace=root, commands=[["node", str(script)]], timeout_seconds=1)
            except subprocess.TimeoutExpired:
                pass
            require(result is None, "Actual deadline did not fire: " + str(result))
        finally:
            if pidfile.exists():
                import psutil
                try:
                    child = psutil.Process(int(pidfile.read_text(encoding="utf-8"))); child.kill(); child.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
        return {"actualOwnedNodeDeadline": True, "noCompletedReceiptFabricated": True, "ownedChildClosed": True, "pytestTestsExecuted": 0}
    receipt = build_backend_command_smoke_receipt(mission_id=text, workspace=root, commands=[["node", str(script)], ["node", "-e", "process.exit(9)"], ["node", "-e", "require('node:fs').writeFileSync('must-not-exist','bad')"]])
    require(receipt["status"] == "failed" and len(receipt["commands"]) == 2 and receipt["commands"][0]["stdoutSummary"] == "actual Node command" and not (root / "must-not-exist").exists(), "Smoke receipt lost failure or executed after failed phase")
    ui = build_ui_button_smoke_receipt(mission_id=text, target=text, interactions=[], proof_paths=[])
    require(ui["status"] == "skipped", "No actual button evidence became UI proof")
    return {"actualNodeSmokeCommands": 2, "stoppedAtRealExit9": True, "pytestTestsExecuted": 0, "renderedProof": False}


def _performance(root, category):
    script = REPO / "scripts/verify_performance_budget.py"
    spec = importlib.util.spec_from_file_location("c7d_actual_performance", script)
    owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
    config = json.loads((REPO / "config/neyvia_performance_budgets.json").read_bytes())
    build = root / "build"; build.mkdir(); assets = build / "assets"; assets.mkdir()
    source = assets / "main.js"; source.write_text("console.log(" + json.dumps(TEXT.get(category, "owned")) + ");", encoding="utf-8")
    (build / "index.html").write_text('<script type="module" src="./assets/main.js"></script>')
    runtime = root / "runtime.json"; runtime.write_text("{}")
    now = datetime.now(UTC)
    def observe():
        return owner.evaluate(config=config, build_dir=build, runtime_evidence_path=runtime, now=now)
    report = observe()
    require(not report["promotionEligible"] and report["status"] in {"unproven", "fail"} and report["summary"]["unproven"] > 0, "Generated empty runtime evidence promoted real artifact sizes into runtime proof")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with _deny_read(source):
            denied = observe()
        require(denied["summary"]["unproven"] > 0 and not denied["promotionEligible"], "Unreadable build acquired measured promotion proof")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: observe(), range(16)))
        require(all(value == report for value in values), "Stable concurrent measured build classification diverged")
    if category == "stale":
        source.write_text("actually changed artifact bytes")
        changed = observe()
        require(changed["build"] != report["build"] and not changed["promotionEligible"], "Build measurement reused stale source fingerprint")
    return {"actualLocalArtifactBytesMeasured": True, "missingRuntimeEvidenceUnproven": True, "promotionEligible": False, "renderedProof": False}


def _video_route(root, category):
    from .action_executor import HybridExecutionAdapter
    from .models import PlannedStep, ExecutionScope, ExecutionPolicy
    name = "café-東京.mp4" if category == "unicode" else "owned.mp4"
    source = root / name
    source.write_bytes(b"Routing input only, never decoded")
    description = "Analyze " + str(source) + " " + TEXT.get(category, "")
    result = HybridExecutionAdapter().build_action_proposal(PlannedStep("owned", "Video evidence", description), "Analyze local video", root, [],
            "owned", ExecutionScope(execution_root=str(root), workspace_root=str(root)), ExecutionPolicy("builder"))
    require(result.args["tool"] == "video.digest" and result.args["arguments"]["path"] == str(source), "Video route changed recognized path or dispatch owner")
    require(source.read_bytes() == b"Routing input only, never decoded", "Nonexecuting video proposal changed supplied source")
    return {"actualNonexecutingProposal": True, "recognizedSourcePreserved": True, "videoDecoded": False}


def _video(root, category, digest=False):
    from .video_tools import VideoEvidenceBuilder
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    owner = VideoEvidenceBuilder(root)
    require(owner.ffmpeg and owner.ffprobe, "Installed FFmpeg/FFprobe required; no synthetic metadata fallback")
    source = root / ("café-東京.mp4" if category == "unicode" else "owned.mp4")
    def generate(pattern="testsrc2"):
        command = [owner.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", pattern + "=size=128x96:rate=4", "-t", "1", "-c:v", "mpeg4", "-y", str(source)]
        completed = subprocess.run(command, capture_output=True, timeout=30, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0, "Actual FFmpeg source generation failed: " + completed.stderr.decode(errors="replace")[-500:])
    if category == "empty":
        deny(lambda: owner.digest({}) if digest else owner.inspect(""), (FileNotFoundError,))
    generate()
    before = source.read_bytes(); digest_args = {"path": str(source), "outputDir": str(root / "digest"), "maxFrames": 500 if category == "huge" else 2,
                                              "maxSceneFrames": -1, "transcribe": "none", "extractAudio": False}
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with _deny_read(source):
            deny(lambda: owner.digest(digest_args) if digest else owner.inspect(source))
        require(source.read_bytes() == before and not (root / "digest").exists(), "Denied video read changed source or acquired a digest")
        return {"actualFFprobeSourceReadDenied": True, "inputKeeperUnchanged": True, "completedDigest": False}
    if category == "interrupted" and digest:
        import psutil
        output = root / "digest"
        code = "import sys;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.video_tools import VideoEvidenceBuilder;VideoEvidenceBuilder(r).digest({'path':sys.argv[2],'outputDir':sys.argv[3],'maxFrames':36,'maxSceneFrames':-1,'transcribe':'none','extractAudio':False})"
        child = subprocess.Popen([sys.executable, "-c", code, str(root), str(source), str(output)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    env={**os.environ, "PYTHONPATH": str(REPO / "src")}, **hidden_windows_subprocess_kwargs())
        descendants = []
        try:
            deadline = time.monotonic() + 20
            while not (output / "frame-001.jpg").exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.005)
            require((output / "frame-001.jpg").exists(), "Owned video worker did not reach an actual partial-effect boundary")
            descendants = psutil.Process(child.pid).children(recursive=True)
            for worker in descendants:
                try:
                    worker.kill()
                except psutil.NoSuchProcess:
                    pass
            child.kill(); child.wait(timeout=5)
            psutil.wait_procs(descendants, timeout=5)
            require(not (output / "video-digest.json").exists() and source.read_bytes() == before, "Interrupted partial frames became a completed manifest or changed source")
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
            child.stderr.close()
        return {"actualOwnedWorkerInterruptedAfterFirstFrame": True, "finalManifestAbsent": True, "ownedChildrenClosed": True}
    def observe(index=0):
        if digest:
            args = {**digest_args, "outputDir": str(root / ("digest-" + str(index)))}
            result = owner.digest(args)
            manifest = json.loads(Path(result["manifestPath"]).read_bytes())
            require(result["sampledFrameCount"] == (4 if category == "huge" else 2) and result["frameCount"] > 0, "Digest did not enforce requested/bounded actual frame count")
            for frame in manifest["frames"]:
                require(hashlib.sha256(Path(frame["path"]).read_bytes()).hexdigest() == frame["sha256"], "Actual frame bytes differ from manifest")
            require(hashlib.sha256(Path(result["storyboardPath"]).read_bytes()).hexdigest() == manifest["storyboard"]["sha256"], "Actual storyboard differs from accepted digest")
            return result
        result = owner.inspect(source)
        require(result["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest() and result["video"]["width"] == 128 and result["video"]["height"] == 96 and
                result["video"]["frameRate"] == 4 and not result["audio"]["present"], "Actual FFprobe metadata differs from encoded source")
        return result
    result = observe()
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(observe, range(1, 5)))
        require(len(values) == 4 and source.read_bytes() == before, "Parallel video owners changed source bytes or lost results")
    if category == "stale":
        prior = hashlib.sha256(source.read_bytes()).hexdigest(); generate("testsrc")
        current = observe(1)
        require(hashlib.sha256(source.read_bytes()).hexdigest() != prior and (digest or current["sha256"] != prior), "Explicit new video inspection reused stale source bytes")
    return {"actualEncodedVideo": True, "actualDigest": digest, "sourceBytes": source.stat().st_size, "modelReadableFramesBoundToBytes": bool(digest), "renderedProof": False}


BUILDERS = {"sv.suite.artifacts": _suite, "sv.verification.discovery": _discovery, "sv.verification.result": _runner,
            "sv.ladder.receipt": _ladder, "sv.performance.fail-closed": _performance, "sv.video.route": _video_route,
            "sv.video.metadata": _video, "sv.video.digest": lambda root, category: _video(root, category, digest=True)}


def run(root, contracts, categories):
    rows = []
    for identity in sorted(BUILDERS.keys() & contracts.keys()):
        for category in categories:
            if category == "offline" or category not in TEXT and identity in PURE or category == "interrupted" and identity in {"sv.verification.discovery", "sv.performance.fail-closed", "sv.video.metadata"}:
                continue
            area = Path(root) / (identity.replace(".", "-") + "-" + category + "-" + uuid.uuid4().hex[:8]); area.mkdir(parents=True)
            row = {"id": "c7d-verification." + identity + "." + category, "contracts": [identity], "category": category,
                   "boundary": "Exact local production owner and actual artifact/Node process outcomes; no Python tests, rendered/provider/promotion claim"}
            try:
                row.update(status="passed", detail=BUILDERS[identity](area, category))
            except Exception as error:
                row.update(status="failed", detail={"type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()[-3500:]})
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity in PURE and category not in TEXT:
        return {"kind": "not_applicable", "reason": "Exact video route proposal recognizes supplied textual path and selects a tool descriptor. It never reads/decodes the source, launches a worker, checks an OS grant or admits shared revision; actual FFprobe/digest execution is exercised separately."}
    if identity in BUILDERS and category == "offline":
        return {"kind": "not_applicable", "reason": f"Inspected exact {identity} reads local metadata/artifact bytes, runs explicitly supplied local commands or serializes local suite files. These fixture branches have no endpoint/provider operation; command discovery is not execution, and runtime measurements without provenance remain unproven."}
    if identity in {"sv.verification.discovery", "sv.performance.fail-closed", "sv.video.metadata"} and category == "interrupted":
        return {"kind": "not_applicable", "reason": f"Exact {identity} reads selected current files into a synchronous return without a durable writer/resumable worker. Interrupted readers have no accepted result to replay; actual command timeouts and artifact writer interruption have separate owners."}
    return None
