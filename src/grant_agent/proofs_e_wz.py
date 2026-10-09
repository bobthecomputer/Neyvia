"""Contracts at authentication, background process, repair and source boundaries."""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proof_ports import proof_port, proof_text

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

def require(condition, contract, detail):
    if not condition:
        from .proof_contracts import ContractViolation
        raise ContractViolation(f"{contract}: {detail}")


def check_session_lookup(db, token_hash, previous, expected, now, ttl, renewed, updated):
    stored = db.execute("SELECT identity_hash,username,display_name,role,created_at,expires_at,last_seen FROM web_auth_sessions WHERE token_hash=?", (token_hash,)).fetchone()
    wanted = (expected if updated else previous[0], *previous[1:5], now + ttl if renewed else previous[5], now if updated else previous[6])
    require(stored == wanted, "proofs-e-wz.auth-renewal", "session identity, expiry or last-use persistence differs from the accepted lookup")


def check_session_rejected(db, token_hash):
    require(db.execute("SELECT 1 FROM web_auth_sessions WHERE token_hash=?", (token_hash,)).fetchone() is None,
            "proofs-e-wz.auth-rejection", "expired or invalid session remained persisted")


def session_snapshot(db):
    return {row[0]: tuple(row[1:]) for row in db.execute("SELECT token_hash,identity_hash,username,display_name,role,created_at,expires_at,user_agent,address,last_seen FROM web_auth_sessions")}


def check_session_issued(db, token_hash, expected, live_before):
    stored = session_snapshot(db)
    require(len(token_hash) == 64 and stored == {**live_before, token_hash: tuple(expected)},
            "proofs-e-wz.auth-issuance", "session issuance lost another live session or persisted incorrect identity")


def check_hidden_kwargs(payload, windows, group):
    if not windows:
        require(payload == {}, "proofs-e-wz.hidden-options", "non-Windows spawn received Windows options")
        return
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    wanted = no_window | (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if group else 0)
    require(payload.get("creationflags") == wanted and bool(no_window), "proofs-e-wz.hidden-options", "background spawn lacks the required no-window flags")
    startup = payload.get("startupinfo")
    if startup is not None:
        require(startup.wShowWindow == getattr(subprocess, "SW_HIDE", 0) and startup.dwFlags & getattr(subprocess, "STARTF_USESHOWWINDOW", 0),
                "proofs-e-wz.hidden-options", "background startup info can display a console")


def check_spawn_flags(original_args, original_kwargs, args, kwargs, no_window):
    if len(original_args) > 13:
        require(args == original_args and kwargs == original_kwargs, "proofs-e-wz.hidden-default", "explicit positional creation flags were changed")
    else:
        wanted = original_kwargs.get("creationflags") or no_window
        require(kwargs == {**original_kwargs, "creationflags": wanted} and args == original_args,
                "proofs-e-wz.hidden-default", "missing flags must hide the child while explicit flags remain intact")


def check_hidden_install(previous, current, windows, active):
    if windows:
        require(active is True and getattr(current, "_neyvia_hidden_default", False),
                "proofs-e-wz.hidden-default", "Windows hidden default is not installed")
        if getattr(previous, "_neyvia_hidden_default", False):
            require(current is previous, "proofs-e-wz.hidden-default", "repeat installation changed the wrapper")
    else:
        require(active is False and current is previous, "proofs-e-wz.hidden-default", "non-Windows installation modified Popen")


def check_following(snapshot, max_accounts, pages=None):
    accounts = snapshot["accounts"]
    handles = [item["screenName"].casefold() for item in accounts]
    require(snapshot["accountCount"] == len(accounts) and 0 < len(accounts) <= max_accounts and len(handles) == len(set(handles)),
            "proofs-e-wz.x-following", "following results are unbounded, duplicated or have an incorrect count")
    require(snapshot["authentication"] == "none" and snapshot["cost"] == "free_no_key" and snapshot["sourceUrls"]
            and all(url.startswith("https://") for url in snapshot["sourceUrls"]), "proofs-e-wz.x-following", "source access provenance is missing")
    require(snapshot["truncated"] == (snapshot["paginationStopReason"] != "exhausted") and
            (snapshot["paginationStopReason"] != "exhausted" or not snapshot["nextCursorAvailable"]),
            "proofs-e-wz.x-following", "pagination status contradicts exhaustion")
    if pages is not None:
        from .x_following_sources import _profile_row
        expected, seen = [], set()
        for payload, url in pages:
            for item in payload["results"]:
                if not isinstance(item, dict):
                    continue
                try:
                    row = _profile_row(item)
                except ValueError:
                    continue
                key = row["screenName"].casefold()
                if key not in seen:
                    seen.add(key)
                    expected.append(row)
        require(accounts == expected[:max_accounts] and snapshot["sourceUrls"] == [url for payload, url in pages],
                "proofs-e-wz.x-following", "following projection lost/reordered provider rows or pagination source evidence")


def check_source_bundle(bundle):
    following, timelines, failures, summary = bundle["following"], bundle["timelines"], bundle["failures"], bundle["summary"]
    public = {row["screenName"].casefold() for row in following["accounts"] if not row["protected"]}
    successes = [row["screenName"].casefold() for row in timelines]
    failed = [row["screenName"].casefold() for row in failures]
    require(len(successes + failed) == len(public) and set(successes + failed) == public,
            "proofs-e-wz.x-public-timelines", "protected accounts were requested or public requests are missing/duplicated")
    wanted = {"followingAccounts": len(following["accounts"]), "protectedAccounts": len(following["accounts"]) - len(public),
              "timelinesRequested": len(public), "timelinesSucceeded": len(timelines), "timelinesFailed": len(failures),
              "postsCollected": sum(len(row["entries"]) for row in timelines)}
    require(summary == wanted, "proofs-e-wz.x-public-timelines", "summary differs from actual following/timeline data")


def check_source_artifacts(folder, files, manifest, receipt):
    require(sorted(row["path"] for row in manifest["artifacts"]) == sorted(files) and
            manifest["status"] == ("collected" if files["recent_posts.json"]["summary"]["timelinesSucceeded"] else "blocked"),
            "proofs-e-wz.x-artifacts", "manifest omits source files or misstates collection status")
    for artifact in manifest["artifacts"]:
        path = folder / artifact["path"]
        content = path.read_bytes()
        require(json.loads(content) == files[path.name] and artifact["bytes"] == len(content) and artifact["sha256"] == hashlib.sha256(content).hexdigest(),
                "proofs-e-wz.x-artifacts", "persisted source bytes or their manifest hash differ")
    path = Path(receipt["manifestPath"])
    require(json.loads(path.read_text(encoding="utf-8")) == manifest and hashlib.sha256(path.read_bytes()).hexdigest() == receipt["manifestSha256"],
            "proofs-e-wz.x-artifacts", "manifest persistence or receipt digest differs")


