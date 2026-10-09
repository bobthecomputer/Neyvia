"""PROOFS-d host invariants and disposable local action procedures."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from .proof_contracts import REPO, ContractViolation

CONTRACTS = ["d.host.event-identity", "d.host.skill-provenance", "d.host.remote-transport",
             "d.host.stage-receipt", "d.host.stage-refusal", "d.host.delta-merge", "d.host.delta-synthesis"]


def require(condition, identity, detail):
    if not condition:
        raise ContractViolation(identity + ": " + detail)


def check_event_identity(before, after):
    for original, row in zip(before["events"], after["events"]):
        if not isinstance(original, dict):
            require(row == original, CONTRACTS[0], "non-event data changed")
            continue
        provided = original.get("eventId") or original.get("event_id")
        if str(provided or "").strip():
            require(row == original, CONTRACTS[0], "caller-supplied identity changed")
            continue
        identity = {"missionId": original.get("missionId") or original.get("mission_id"),
                    "at": original.get("timestamp") or original.get("created_at") or original.get("createdAt") or original.get("at"),
                    "kind": original.get("kind") or original.get("event") or original.get("type"),
                    "actor": original.get("actor") or original.get("agent") or original.get("runtime"),
                    "message": original.get("message") or original.get("detail") or original.get("summary")}
        wanted = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:24]
        require(row.get("eventId") == wanted, CONTRACTS[0], "detail/delta identity differs from canonical event")


def check_skill_catalog(path, payload):
    if Path(path).resolve() != REPO / "config/skills.json":
        return
    expected = {"design_taste_frontend", "premium_product_ui_visuals", "fluxio_supervision_shell",
                "fluxio_human_feel_audit", "user_path_validator"}
    rows = {row["name"]: row for row in payload}
    require(expected <= rows.keys(), CONTRACTS[1], "required design/verification skill missing")
    for name in expected:
        row = rows[name]
        require(bool(row.get("description")) and bool(row.get("action_kinds")) and
                type(row.get("guidance_only")) is bool and type(row.get("execution_capable")) is bool,
                CONTRACTS[1], "catalog provenance/capability fields invalid")


def check_stage_receipt(plan, receipt):
    identity = CONTRACTS[3]
    require(receipt["planHash"] == plan["planHash"], identity, "receipt is not bound to compiled plan")
    ordered = [str(item) for stage in plan["executionStages"] for item in stage["stepIds"]]
    actual = [row["step_id"] for row in receipt["outcomes"]]
    require(actual == ordered[:len(actual)] and len(actual) == len(set(actual)), identity, "merge order differs from compiled stages")
    require(receipt["ultraCompetingCandidates"]["enabled"] is False, identity, "unproven competing candidates enabled")
    require(json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf-8")) == receipt, identity, "durable receipt differs")
    for rollback in receipt["rollbacks"]:
        require(rollback["reason"] == "repair_decreased_verification_score" and
                rollback["decreasedTo"] < receipt["bestVerificationScore"] and
                Path(rollback["receiptPath"]).is_file(), identity, "rollback lost score or receipt")
    completed = [row["step_id"] for row in receipt["outcomes"] if row["ok"] and not row["rolled_back"]]
    require(set(receipt["completedStepIds"]) <= set(completed), identity, "failed/rolled-back step reported complete")


def check_delta_merge(merged, buckets, notes):
    require(all(getattr(merged, key) == list(value.values()) for key, value in buckets.items()) and
            merged.notes == notes and merged.schema == "neyvia.agent_delta.v1", CONTRACTS[5], "stable later-wins delta merge changed")


def check_synthesis(result):
    merged = result["merged"]
    wanted = "blocked" if merged["blockers"] else "conflicted" if merged["conflicts"] else "ready"
    require(result["status"] == wanted and result["transcriptsIncluded"] is False and
            result["ultraCompetingCandidates"]["enabled"] is False and merged["schema"] == "neyvia.agent_delta.v1",
            CONTRACTS[6], "synthesis status, typed delta or proof boundary changed")


def check_context_packet(packet, max_items, max_chars):
    identity = "d.host.selected-context"
    rows = packet["selected"]
    require(packet["schema"] == "neyvia.selected_context_packet.v1" and packet["bounded"] is True and
            packet["itemCount"] == len(rows) and len(rows) <= max_items and sum(len(row["content"]) for row in rows) <= max_chars,
            identity, "context exceeded caller bounds")
    require(packet["sourceIds"] == [row["sourceId"] for row in rows] and
            all(row["contentHash"] == hashlib.sha256(row["content"].encode("utf-8")).hexdigest() for row in rows) and
            packet["contentHash"] == hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            identity, "selected evidence identities or hashes differ")
    imports = sorted({row["importId"] for row in rows if row.get("importId")})
    sources = sorted({row["sourceSha256"] for row in rows if row.get("sourceSha256")})
    require(packet["importIds"] == imports and packet["sourceSha256s"] == sources and
            packet["sourceSha256"] == (sources[0] if len(sources) == 1 else None), identity, "import lineage changed")


def check_nearby_projection(raw, public):
    from .nearby_send import _MAX_PUBLIC_FILES, _MAX_TRANSFER_PARTS
    identity = "d.host.nearby-redaction"
    private = {"recipient", "endpoint", "certificateFingerprint", "sessionId", "token", "path", "ownerPid"}
    def check(value, *, artifact=False):
        if isinstance(value, dict):
            require(not (private - ({"path"} if artifact else set())).intersection(value), identity, "public receipt contains private transport fields")
            if artifact and "path" in value:
                path = Path(str(value["path"]))
                require(not path.is_absolute() and not path.drive and ".." not in path.parts and
                        "\x00" not in str(path), identity, "public artifact path escapes workspace-relative scope")
            for key, item in value.items():
                check(item, artifact=key == "artifacts")
        elif isinstance(value, list):
            for item in value:
                check(item, artifact=artifact)
    check(public)
    files = public.get("files", [])
    raw_files = [row for row in raw.get("files", []) if isinstance(row, dict)]
    require(len(files) == min(len(raw_files), _MAX_PUBLIC_FILES), identity, "public file projection lost its bound")
    require(public["summary"]["filesTruncated"] == max(0, len(raw_files)-_MAX_PUBLIC_FILES), identity, "truncation is not disclosed")
    for row in files:
        ref = row["sourceRef"]
        require(not Path(ref).is_absolute() and ".." not in Path(ref).parts and len(row["fileName"]) <= 260 and
                len(row.get("chunkReceipts", [])) <= _MAX_TRANSFER_PARTS, identity, "source path or chunk projection escapes its bound")


def check_nearby_state(service, state, result):
    identity = "d.host.nearby-recovery"
    recovery = result.get("recovery")
    if recovery == "stale_transfer_recovered":
        require(not result["active"] and result["progress"]["status"] == "interrupted" and
                not service.transfer_claim_path.exists() and not state.get("recipient") and not state.get("sessionId"),
                identity, "stale owner retained activity, claim or transport secrets")
    if recovery in {"corrupt_state_discarded", "invalid_state_discarded"}:
        require(not result["active"] and result["progress"] is None and not service.transfer_claim_path.exists(), identity, "corrupt state kept transfer authority")


def check_nearby_history(result):
    from .nearby_send import _MAX_PUBLIC_HISTORY
    identity = "d.host.nearby-history"
    rows, summary = result["transfers"], result["summary"]
    require(len(rows) <= summary["effectiveLimit"] <= _MAX_PUBLIC_HISTORY and summary["transfers"] == len(rows), identity, "history exceeds its caller/server limit")
    for status in ["completed", "cancelled", "failed", "interrupted"]:
        require(summary[status] == sum(row["status"] == status for row in rows), identity, "history summary does not describe returned rows")


def check_policy_release(owner, before, after):
    require(after == {key: value for key, value in before.items() if key is not owner}, "d.host.policy-owner", "closing one owner changed another owner's policy lifetime")


def check_artifact_row(row, *, approved):
    if approved:
        require(row.get("safeEndpoint") == "/api/artifact" and re.fullmatch(r"/api/artifact\?id=[0-9a-f]{24}", row.get("servedUrl", "")) and
                bool(row.get("mediaType")), "d.host.artifact-serving", "accepted artifact has no safe endpoint/media type")
    else:
        require(not str(row.get("servedUrl") or "").startswith("/api/artifact") and "safeEndpoint" not in row,
                "d.host.artifact-serving", "refused path retained artifact endpoint")


def self_check(root):
    from .web_backend import FluxioWebBackend
    from .skills import SkillRegistry
    from .neyvia_remote import _url, RemoteError
    from .neyvia_stage_scheduler import execute_neyvia_stages, default_step_handler
    from .agent_delta import merge_agent_deltas, synthesize_agent_deltas
    start = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="host-", dir=root))
    cases = []

    def run(name, contracts, action):
        from .contract_gate import wants
        if not wants(contracts):
            return
        try:
            action()
            cases.append({"id": name, "contracts": contracts, "ok": True})
        except Exception as error:
            cases.append({"id": name, "contracts": contracts, "ok": False, "error": str(error)})

    def events():
        event = {"missionId": "proof", "timestamp": "2026-10-03T00:00:00Z", "kind": "artifact_delivered", "actor": "owner", "message": "Delivered receipt"}
        detail = FluxioWebBackend._decorate_mission_events({"events": [event]})
        delta = FluxioWebBackend._decorate_mission_events({"events": [dict(event)]})
        require(detail == delta and re.fullmatch(r"[0-9a-f]{24}", detail["events"][0]["eventId"]), CONTRACTS[0], "detail/delta disagree")
        require("eventId" not in event, CONTRACTS[0], "source event mutated")
        try:
            check_event_identity({"events": [event]}, {"events": [{**event, "eventId": "wrong"}]})
        except ContractViolation:
            return
        raise ValueError("Corrupt event identity escaped host checker")

    def skills():
        registry = SkillRegistry(REPO / "config/skills.json")
        require(any(row.name == "user_path_validator" for row in registry.skills), CONTRACTS[1], "live catalog did not load")
        try:
            check_skill_catalog(REPO / "config/skills.json", [])
        except ContractViolation:
            return
        raise ValueError("Missing catalog provenance escaped host checker")

    def transports():
        keys = ("NEYVIA_REMOTE_PROOF_LOOPBACK", "NEYVIA_REMOTE_PROOF_PORTS")
        previous = {key: os.environ.get(key) for key in keys}
        try:
            os.environ.update(NEYVIA_REMOTE_PROOF_LOOPBACK="1", NEYVIA_REMOTE_PROOF_PORTS=proof_text("48491,48494"))
            require(_url(proof_text("http://127.0.0.1:48491/")) == proof_text("http://127.0.0.1:48491"), CONTRACTS[2], "assigned transport rejected")
            for url in [proof_text("http://127.0.0.1:48492"), proof_text("http://127.0.0.1:48491/api"), proof_text("http://user:secret@127.0.0.1:48491"),
                        proof_text("http://example.com:48491"), proof_text("http://127.0.0.1:48491/?next=1"), proof_text("http://127.0.0.1:48491/#x")]:
                try:
                    _url(url)
                except RemoteError:
                    continue
                raise ValueError("Ungrantable URL accepted")
            os.environ.pop(keys[0])
            try:
                _url(proof_text("http://127.0.0.1:48491"))
            except RemoteError:
                return
            raise ValueError("Loopback admitted without explicit proof authority")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def stages():
        source = 'NEYVIA/1\nGOAL text="Checkpoint receipt"\nBUDGET repairs=2\nLANE worker runtime=neyvia-native model=none effort=none permissions=read\nSTEP initial lane=worker action=checkpoint risk=read\nVERIFY first lane=worker after=initial args=\'{"verificationScore":0.9}\'\nSTEP repair lane=worker action=repair after=first risk=read args=\'{"verificationScore":0.4}\'\nVERIFY final lane=worker after=repair args=\'{"verificationScore":0.9}\'\n'
        receipt = execute_neyvia_stages(scratch, source, mission_id="proof-stage")
        require(receipt["ok"] and receipt["bestVerificationScore"] == .9 and receipt["rollbacks"] and any(row["rolled_back"] for row in receipt["outcomes"]), CONTRACTS[3], "repair regression did not rollback")

    def refusal():
        row = default_step_handler({"step_id": "unknown", "action": "runtime", "arguments": {"runtime": "codex"}}, {})
        require(not row["ok"] and row["metadata"]["error"] == "no_handler" and "runtime" in row["summary"], CONTRACTS[4], "unknown action did not fail closed")

    def progressive_stages():
        from .neyvia_stage_scheduler import build_progressive_step_handler
        from .progressive_tools import ProgressiveToolSpec, ProgressiveToolSurface
        from .orchestration_language import compile_neyvia_program
        folder = scratch / "progressive"
        folder.mkdir()
        (folder / "input.txt").write_text("real workspace content", encoding="utf-8")
        surface = ProgressiveToolSurface()
        surface.register(ProgressiveToolSpec(name="proof.read", description="Read local fixture", category="workspace",
                         annotations={"readOnlyHint": True}), handler=lambda args: {"ok": True, "text": (folder / "input.txt").read_text(encoding="utf-8")})
        def write(args):
            (folder / "written.txt").write_text("approved actual mutation", encoding="utf-8")
            return {"ok": True}
        surface.register(ProgressiveToolSpec(name="proof.write", description="Write local fixture", category="workspace",
                         annotations={"readOnlyHint": False, "requiresApproval": True}), handler=write)
        handler = build_progressive_step_handler(folder, progressive=surface)
        read = handler({"step_id": "read", "action": "tool", "tool": "proof.read", "risk": "read"}, {})
        require(read["ok"] and read["metadata"]["routed"] == "progressive" and read["metadata"]["result"]["text"] == "real workspace content", "d.host.stage-tool-authority", "read dispatch lost workspace content")
        denied = handler({"step_id": "denied", "action": "tool", "tool": "proof.write", "risk": "workspace_write"}, {})
        require(not denied["ok"] and denied["metadata"]["approval_required"] and not (folder / "written.txt").exists(), "d.host.stage-tool-authority", "unapproved write ran")
        accepted = handler({"step_id": "accepted", "action": "tool", "tool": "proof.write", "risk": "workspace_write"}, {"approved": True})
        require(accepted["ok"] and (folder / "written.txt").read_text() == "approved actual mutation", "d.host.stage-tool-authority", "approved write not durable")
        source = 'NEYVIA/1\nGOAL text="Read and verify"\nLANE worker runtime=neyvia-native model=none effort=none permissions=read\nSTEP read lane=worker action=tool tool=proof.read risk=read\nVERIFY check lane=worker after=read args=\'{"verificationScore":1.0}\'\n'
        plan = compile_neyvia_program(source)
        receipt = execute_neyvia_stages(folder, plan, mission_id="proof-simple", step_handler=handler)
        require(receipt["ok"] and receipt["completedStepIds"] == ["read", "check"] and receipt["planHash"] == plan["planHash"], CONTRACTS[3], "compiled stages did not complete")
        barrier = threading.Barrier(2)
        overlaps = []
        def parallel_read(args):
            overlaps.append(threading.get_ident())
            barrier.wait(timeout=3)
            return {"ok": True, "text": (folder / "input.txt").read_text(encoding="utf-8")}
        surface.register(ProgressiveToolSpec(name="proof.parallel", description="Independent file read", category="workspace",
                         annotations={"readOnlyHint": True}), handler=parallel_read)
        source = 'NEYVIA/1\nGOAL text="Parallel workspace reads"\nLANE worker runtime=neyvia-native model=none effort=none permissions=read\nSTEP a lane=worker action=tool tool=proof.parallel risk=read\nSTEP b lane=worker action=tool tool=proof.parallel risk=read\n'
        plan = compile_neyvia_program(source)
        receipt = execute_neyvia_stages(folder, plan, mission_id="proof-parallel", step_handler=handler)
        require(receipt["ok"] and receipt["parallelStagesRun"] >= 1 and receipt["completedStepIds"] == ["a", "b"] and len(set(overlaps)) == 2,
                "d.host.stage-parallel", "independent stages did not overlap and merge deterministically")

    def deltas():
        merged = merge_agent_deltas({"claims": [{"id": "one", "text": "before"}], "evidence": [{"id": "proof", "path": "receipt.json"}]},
                                    {"claims": [{"id": "one", "text": "after"}], "artifacts": [{"path": "artifact.txt"}], "blockers": [{"text": "review"}]})
        require(merged.claims == [{"id": "one", "text": "after"}] and len(merged.evidence) == len(merged.artifacts) == len(merged.blockers) == 1, CONTRACTS[5], "merge lost or reordered evidence")
        synthesis = synthesize_agent_deltas([{"nodeId": "first", "resultSummary": {"delta": {"claims": [{"id": "one", "text": "done"}]}}, "transcript": "PRIVATE_TRANSCRIPT_SENTINEL"},
                                             {"nodeId": "second", "resultSummary": {"delta": {"conflicts": [{"text": "scope"}]}}}])
        require(synthesis["status"] == "conflicted" and "PRIVATE_TRANSCRIPT_SENTINEL" not in json.dumps(synthesis) and "first" in synthesis["byNode"], CONTRACTS[6], "transcript included or conflict lost")

    def context_packets():
        from .neyvia_runtime_invocation import build_selected_context_packet, validate_route_selection
        source = [{"sourceId": "selected-evidence", "kind": "imported-context", "content": "Evidence " * 2000,
                   "importId": "local-import", "sourceSha256": "a" * 64}]
        packet = build_selected_context_packet(source, max_chars=80)
        repeated = build_selected_context_packet(source, max_chars=80)
        require(packet == repeated and packet["sourceIds"] == ["selected-evidence"] and packet["importIds"] == ["local-import"] and
                packet["sourceSha256"] == "a" * 64 and len(packet["selected"][0]["content"]) == 80,
                "d.host.selected-context", "bounded packet lost import lineage")
        require(build_selected_context_packet([])["sourceIds"] == [] and validate_route_selection(
                {"runtimeId": "codex", "provider": "openai-codex", "model": "gpt-5.6-sol", "effort": "ultra"}, runtime="codex")["ok"],
                "d.host.selected-context", "empty selection or route shape rejected")
        try:
            check_context_packet({**packet, "contentHash": "bad"}, 16, 80)
        except ContractViolation:
            return
        raise ValueError("Corrupt context hash escaped host contract")

    def nearby_local_state():
        from .nearby_send import NearbySendService, NEARBY_TRANSFER_STATE_SCHEMA, NEARBY_TRANSFER_RECEIPT_SCHEMA
        folder = scratch / "nearby"
        folder.mkdir()
        service = NearbySendService(folder)
        service.nearby_root.mkdir(parents=True, exist_ok=True)
        state = {"schema": NEARBY_TRANSFER_STATE_SCHEMA, "transferId": "stale", "status": "uploading", "active": True,
                 "ownerPid": 2_000_000_000, "recipient": {"endpoint": "https://private.invalid"}, "sessionId": "private-session", "files": [], "summary": {}}
        service.active_state_path.write_text(json.dumps(state), encoding="utf-8")
        service.transfer_claim_path.write_text(json.dumps({"transferId": "stale", "ownerPid": state["ownerPid"]}), encoding="utf-8")
        recovered = NearbySendService(folder).get_active_transfer()
        require(recovered.get("recovery") == "stale_transfer_recovered" and "private-session" not in json.dumps(recovered), "d.host.nearby-recovery", "stale local transfer not recovered")
        service.active_state_path.write_text("{broken", encoding="utf-8")
        require(service.get_active_transfer().get("recovery") == "corrupt_state_discarded", "d.host.nearby-recovery", "corrupt state not recovered")
        service.receipt_root.mkdir(parents=True, exist_ok=True)
        files = [{"fileId": str(i), "fileName": f"{i}.txt", "path": str(folder / "private.txt"),
                  "sourceRef": "safe/receipt.txt" if i == 0 else "../private.txt", "size": 1, "sha256": "a"*64} for i in range(105)]
        receipt = {"schema": NEARBY_TRANSFER_RECEIPT_SCHEMA, "receiptId": "nearby_receipt_000", "transferId": "transfer", "status": "completed", "ok": True,
                   "recipient": {"endpoint": "https://private.invalid"}, "sessionId": "private-session", "files": files,
                   "summary": {"fileCount": 105, "totalBytes": 105}, "cancellation": {}}
        public = service._public_receipt(receipt, artifacts=True)
        require(public["artifacts"] and all(not Path(row["path"]).is_absolute() for row in public["artifacts"]),
                "d.host.nearby-redaction", "workspace-relative receipt artifacts were lost")
        altered = json.loads(json.dumps(public))
        altered["artifacts"][0]["path"] = str(folder / "private.txt")
        try:
            check_nearby_projection(receipt, altered)
        except ContractViolation:
            pass
        else:
            raise ValueError("Absolute public artifact escaped redaction contract")
        for i in range(105):
            service.receipt_root.joinpath(f"nearby_receipt_{i:03d}.json").write_text(json.dumps({**receipt,"receiptId":f"nearby_receipt_{i:03d}"}), encoding="utf-8")
        history = service.list_transfer_history(limit=500)
        require(len(history["transfers"]) == 100 and history["transfers"][0]["summary"]["filesTruncated"] == 5 and
                "private-session" not in json.dumps(history) and str(folder / "private.txt") not in json.dumps(history), "d.host.nearby-redaction", "history lost redaction/bounds")
        service.active_state_path.write_text(json.dumps({**state, "ownerPid": os.getpid(), "files": files}), encoding="utf-8")
        progress = service.get_active_transfer()
        require(progress["active"] and len(progress["progress"]["files"]) == 100 and progress["progress"]["summary"]["filesTruncated"] == 5,
                "d.host.nearby-redaction", "live projection lost file limit")
        service = NearbySendService(scratch / "corrupt-history")
        service.receipt_root.mkdir(parents=True, exist_ok=True)
        service.receipt_root.joinpath("nearby_receipt_corrupt.json").write_text("{broken", encoding="utf-8")
        history = service.list_transfer_history(limit=10)
        require(history["transfers"] == [] and history["summary"]["skippedInvalidReceipts"] == 1, "d.host.nearby-history", "corrupt history was not skipped")
        try:
            service.list_transfer_history(limit="many")
        except ValueError:
            return
        raise ValueError("Invalid history limit accepted")

    def settings_policy_lifetime():
        import socket
        from . import local_network_policy as policy
        from .neyvia_workspace_tools import WorkspaceTools, workspace_for
        from .neyvia_settings import get, update, SettingsConflict
        from .connected_sessions.claude_terminal import spawn_terminal
        folder = scratch / "policy"
        first, second = workspace_for(folder), WorkspaceTools(folder)
        try:
            ready = threading.Event()
            def create_socket():
                with socket.socket():
                    ready.set()
            with policy.child_start():
                worker = threading.Thread(target=create_socket)
                worker.start()
                require(ready.wait(2), "d.host.policy-startup", "pending child prevented socket worker startup")
                try:
                    with policy.transition(True):
                        pass
                except SettingsConflict:
                    pass
                else:
                    raise ValueError("Local-only activation raced pending child startup")
            worker.join(2)
            require(not worker.is_alive(), "d.host.policy-startup", "socket worker did not stop")
            missing = folder / "removed-root"
            policy.install(missing)
            live = folder / "live-root"
            live.mkdir(parents=True)
            policy.install(live)
            policy.enabled()
            require(missing not in policy._roots and live in policy._roots, "d.host.policy-root", "removed/live root lifetime differs")
            saved = update(first, {"localOnly": True}, get(first)["revision"])
            require(policy._owners[first] == first.bus.root, "d.host.policy-owner", "Settings did not register current owner")
            try:
                spawn_terminal(["must-not-run"], str(folder), {})
            except policy.LocalOnlyError:
                pass
            else:
                raise ValueError("Native terminal launched in local-only mode")
            first.close()
            require(policy.enabled(), "d.host.policy-owner", "remaining owner lost persisted policy")
            second.close()

            require(not policy.enabled(), "d.host.policy-owner", "closed owners kept imposing policy")
            reopened = workspace_for(folder)
            try:
                require(reopened is not first and not reopened.closed.is_set() and get(reopened)["settings"]["localOnly"] and policy.enabled(),
                        "d.host.policy-owner", "reopened owner ignored persistent setting")
                update(reopened, {"localOnly": False}, saved["revision"])
            finally:
                reopened.close()
        finally:
            # Reversible scratch policy cleanup even after an adverse observation.
            service = workspace_for(folder)
            if get(service)["settings"]["localOnly"]:
                update(service, {"localOnly": False}, get(service)["revision"])
            service.close()
            first.close()
            second.close()

    def artifact_serving():
        folder = scratch / "artifacts"
        folder.mkdir()
        artifact = folder / ".agent_control/mission_artifacts/proof/report.pdf"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"%PDF-1.4\n")
        backend = FluxioWebBackend(folder, folder)
        allowed = backend._decorate_mission_artifacts({"artifacts": [{"path": str(artifact), "label": "Report"}]})
        row = allowed["artifacts"][0]
        require(row["safeEndpoint"] == "/api/artifact" and row["mediaType"] == "application/pdf", "d.host.artifact-serving", "registered PDF not served safely")
        outside = scratch / "outside.pdf"
        outside.write_bytes(b"%PDF-1.4\n")
        denied = backend._decorate_mission_artifacts({"artifacts": [{"path": str(outside), "servedUrl": "/api/artifact?id=" + "0"*24, "safeEndpoint": "/api/artifact"}]})["artifacts"][0]
        require(denied["servedUrl"] == "" and "safeEndpoint" not in denied and denied["path"] == str(outside), "d.host.artifact-serving", "outside path kept serving authority")

    run("stable-event-identity", [CONTRACTS[0]], events)
    run("live-skill-catalog", [CONTRACTS[1]], skills)
    run("scoped-remote-url-refusals", [CONTRACTS[2]], transports)
    run("durable-stage-checkpoint-rollback", [CONTRACTS[3]], stages)
    run("unknown-executable-refused", [CONTRACTS[4]], refusal)
    run("typed-delta-merge-synthesis", CONTRACTS[5:], deltas)
    run("progressive-real-file-authority-and-parallel-stages", [CONTRACTS[3], "d.host.stage-tool-authority", "d.host.stage-parallel"], progressive_stages)
    run("bounded-import-lineage-context", ["d.host.selected-context"], context_packets)
    run("nearby-durable-recovery-redacted-bounded-history", ["d.host.nearby-recovery", "d.host.nearby-redaction", "d.host.nearby-history"], nearby_local_state)
    run("settings-real-owner-lifetime-child-start-and-socket-worker", ["d.host.policy-owner", "d.host.policy-root", "d.host.policy-startup"], settings_policy_lifetime)
    run("artifact-gate-safe-url-and-outside-refusal", ["d.host.artifact-serving"], artifact_serving)
    return {"ok": all(row["ok"] for row in cases), "contracts": CONTRACTS + ["d.host.stage-tool-authority", "d.host.stage-parallel", "d.host.selected-context", "d.host.nearby-recovery", "d.host.nearby-redaction", "d.host.nearby-history", "d.host.policy-owner", "d.host.policy-root", "d.host.policy-startup", "d.host.artifact-serving"], "cases": cases,
            "failures": [row for row in cases if not row["ok"]], "scratchRoot": str(scratch), "durationMs": round((time.perf_counter()-start)*1000)}
