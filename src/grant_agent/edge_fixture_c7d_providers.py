"""Confined provider host semantics; supplied protocol inputs are never model proof."""
from __future__ import annotations
import base64
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = {"empty": "", "huge": "owned protocol input " * 4096, "unicode": "雪 café e\u0301 العربية"}
CLAUDE = {"providers.claude." + name for name in ("aggregate", "auth", "capabilities", "context", "live", "login", "media", "options", "page", "request", "summary", "title_priority", "transports")}
PURE = {"providers.claude.aggregate", "providers.claude.capabilities", "providers.claude.transports"}
IDS = set(CLAUDE)
IDS |= {"providers.terminal." + name for name in ("answer", "compact", "hook", "images")}
from .edge_fixture_c7d_codex import IDS as CODEX_IDS
IDS |= CODEX_IDS
PURE |= {"providers.terminal.compact"}

CLAUDE_PEER = r'''
const fs=require('node:fs');const readline=require('node:readline');const worldPath=process.argv[2];const args=process.argv.slice(3);const world=()=>JSON.parse(fs.readFileSync(worldPath,'utf8'));
const send=x=>process.stdout.write(JSON.stringify(x)+'\n');
if(args[0]==='agents'){send(world().agents);process.exit(0)}
if(args[0]==='auth'){send(world().auth);process.exit(0)}
if(args.includes('--help')){process.stdout.write('--permission-mode <mode> (choices: "manual", "plan", "acceptEdits")\n--effort <effort> (choices: "low", "high")\n');process.exit(0)}
if(args[0]==='plugin'||args[0]==='mcp'){send([]);process.exit(0)}
readline.createInterface({input:process.stdin}).on('line',line=>{const m=JSON.parse(line);fs.appendFileSync(world().log,JSON.stringify(m)+'\n');if(m.type==='control_request'){send({type:'control_response',response:{subtype:'success',request_id:m.request_id,response:{models:[{value:'owned',displayName:world().text,supportsEffort:true,supportedEffortLevels:['low','high']}]}}})}else if(m.type==='user'){const w=world();send({type:'system',subtype:'init',session_id:'owned-session',model:'owned'});send({type:'assistant',session_id:'owned-session',message:{id:'owned-answer',role:'assistant',model:'owned',content:[{type:'text',text:w.text}],usage:{input_tokens:7,output_tokens:3}}});send({type:'result',subtype:'success',is_error:false,session_id:'owned-session',result:w.text});setTimeout(()=>process.exit(0),20)}});
'''


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def rejected(action, code=None):
    try:
        action()
    except Exception as error:
        if code:
            require(getattr(error, "code", None) == code, "Refusal code differs: " + str(getattr(error, "code", None)))
        return error
    raise AssertionError("Invalid/denied supplied input was accepted")


