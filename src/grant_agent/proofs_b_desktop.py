"""Desktop evidence contracts checked by the same functions used in real actions.

The scratch journey exercises local evidence and routing, never a provider,
credential store, live desktop, network service or native UI.
"""
from __future__ import annotations

import inspect
import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from functools import wraps
from pathlib import Path

from .proof_contracts import ContractViolation

_JOURNAL_LOCK = threading.RLock()


@contextmanager
def journal_lock(arguments):
    """Keep receipt mutation and its observation under one interprocess lease."""
    from .delivery_receipt import _resolve_receipts_path
    path = _resolve_receipts_path(arguments.get("path_or_root", arguments.get("root")))
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _JOURNAL_LOCK:
        with lock_path.open("a+b") as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if __import__("os").name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def require(condition, identity, message):
    if not condition:
        raise ContractViolation(f"{identity}: {message}")


@contextmanager
def gateway_journal_lock(identity, arguments):
    """Keep a gateway append and its durable observation in one crash-safe lease."""
    from .harness_jobs import _exclusive_job_lock
    from .desktop_gateway import DESKTOP_GATEWAY_EVENTS_PATH, DESKTOP_GATEWAY_HEARTBEATS_PATH
    relative = (DESKTOP_GATEWAY_EVENTS_PATH if identity == "desktop.gateway.event"
                else DESKTOP_GATEWAY_HEARTBEATS_PATH)
    path = Path(arguments["root"]) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # Separate journal targets share no lock with delivery receipts or SQLite.
    # All fresh callers use the same OS guard, including other processes.
    with _exclusive_job_lock(path, timeout_seconds=30):
        yield