def check_repair(receipt, path=None):
    bounds, proof, phases = receipt["bounds"], receipt["proof"], receipt["phases"]
    from .self_repair import MAX_REPAIR_ATTEMPTS
    require(0 <= bounds["attemptsUsed"] <= bounds["maxAttempts"] <= MAX_REPAIR_ATTEMPTS,
            "proofs-e-wz.repair-bounds", "repair exceeded the hard attempt cap")
    changed = sorted(key for key in set(proof["trackedBefore"]) | set(proof["trackedAfter"])
                     if proof["trackedBefore"].get(key) != proof["trackedAfter"].get(key))
    require(proof["trackedPathChanges"] == changed, "proofs-e-wz.repair-receipt", "tracked changes contradict before/after hashes")
    if receipt["status"] == "blocked":
        require(receipt["stopReason"] == "invalid_repair_contract" and receipt["contractError"] and not phases and not proof["finalVerificationPassed"],
                "proofs-e-wz.repair-blocked", "invalid request executed phases or claimed verification")
    else:
        require(bounds["maxAttempts"] == max(1, min(MAX_REPAIR_ATTEMPTS, bounds["requestedMaxAttempts"])),
                "proofs-e-wz.repair-bounds", "hard attempt cap differs from normalized request")
        detects = [phase for phase in phases if phase["phase"] == "detect"]
        repairs = [phase for phase in phases if phase["phase"] == "repair"]
        verifies = [phase for phase in phases if phase["phase"] == "verify"]
        require(len(detects) == 1 and proof["initialDetectionFailed"] == (not detects[0]["ok"]) and
                proof["repairCommandPassed"] == any(phase["ok"] for phase in repairs),
                "proofs-e-wz.repair-receipt", "phase outcomes contradict the receipt")
        require(len(repairs) == bounds["attemptsUsed"] and len(verifies) <= len(repairs), "proofs-e-wz.repair-bounds", "phase count differs from attempts")
        proven = detects[0]["ok"] or any(phase["ok"] for phase in verifies)
        require(proof["finalVerificationPassed"] == proven and (receipt["status"] == "completed") == proven,
                "proofs-e-wz.repair-receipt", "completion lacks a passed real detection or verification")
        if not proven:
            require(bounds["attemptsUsed"] == bounds["maxAttempts"] and receipt["stopReason"] == "verification_not_proven",
                    "proofs-e-wz.repair-bounds", "failed repair did not consume exactly its bounded attempts")
    if path is not None:
        require(json.loads(Path(path).read_text(encoding="utf-8")) == receipt, "proofs-e-wz.repair-receipt", "durable repair receipt differs from returned result")


def check_worker_repair(registry, job, result):
    stored = registry.get_job(job["jobId"])
    require(stored["status"] == result["status"], "proofs-e-wz.worker-repair", "worker completion status was not persisted")
    kinds = {event["kind"] for event in registry.list_events(job_id=job["jobId"], limit=100)}
    require({event["kind"] for event in result.get("phaseEvents", [])} <= kinds,
            "proofs-e-wz.worker-repair", "worker phase events were not persisted")
    if result["status"] == "completed":
        require("job.completed" in kinds, "proofs-e-wz.worker-repair", "successful worker completion did not record its job event")
    with registry._connect() as db:
        artifacts = db.execute("SELECT kind,path FROM artifacts WHERE job_id=?", (job["jobId"],)).fetchall()
    require(any(row["kind"] == "self_repair_receipt" and row["path"] == result["repairReceiptPath"] for row in artifacts),
            "proofs-e-wz.worker-repair", "worker did not register its durable repair receipt")


def check_json_response(handler, payload, logical_body, body, gzipped, threshold, accepted):
    import gzip
    require(gzipped == (len(logical_body) >= threshold and accepted) and
            (gzip.decompress(body) if gzipped else body) == logical_body,
            "proofs-e-wz.http-json", "wire JSON changed or compression ignores negotiated size/encoding")
    require(b"\n  " not in logical_body, "proofs-e-wz.http-json", "JSON transport must remain compact")
    require(handler.protocol_version == "HTTP/1.1", "proofs-e-wz.http-json", "HTTP response transport is not HTTP/1.1")


def check_request_body(raw, limit, compressed):
    if compressed:
        require(len(raw) <= limit, "proofs-e-wz.http-request", "decompressed request exceeded its bounded allocation")


def check_io_timeout(handler, timeout):
    require(handler.connection.gettimeout() == timeout, "proofs-e-wz.http-io-timeout", "request transfer retained the short accept timeout")


def check_conversation_session(output, session, turns, returned, if_revision):
    stable = {key: value for key, value in (session or {}).items() if key not in {"createdAt", "updatedAt"}}
    revision = hashlib.sha1(json.dumps([stable, returned], separators=(",", ":"), default=str).encode("utf-8", "replace"), usedforsecurity=False).hexdigest()
    require(output["revision"] == revision and output["totalTurns"] == len(turns), "proofs-e-wz.conversation-revision", "revision or total differs from persisted semantic session/turns")
    if str(if_revision or "") == revision:
        require(output.get("notModified") is True and "turns" not in output and "session" not in output,
                "proofs-e-wz.conversation-revision", "unchanged revision echoed the transcript")
    else:
        require("notModified" not in output and output["session"] == session and output["turns"] == returned and output["returnedTurns"] == len(returned) and output["hasEarlierTurns"] == (len(returned) < len(turns)),
                "proofs-e-wz.conversation-revision", "changed revision did not return exactly the selected session page")


def check_conversation_save(state, output, payload):
    source = payload if isinstance(payload, dict) else {}
    incoming = source["state"] if isinstance(source.get("state"), dict) else source
    mode = str(incoming.get("storageMode") or incoming.get("storage_mode") or source.get("storageMode") or source.get("storage_mode") or "auto").strip().lower().replace("_", "-")
    expected_mode = "nas" if mode in {"nas", "web", "shared", "remote"} else ("local" if mode in {"local", "this-device", "device"} else "auto")
    active = str(incoming.get("activeChatSessionId") or incoming.get("active_chat_session_id") or "").replace("\x00", "").strip()[:160]
    require(state["storageMode"] == expected_mode and state["activeChatSessionId"] == active,
            "proofs-e-wz.conversation-save", "save changed selected storage marker or active session identity")
    if isinstance(payload, dict) and payload.get("returnState") is False:
        require(output.get("schema") == "fluxio.conversation_state_receipt.v1" and output.get("saved") is True and
                output.get("sessionCount") == len(state.get("chatSessions") or []) and output.get("transcriptCount") == len(state.get("chatSessionTranscripts") or {}) and "chatSessionTranscripts" not in output,
                "proofs-e-wz.conversation-save", "receipt-only save echoes state or has inaccurate counts")
    else:
        require(output == state, "proofs-e-wz.conversation-save", "full save response differs from its persisted normalized state")


def check_conversation_persistence(path, state):
    require(json.loads(path.read_text(encoding="utf-8")) == state, "proofs-e-wz.conversation-save", "saved chat state differs from its durable bytes")
    for turns in state.get("chatSessionTranscripts", {}).values():
        timestamps = [str(turn.get("createdAt") or "") for turn in turns]
        require(timestamps == sorted(timestamps), "proofs-e-wz.conversation-save", "persisted chat turns lost chronological order")


def check_conversation_bootstrap(output, state, requested, limit):
    transcripts = state.get("chatSessionTranscripts") or {}
    selected = list(transcripts.get(requested) or [])[-limit:] if requested else []
    expected_index = {identity: {"turnCount": len(turns), "lastTurnAt": str((turns[-1] if turns else {}).get("createdAt") or "")} for identity, turns in transcripts.items() if isinstance(turns, list)}
    require(output["summaryMode"] == "bootstrap" and output["chatSessions"] == state["chatSessions"] and output["chatSessionTranscripts"] == ({requested: selected} if requested and selected else {}) and
            output["transcriptIndex"] == expected_index and output["hydratedSessionIds"] == ([requested] if requested else []),
            "proofs-e-wz.conversation-bootstrap", "bootstrap omitted the index or eagerly returned unselected history")
    expected = {"schema": "fluxio.conversation_bootstrap_performance.v1", "sessionCount": len(state["chatSessions"]), "transcriptCount": len(transcripts),
                "returnedTranscriptCount": int(bool(requested and selected)), "returnedTurnCount": len(selected), "turnLimit": limit, "detailCommand": "get_conversation_session_state_command"}
    require(output["performance"] == expected, "proofs-e-wz.conversation-bootstrap", "bootstrap counts or lazy detail command differ")