def _claude(root, category, identity):
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.claude_transcript import SummaryIndex, AgentAggregate
    from .connected_sessions.model import TurnOptions
    text = TEXT.get(category, "owned protocol input")
    peer = root / "protocol.cjs"; peer.write_text(CLAUDE_PEER, encoding="utf-8")
    world_path = root / "supplied-world.json"
    world = {"agents": [], "auth": {"loggedIn": False, "email": "generated@example.invalid"}, "text": text, "log": str(root / "wire.jsonl")}
    world_path.write_text(json.dumps(world), encoding="utf-8")
    config = root / "provider-home"; project = config / "projects/owned"; project.mkdir(parents=True)
    (config / "settings.json").write_text(json.dumps({"autoCompactWindow": 12345, "model": "owned"}), encoding="utf-8")
    owner = ClaudeAdapter(state_root=root, config_dir=config, cli_path=["node", str(peer), str(world_path)], host={"deviceId": "c7d-owned", "deviceName": "Owned scratch"}, context_probe=False, agents_ttl=0)
    if identity == "providers.claude.capabilities":
        require(not owner._capabilities(None, installed=False).new_session, "Missing installed capability invented a session")
        for who, state, allowed in ((None, "idle", True), ("app", "idle", True), ("app", "working", False), ("cli", "idle", False)):
            value = owner._capabilities(who, state, installed=True)
            require(value.continue_session is allowed and value.compact is allowed, "Supplied foreign ownership projection enabled competing writer")
        return {"actualOwnershipProjection": True, "providerObserved": False}
    if identity == "providers.claude.transports":
        for kind in ("subscription", "unknown", "api-key"):
            value = owner._transports({"kind": kind, "label": text})
            require([row["id"] for row in value] == ["print", "terminal"] and value[0]["default"] and not value[1]["default"] and value[1]["risk"], "Supplied transport metadata lost safe default or consent disclosure")
        return {"actualTransportDescriptor": True, "terminalSpawned": False}
    if identity == "providers.claude.aggregate":
        agg = AgentAggregate()
        for i in range(1 if category == "empty" else 300 if category == "huge" else 3):
            record = {"type": "assistant", "uuid": "r" + str(i), "timestamp": "2026-10-05T12:00:00Z", "message": {"id": "same", "model": text, "usage": {"input_tokens": 7, "cache_read_input_tokens": 4, "output_tokens": i + 1}, "content": [{"type": "tool_use", "id": "tool" + str(i), "name": "Read", "input": {"file_path": text}}]}}
            agg.feed(record)
        result = agg.summarize({"syncResult": False, "totals": {"outputTokens": 31, "inputTokens": 41, "toolCount": 5}}, now=0)
        require((result["outputTokens"], result["inputTokens"], result["toolCount"]) == (31, 41, 5), "Authoritative supplied completion totals became streamed sums")
        live = agg.summarize({"totals": {}}, now=0)
        require(live["inputTokens"] == 11 and live["outputTokens"] == (1 if category == "empty" else 300 if category == "huge" else 3), "Latest supplied context or duplicate message-output accounting changed")
        return {"actualSuppliedUsageAggregation": True, "providerUsageMeasured": False}
    if identity == "providers.claude.login":
        from .connected_sessions.claude_login import CliLogin
        login = CliLogin()
        for invalid in ("", text if category != "empty" else "not a code"):
            rejected(lambda: login.finish(invalid), "invalid_code")
        rejected(lambda: login.finish("owned-code#owned-state"), "sign_in_expired")
        require(login._proc is None, "Expired login retained a child")
        return {"actualInvalidCodeRefusal": True, "actualExpiredLoginRefusal": True, "accountSignedIn": False}
    if identity == "providers.claude.request":
        for message, code in (("", "empty_message"), ("x" * 100001, "message_too_long"), ("/new " + text, "unsupported_command")):
            events = []
            rejected(lambda: owner.start_turn(None, message, TurnOptions(), cwd=str(root), run_id="invalid", emit=events.append), code)
            require(not events and not (root / "wire.jsonl").exists(), "Invalid request emitted a run or started a protocol child")
        if category == "unicode":
            events = []
            session = owner.start_turn(None, text, TurnOptions(), cwd=str(root), run_id="unicode", emit=events.append)
            require(session == "owned-session" and any(row.get("item", {}).get("data", {}).get("text") == text for row in events), "Actual supplied Unicode stdio request/output changed")
        return {"actualPreallocationRequestBounds": True, "confinedProtocolOnly": True, "providerObserved": False}
    if identity in {"providers.claude.auth", "providers.claude.live", "providers.claude.options"}:
        def observe():
            if identity == "providers.claude.auth":
                value = owner.auth(force=True)
                require(value == {"kind": "signed-out", "label": "no sign-in"}, "Supplied signed-out CLI response leaked account fields or invented login")
            elif identity == "providers.claude.live":
                value = owner._agents_entries(force=True)
                require(value == world["agents"], "Actual protocol agents projection changed supplied rows")
            else:
                value = owner.options()
                require(any(row["id"] == "owned" for row in value["models"]) and value["defaultEffort"] is None and value["auth"]["kind"] == "signed-out", "Actual CLI catalog output lost typed model or public auth projection")
            return value
        if category == "permissions":
            from .edge_fixture_models import _deny_read
            with _deny_read(peer):
                value = owner.auth(force=True) if identity == "providers.claude.auth" else owner._agents_entries(force=True) if identity == "providers.claude.live" else owner.options()
            require(value["kind"] == "unknown" if identity == "providers.claude.auth" else value is None if identity == "providers.claude.live" else value["auth"]["kind"] == "unknown" and not any(row["id"] == "owned" for row in value["models"]), "Denied real protocol source read invented an observed CLI result")
            return {"actualWindowsProtocolSourceDenied": True, "providerObserved": False}
        if category == "offline":
            peer.write_text("process.exit(3)")
            value = owner.auth(force=True) if identity == "providers.claude.auth" else owner._agents_entries(force=True) if identity == "providers.claude.live" else owner.options()
            require(value["kind"] == "unknown" if identity == "providers.claude.auth" else value is None if identity == "providers.claude.live" else value["auth"]["kind"] == "unknown", "Actual unavailable local protocol child became an observed sign-in/live result")
            return {"actualLocalChildUnavailable": True, "providerObserved": False}
        result = observe()
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                require(all(value == result for value in pool.map(lambda _: observe(), range(8))), "Concurrent confined CLI observations diverged")
        if category == "stale" and identity == "providers.claude.live":
            world["agents"] = [{"sessionId": "fresh", "name": "fresh supplied row", "pid": 999999, "status": "idle", "kind": "foreground"}]
            world_path.write_text(json.dumps(world), encoding="utf-8"); observe()
        if category == "stale" and identity == "providers.claude.auth":
            world["auth"] = {"loggedIn": True, "authMethod": "oauth", "subscriptionType": "generated-plan"}
            world_path.write_text(json.dumps(world), encoding="utf-8")
            require(owner.auth(force=True)["kind"] == "subscription", "Explicit force auth projection reused previous supplied CLI bytes")
        return {"actualOwnedNodeCLI": True, "generatedProtocolInputs": True, "providerObserved": False, "accountSignedIn": False}
    path = project / "owned-session.jsonl"
    def append(kind, **fields):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": kind, "uuid": uuid.uuid4().hex, "sessionId": "owned-session", "cwd": str(root), "gitBranch": "owned", "timestamp": "2026-10-05T12:00:00Z", **fields}, ensure_ascii=False) + "\n")
    append("user", message={"role": "user", "content": text or "owned initial prompt"})
    append("assistant", message={"id": "answer", "role": "assistant", "model": "owned", "content": [{"type": "text", "text": text}], "usage": {"input_tokens": 7, "cache_read_input_tokens": 4, "output_tokens": 3}})
    index = SummaryIndex(path, "owned-session"); index.refresh()
    if identity == "providers.claude.title_priority":
        for kind, field, wanted in (("ai-title", "aiTitle", "ai supplied"), ("summary", "summary", "summary supplied"), ("custom-title", "customTitle", "custom supplied")):
            append(kind, **{field: wanted + text[:30]}); index.refresh()
            require(index.title == wanted + text[:30], "Actual appended title priority lost current highest-priority supplied title")
        return {"actualTranscriptTitlePriority": True, "providerObserved": False}
    if identity == "providers.claude.context":
        if category == "permissions":
            from .edge_fixture_models import _deny_read
            with _deny_read(config / "settings.json"):
                require(owner._context(index).auto_compact_tokens is None, "Denied settings read invented configured threshold")
            return {"actualWindowsSettingsReadDenied": True, "missingThresholdNotInvented": True}
        result = owner._context(index)
        require(result.used_tokens == 11 and result.window_tokens is None and result.auto_compact_tokens == 12345, "Transcript context invented missing model window or changed actual usage/settings")
        return {"actualUsageAndSettingsRead": True, "providerUsageMeasured": False}
    if identity == "providers.claude.summary":
        result = owner._summary(index, {}, installed=True)
        require(result.cwd == str(root) and result.model == "owned" and result.git_branch == "owned" and result.title == index.title, "Actual transcript summary invented metadata")
        return {"actualTranscriptSummary": True, "providerObserved": False}
    if identity == "providers.claude.media":
        data = text.encode("utf-8") or b"owned"
        append("user", message={"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(data).decode()}}]})
        page = owner.read("owned-session")
        attachment = next(item.data["attachments"][0] for item in page.items if item.data.get("attachments"))
        result = owner.read_media("owned-session", attachment["mediaRef"])
        require(result[0] == data and result[1] == "image/png" and owner.read_media("owned-session", "invalid") is None, "Opaque local media projection changed supplied bytes or accepted invalid token")
        if category == "permissions":
            from .edge_fixture_models import _deny_read
            with _deny_read(path):
                fresh = ClaudeAdapter(state_root=root, config_dir=config, cli_path=["node", str(peer), str(world_path)], context_probe=False)
                rejected(lambda: fresh.read_media("owned-session", attachment["mediaRef"]))
        return {"actualMediaBytesReadback": True, "imageDecoded": False, "providerObserved": False}
    def observe():
        page = owner.read("owned-session", limit=999999 if category == "huge" else 20)
        require(page.session.model == "owned" and all(item.kind in {"user", "assistant"} for item in page.items) and any(item.data.get("text") == (text or "owned initial prompt") for item in page.items), "Current supplied transcript page projection changed identity or content")
        return page
    first = observe()
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = path.read_bytes()
        with _deny_read(path):
            rejected(lambda: ClaudeAdapter(state_root=root, config_dir=config, cli_path=["node", str(peer), str(world_path)], context_probe=False).read("owned-session"))
        require(path.read_bytes() == before, "Denied transcript read changed keeper")
    if category == "stale":
        append("user", message={"role": "user", "content": "fresh supplied transcript bytes"})
        fresh = owner.read("owned-session", cursor=first.cursor)
        require(any(item.data.get("text") == "fresh supplied transcript bytes" for item in fresh.items), "Appended current transcript was masked by old cursor")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            require(all(value.session.id == first.session.id for value in pool.map(lambda _: observe(), range(8))), "Concurrent read changed session identity")
    return {"actualLocalTranscriptPage": True, "generatedProtocolInput": True, "providerObserved": False}


def _terminal(root, category, identity):
    from .connected_sessions import claude_terminal as module
    from .connected_sessions.claude_stream import Pending
    from .connected_sessions.model import Item, TurnOptions
    text = TEXT.get(category, "owned terminal input")
    if identity == "providers.terminal.images":
        saved = module.IMAGE_DIR; module.IMAGE_DIR = root / "image-bytes"
        try:
            data = text.encode() or b"owned supplied bytes"
            output = module.attach_images_as_files(text, [{"mime": "image/png", "data": base64.b64encode(data).decode()}])
            files = list(module.IMAGE_DIR.glob("*.png")); require(len(files) == 1 and files[0].read_bytes() == data and str(files[0]) in output, "Actual terminal image attachment changed supplied bytes or omitted owned path")
            rejected(lambda: module.attach_images_as_files(text, [{"mime": "image/unsupported", "data": "AA=="}]))
            rejected(lambda: module.attach_images_as_files(text, [{"mime": "image/png", "data": "invalid%"}]))
            if category == "permissions":
                from .edge_fixture_c7d_local import _deny_child_creation
                with _deny_child_creation(module.IMAGE_DIR, root):
                    rejected(lambda: module.attach_images_as_files(text, [{"mime": "image/png", "data": "AA=="}]))
                require(len(list(module.IMAGE_DIR.glob("*.png"))) == 1 and files[0].read_bytes() == data, "Denied new attachment created bytes or altered keeper")
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:
                    outputs = list(pool.map(lambda _: module.attach_images_as_files(text, [{"mime": "image/png", "data": base64.b64encode(data).decode()}]), range(8)))
                require(len(set(outputs)) == 8 and len(list(module.IMAGE_DIR.glob("*.png"))) == 9, "Concurrent new attachments collided at durable paths")
            if category == "stale":
                newer = module.attach_images_as_files("fresh", [{"mime": "image/png", "data": base64.b64encode(b"fresh owned bytes").decode()}])
                require(newer != output and len(list(module.IMAGE_DIR.glob("*.png"))) == 2, "New attachment reused previous image path/bytes")
            return {"actualOwnedAttachmentFiles": True, "imageDecoded": False, "terminalSpawned": False}
        finally:
            module.IMAGE_DIR = saved
    if identity == "providers.terminal.hook":
        from .connected_sessions.claude_hook import write_json, main
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        folder = root / "events"
        value = {"event": "owned", "data": {"text": text}}
        write_json(folder, "owned.json", value)
        require(json.loads((folder / "owned.json").read_bytes()) == value, "Atomic hook event changed supplied data")
        if category == "permissions":
            from .edge_fixture_models import _deny_read
            before = (folder / "owned.json").read_bytes()
            with _deny_read(folder / "owned.json"):
                rejected(lambda: write_json(folder, "owned.json", {"text": "denied"}))
            require((folder / "owned.json").read_bytes() == before, "Denied hook event replacement changed keeper")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i: write_json(folder, str(i) + ".json", {"index": i}), range(8)))
            require(all(json.loads((folder / (str(i) + ".json")).read_bytes()) == {"index": i} for i in range(8)), "Concurrent independent actual hook event names lost bytes")
        if category == "stale":
            write_json(folder, "owned.json", {"text": "fresh"}); require(json.loads((folder / "owned.json").read_bytes()) == {"text": "fresh"}, "Hook replacement retained previous current data")
        if category == "interrupted":
            code = "import sys,os;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.connected_sessions.claude_hook import write_json;write_json(r/'events','crash.json',{'completed':True});os._exit(23)"
            child = subprocess.run([sys.executable, "-c", code, str(root)], env={**os.environ, "PYTHONPATH": str(REPO / "src")}, timeout=20, **hidden_windows_subprocess_kwargs())
            require(child.returncode == 23 and json.loads((folder / "crash.json").read_bytes()) == {"completed": True}, "Atomic completed hook event disappeared at real process-exit boundary")
        return {"actualAtomicHookFiles": True, "standaloneProductionHook": True, "terminalSpawned": False}
    run = module.ClaudeTerminalRun(cli=["node", str(root / "never-started.cjs")], run_id="owned", session_id="owned-session", message="/compact", options=TurnOptions(), cwd=str(root), emit=lambda _: None, projects=root, store_for=lambda *_: None, spool_root=root)
    if identity == "providers.terminal.compact":
        from datetime import datetime, timezone
        at = datetime.now(timezone.utc).isoformat()
        run._note_local_result(Item("owned", 1, "compaction", at, {"state": "completed"}))
        require(run._prompted and run._stop_at is not None, "Supplied completed local compact boundary did not settle pending command")
        return {"actualSuppliedCompactTransition": True, "terminalSpawned": False}
    run._spool = root / "spool"; pending = Pending("owned-request", "approval", "Bash", "tool-owned", {"command": "owned supplied command"}, "item-owned")
    run._pending[pending.request_id] = pending
    rejected(lambda: run.answer("missing", {"decision": "approve"}), "request_not_pending")
    rejected(lambda: run.answer(pending.request_id, {"decision": text or "invalid"}), "invalid_decision")
    if category == "permissions":
        from .edge_fixture_c7d_local import _deny_child_creation
        folder = run._spool / "decisions"; folder.mkdir(parents=True)
        with _deny_child_creation(folder, root):
            rejected(lambda: run.answer(pending.request_id, {"decision": "deny"}))
        require(pending.request_id in run._pending and not (folder / "owned-request.json").exists(), "Denied decision-file delivery consumed pending request without a durable hook reply")
    run.answer(pending.request_id, {"decision": "deny"})
    value = json.loads((run._spool / "decisions/owned-request.json").read_bytes())
    require(value["hookSpecificOutput"]["decision"]["behavior"] == "deny" and not run._pending, "Actual deny answer did not persist precise hook decision or consume pending request")
    rejected(lambda: run.answer(pending.request_id, {"decision": "approve"}), "request_not_pending")
    return {"actualTypedPendingDecisionFile": True, "doubleAnswerRefused": True, "terminalSpawned": False}


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity in CODEX_IDS:
        from .edge_fixture_c7d_codex import blocker as codex_blocker
        return codex_blocker(contract, category)
    if identity not in IDS:
        return None
    if identity in PURE and category not in TEXT:
        return {"kind": "not_applicable", "reason": f"Exact {identity} projects explicitly supplied usage/ownership/billing fields into a value. It executes no model, reads no selected credential, grants no OS authority, admits no revision and creates no resumable worker."}
    if category == "offline" and identity not in {"providers.claude.auth", "providers.claude.live", "providers.claude.options"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} validates supplied input or reads selected root-local transcript bytes. Endpoint connectivity/model account availability is not admitted in that invariant; confined CLI unavailability is exercised at actual CLI metadata owners."}
    if category == "interrupted" and identity != "providers.terminal.hook":
        return {"kind": "not_applicable", "reason": f"Exact {identity} has no durable interruption receipt or resumable write. A killed local reader/CLI metadata probe yields no accepted returned observation; actual model-turn interruption is independently owned by providers.claude.lifecycle."}
    if category == "permissions" and identity not in {"providers.claude.page", "providers.claude.auth", "providers.claude.live", "providers.claude.options", "providers.claude.context", "providers.claude.media", "providers.terminal.hook", "providers.terminal.images", "providers.terminal.answer"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} validates/project supplied input or probes one selected local metadata command; it does not grant an OS/model action or store login credentials. Actual selected-transcript sharing denial is exercised under page; no account access is claimed."}
    if category in {"concurrency", "stale"} and identity in {"providers.claude.login", "providers.claude.request", "providers.claude.context", "providers.claude.summary", "providers.claude.media", "providers.claude.title_priority", "providers.terminal.answer"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} transforms one selected supplied request/index/media token and has no shared revision/CAS or writer admission. Current transcript append, concurrent read and forced CLI-cache observations are exercised at their stateful owner. Invalid/expired login has no active process or account."}
    return None


def run(root, contracts, categories):
    rows = []
    for identity in sorted(IDS & contracts.keys()):
        for category in categories:
            if blocker(contracts[identity], category):
                continue
            area = Path(root) / (identity.replace('.', '-') + '-' + category + '-' + uuid.uuid4().hex[:8]); area.mkdir(parents=True)
            row = {"id": "c7d-providers." + identity + "." + category, "contracts": [identity], "category": category,
                   "boundary": "Actual confined host parser/process/file boundary with generated protocol inputs; no real provider/model/account/terminal/rendered proof"}
            try:
                if identity in CODEX_IDS:
                    from .edge_fixture_c7d_codex import exercise
                    detail = exercise(area, category, identity)
                else:
                    detail = (_terminal if identity.startswith("providers.terminal.") else _claude)(area, category, identity)
                row.update(status="passed", detail=detail)
            except Exception as error:
                row.update(status="failed", detail={"type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()[-2500:]})
            rows.append(row)
    return rows
