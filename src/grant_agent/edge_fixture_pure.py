"""Generated semantic fixtures for production parsers and local browser state.

These fixtures feed adversarial data into the owning production functions and
compare observed values, files and revision deltas. They never treat response
schema admission or an unrelated self-check as proof of a semantic pair.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import hashlib
import json
from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

TEXTS = {"empty": "", "huge": "long " * 14000,
         "unicode": "雪🙂e\u0301\u202e العربية"}
PURE = {
    "providers.claude.identity", "providers.claude.origin",
    "providers.claude.category", "providers.claude.title",
    "providers.claude.classify", "providers.claude.output",
    "a-cli.cursor.text", "a-cli.catalog.fact", "a-cli.catalog.classify",
    "a-cli.catalog.actions", "a-cli.catalog.recommend", "a-cli.catalog.size",
    "neyvia-core.browser-url", "sv.ui.semantic-identity", "sv.ui.delta",
    "sv.ui.query", "sv.ui.compact-delta",
}
LOCAL = {"a-cli.archive.summary", "a-cli.archive.inspect",
         "proofs-b.engine.skill-load", "neyvia-core.browser-pending",
         "neyvia-core.browser-authority", "sv.ui.graph-state"}
SUPPORTED = PURE | LOCAL


def blocker(contract, category):
    """Only assert non-applicability for the audited stateless production owners."""
    identity = contract.get("id", "")
    if identity in PURE and category in {"concurrency", "interrupted", "stale", "permissions", "offline"}:
        if identity == "a-cli.catalog.size":
            return {"kind": "not_applicable", "reason":
                    f"The {identity} invariant concerns only runtimes without a declared npm package; "
                    "the inspected resolve_package_size branch returns unknown locally before any network lookup. "
                    f"That branch has no grant, worker, durable revision or network endpoint for {category}."}
        return {"kind": "not_applicable", "reason":
                f"{identity} is a deterministic in-memory transform at {contract.get('checkedAt', [])}; "
                f"it has no persisted revision, worker, grant or network endpoint to exercise {category}."}
    return None


def _check(condition, detail):
    if not condition:
        raise AssertionError(detail)


def _provider(identity, text):
    from .connected_sessions import claude_items as c
    if identity.endswith("identity"):
        host = {"deviceId": "fixture-host"}
        actual = c.session_identity(text, host)
        _check(actual == "external:claude-code:fixture-host:" + quote(text, safe="-_.~"), "identity loses supplied session bytes")
    elif identity.endswith("origin"):
        _check(not c.is_harness_cwd("/fixture/projects/" + text, temp_roots=["/owned-temp"]), "ordinary project classified harness")
        for marker in (".agent_control", "proof"):
            _check(c.is_harness_cwd("/fixture/" + marker + "/" + text, temp_roots=[]), "harness marker not classified")
    elif identity.endswith("category"):
        for name, expected in (("Bash", "command"), ("Write", "edit"), ("Read", "read"), ("Grep", "search"), ("WebFetch", "web"), ("Task", "agent"), ("mcp__" + text, "mcp"), (text, "other")):
            _check(c.tool_category(name) == expected, "tool family classification disagrees")
    elif identity.endswith("title"):
        for name, field in (("Bash", "command"), ("Grep", "pattern"), ("WebSearch", "query"), ("Task", "description"), ("Skill", "skill")):
            result = c.tool_title(name, {field: text})
            flattened = " ".join((text or name).split())
            expected = flattened if len(flattened) <= 120 else flattened[:119].rstrip() + "…"
            _check(result == expected, "title changed relevant text or exceeds bound")
    elif identity.endswith("classify"):
        _check(c.classify_user_text(text) == (("prose", text.strip(), "info") if text.strip() else ("hidden", "", "info")), "prose classification changed text")
        _check(c.classify_user_text("<system-reminder>" + text + "</system-reminder>") == ("hidden", "", "info"), "internal reminder exposed")
        _check(c.classify_user_text("<local-command-stderr>" + text + "</local-command-stderr>") == (("notice", text.strip(), "warning") if text.strip() else ("hidden", "", "info")), "stderr notice changed")
    elif identity.endswith("output"):
        for limit in (64, 2000):
            bounded, truncated, total = c.bound_output(text, limit)
            raw = text.encode("utf-8", "replace")
            _check(total == len(raw) and truncated == (len(raw) > limit), "output byte receipt wrong")
            if not truncated:
                _check(bounded == text, "unbounded output changed")
            else:
                head = raw[:int(limit * .7)].decode("utf-8", "ignore")
                tail = raw[-int(limit * .25):].decode("utf-8", "ignore")
                omitted = len(raw) - len(head.encode()) - len(tail.encode())
                _check(bounded == f"{head}\n… {omitted} bytes omitted …\n{tail}", "head/tail conservation differs")


def _catalog(identity, text):
    from . import cli_catalog as c
    from .models import RuntimeInstallStatus
    if identity.endswith("size"):
        entry = c.CatalogEntry("fixture", text, publisher=text, package_kind=None, package_name=None)
        result = c.resolve_package_size(entry)
        _check(result["bytes"] is None and result["source"] is None and bool(result["detail"]), "unknown package size invented")
    elif identity.endswith("fact"):
        for confidence in ("verified", "unverified"):
            _check(c._fact(text, confidence) == {"value": text or None, "confidence": confidence if text else "unverified"}, "fact invents missing knowledge")
    elif identity.endswith("classify"):
        variants = [(False, None, [], False, c.STATE_UNAVAILABLE),
                    (False, text or "install locally", [], False, c.STATE_AVAILABLE),
                    (True, None, [], False, c.STATE_READY),
                    (True, None, [], True, c.STATE_UPDATE_RECOMMENDED),
                    (True, None, ["login " + text], False, c.STATE_CONNECTION_REQUIRED)]
        for detected, hint, issues, update, expected in variants:
            status = RuntimeInstallStatus("fixture", text, detected, install_hint=hint, issues=issues, update_available=update)
            _check(c.classify(status, None)[0] == expected, "readiness classification invented availability")
    elif identity.endswith("actions"):
        for managed in (False, True):
            for owned in (False, True):
                states = {c.STATE_READY: ["repair", "uninstall"] if owned else [],
                          c.STATE_UPDATE_RECOMMENDED: ["update", "repair", "uninstall"] if owned else [],
                          c.STATE_CONNECTION_REQUIRED: ["connect", "repair", "uninstall"] if owned else ["connect"],
                          c.STATE_AVAILABLE: ["install", "skip"] if managed else ["skip"],
                          c.STATE_UNSUPPORTED: ["skip"], c.STATE_UNAVAILABLE: ["skip"]}
                for state, expected in states.items():
                    _check(c._actions_for(state, managed_install=managed, managed_owned=owned) == expected, "catalog actions widened install ownership")
                try:
                    actual = c._actions_for(text, managed_install=managed, managed_owned=owned)
                except ValueError as exc:
                    _check("state lacks label" in str(exc), "unknown state refusal is not precise")
                else:
                    _check(actual == ["skip"], "unknown state exposes active operation")
    elif identity.endswith("recommend"):
        entries = [{"runtimeId": rid, "label": text, "usefulFor": text, "state": state}
                   for rid, state in (("claude-code", c.STATE_READY), ("opencode", c.STATE_UNSUPPORTED), ("cursor", c.STATE_AVAILABLE))]
        result = c.recommend({"entries": entries}, [text, "software", "software"], limit=2)
        _check([r["runtimeId"] for r in result] == ["claude-code", "cursor"] and all(r["because"] for r in result), "recommendations lose affinity, uniqueness or explanation")


def _graph(root, category, text):
    from .ui_graph import UiNode, UiGraph, Bounds, compute_semantic_hash, diff_graphs, format_compact_delta, find_nodes
    count = 0 if category == "empty" else 220 if category == "huge" else 3
    nodes = [UiNode(f"node-{i}", "button" if i % 2 == 0 else "textbox", name=text + str(i), value=text,
                    actions=("click",), bounds=Bounds(i * 8, 0, 32, 16)) for i in range(count)]
    graph = UiGraph()
    graph.replace_nodes(nodes)
    _check(len(graph.nodes) == count and all(n.revision == 1 for n in graph.nodes.values()), "graph revision stamp differs")
    _check(graph.semantic_hash == compute_semantic_hash(reversed(nodes)), "semantic hash depends on input order")
    for n in nodes:
        _check(n.semantic_tuple() == replace(n, states=("focused", "hovered"), revision=999).semantic_tuple(), "presentation noise alters identity")
        _check(n.semantic_tuple() != replace(n, value=n.value + "changed").semantic_tuple(), "value absent from identity")
    matches = find_nodes(graph.nodes.values(), "button", limit=1000)
    _check([n.id for n in matches] == [n.id for n in sorted(nodes, key=lambda n: (n.role, n.name, n.id)) if n.role == "button"][:100], "graph role query bound/order differs")
    before = graph.snapshot_nodes()
    changed = [replace(n, value=n.value + "changed") for n in nodes[1:]]
    changed.append(UiNode("new-node", "button", name=text))
    deltas = graph.replace_nodes(changed)
    expected = ({("removed", nodes[0].id)} if nodes else set()) | {("changed", n.id) for n in nodes[1:]} | {("added", "new-node")}
    _check({(d.kind, d.node_id) for d in deltas} == expected, "replacement delta does not match actual changes")
    _check({(d.kind, d.node_id) for d in diff_graphs(before, graph.nodes)} == expected, "standalone delta differs from effect")
    compact = format_compact_delta(graph, limit=80)
    _check(compact.startswith(graph.header_line()) and all(d.node_id in compact for d in list(deltas)[:80]), "compact projection drops revision or bounded identities")
    return {"nodes": count, "revision": graph.revision, "semanticHash": graph.semantic_hash}


def _archive(root, category, text):
    from .communication_archive import inspect_communication_archive, MAX_BODY_PREVIEW
    msg = EmailMessage()
    msg["Subject"] = text[:200] or "(no subject)"
    msg["From"] = "fixture@example.invalid"
    msg["To"] = "other@example.invalid"
    msg.set_content(text)
    payload = (text or "fixture").encode()
    msg.add_attachment(payload, maintype="application", subtype="octet-stream", filename="attachment-雪.bin")
    path = root / "message.eml"
    path.write_bytes(msg.as_bytes())
    result = inspect_communication_archive(path)
    expected_digest = hashlib.sha256(path.name.encode() + hashlib.sha256(path.read_bytes()).digest()).hexdigest()
    _check(result["sourceDigest"] == expected_digest, "archive source hash differs")
    row = result["messages"][0]
    _check(row["bodyPreview"] == " ".join(text.split())[:MAX_BODY_PREVIEW] and row["attachments"] == [{"filename": "attachment-雪.bin", "mediaType": "application/octet-stream", "bytes": len(payload)}], "MIME parse differs from generated original")
    _check(row["subject"] == msg["Subject"] and row["from"] == msg["From"] and row["to"] == msg["To"], "MIME headers differ from original")
    _check(result["messageCount"] == 1 and result["attachmentCount"] == 1 and not result["truncated"], "archive counts differ")
    return {"sourceDigest": result["sourceDigest"], "attachmentBytes": len(payload)}


def _browser(root, identity, category, text):
    from .neyvia_browser import BrowserService, BrowserError, web_url
    if identity.endswith("browser-url"):
        valid = "https://example.invalid/" + text.replace(" ", "%20")
        if category == "huge":
            invalids = [valid]
        else:
            _check(web_url(valid) == valid, "valid URL changed")
            invalids = ["", "file:///owned", "https://user:pass@example.invalid/", "https://example.invalid:wrong/"]
        for value in invalids:
            try:
                web_url(value)
            except (BrowserError, ValueError):
                continue
            raise AssertionError("invalid browser URL admitted")
        return {"rejected": len(invalids), "contactedNetwork": False}
    if category == "interrupted":
        import subprocess
        import sys
        command = [sys.executable, "-c",
                   "import os,sys; from grant_agent.neyvia_browser import BrowserService; "
                   "s=BrowserService(sys.argv[1]); s.request('runtime.connect',owner=True); "
                   "r=s.request('tab.open',{'url':'https://example.invalid/interrupted'}); "
                   "s.request('tab.grant',{'tabId':r['tabId'],'enabled':True},owner=True); os._exit(23)",
                   str(root.resolve())]
        child = subprocess.run(command, capture_output=True, timeout=40, **hidden_windows_subprocess_kwargs())
        _check(child.returncode == 23, "owned interrupted worker did not reach durable grant boundary")
        persisted = json.loads((root / ".neyvia/browser/state.json").read_text(encoding="utf-8"))
        _check(any(t["agentGranted"] for t in persisted["tabs"]), "worker never persisted an owner grant")
        restored = BrowserService(root)
        _check(restored.token is None and all(not t["agentGranted"] and not t["live"] for t in restored.state["tabs"]), "abruptly ended runtime retained restored authority")
        return {"childExit": child.returncode, "persistedOwnerGrant": True, "restoredGrants": 0, "restoredLiveTabs": 0}
    service = BrowserService(root)
    if identity.endswith("browser-authority"):
        if category == "offline":
            token = service.request("runtime.connect", owner=True)["token"]
            service.request("runtime.disconnect", owner=True)
            try:
                service.runtime({"op": "poll", "token": token})
            except BrowserError as exc:
                _check(exc.code == "invalid_runtime", "disconnected runtime capability refusal wrong")
            else:
                raise AssertionError("disconnected runtime retained authority")
            return {"runtimeDisconnected": True, "previousCapabilityRejected": True}
        if category == "stale":
            old = service.request("runtime.connect", owner=True)["token"]
            current = service.request("runtime.connect", owner=True)["token"]
            try:
                service.runtime({"op": "poll", "token": old})
            except BrowserError as exc:
                _check(exc.code == "invalid_runtime", "old capability refusal wrong")
            else:
                raise AssertionError("replaced capability retained runtime authority")
            _check(service.runtime({"op": "poll", "token": current})["ok"], "current capability refused")
            return {"oldCapabilityRejected": True, "currentCapabilityAccepted": True}
        if category == "concurrency":
            from concurrent.futures import ThreadPoolExecutor
            from threading import Barrier
            barrier = Barrier(2)
            def connect(_):
                barrier.wait(timeout=5)
                return service.request("runtime.connect", owner=True)["token"]
            with ThreadPoolExecutor(max_workers=2) as executor:
                tokens = list(executor.map(connect, range(2)))
            accepted = 0
            for token in tokens:
                try:
                    accepted += bool(service.runtime({"op": "poll", "token": token})["ok"])
                except BrowserError as exc:
                    _check(exc.code == "invalid_runtime", "competing capability refusal wrong")
            _check(accepted == 1 and len(set(tokens)) == 2, "competing runtime grants leave multiple writers")
            return {"competingGrants": 2, "activeGrants": accepted}
        for operation in ("runtime.connect", "runtime.disconnect", "headless.start", "headless.stop", "profile.create", "space.create", "tab.grant", "layout", "split", "peek"):
            before = json.dumps(service.state, sort_keys=True)
            try:
                service.request(operation, {"name": text}, owner=False)
            except BrowserError as exc:
                _check(exc.code == "owner_required" and json.dumps(service.state, sort_keys=True) == before, "owner denial changes state")
            else:
                raise AssertionError("model granted owner operation")
        return {"deniedOwnerOperations": 10}
    result = service.request("tab.open", {"url": "https://example.invalid/" + quote(text[:100])})
    _check(result["status"] == "queued" and not result["tab"]["live"] and not result["tab"]["agentGranted"], "queue claims native effect")
    if category == "concurrency":
        from .edge_fixture_local import _parallel
        queued = _parallel(lambda i: service.request("tab.open", {"url": f"https://example.invalid/owned-{i}"}), range(8))
        _check(len({row["actionId"] for row in queued}) == 8 and all(row["status"] == "queued" and not row["tab"]["live"] and not row["tab"]["agentGranted"] for row in queued), "Concurrent queued requests lost distinct pending actions or claimed execution")
    if category == "permissions":
        before = json.dumps(service.state, sort_keys=True)
        try:
            service.request("tab.grant", {"tabId": result["tabId"], "enabled": True}, owner=False)
        except BrowserError as error:
            _check(error.code == "owner_required" and json.dumps(service.state, sort_keys=True) == before, "Denied pending tab grant changed queued state")
        else:
            raise AssertionError("Pending browser operation gained owner grant")
    if category == "stale":
        old = service.request("runtime.connect", owner=True)["token"]
        service.request("runtime.connect", owner=True)
        try:
            service.runtime({"op": "poll", "token": old})
        except BrowserError as error:
            _check(error.code == "invalid_runtime", "Stale pending runtime refusal wrong")
        else:
            raise AssertionError("Stale native runtime adopted pending action")
        _check(all(not tab["live"] for tab in service.state["tabs"]), "Runtime handover promoted unobserved pending effects")
    if category == "offline":
        count = len(service.actions)
        try:
            service.request("wait", {"actionId": result["actionId"], "timeoutMs": 100})
        except BrowserError as exc:
            _check(exc.code == "action_timeout" and len(service.actions) == count, "offline timeout replayed effects or invented completion")
        else:
            raise AssertionError("offline native operation claimed completion")
    restored = BrowserService(root)
    _check(all(not t["live"] and not t["agentGranted"] and t["status"] == "runtime_needed" for t in restored.state["tabs"]), "restart retained native liveness or grant")
    return {"queued": result["actionId"], "restartTabs": len(restored.state["tabs"]), "contactedNetwork": False}


def run(root, contracts, categories):
    root = Path(root)
    rows = []
    graph_ids = {i for i in SUPPORTED if i.startswith("sv.ui.")}
    for category in categories:
        if category == "permissions" and "proofs-b.engine.skill-load" in contracts:
            rows.append(_locked_skill(root))
        extra = {
            "permissions": {"neyvia-core.browser-authority", "neyvia-core.browser-pending"},
            "stale": {"neyvia-core.browser-authority", "neyvia-core.browser-pending"},
            "concurrency": {"neyvia-core.browser-authority", "neyvia-core.browser-pending"},
            "offline": {"neyvia-core.browser-authority", "neyvia-core.browser-pending"},
            "interrupted": {"neyvia-core.browser-authority", "neyvia-core.browser-pending"},
        }
        identities = SUPPORTED if category in TEXTS else extra.get(category, set())
        text = TEXTS.get(category, "generated " + category)
        for identity in sorted(identities & set(contracts)):
            case_root = root / identity / category
            case_root.mkdir(parents=True, exist_ok=True)
            row = {"id": f"pure:{identity}:{category}", "category": category,
                   "contracts": [identity], "boundary": "owning production function, generated data and independently compared semantic result"}
            try:
                if identity in graph_ids:
                    detail = _graph(case_root, category, text)
                elif identity.startswith("providers."):
                    _provider(identity, text)
                    detail = {"characters": len(text)}
                elif identity.startswith("a-cli.catalog."):
                    _catalog(identity, text)
                    detail = {"characters": len(text)}
                elif identity.startswith("a-cli.archive."):
                    detail = _archive(case_root, category, text)
                elif identity == "a-cli.cursor.text":
                    from .cursor_bridge import _message_text
                    for field in ("content", "text", "result", "summary"):
                        _check(_message_text({field: text}) == text.strip(), "cursor fallback text changed")
                    _check(_message_text({"message": {"content": [{"type": "text", "text": text}, "suffix"]}}) == "\n".join([v for v in (text.strip(), "suffix") if v]), "cursor structured fragment order differs")
                    detail = {"characters": len(text)}
                elif identity == "proofs-b.engine.skill-load":
                    from .skill_library import SkillLibrary
                    path = case_root / "skills.json"
                    payload = [] if category == "empty" else [{"id": "generated", "text": text}]
                    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    _check(SkillLibrary._load_skill_rows(None, path) == payload, "skill records changed")
                    path.write_text("[1, null, \"not-an-object\"]", encoding="utf-8")
                    try:
                        invalid = SkillLibrary._load_skill_rows(None, path)
                    except ValueError as exc:
                        _check("Contract proofs-b.engine.skill-load:" in str(exc), "invalid skill list refusal came from an unrelated error")
                        invalid = []  # Explicit contract refusal is valid fail-closed behavior.
                    _check(invalid == [], "invalid skill object list admitted")
                    detail = {"characters": len(text), "invalidObjectListRefused": True}
                else:
                    detail = _browser(case_root, identity, category, text)
                row.update(status="passed", detail=detail)
            except Exception as exc:
                row.update(status="failed", detail=f"{type(exc).__name__}: {exc}")
            rows.append(row)
    return rows


def _locked_skill(root):
    """A real Windows sharing denial, confined to one generated fixture file."""
    import ctypes
    import os
    row = {"id": "pure:proofs-b.engine.skill-load:permissions", "category": "permissions",
           "contracts": ["proofs-b.engine.skill-load"],
           "boundary": "real Windows exclusive file handle denies production loader access"}
    if os.name != "nt":
        return {**row, "status": "blocked", "detail": "Windows exclusive sharing fixture is unavailable on this OS"}
    path = root / "locked-skill.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[{"id":"owned"}]', encoding="utf-8")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 0, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return {**row, "status": "failed", "detail": f"Exclusive fixture open failed with Windows error {ctypes.get_last_error()}"}
    try:
        from .skill_library import SkillLibrary
        result = SkillLibrary._load_skill_rows(None, path)
        _check(result == [], "unreadable skill file did not return empty records")
        row.update(status="passed", detail={"sharingDenied": True, "records": result})
    except Exception as exc:
        row.update(status="failed", detail=f"{type(exc).__name__}: {exc}")
    finally:
        kernel.CloseHandle(handle)
    return row