def check_chat_route(payload, output):
    requested = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    provider = str(requested.get("provider") or payload.get("provider") or "openai-codex").strip()
    raw_model = str(requested.get("model") or payload.get("model") or "").strip()
    if provider == "opencode-go" and raw_model:
        expected = raw_model
        for prefix in ("opencode-go/", "openrouter/z-ai/", "z-ai/"):
            if expected.startswith(prefix):
                expected = expected[len(prefix):]
        if expected in {"glm-5.2", "minimax-m3", "qwen3.7-max"}:
            require(output["provider"] == provider and output["model"] == expected and output["model_id"] == provider+"/"+expected,
                    "proofs-e-wz.chat-route", "OpenCode Go route changed provider or retained a redundant provider/catalog prefix")
    runtime = str(payload.get("runtime") or payload.get("runtimeId") or requested.get("runtimeId") or "").strip().lower()
    if runtime not in {"opencode", "open-code", "opencode-native", "opencode-go"} and provider == "opencon-pro" and raw_model.lower() == "glm-5.2":
        require(output["provider"] == "openrouter" and output["model"] == "z-ai/glm-5.2" and output["model_id"] == "openrouter/z-ai/glm-5.2",
                "proofs-e-wz.chat-route", "OpenCon GLM route did not preserve the canonical OpenRouter model")


def check_static_response(root, target, body, origin, cors, allowed_origins, cache_control, frame_options, query):
    target.resolve().relative_to(root.resolve())
    require(cors == (origin in allowed_origins and target.name != "index.html"), "proofs-e-wz.desktop-shell", "desktop CORS permission includes a page/foreign origin or excludes an interface asset")
    require(body == target.read_bytes(), "proofs-e-wz.desktop-shell", "served static bytes differ from selected file")
    if target.name in {"index.html", "service-worker.js"}:
        require(cache_control == "no-store", "proofs-e-wz.desktop-shell", "entry page or service worker was browser-cached")
    if target.name == "index.html":
        embedded = (query.get("embedded") or [""])[0]
        require(frame_options == ("SAMEORIGIN" if embedded in {"browser-proof", "fluxio-browser"} else "DENY"),
                "proofs-e-wz.desktop-shell", "page framing permission differs from supported embed mode")


def check_update_response(folder, target, body, pattern):
    target.resolve().relative_to(folder.resolve())
    require(pattern.fullmatch(target.name) and target.is_file() and body == target.read_bytes(),
            "proofs-e-wz.desktop-update", "update response is outside its folder/allowlist or has changed bytes")


def check_artifact_access(backend, handler):
    require(backend.is_authenticated(handler), "proofs-e-wz.auth-artifact", "private artifact bytes would be served without a live session")


def check_capture_failure(failure, pid, started_at):
    require(getattr(failure, "process_id", None) == pid and isinstance(pid, int) and pid > 0 and
            type(getattr(failure, "elapsed_ms", None)) is int and failure.elapsed_ms >= 0 and
            getattr(failure, "started_at", "") == started_at and getattr(failure, "ended_at", "") >= started_at,
            "proofs-e-wz.capture-failure", "failure lost invocation process identity or measured timing")


def check_terminal_text(value, result):
    from .web_backend import ANSI_ESCAPE_PATTERN
    source = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    require(result == ANSI_ESCAPE_PATTERN.sub("", source).replace("\r\n", "\n").replace("\r", "\n"),
            "proofs-e-wz.terminal-text", "terminal cleaning lost readable bytes or kept ANSI/CR sequences")


def check_workflow_budget(payload, result):
    seconds = int(payload.get("runtimeSeconds", 180))
    require(120 <= seconds <= 1800 and result["preset"]["runtimeSeconds"] == seconds and
            all(task["teamContract"]["budget"]["runtimeSeconds"] == seconds for task in result["tasks"]),
            "proofs-e-wz.workflow-budget", "workflow stages did not freeze the selected bounded runtime budget")


def check_model_message(selected, command):
    import re
    collapsed = " ".join(selected.split())
    command_text = " ".join(str(command or "").split())
    trace = re.compile(r"^(?:(?:command|feedback|response|reply)\s*:?\s+)?(?:/volume\d+/|[A-Z]:\\|wsl\s+|python\s+-m\s+|node\s+|npm\s+|pnpm\s+|yarn\s+|hermes\s+|opencode\s+|openclaw\s+|codex\s+)", re.I)
    require(not selected or (collapsed != command_text and not trace.search(collapsed)),
            "proofs-e-wz.assistant-selection", "command trace was presented as an assistant answer")


def check_chat_compartment(compartment, payload, result, previous_messages, path):
    receipt = compartment["turnReceipt"]
    assistant = str(receipt["assistantMessage"] or "").strip()
    check_model_message(assistant, receipt["command"])
    require(receipt["finalMessage"] == receipt["assistantMessage"], "proofs-e-wz.assistant-selection", "final answer differs from selected assistant message")
    expected = list(previous_messages)
    operator = str(payload.get("message") or "").strip()
    if operator:
        expected.append({"role": "operator", "text": operator, "source": "operator-submitted"})
    if assistant:
        expected.append({"role": "assistant", "text": assistant, "source": "backend-model-message"})
    projection = lambda rows: [{key: item.get(key) for key in ("role", "text", "source")} if isinstance(item, dict) else item for item in rows]
    require(projection(compartment["messages"]) == projection(expected[-40:]),
            "proofs-e-wz.chat-recording", "persisted message window lost an operator/selected assistant or included a trace answer")
    kinds = [item.get("kind") for item in compartment["toolTimeline"] if isinstance(item, dict)]
    raw = str(result.get("reply") or result.get("message") or "").strip()
    if assistant:
        require("runtime.model_message" in kinds, "proofs-e-wz.chat-recording", "model message was not recorded in the activity timeline")
    elif raw:
        require("runtime.trace_only_reply" in kinds, "proofs-e-wz.chat-recording", "command-only reply lost its trace activity event")
    for key in ("modelMessageSource", "modelMessageSourceLabel", "modelMessageSourceTitle", "modelMessageSourceId", "transcriptSessionId"):
        prior = result.get("turnReceipt") if isinstance(result.get("turnReceipt"), dict) else {}
        require(receipt[key] == (prior.get(key) or str(result.get(key) or "")), "proofs-e-wz.chat-recording", "model answer provenance changed during recording")
    require(json.loads(path.read_text(encoding="utf-8")) == compartment, "proofs-e-wz.chat-recording", "durable compartment differs from delivered recording")


def check_humanized_message(lines, headline, facts, route, output):
    require(output.startswith("OpenRuntime returned a real result for this mission") and
            (not headline or headline in output) and all(fact in output for fact in facts) and (not route or route in output),
            "proofs-e-wz.assistant-selection", "humanized runtime summary lost its supplied headline/facts/route")
    import re
    artifact_lines = [line for line in lines if re.match(r"^(?:artifact|preview url|command|status)\s*:", line, re.I) or re.match(r"^(?:/volume\d+/|https?://|/api/artifact\b)", line, re.I)]
    require(all(line not in output.splitlines() for line in artifact_lines), "proofs-e-wz.assistant-selection", "humanized summary includes raw artifact/path metadata")