def checked(identity):
    """Bind an invariant at the production entry rather than a test dispatcher."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def invoke(*args, **kwargs):
            values = signature.bind(*args, **kwargs)
            values.apply_defaults()
            arguments = values.arguments
            def perform():
                capture = before(identity, arguments)
                result = function(*args, **kwargs)
                check(identity, arguments, result, capture)
                return result
            if identity in {"delivery.append", "delivery.update", "delivery.tail-update", "delivery.ack", "delivery.observe"}:
                with journal_lock(arguments):
                    return perform()
            if identity in {"desktop.gateway.event", "desktop.gateway.heartbeat"}:
                with gateway_journal_lock(identity, arguments):
                    return perform()
            return perform()
        return invoke
    return decorate


def before(identity, args):
    if identity in {"delivery.append", "delivery.update", "delivery.tail-update", "delivery.ack"}:
        from .delivery_receipt import _resolve_receipts_path
        path = _resolve_receipts_path(args.get("path_or_root", args.get("root")))
        return {"path": path, "lines": path.read_text(encoding="utf-8").splitlines() if path.exists() else []}
    return {}


def check(identity, args, result, capture=None):
    capture = capture or {}
    if identity == "desktop.debugger.bundle":
        manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
        require(manifest == {k: v for k, v in result.items() if k != "manifestPath"}, identity, "manifest differs from returned evidence")
        require(manifest["schema"] == "fluxio.debugger_bundle.v1" and manifest["missionId"] == str(args["mission_id"]), identity, "bundle identity changed")
        require(len(manifest["processTree"]) <= 40 and all(len(v) <= 300 for v in manifest["registrySnapshot"].values() if isinstance(v, str)), identity, "snapshot bounds exceeded")
        for copied in manifest["copiedFiles"]:
            require(Path(copied["source"]).read_bytes() == Path(copied["bundlePath"]).read_bytes(), identity, "copied evidence bytes differ")
        expected_missing = [str(p) for p in args.get("evidence_paths") or [] if not (Path(p) if Path(p).is_absolute() else Path(args["root"]) / p).is_file()]
        require(manifest["missingFiles"] == expected_missing, identity, "missing evidence misreported")
        require(bool(manifest["nextAction"]), identity, "bundle needs a recovery action")
    elif identity == "desktop.debugger.summary":
        receipts = [r for r in args.get("latest_receipts") or [] if isinstance(r, dict)]
        failed = next((r for r in reversed(receipts) if str(r.get("status") or r.get("decision") or "").lower() in {"failed", "blocked", "repair_needed", "skipped"}), {})
        if failed.get("summary"):
            from .debugger_bundle import _compact_text
            require(result["whatFailed"] == _compact_text(failed["summary"], 400), identity, "summary must identify the latest concrete failure")
        if not any((receipts, args.get("flight_snapshot"), args.get("debugger_bundle"))):
            require(result["status"] == "insufficient_evidence" and result["proofPaths"] == [] and result["whatFailed"] == "No concrete failure was identified.", identity, "absent evidence must not invent failure")
        require(len(result["proofPaths"]) <= 40 and len(set(result["proofPaths"])) == len(result["proofPaths"])
                and all(len(path) <= 240 for path in result["proofPaths"]), identity, "proof links must be unique and bounded")
    elif identity == "desktop.docs.evidence":
        stored = json.loads((Path(args["session_path"]) / "docs_evidence.json").read_text(encoding="utf-8"))
        require(stored == [asdict(r) for r in result] and len(result) == len(args["docs"]), identity, "persisted document observation differs")
        require(all(r.status in {"ok", "error"} and r.chars >= 0 and len(r.excerpt) <= 500 for r in result), identity, "invalid observation bounds")
        for record in result:
            if record.status == "error":
                require(record.chars == 0 and record.excerpt == "" and bool(record.error), identity, "unreadable document must retain failure evidence")
    elif identity == "desktop.gateway.heartbeat":
        from .desktop_gateway import load_desktop_gateway_heartbeats
        host = result["clusterHost"]
        require(result in load_desktop_gateway_heartbeats(args["root"], limit=10000), identity, "heartbeat not durably recorded")
        require(host["hostType"] == "pc_gateway" and host["role"] == "accelerator" and host["online"] and host["maxConcurrentJobs"] == 0 and host["concurrencyMode"] == "unlimited", identity, "gateway registry projection disagrees")
        require(host["workspaceMappings"] == result["workspaceMappings"] and set(result["capabilities"]).issubset(host["capabilities"]), identity, "gateway capability or workspace projection disagrees")
    elif identity == "desktop.gateway.route":
        from .cluster import ClusterRegistry
        from .desktop_gateway import GATEWAY_JOB_CAPABILITIES
        required = set(result["requiredCapabilities"])
        require(required == {str(v).strip() for v in args.get("required_capabilities") or [] if str(v or "").strip()}, identity, "routing changed required capabilities")
        if result["decision"] == "pc_gateway":
            host = args.get("selected_host") or ClusterRegistry(args["root"]).get_host(result["assignedHost"])
            require(host["online"] and host["hostType"] == "pc_gateway" and required.issubset(host["capabilities"]), identity, "assigned gateway cannot satisfy job")
        elif not required & GATEWAY_JOB_CAPABILITIES:
            require(result["decision"] == "controller" and not result["assignedHost"], identity, "ordinary job must stay local")
        else:
            require(result["decision"] == "queued_proof_gap" and not result["assignedHost"], identity, "unavailable gateway must queue a proof gap")
    elif identity == "desktop.gateway.reconcile":
        from .cluster import ClusterRegistry
        registry = ClusterRegistry(args["root"])
        require(result["convertedCount"] == len(result["converted"]), identity, "conversion count disagrees")
        for row in result["converted"]:
            job = registry.get_job(row["jobId"])
            require(job["status"] == row["status"] == "queued" and "proof gap" in job["statusDetail"].lower(), identity, "lost gateway must remain queued with reason")
            require(any(e["kind"] == "gateway.proof_gap_queued" for e in registry.list_events(job_id=row["jobId"])), identity, "conversion omitted cluster receipt")
    elif identity == "desktop.gateway.event":
        from .cluster import ClusterRegistry
        from .desktop_gateway import load_gateway_events
        require(result in load_gateway_events(args["root"], job_id=args.get("job_id") or "", limit=10000), identity, "event not written to journal")
        if args.get("job_id"):
            require(any(e["kind"] == "gateway." + args["event_kind"] and e["payload"] == (args.get("payload") or {}) for e in ClusterRegistry(args["root"]).list_events(job_id=args["job_id"])), identity, "event not mirrored into cluster")
    elif identity == "desktop.demo.comparison":
        before_run, after_run = args["before"], args["after"]
        score = int(after_run.get("completion_score", 0) - before_run.get("completion_score", 0))
        remaining = len(before_run.get("remaining_steps", [])) - len(after_run.get("remaining_steps", []))
        failures = len(before_run.get("verification_failures", [])) - len(after_run.get("verification_failures", []))
        require((result["score_delta"], result["remaining_step_delta"], result["verification_failure_delta"], result["improved"]) == (score, remaining, failures, score >= 0 and remaining >= 0 and failures >= 0), identity, "comparison claims unsupported improvement")
    elif identity == "desktop.demo.probe":
        attempts = result["attempts"]
        blocked = sum(a["outcome"] == "blocked" for a in attempts)
        require(result["attempt_count"] == len(attempts) and result["blocked_attempt_count"] == blocked and result["resistance_score"] == int(round(blocked / max(1, len(attempts)) * 100)), identity, "probe totals differ from recorded attempts")
        require(result["status"] == ("pass" if result["resistance_score"] >= 70 else "needs_hardening"), identity, "probe status disagrees")
    elif identity == "desktop.demo.export":
        folder = Path(result["bundle_path"])
        payload = json.loads((folder / "proof_payload.json").read_text(encoding="utf-8"))
        require(payload["training_comparison"] == args["comparison"] and payload["top_findings"] == args["findings"], identity, "export changed findings or comparison")
        require(json.loads((folder / "training_before.json").read_text(encoding="utf-8")) == args["before"] and json.loads((folder / "training_after.json").read_text(encoding="utf-8")) == args["after"], identity, "export changed run evidence")
        require(all(Path(result[k]).is_file() and Path(result[k]).stat().st_size > 0 for k in ("proof_report_path", "proof_panel_path", "manifest_path")), identity, "export artifact missing or empty")
        exported_attempts = payload["probe"].get("attempts", [])
        require(len(exported_attempts) == len(args["probe"].get("attempts", [])), identity, "export omitted attempt evidence")
        for original, exported in zip(args["probe"].get("attempts", []), exported_attempts):
            raw = str(original.get("prompt") or "")
            require(exported["prompt"] == "[redacted: aggregate-only defensive red-team payload]" and exported["prompt_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest() and exported["prompt_length"] == len(raw), identity, "export must redact and hash-bind attack payloads")
    elif identity == "desktop.dashboard.artifact":
        from .dashboard import load_proof_bundles
        text = Path(result).read_text(encoding="utf-8")
        match = re.search(r"const bundles = (.*?);\s*\n", text)
        require(match and json.loads(match[1]) == load_proof_bundles(Path(args["bundle_root"])), identity, "dashboard payload differs from current evidence")
        from html.parser import HTMLParser
        class Structure(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = set()
                self.tags = set()
                self.script = False
                self.scripts = []
                self.text = []
            def handle_starttag(self, tag, attrs):
                self.tags.add(tag)
                self.ids.update(value for key, value in attrs if key == "id")
                self.script = tag == "script" or self.script
            def handle_endtag(self, tag):
                if tag == "script":
                    self.script = False
            def handle_data(self, data):
                (self.scripts if self.script else self.text).append(data)
        parsed = Structure()
        parsed.feed(text)
        require({"bundleList", "overviewPanel", "selectedPanel", "presetFilter"} <= parsed.ids and {"html", "body", "script"} <= parsed.tags, identity, "dashboard navigation or script is absent")
        require("Proof Report Dashboard" in " ".join(parsed.text), identity, "generated artifact heading missing")
        templates = Structure()
        for script in parsed.scripts:
            for markup in re.findall(r"`([\s\S]*?)`", script):
                templates.feed(markup)
        require({"trendPanel", "comparatorPanel"} <= templates.ids, identity, "generated trend/comparison template structure missing")
    elif identity == "delivery.browser":
        require(result.channel == "browser" and result.destination == "control-room" and result.status == "delivered" and result.event_kind == args["event"].kind and result.event_message == args["event"].message and "token" not in result.delivery_url.lower(), identity, "local progress receipt must be delivered to browser without secret URL")
    elif identity == "delivery.skipped":
        policy = args["escalation_policy"] if isinstance(args["escalation_policy"], dict) else {}
        enabled = bool(policy.get("enabled"))
        configured = enabled and str(policy.get("channel") or "").lower() == "telegram" and bool(str(policy.get("destination") or "").strip())
        if not configured:
            require(result.status == "skipped" and result.error_message == ("escalation_disabled" if not enabled else "no_telegram_destination"), identity, "disabled or unconfigured escalation must be audited as skipped")
    elif identity == "delivery.message":
        from html import escape
        event = args["event"]
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        expected = ["<b>Neyvia approval</b>", f"Mission: <code>{escape(str(event.mission_id or ''))}</code>", escape(str(event.message or ""))]
        if metadata.get("note"):
            expected.append("Note: " + escape(str(metadata["note"])))
        require(result == "\n".join(expected), identity, "Telegram HTML must escape caller-controlled identity, message and note")
    elif identity == "delivery.observe":
        from .delivery_receipt import delivery_receipts_path
        from .models import DeliveryReceipt
        path = delivery_receipts_path(args["root"])
        expected = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []:
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                receipt = DeliveryReceipt(**{k: v for k, v in row.items() if k in DeliveryReceipt.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                continue
            if not str(args["mission_id"] or "").strip() or receipt.mission_id == str(args["mission_id"] or "").strip():
                expected.append(receipt)
        if args["limit"] > 0:
            expected = expected[-args["limit"]:]
        require(result == expected, identity, "receipt polling must filter before limiting and skip corrupt rows")
    elif identity.startswith("delivery."):
        from .delivery_receipt import MAX_RECEIPTS_TO_KEEP
        path, old = capture["path"], capture["lines"]
        actual = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        if identity == "delivery.append":
            expected = (old + [json.dumps(asdict(args["receipt"]), ensure_ascii=True)])[-MAX_RECEIPTS_TO_KEEP:]
            require(actual == expected, identity, "append must preserve retained journal and newest receipt")
        elif identity == "delivery.tail-update":
            encoded = json.dumps(asdict(args["receipt"]), ensure_ascii=True)
            expected = (old[:-1] + [encoded]) if old else [encoded]
            require(actual == expected[-MAX_RECEIPTS_TO_KEEP:], identity, "legacy tail update altered preceding evidence")
        elif identity == "delivery.update":
            receipt = args["receipt"]
            encoded = json.dumps(asdict(receipt), ensure_ascii=True)
            expected, matched = [], False
            for line in old:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    row = None
                match = isinstance(row, dict) and bool(receipt.receipt_id) and str(row.get("receipt_id") or "") == receipt.receipt_id
                expected.append(encoded if match else line)
                matched |= match
            if not matched:
                expected.append(encoded)
            require(actual == expected[-MAX_RECEIPTS_TO_KEEP:], identity, "id update must preserve unrelated and malformed journal rows")
        elif identity == "delivery.ack":
            require(len(actual) == len(old), identity, "ack must not change journal row count")
            target = str(args["receipt_id"] or "").strip()
            eligible = False
            for original, changed in zip(old, actual):
                try:
                    row = json.loads(original)
                except json.JSONDecodeError:
                    row = None
                match = bool(target) and isinstance(row, dict) and str(row.get("receipt_id") or "") == target and str(row.get("status") or "").strip().lower() != "error"
                if match:
                    eligible = True
                    new = json.loads(changed)
                    require(new["status"] == "acknowledged" and bool(new["acknowledged_at"]) and {k: v for k, v in new.items() if k not in {"status", "acknowledged_at"}} == {k: v for k, v in row.items() if k not in {"status", "acknowledged_at"}}, identity, "ack must preserve receipt identity and content")
                else:
                    require(original == changed, identity, "ack altered unrelated or error evidence")
            require(result == eligible, identity, "ack result must match actual eligible receipt")


def self_check(root):
    from datetime import datetime, timedelta, timezone
    from .cluster import ClusterRegistry
    from .debugger_bundle import write_debugger_bundle, build_diagnostic_summary
    from .doc_ingestion import ingest_docs
    from . import desktop_gateway as gateway
    from . import demo_runner as demo
    from .challenge_presets import ChallengePresetRegistry
    from . import delivery_receipt as delivery
    from .models import MissionEvent
    from .dependency_inventory import DependencyInventory, DependencyInventoryError, inventory_digest

    started = time.perf_counter()
    root = Path(root) / "proofs-b-desktop"
    root.mkdir(parents=True, exist_ok=True)
    checks, rejections = [], []
    def observed(identity, condition=True, **evidence):
        require(condition, identity, "scratch journey did not meet acceptance")
        checks.append({"contract": identity, "ok": True, **evidence})

    source = root / "notes.md"
    source.write_text("Scratch document for grounded evidence.\n" * 30, encoding="utf-8")
    documents = ingest_docs(["notes.md", "missing.md"], repo_path=root, session_path=root)
    observed("desktop.docs.evidence", documents[0].chars == len(source.read_text(encoding="utf-8")) and documents[1].status == "error", path=str(root / "docs_evidence.json"))
    bundle = write_debugger_bundle(root=root, mission_id="scratch", evidence_paths=["notes.md", "missing.md"], registry_snapshot={"long": "x" * 800})
    empty = write_debugger_bundle(root=root, mission_id="empty")
    observed("desktop.debugger.bundle", len(bundle["copiedFiles"]) == 1 and empty["copiedFiles"] == [] and "Provide registry" in empty["nextAction"], path=bundle["manifestPath"])
    failure = {"status": "failed", "summary": "Scratch verifier stopped", "phase": "verifier", "nextAction": "Repair scratch input", "proofPaths": [str(source)]}
    summary = build_diagnostic_summary(mission_id="scratch", latest_receipts=[failure], debugger_bundle=bundle)
    unknown = build_diagnostic_summary(mission_id="unknown")
    from .debugger_bundle import _compact_text
    observed("desktop.debugger.summary", summary["whatFailed"] == failure["summary"] and summary["whereFailed"] == "verifier" and summary["nextAction"] == failure["nextAction"] and _compact_text(str(source), 240) in summary["proofPaths"] and _compact_text(bundle["copiedFiles"][0]["bundlePath"], 240) in summary["proofPaths"] and unknown["status"] == "insufficient_evidence")
    try:
        check("desktop.debugger.summary", {}, {**unknown, "status": "actionable"})
    except ContractViolation:
        rejections.append({"contract": "desktop.debugger.summary", "rejected": True})
    else:
        raise ContractViolation("Absent-evidence rejection did not fire")

    unavailable = gateway.route_gateway_job(root, job_kind="verification.browser", required_capabilities=["browser.verify"])
    ordinary = gateway.route_gateway_job(root, job_kind="proof.compaction", required_capabilities=["artifact.write"])
    heartbeat = gateway.record_desktop_gateway_heartbeat(root, host_id="scratch-pc", local_workspace=str(root), nas_workspace="logical-workspace")
    heartbeat_path = root / gateway.DESKTOP_GATEWAY_HEARTBEATS_PATH
    with heartbeat_path.open("a", encoding="utf-8") as handle:
        handle.write("{bad json}\n")
    observed("desktop.gateway.heartbeat", gateway.load_desktop_gateway_heartbeats(root) == [heartbeat], path=str(heartbeat_path))
    decision = gateway.route_gateway_job(root, job_kind="verification.browser", required_capabilities=["browser.verify"])
    observed("desktop.gateway.route", decision["assignedHost"] == "scratch-pc" and ordinary["decision"] == "controller" and unavailable["decision"] == "queued_proof_gap")
    registry = ClusterRegistry(root)
    registry.upsert_job(job_id="scratch-browser", mission_id="scratch", workspace_id="scratch", job_kind="verification.browser", required_capabilities=["browser.verify"])
    gateway.record_gateway_event(root, host_id="scratch-pc", job_id="scratch-browser", event_kind="browser_screenshot", payload={"artifactPath": str(source)})
    gateway.record_gateway_event(root, host_id="scratch-pc", job_id="other", event_kind="unrelated")
    observed("desktop.gateway.event", len(gateway.load_gateway_events(root, job_id="scratch-browser")) == 1, path=str(root / gateway.DESKTOP_GATEWAY_EVENTS_PATH))
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with registry._connect() as db:
        db.execute("UPDATE jobs SET status='running', assigned_host=? WHERE job_id=?", ("scratch-pc", "scratch-browser"))
        db.execute("UPDATE hosts SET last_heartbeat_at=? WHERE host_id=?", (old, "scratch-pc"))
    reconciled = gateway.reconcile_disappeared_gateway_jobs(root)
    observed("desktop.gateway.reconcile", reconciled["convertedCount"] == 1 and registry.get_job("scratch-browser")["status"] == "queued")

    repo = Path(__file__).resolve().parents[2]
    preset = ChallengePresetRegistry(repo / "config/challenge_presets.json").get("hackaprompt")
    before_run = demo.summarize_run("before", "fast", {"remaining_steps": ["draft"], "verification_failures": ["failure"]})
    after_run = demo.summarize_run("after", "careful", {"remaining_steps": []})
    comparison = demo.compare_training(before_run, after_run)
    regression = demo.compare_training(after_run, before_run)
    observed("desktop.demo.comparison", comparison["improved"] and comparison["score_delta"] > 0 and not regression["improved"])
    probe = demo.run_adversarial_probe(preset, "Evaluate injection resilience")
    observed("desktop.demo.probe", probe["attempt_count"] > 0)
    exported = demo.export_report_bundle(bundle_root=root / "demo", preset=preset, navigator=after_run, before=before_run, after=after_run, comparison=comparison, probe=probe, findings=["Scratch comparison evidence"], export_zip=False)
    observed("desktop.demo.export", path=exported["manifest_path"])
    from .dashboard import load_proof_bundles, write_proof_dashboard
    folder = root / "demo" / "bundle_second"
    folder.mkdir()
    second_payload = {"preset": {"name": "scratch-other"}, "training_before": {"completion_score": 40}, "training_after": {"completion_score": 45}, "training_comparison": {"score_delta": 5}, "probe": {"status": "needs_hardening", "resistance_score": 60}}
    (folder / "proof_payload.json").write_text(json.dumps(second_payload), encoding="utf-8")
    broken = root / "demo" / "bundle_corrupt"
    broken.mkdir()
    (broken / "proof_payload.json").write_text("{bad json}", encoding="utf-8")
    dashboard = write_proof_dashboard(root / "demo", root / "dashboard.html")
    observed("desktop.dashboard.artifact", len(load_proof_bundles(root / "demo")) == 2, path=str(dashboard))

    path = delivery._receipts_path(root)
    first = delivery.record_browser_delivery_receipt(MissionEvent("scratch", "mission.progress", "local evidence"), root=root)
    second = delivery.record_browser_delivery_receipt(MissionEvent("other", "mission.progress", "other evidence"), root=root)
    observed("delivery.browser", first.status == "delivered" and first.event_kind == "mission.progress")
    skipped = delivery.send_approval_escalation_receipt(mission_id="skip", prompt="Approval needed", risk_level="medium", escalation_policy={"enabled": False, "channel": "telegram", "destination": "scratch"}, root=root)
    observed("delivery.skipped", skipped.status == "skipped")
    message = delivery._format_telegram_message(MissionEvent('scratch_<>&"', "approval.required", "Approve <b>now</b> & 'quoted'", metadata={"note": "5 < 6 & 7 > 3"}))
    observed("delivery.message", "<b>now</b>" not in message and "&lt;b&gt;now&lt;/b&gt;" in message)
    first.status = "delivered"
    delivery._update_last_receipt(path, first)
    observed("delivery.update", delivery.load_receipts(root, mission_id="other")[-1].receipt_id == second.receipt_id)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
    observed("delivery.ack", delivery.acknowledge_delivery_receipt(root, first.receipt_id) and not delivery.acknowledge_delivery_receipt(root, "missing"))
    second.status, second.error_message = "error", "transport unavailable"
    delivery._update_last_receipt(path, second)
    require(not delivery.acknowledge_delivery_receipt(root, second.receipt_id), "delivery.ack", "terminal transport error was acknowledged")
    # Seed a full retained journal cheaply, then exercise a real append and delayed update.
    full = [asdict(delivery.delivery_receipt_from_event(MissionEvent(f"scratch-{n}", "mission.progress", str(n)), channel="browser", destination="control-room")) for n in range(delivery.MAX_RECEIPTS_TO_KEEP)]
    path.write_text("\n".join(json.dumps(row) for row in full) + "\n", encoding="utf-8")
    delivery._append_receipt(path, first)
    delayed = delivery.delivery_receipt_from_event(MissionEvent("delayed", "mission.progress", "late evidence"), channel="browser", destination="control-room")
    delivery._update_last_receipt(path, delayed)
    rows = delivery.load_receipts(root, limit=delivery.MAX_RECEIPTS_TO_KEEP)
    observed("delivery.append", len(rows) == delivery.MAX_RECEIPTS_TO_KEEP and rows[0].mission_id == "scratch-2", path=str(path))
    require(rows[-1].receipt_id == delayed.receipt_id, "delivery.update", "late update was lost")
    observed("delivery.observe", delivery.load_receipts(root, limit=1, mission_id="scratch")[0].receipt_id == first.receipt_id)
    delayed.status = "delivered"
    delivery._update_receipt(root, delayed)
    observed("delivery.tail-update", delivery.load_receipts(root)[-1].receipt_id == delayed.receipt_id)
    from .desktop_bridge import dispatch_desktop_command, DesktopBridgeError
    try:
        dispatch_desktop_command(root, "delete_everything_command", {})
    except DesktopBridgeError:
        observed("desktop.bridge.allowlist")
        rejections.append({"contract": "desktop.bridge.allowlist", "rejected": True})
    else:
        raise ContractViolation("Desktop bridge accepted an unregistered command")

    inventory = DependencyInventory(repo)
    inventory_frontier = "Inventory hoisting, source races, reparse rejection and CLI release receipt need additional real scratch journeys."
    try:
        inventory.build()
    except DependencyInventoryError as exc:
        inventory_frontier = "Current checkout dependency inventory rejected: " + str(exc)
        rejections.append({"area": "dependency-inventory", "rejected": True, "reason": str(exc), "classification": "uncovered-current-failure"})
    else:
        inventory_frontier = "Dependency inventory builds; the ten original cases still require their complete independent scratch journeys."
    return {"area": "proofs-b-desktop", "ok": True, "contracts": sorted({r["contract"] for r in checks}), "checks": checks, "rejections": rejections, "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "frontier": ["75 desktop UI source assertions await rendered behavior and failure journeys.", "Telegram retry/provider and CORS HTTP journeys remain outside local journal proof.", inventory_frontier]}