def self_check_chat_recording(root):
    from .web_backend import FluxioWebBackend
    folder = Path(root) / "recording"
    folder.mkdir()
    backend = FluxioWebBackend(folder, folder)
    route = {"provider": "minimax-oauth", "model": "MiniMax-M3", "effort": "high"}
    command = "/volume1/Saclay/projects/system-loss/bin/ms-one-shot execute model mission"
    for index, field in enumerate(({"message": command}, {"reply": "Command: "+command}, {"reply": "Command "+command})):
        compartment = backend._save_chat_compartment({"sessionId": f"trace-{index}", "message": "Run this.", "runtime": "hermes", "route": route},
            {**field, "sessionId": f"trace-{index}", "runtime": "hermes", "command": command, "result_summary": "Delegated runtime lane launched.", "elapsedMs": 80, "filesChanged": [], "toolTimeline": [], "route": route})
        receipt = compartment["turnReceipt"]
        require(receipt["assistantMessage"] == receipt["finalMessage"] == "" and receipt["runSummary"] == "Delegated runtime lane launched." and command == receipt["command"] and
                [row["role"] for row in compartment["messages"]] == ["operator"] and "runtime.trace_only_reply" in [row["kind"] for row in compartment["toolTimeline"]],
                "proofs-e-wz.chat-recording", "command-only recording invented an assistant answer")
    answer = "Implemented and verified the recording fix."
    for index, previous_receipt in enumerate(({}, {"assistantMessage": command})):
        result = {"turnReceipt": previous_receipt, "sessionId": f"answer-{index}", "openRuntimeMessage": answer, "reply": command, "command": command, "runtime": "hermes", "elapsedMs": 80,
                  "modelMessageSource": "runtime_transcript", "modelMessageSourceLabel": "Runtime output artifact", "modelMessageSourceTitle": "What changed in this resume", "transcriptSessionId": "runtime_artifact", "filesChanged": [], "toolTimeline": [], "route": route}
        compartment = backend._save_chat_compartment({"sessionId": f"answer-{index}", "message": "Show the recorded answer", "runtime": "hermes", "route": route}, result)
        require(compartment["turnReceipt"]["assistantMessage"] == answer and compartment["messages"][-1]["text"] == answer and compartment["messages"][-1]["source"] == "backend-model-message",
                "proofs-e-wz.assistant-selection", "recording did not prefer usable model output over command text")
    result = {"sessionId": "humanized", "runtime": "hermes", "command": command, "elapsedMs": 80, "filesChanged": [], "toolTimeline": [], "route": route,
              "openRuntimeMessage": "Telemetry board\nArtifact: /volume1/Saclay/private/index.html\nPreview URL: /api/artifact?path=fixture\nRoute: Hermes harness; executor route preserved.\nFastest lap: ARO L3 83.140s."}
    compartment = backend._save_chat_compartment({"sessionId": "humanized", "message": "Read the recorded result", "runtime": "hermes", "route": route}, result)
    answer = compartment["turnReceipt"]["assistantMessage"]
    require("OpenRuntime returned a real result" in answer and "Fastest lap" in answer and "/volume1/Saclay" not in answer and "/api/artifact" not in answer and compartment["messages"][-1]["text"] == answer,
            "proofs-e-wz.assistant-selection", "artifact-shaped recording was not humanized without path noise")
    try:
        check_model_message("Command: "+command, command)
    except ValueError:
        pass
    else:
        raise ValueError("mutated command-as-answer accepted")


def self_check_capture(root):
    from .web_backend import _run_process_capture, _clean_terminal_text
    from .efficient_workflow import build_efficient_workflow
    folder = Path(root) / "capture"
    folder.mkdir()
    for command, timeout, expected in [([sys.executable, "-I", "-c", "import time; time.sleep(30)"], 1, "timed out after 1 seconds"),
                                      ([sys.executable, "-I", "-c", "import sys; print('boom',file=sys.stderr); sys.exit(3)"], 5, "boom")]:
        try:
            _run_process_capture(command, cwd=folder, timeout=timeout)
        except RuntimeError as exc:
            require(expected in str(exc) and exc.elapsed_ms > 0 and exc.process_id > 0 and exc.started_at and exc.ended_at >= exc.started_at,
                    "proofs-e-wz.capture-failure", "real runtime failure did not retain timing/pid or readable reason")
        else:
            raise ValueError("failed real child returned success")
    require(_clean_terminal_text(b"\x1b[31mtimeout\r\n") == "timeout\n", "proofs-e-wz.terminal-text", "timeout bytes were not readable")
    for seconds in (None, 120, 1800):
        payload = {"objective": "Inspect scratch source"}
        if seconds is not None:
            payload["runtimeSeconds"] = seconds
        result = build_efficient_workflow(folder, payload)
        check_workflow_budget(payload, result)
    for invalid in (119, 1801, "invalid"):
        try:
            build_efficient_workflow(folder, {"objective": "Inspect scratch", "runtimeSeconds": invalid})
        except ValueError:
            pass
        else:
            raise ValueError("unbounded workflow budget accepted")
    result["preset"]["runtimeSeconds"] = 0
    try:
        check_workflow_budget({"runtimeSeconds": 1800}, result)
    except ValueError:
        pass
    else:
        raise ValueError("corrupt workflow budget accepted")


def self_check_bootstrap_and_routes(root):
    from .web_backend import FluxioWebBackend
    folder = Path(root) / "bootstrap-routes"
    folder.mkdir()
    backend = FluxioWebBackend(folder, folder)
    sessions = [{"id": f"chat-{index}", "workspaceId": "workspace_primary", "title": f"Conversation {index}", "createdAt": "2026-07-24T10:00:00Z", "updatedAt": f"2026-07-24T10:0{index}:00Z"} for index in range(3)]
    transcripts = {row["id"]: [{"id": f"{row['id']}-turn-{index}", "role": "assistant" if index%2 else "user", "title": f"Turn {index}", "createdAt": f"2026-07-24T10:{index:02d}:00Z"} for index in range(40)] for row in sessions}
    saved = backend.dispatch("save_conversation_state_command", {"storageMode": "nas", "activeChatSessionId": "chat-1", "chatSessions": sessions, "chatSessionTranscripts": transcripts})
    require(saved["storageMode"] == "nas" and saved["activeChatSessionId"] == "chat-1" and saved["chatSessions"][0]["workspaceId"] == "workspace_primary" and saved["chatSessionTranscripts"]["chat-1"][1]["role"] == "assistant",
            "proofs-e-wz.conversation-save", "saved cross-device chat metadata was not retained")
    loaded = backend.dispatch("get_conversation_state_command", {})
    require(loaded["exists"] and loaded["path"] == str(folder.resolve()/".agent_control/conversation_state.json") and loaded["storageMode"] == "nas" and loaded["chatSessions"][0]["title"].startswith("Conversation"),
            "proofs-e-wz.conversation-save", "cross-device state did not reload its persisted metadata")
    bootstrap = backend.dispatch("get_conversation_state_command", {"summaryMode": "bootstrap", "activeChatSessionId": "chat-1", "turnLimit": 12})
    require(len(bootstrap["chatSessions"]) == 3 and list(bootstrap["chatSessionTranscripts"]) == ["chat-1"] and len(bootstrap["chatSessionTranscripts"]["chat-1"]) == 12 and bootstrap["transcriptIndex"]["chat-0"]["turnCount"] == 40,
            "proofs-e-wz.conversation-bootstrap", "bootstrap did not retain lazy history hydration")
    detail = backend.dispatch("get_conversation_session_state_command", {"sessionId": "chat-0", "turnLimit": 160})
    require(detail["sessionId"] == "chat-0" and detail["totalTurns"] == detail["returnedTurns"] == 40 and not detail["hasEarlierTurns"],
            "proofs-e-wz.conversation-revision", "lazy detail page counts changed")
    backend.dispatch("save_conversation_state_command", {"storageMode": "nas", "activeChatSessionId": "chat-1", "chatSessions": sessions, "chatSessionTranscripts": {"chat-1": [{"id": "chat-1-new", "role": "assistant", "title": "Newest turn", "createdAt": "2026-07-24T11:00:00Z"}]}, "mergeExistingTranscripts": True})
    merged = backend.dispatch("get_conversation_state_command", {})
    require(len(merged["chatSessionTranscripts"]["chat-0"]) == 40 and len(merged["chatSessionTranscripts"]["chat-1"]) == 41 and merged["chatSessionTranscripts"]["chat-1"][-1]["id"] == "chat-1-new",
            "proofs-e-wz.conversation-save", "merge removed history or lost chronological turn ordering")
    corrupt = json.loads(json.dumps(merged))
    corrupt["chatSessionTranscripts"]["chat-1"].reverse()
    corrupt_path = folder / "reordered-state.json"
    corrupt_path.write_text(json.dumps(corrupt), encoding="utf-8")
    try:
        check_conversation_persistence(corrupt_path, corrupt)
    except ValueError:
        pass
    else:
        raise ValueError("reordered persisted chat accepted")
    samples = [("opencon-pro", "glm-5.2", "openrouter", "z-ai/glm-5.2"),
               ("opencode-go", "opencode-go/glm-5.2", "opencode-go", "glm-5.2"),
               ("opencode-go", "openrouter/z-ai/glm-5.2", "opencode-go", "glm-5.2"),
               ("opencode-go", "opencode-go/minimax-m3", "opencode-go", "minimax-m3"),
               ("opencode-go", "opencode-go/qwen3.7-max", "opencode-go", "qwen3.7-max")]
    for provider, model, expected_provider, expected_model in samples:
        route = backend._chat_route({"route": {"provider": provider, "model": model}})
        require(route["provider"] == expected_provider and route["model"] == expected_model and route["model_id"] == expected_provider+"/"+expected_model,
                "proofs-e-wz.chat-route", "pure prepared provider/model identity did not preserve the requested route")


def self_check_http(root):
    """Real localhost transport, generated fixture account, restart and media gates."""
    import gzip
    import http.client
    import threading
    import urllib.parse
    from . import web_backend
    folder = Path(root) / "http"
    static = folder / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Scratch shell</title>", encoding="utf-8")
    (static / "assets/index-AbCdEf12.js").write_text("export const ok = 1;", encoding="utf-8")
    (static / "desktop-entry.json").write_text(json.dumps({"js": "/assets/index-AbCdEf12.js", "css": []}), encoding="utf-8")
    updates = web_backend.desktop_updates_dir(folder)
    updates.mkdir(parents=True)
    (updates / "latest.json").write_text('{"version":"0.2.1"}', encoding="utf-8")
    (updates / "Neyvia_0.2.1_x64-setup.exe").write_bytes(b"MZ-disposable-release-fixture")
    media = folder / ".agent_control/generated_image_artifacts/session-proof.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"private disposable artifact")
    env_values = {"SYNTELOS_ACCOUNT_USER": "proofs-e-http", "SYNTELOS_ACCOUNT_PASSWORD": "Disposable-Auth-Password-42",
                  "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0"}
    saved_env = {key: os.environ.get(key) for key in env_values}
    server = None
    try:
        os.environ.update(env_values)
        backend = web_backend.FluxioWebBackend(folder, static)
        server = web_backend._HandshakeSafeThreadingHTTPServer(("127.0.0.1", proof_port(48503)), web_backend.make_handler(backend))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cookie = ""
        def request(method, path, data=None, headers=None, *, authenticated=True, delayed=False):
            connection = http.client.HTTPConnection("127.0.0.1", proof_port(48503), timeout=30)
            outgoing = {"Content-Type": "application/json", **(headers or {})}
            if authenticated and cookie:
                outgoing["Cookie"] = cookie
            connection.request(method, path, data, outgoing)
            response = connection.getresponse()
            if delayed:
                first = response.read(64*1024)
                time.sleep(11)
                raw = first + response.read()
            else:
                raw = response.read()
            result = (response.status, raw, response.headers)
            connection.close()
            return result
        login = request("POST", "/api/auth/login", json.dumps({"username": env_values["SYNTELOS_ACCOUNT_USER"], "password": env_values["SYNTELOS_ACCOUNT_PASSWORD"]}).encode())
        require(login[0] == 200, "proofs-e-wz.auth-artifact", "fixture account could not sign in")
        cookie = login[2].get("Set-Cookie", "").split(";", 1)[0]
        require(bool(cookie), "proofs-e-wz.auth-artifact", "login did not issue a session cookie")
        require(json.loads(login[1])["data"]["user"]["username"] == env_values["SYNTELOS_ACCOUNT_USER"] and
                env_values["SYNTELOS_ACCOUNT_PASSWORD"].encode() not in backend.web_auth_sessions.path.read_bytes(),
                "proofs-e-wz.auth-issuance", "login changed the account name or wrote its raw environment password into session storage")
        media_url = "/api/artifact?path=" + urllib.parse.quote(str(media.resolve()))
        require(request("GET", media_url, authenticated=False)[0] == 401, "proofs-e-wz.auth-artifact", "private media allowed an unsigned caller")
        authorized = request("GET", media_url)
        require(authorized[0] == 200 and authorized[1] == media.read_bytes(), "proofs-e-wz.auth-artifact", "signed caller did not receive exact artifact bytes")
        for generation in range(2):
            backend = web_backend.FluxioWebBackend(folder, static)
            server.RequestHandlerClass = web_backend.make_handler(backend)
            status = request("GET", "/api/auth/status")
            require(status[0] == 200 and json.loads(status[1])["data"]["authenticated"] is True and json.loads(status[1])["data"]["user"]["username"] == env_values["SYNTELOS_ACCOUNT_USER"] and request("GET", media_url)[0] == 200,
                    "proofs-e-wz.auth-artifact", "backend recreation or regenerated password salt invalidated a valid login")
        os.environ["SYNTELOS_ACCOUNT_PASSWORD"] = "Changed-Auth-Password-43"
        backend = web_backend.FluxioWebBackend(folder, static)
        server.RequestHandlerClass = web_backend.make_handler(backend)
        require(json.loads(request("GET", "/api/auth/status")[1])["data"]["authenticated"] is False,
                "proofs-e-wz.auth-rejection", "changed environment password accepted an old login")
        login = request("POST", "/api/auth/login", json.dumps({"username": env_values["SYNTELOS_ACCOUNT_USER"], "password": "Changed-Auth-Password-43"}).encode())
        cookie = login[2].get("Set-Cookie", "").split(";", 1)[0]
        require(login[0] == 200 and request("POST", "/api/auth/logout", b"{}")[0] == 200 and request("GET", media_url)[0] == 401 and
                json.loads(request("GET", "/api/auth/status")[1])["data"]["authenticated"] is False,
                "proofs-e-wz.auth-rejection", "logout did not immediately end login/media access")
        for name, expected in (("latest.json", b'{"version":"0.2.1"}'), ("Neyvia_0.2.1_x64-setup.exe", b"MZ-disposable-release-fixture")):
            response = request("GET", "/updates/desktop/" + name, authenticated=False)
            require(response[0] == 200 and response[1] == expected, "proofs-e-wz.desktop-update", "public update feed returned incorrect bytes")
        for path in ("/updates/desktop/../desktop-updates/latest.json", "/updates/desktop/%2e%2e%5cweb-auth.json", "/updates/desktop/missing.json", "/updates/desktop/"):
            require(request("GET", path, authenticated=False)[0] in {403, 404}, "proofs-e-wz.desktop-update", "update feed allowed traversal/missing file")
        for path in ("/assets/index-AbCdEf12.js", "/desktop-entry.json", "/control"):
            response = request("GET", path, headers={"Origin": "http://tauri.localhost"}, authenticated=False)
            require(response[2].get("Access-Control-Allow-Origin") == (None if path == "/control" else "http://tauri.localhost"),
                    "proofs-e-wz.desktop-shell", "desktop origin asset/page permission differs")
        require(request("GET", "/assets/index-AbCdEf12.js", headers={"Origin": "https://evil.example"})[2].get("Access-Control-Allow-Origin") is None,
                "proofs-e-wz.desktop-shell", "foreign origin received credentialed interface CORS")
        login = request("POST", "/api/auth/login", json.dumps({"username": env_values["SYNTELOS_ACCOUNT_USER"], "password": "Changed-Auth-Password-43"}).encode())
        cookie = login[2].get("Set-Cookie", "").split(";", 1)[0]
        # Real saved chat output supplies transfer load through the existing command.
        def chat_payload(count, turns=30):
            return {"chatSessions": [{"id": f"chat-{index}", "title": "Fixture", "workspaceId": "scratch", "createdAt": "2026-09-29T10:00:00Z", "updatedAt": "2026-09-29T10:59:00Z"} for index in range(count)],
                    "chatSessionTranscripts": {f"chat-{index}": [{"id": f"t{turn}", "role": "assistant", "title": "tool output "*1000, "createdAt": "2026-09-29T10:00:00Z"} for turn in range(turns)] for index in range(count)}}
        web_backend._save_conversation_state(folder, chat_payload(1))
        observe = json.dumps({"command": "get_conversation_state_command", "payload": {}}).encode()
        plain = request("POST", "/api/backend", observe)
        compressed = request("POST", "/api/backend", observe, headers={"Accept-Encoding": "gzip"})
        require(plain[0] == compressed[0] == 200 and plain[2].get("Content-Encoding") is None and compressed[2].get("Content-Encoding") == "gzip" and
                gzip.decompress(compressed[1]) == plain[1] and len(compressed[1])*10 < len(plain[1]) and "Accept-Encoding" in compressed[2].get_all("Vary"),
                "proofs-e-wz.http-json", "real large HTTP response lost bytes or compression negotiation")
        web_backend._save_conversation_state(folder, chat_payload(24, 160))
        delayed = request("POST", "/api/backend", observe, delayed=True)
        observed = json.loads(delayed[1])["data"]["chatSessionTranscripts"]
        require(delayed[0] == 200 and len(delayed[1]) > 40*1024*1024 and len(observed) == 24 and all(len(rows) == 160 for rows in observed.values()),
                "proofs-e-wz.http-io-timeout", "stalled reader did not receive the full real saved chat output")
        small = request("GET", "/api/auth/status", headers={"Accept-Encoding": "gzip"})
        require(small[2].get("Content-Encoding") is None, "proofs-e-wz.http-json", "small response was unnecessarily compressed")
        # Gzip request decoder with a reviewed small allocation limit; no action runs.
        import io
        from types import SimpleNamespace
        request_body = json.dumps({"text": "x"*500000}).encode()
        zipped = gzip.compress(request_body)
        handler = SimpleNamespace(headers={"content-length": str(len(zipped)), "Content-Encoding": "gzip"}, rfile=io.BytesIO(zipped))
        require(web_backend._read_json_body(handler) == json.loads(request_body), "proofs-e-wz.http-request", "compressed request text changed")
        previous_limit = web_backend.MAX_REQUEST_JSON_BYTES
        try:
            web_backend.MAX_REQUEST_JSON_BYTES = 1024
            handler.rfile = io.BytesIO(zipped)
            try:
                web_backend._read_json_body(handler)
            except ValueError:
                pass
            else:
                raise ValueError("gzip allocation bomb accepted")
        finally:
            web_backend.MAX_REQUEST_JSON_BYTES = previous_limit
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def self_check(root):
    started = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="proofs-e-wz-", dir=root))
    cases = []

    def run(identity, contracts, action):
        from .contract_gate import wants
        if not wants(contracts):
            return
        case_started = time.perf_counter()
        from .durability import atomic_write_json
        atomic_write_json(scratch / "case-progress.json", {"id": identity, "phase": "running"})
        try:
            action()
            cases.append({"id": identity, "contracts": contracts, "ok": True, "durationMs": round((time.perf_counter()-case_started)*1000, 3)})
        except Exception as exc:
            cases.append({"id": identity, "contracts": contracts, "ok": False, "durationMs": round((time.perf_counter()-case_started)*1000, 3), "error": str(exc)})
        atomic_write_json(scratch / "case-receipts.json", cases)
        atomic_write_json(scratch / "case-progress.json", {"id": identity, "phase": "finished", "ok": cases[-1]["ok"]})

    def rejected(action):
        try:
            action()
        except ValueError:
            return
        raise ValueError("adversarial mutated result was accepted")

    def renewal():
        from .web_auth_sessions import WebAuthSessions
        now = [1_000_000.0]
        day = 86400
        sessions = WebAuthSessions(scratch / "renewal", auth_identity="fixture-owner", ttl_seconds=3*day, clock=lambda: now[0])
        used = sessions.issue({"username": "fixture", "role": "admin"})
        idle = sessions.issue({"username": "fixture", "role": "admin"})
        for _ in range(2):
            now[0] += 2*day
            require(sessions.lookup(used) is not None, "proofs-e-wz.auth-renewal", "active session expired")
        require(sessions.lookup(idle) is None, "proofs-e-wz.auth-rejection", "idle session survived expiration")
        with sessions._connect() as db:
            row = db.execute("SELECT identity_hash,username,display_name,role,created_at,expires_at,last_seen FROM web_auth_sessions WHERE token_hash=?", (sessions._token_hash(used),)).fetchone()
            rejected(lambda: check_session_lookup(db, sessions._token_hash(used), row, row[0], now[0]+1, sessions.ttl_seconds, True, True))

    def changed_identity():
        from .web_auth_sessions import WebAuthSessions
        folder = scratch / "identity"
        token = WebAuthSessions(folder, auth_identity="fixture-a").issue({"username": "fixture", "role": "admin"})
        require(WebAuthSessions(folder, auth_identity="fixture-b").lookup(token) is None, "proofs-e-wz.auth-rejection", "changed identity accepted an old session")

    def persisted_concurrent_auth():
        from .web_auth_sessions import WebAuthSessions
        folder = scratch / "concurrent-auth"
        # Independently launched interpreters exercise SQLite locks and restart recovery.
        source = "from grant_agent.web_auth_sessions import WebAuthSessions; import sys,json; s=WebAuthSessions(sys.argv[1],auth_identity='fixture-shared'); print(json.dumps({'token':s.issue({'username':sys.argv[2],'role':'account'})}))"
        child_env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        processes = [subprocess.Popen([sys.executable, "-c", source, str(folder), f"fixture-{index}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=child_env, **hidden_windows_subprocess_kwargs()) for index in range(8)]
        tokens = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                require(process.returncode == 0, "proofs-e-wz.auth-issuance", "parallel session issuer failed: " + stderr.strip().splitlines()[-1] if stderr.strip() else "parallel session issuer failed")
                tokens.append(json.loads(stdout)["token"])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=15)
        require(len(set(tokens)) == 8, "proofs-e-wz.auth-issuance", "concurrent issuers reused a token")
        store = WebAuthSessions(folder, auth_identity="fixture-shared")
        for index, token in enumerate(tokens):
            session = store.lookup(token)
            require(session and session["username"] == f"fixture-{index}" and session["role"] == "account",
                    "proofs-e-wz.auth-issuance", "persisted token lost its account after process recreation")
        require(all(token.encode() not in store.path.read_bytes() for token in tokens), "proofs-e-wz.auth-issuance", "database exposed a bearer token")
        store.revoke(tokens[0])
        require(WebAuthSessions(folder, auth_identity="fixture-shared").lookup(tokens[0]) is None,
                "proofs-e-wz.auth-rejection", "logout did not survive store recreation")
        with store._connect() as db:
            rejected(lambda: check_session_issued(db, "x"*64, (), {}))

    def windows():
        from .subprocess_utils import install_hidden_subprocess_default, hidden_windows_subprocess_kwargs, _hidden_popen_init
        if os.name != "nt":
            require(hidden_windows_subprocess_kwargs() == {} and not install_hidden_subprocess_default(), "proofs-e-wz.hidden-options", "non-Windows changed spawn policy")
            return
        require(install_hidden_subprocess_default(), "proofs-e-wz.hidden-default", "Windows default was not installed")
        installed = subprocess.Popen.__init__
        require(install_hidden_subprocess_default() and subprocess.Popen.__init__ is installed, "proofs-e-wz.hidden-default", "repeat install changed wrapper identity")
        for group in (False, True):
            check_hidden_kwargs(hidden_windows_subprocess_kwargs(new_process_group=group), True, group)
        captured = []
        wrapper = _hidden_popen_init(lambda _self, *args, **kwargs: captured.append((args, kwargs)), subprocess.CREATE_NO_WINDOW)
        for flags in (None, 0, 0x10, 0x208):
            options = {} if flags is None else {"creationflags": flags}
            wrapper(None, ["fixture"], **options)
            require(captured[-1][1]["creationflags"] == (flags or subprocess.CREATE_NO_WINDOW), "proofs-e-wz.hidden-default", "flags were not preserved/defaulted")
        positional = (["fixture"], -1, None, None, None, None, None, True, False, None, None, None, None, 0x10)
        wrapper(None, *positional)
        require(captured[-1] == (positional, {}), "proofs-e-wz.hidden-default", "positional explicit flags changed")
        probe = subprocess.run([sys.executable, "-I", "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"], capture_output=True, text=True, timeout=30)
        require(probe.returncode == 0 and probe.stdout.strip() == "0", "proofs-e-wz.hidden-default", "real owned child had a console window")
        rejected(lambda: check_spawn_flags((["fixture"],), {}, (["fixture"],), {"creationflags": 0}, subprocess.CREATE_NO_WINDOW))
        # Controlled platform-policy branch only; no POSIX child is claimed.
        previous_platform = os.name
        try:
            os.name = "posix"
            require(hidden_windows_subprocess_kwargs() == {} and install_hidden_subprocess_default() is False and subprocess.Popen.__init__ is installed,
                    "proofs-e-wz.hidden-options", "non-Windows policy branch modified Popen or returned Windows options")
        finally:
            os.name = previous_platform

    def x_sources():
        from .x_following_sources import normalize_x_handle, fetch_following_accounts, collect_following_digest_sources, write_following_source_bundle
        import urllib.parse
        require(normalize_x_handle("@PoleSoude") == "PoleSoude", "proofs-e-wz.x-handle", "handle normalization changed")
        rejected(lambda: normalize_x_handle("not/a/handle"))
        calls = []
        def transport(url, **kwargs):
            calls.append(url)
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.netloc == "api.fxtwitter.com":
                names = [("alice", False), ("carol", True)] if query.get("cursor") == ["next-page"] else [("alice", False), ("bob", False)]
                return {"code": 200, "results": [{"screen_name": name, "protected": protected} for name, protected in names], "cursor": {"bottom": None if query.get("cursor") else "next-page"}}
            name = query["url"][0].rsplit("/", 1)[-1]
            return {"code": 0, "data": {"feed": {"siteUrl": f"https://x.com/{name}"}, "entries": [{"title": "Fixture source", "url": f"https://x.com/{name}/status/1"}]}}
        snapshot = fetch_following_accounts("PoleSoude", max_accounts=10, request_json=transport)
        require([row["screenName"] for row in snapshot["accounts"]] == ["alice", "bob", "carol"] and len(calls) == 2,
                "proofs-e-wz.x-following", "pagination did not deduplicate repeated account")
        rejected(lambda: check_following({**snapshot, "accountCount": 99}, 10))
        bundle = collect_following_digest_sources("PoleSoude", max_accounts=10, workers=2, request_json=transport)
        require(bundle["summary"]["protectedAccounts"] == 1 and bundle["summary"]["postsCollected"] == 2,
                "proofs-e-wz.x-public-timelines", "collector did not exclude private timeline")
        rejected(lambda: check_source_bundle({**bundle, "summary": {}}))
        receipt = write_following_source_bundle(bundle, scratch / "sources")
        manifest = json.loads(Path(receipt["manifestPath"]).read_text(encoding="utf-8"))
        path = scratch / "sources/following_snapshot.json"
        path.write_text("{}", encoding="utf-8")
        files = {item["path"]: json.loads((scratch / "sources" / item["path"]).read_text(encoding="utf-8")) for item in manifest["artifacts"]}
        rejected(lambda: check_source_artifacts(scratch / "sources", files, manifest, receipt))

    def repair():
        from .cluster import ClusterRegistry, current_host_id
        from .self_repair import execute_self_repair_job, queue_self_repair_job, MAX_REPAIR_ATTEMPTS, SELF_REPAIR_JOB_KIND
        from .worker import run_local_worker_once
        repair_root = scratch / "repair"
        repair_root.mkdir()
        healthy = b"print('healthy')\n"
        (repair_root / "known.py").write_bytes(healthy)
        (repair_root / "app.py").write_text("raise RuntimeError('controlled break')\n", encoding="utf-8")
        registry = ClusterRegistry(repair_root)
        job = queue_self_repair_job(registry, workspace=repair_root, detect_command=[sys.executable, "-I", "app.py"], repair_command=[sys.executable, "-I", "-c", "from pathlib import Path; Path('app.py').write_bytes(Path('known.py').read_bytes())"], verify_command=[sys.executable, "-I", "app.py"], tracked_paths=["app.py"], mission_id="proofs-e-repair", workspace_id="proofs-e-wz", max_attempts=99, total_timeout_seconds=60)
        result = run_local_worker_once(repair_root, host_id=current_host_id())
        require(result["claimed"] and result["result"]["status"] == "completed" and (repair_root / "app.py").read_bytes() == healthy,
                "proofs-e-wz.worker-repair", "real bundled worker did not repair fixture application")
        check_worker_repair(registry, job, result["result"])
        receipt = result["result"]["repairReceipt"]
        require(receipt["proof"]["trackedPathChanges"] == ["app.py"] and receipt["bounds"]["maxAttempts"] == MAX_REPAIR_ATTEMPTS,
                "proofs-e-wz.repair-bounds", "hard cap or byte change receipt differs")
        rejected(lambda: check_repair({**receipt, "status": "failed"}))
        blocked = registry.upsert_job(mission_id="proofs-e-invalid", workspace_id="proofs-e-wz", lane_role="repair", job_kind=SELF_REPAIR_JOB_KIND, required_capabilities=["app.self_repair"], payload={"executionRoot": str(repair_root), "timeoutSeconds": 30, "selfRepair": {"repairId": "invalid"}})
        result = run_local_worker_once(repair_root, host_id=current_host_id())
        require(result["claimed"] and result["result"]["status"] == "blocked" and "detectCommand" in result["result"]["repairReceipt"]["contractError"],
                "proofs-e-wz.repair-blocked", "invalid repair did not block with a truthful receipt")
        failed = execute_self_repair_job({"jobId": "bounded", "jobKind": SELF_REPAIR_JOB_KIND, "payload": {"selfRepair": {"detectCommand": [sys.executable, "-I", "-c", "raise SystemExit(1)"], "repairCommand": [sys.executable, "-I", "-c", "pass"], "verifyCommand": [sys.executable, "-I", "-c", "raise SystemExit(1)"], "maxAttempts": 99}}}, workspace=repair_root, env=dict(os.environ), timeout_seconds=60)
        require(failed["status"] == "failed" and failed["repairReceipt"]["bounds"]["attemptsUsed"] == MAX_REPAIR_ATTEMPTS and sum(phase["phase"] == "verify" for phase in failed["repairReceipt"]["phases"]) == MAX_REPAIR_ATTEMPTS,
                "proofs-e-wz.repair-bounds", "failed verification did not stop at hard cap")

    run("auth-renewal", ["proofs-e-wz.auth-renewal", "proofs-e-wz.auth-rejection"], renewal)
    run("auth-changed-identity", ["proofs-e-wz.auth-rejection"], changed_identity)
    run("auth-parallel-issuance-and-process-recreation", ["proofs-e-wz.auth-issuance", "proofs-e-wz.auth-rejection"], persisted_concurrent_auth)
    run("hidden-child-real-runtime", ["proofs-e-wz.hidden-options", "proofs-e-wz.hidden-default"], windows)
    run("x-source-local-transport-and-artifacts", ["proofs-e-wz.x-handle", "proofs-e-wz.x-following", "proofs-e-wz.x-public-timelines", "proofs-e-wz.x-artifacts"], x_sources)
    run("worker-repair-real-child-commands", ["proofs-e-wz.repair-bounds", "proofs-e-wz.repair-receipt", "proofs-e-wz.repair-blocked", "proofs-e-wz.worker-repair"], repair)
    run("http-recreation-private-media-desktop-transfer", ["proofs-e-wz.auth-artifact", "proofs-e-wz.auth-rejection", "proofs-e-wz.desktop-update", "proofs-e-wz.desktop-shell", "proofs-e-wz.http-json", "proofs-e-wz.http-request", "proofs-e-wz.http-io-timeout"], lambda: self_check_http(scratch))
    run("conversation-save-and-semantic-revision", ["proofs-e-wz.conversation-save", "proofs-e-wz.conversation-revision"], lambda: self_check_conversation(scratch))
    run("real-process-failure-and-workflow-budget", ["proofs-e-wz.capture-failure", "proofs-e-wz.terminal-text", "proofs-e-wz.workflow-budget"], lambda: self_check_capture(scratch))
    run("recorded-command-traces-and-model-answer", ["proofs-e-wz.assistant-selection", "proofs-e-wz.chat-recording"], lambda: self_check_chat_recording(scratch))
    run("live-bootstrap-and-prepared-route-identities", ["proofs-e-wz.conversation-save", "proofs-e-wz.conversation-bootstrap", "proofs-e-wz.conversation-revision", "proofs-e-wz.chat-route"], lambda: self_check_bootstrap_and_routes(scratch))
    return {"ok": all(row["ok"] for row in cases), "contracts": sorted({contract for row in cases for contract in row["contracts"]}), "cases": cases,
            "failures": [row for row in cases if not row["ok"]], "scratchRoot": str(scratch), "durationMs": round((time.perf_counter()-started)*1000, 3),
            "frontier": ["X self-check supplies bounded transport data; it proves collector/persistence behavior, not provider availability or public data freshness.", "Paired physical desktop controller routing and remaining provider-dependent backend cases are not covered by local transport/recording contracts."]}


def self_check_conversation(root):
    from . import web_backend
    folder = Path(root) / "conversation"
    folder.mkdir()
    turns = [{"id": f"t{index}", "role": "assistant", "title": "tool output "*400, "createdAt": f"2026-09-29T10:{index:02d}:00Z"} for index in range(30)]
    session = {"id": "chat-a", "title": "A", "workspaceId": "scratch", "createdAt": "2026-09-29T10:00:00Z", "updatedAt": "2026-09-29T10:59:00Z"}
    payload = {"chatSessions": [session], "chatSessionTranscripts": {"chat-a": turns}}
    full = web_backend._save_conversation_state(folder, payload)
    receipt = web_backend._save_conversation_state(folder, {**payload, "returnState": False})
    require(len(full["chatSessionTranscripts"]["chat-a"]) == 30 and receipt["sessionCount"] == receipt["transcriptCount"] == 1 and "chatSessionTranscripts" not in receipt,
            "proofs-e-wz.conversation-save", "receipt-only save lost state or echoed transcript")
    first = web_backend._conversation_session_state(folder, session_id="chat-a")
    same = web_backend._conversation_session_state(folder, session_id="chat-a", if_revision=first["revision"])
    require(len(first["turns"]) == 30 and same["notModified"] and "turns" not in same and len(json.dumps(same)) < 400,
            "proofs-e-wz.conversation-revision", "same session did not return a compact revision")
    web_backend._save_conversation_state(folder, {**payload, "mergeExistingTranscripts": True, "chatSessions": [{**session, "updatedAt": "2026-09-29T12:30:00Z"}]})
    require(web_backend._conversation_session_state(folder, session_id="chat-a", if_revision=first["revision"])["notModified"],
            "proofs-e-wz.conversation-revision", "timestamp-only refresh changed semantic revision")
    web_backend._save_conversation_state(folder, {"mergeExistingTranscripts": True, "chatSessions": [], "chatSessionTranscripts": {"chat-a": [{"id": "t30", "role": "user", "title": "next", "createdAt": "2026-09-29T11:00:00Z"}]}})
    changed = web_backend._conversation_session_state(folder, session_id="chat-a", if_revision=first["revision"])
    require("notModified" not in changed and len(changed["turns"]) == 31 and changed["revision"] != first["revision"],
            "proofs-e-wz.conversation-revision", "new turn did not invalidate semantic revision")
    for junk in (None, "", 0, "not-a-revision"):
        require("notModified" not in web_backend._conversation_session_state(folder, session_id="chat-a", if_revision=junk),
                "proofs-e-wz.conversation-revision", "invalid revision suppressed transcript")
    try:
        check_conversation_session({**changed, "revision": "wrong"}, changed["session"], changed["turns"], changed["turns"], "")
    except ValueError:
        pass
    else:
        raise ValueError("mutated semantic revision was accepted")
