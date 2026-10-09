"""Generative provider fixtures on owned files, pipes and operating-system locks.

No fixture reads the user's provider configuration or starts an installed CLI.
Exact bindings deliberately separate transcript owners from live provider RPCs.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TEXTS = {"empty": "", "huge": "x" * 180000, "unicode": "雪🙂e\u0301 العربية\u202e\x00"}
TRANSFORMS = {"providers.claude.argv", "providers.terminal.argv", "providers.terminal.screen",
              "providers.claude.environment", "providers.codex.input", "providers.codex.integrations"}
TRANSCRIPTS = {"providers.claude.read_bytes", "providers.claude.store_page",
               "providers.claude.sequence", "providers.claude.title_priority"}
ADAPTER_READ = {"providers.claude.page", "providers.claude.summary", "providers.claude.context", "providers.claude.media"}
SUPPORTED = TRANSFORMS | TRANSCRIPTS | ADAPTER_READ | {"providers.claude.aggregate", "providers.claude.request",
                                      "providers.terminal.hook", "providers.process.hidden",
                                      "providers.codex.lock"}


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity in TRANSFORMS and category not in TEXTS:
        return {"kind": "not_applicable", "reason":
                f"Audited {identity} at {contract.get('checkedAt')}: this owner transforms supplied "
                "values in memory without a revision, grant, process or network operation. "
                f"{category} belongs to a different provider lifecycle contract."}
    if identity == "providers.claude.aggregate" and category in {"permissions", "offline", "interrupted"}:
        return {"kind": "not_applicable", "reason":
                "AgentAggregate.feed/summarize consume already observed records in memory; "
                "they do not open sidechain files, start workers or contact a provider. "
                f"The {category} boundary belongs to the transcript/lifecycle owner."}
    if identity in SUPPORTED:
        return {"kind": "fixture_not_implemented", "reason":
                f"The owned provider builder has no real {category} effect/refusal fixture for "
                f"{identity}; checked owner {contract.get('checkedAt')}. This is an implementation gap."}
    return None


def _check(value, message):
    if not value:
        raise AssertionError(message)


def _transform(root, identity, category):
    from .connected_sessions import claude_stream as cs, claude_terminal as terminal
    from .connected_sessions.codex import _build_input, build_integrations
    from .connected_sessions.model import TurnOptions
    text = TEXTS[category]
    if identity in {"providers.claude.argv", "providers.terminal.argv"}:
        prefix = [sys.executable, str(root / "literal peer.py")]
        for resume in (False, True):
            for opts in (TurnOptions(), TurnOptions(fork_from="source"),
                         TurnOptions(model="fixture-model", effort="high", permission_mode="default")):
                if identity.endswith("terminal.argv"):
                    result = terminal.terminal_argv(prefix, "chosen", resume, opts, root / "settings.json", text)
                    _check(result[-2:] == ["--", text], "terminal message was split or reinterpreted")
                    _check("-p" not in result, "terminal selected print mode")
                else:
                    result = cs.build_argv(prefix, "chosen" if resume else None, opts, extra_args=["--", text])
                    _check(result[-2:] == ["--", text], "extra literal arguments changed")
                    _check(result[result.index("--permission-prompt-tool")+1] == "stdio", "approval transport changed")
                _check(result[:2] == prefix, "executable prefix changed")
                if opts.permission_mode:
                    _check(result[result.index("--permission-mode")+1] == "manual", "default permission translation changed")
        for field in ("model", "effort", "permission_mode"):
            opts = TurnOptions(**{field: "--inject\n" + text})
            try:
                if identity.endswith("terminal.argv"):
                    terminal.terminal_argv(prefix, "chosen", False, opts, root / "settings.json", text)
                else:
                    cs.build_argv(prefix, None, opts)
            except cs.ClaudeSessionError as exc:
                _check(exc.code == "invalid_option", "invalid option got wrong refusal")
            else:
                raise AssertionError("malformed option accepted")
    elif identity == "providers.terminal.screen":
        raw = "\x1b[2J" + text + "\x1b[1Ctail\r\n\x1b[0m"
        result = terminal.screen_text(raw)
        expected = " ".join((text + " tail").split())
        _check(result == expected and "\x1b" not in result, "ANSI/cursor projection changed text")
    elif identity == "providers.claude.environment":
        result = cs.child_env({"C7B_LITERAL": text, "CLAUDE_CODE_DISABLE_THINKING": "1", "MAX_THINKING_TOKENS": "0"})
        _check(result["C7B_LITERAL"] == text and "CLAUDE_CODE_DISABLE_THINKING" not in result
               and "MAX_THINKING_TOKENS" not in result, "per-child option scrub changed")
        _check(not any(k in result for k in cs._HOST_SESSION_ENV), "outer host identity inherited")
    elif identity == "providers.codex.input":
        image = {"mime": "image/png", "data": base64.b64encode(b"owned image").decode()}
        expected = ([{"type": "text", "text": text, "text_elements": []}] if text else []) + [
            {"type": "image", "url": "data:image/png;base64," + image["data"]}]
        _check(_build_input(text, [image]) == expected, "text/image payload bytes changed")
        _check(_build_input(text, []) == expected[:-1], "text-only payload changed")
    else:
        count = 0 if category == "empty" else 350 if category == "huge" else 3
        plugins = [{"id": f"plugin-{i}", "name": text + str(i), "installed": i % 2 == 0}
                   for i in range(count)]
        servers = [{"name": f"server-{i}", "pluginId": f"plugin-{i}",
                    "runtimeStatus": "disabled" if i % 3 == 0 else "failed" if i % 3 == 1 else "ready",
                    "tools": {}} for i in range(count)]
        rows, states, _ = build_integrations({"marketplaces": [{"plugins": plugins}]}, servers, [])
        _check(len(states) == count and len({r["id"] for r in rows}) == len(rows), "integration IDs duplicated")
        _check(all(r["id"] in {"plugin:" + p["id"] for p in plugins if p["installed"]} for r in rows
                   if r["kind"] == "plugin"), "uninstalled plugin advertised")
        _check([r["state"] for r in states] == ["disabled" if i % 3 == 0 else "error" if i % 3 == 1 else "connected" for i in range(count)], "observed server states changed")
    return {"characters": len(text), "literalInputSha256": hashlib.sha256(text.encode()).hexdigest()}


def _record(index, text):
    return {"type": "user", "uuid": f"user-{index}", "sessionId": "owned-session",
            "timestamp": "2026-10-04T12:00:00Z", "message": {"role": "user", "content": text}}


def _encoded(records):
    return b"".join((json.dumps(r, ensure_ascii=False) + "\n").encode() for r in records)


def _transcript(root, category):
    from .connected_sessions import claude_transcript as ct
    path = root / "owned-session.jsonl"
    text = TEXTS.get(category, "observed text")
    if category == "huge":
        text = text[:12000]  # A real >5MiB transcript forces bounded tail paging.
    count = 450 if category == "huge" else 0 if category == "empty" else 12
    records = [_record(i, f"{text} {i}") for i in range(count)]
    raw = _encoded(records)
    path.write_bytes(raw)
    store = ct.ItemStore(path, "owned-session")
    items, earlier, cursor = store.page(cursor=None, before_seq=None, limit=200)
    _check(len(items) == min(200, count) and earlier is (count > 200), "tail bound/frontier changed")
    expected_ids = [r["uuid"] for r in records[-200:]]
    _check([i.id for i in items] == expected_ids, "page changed source item identities")
    offsets, consumed = ct.split_records(raw, 0)
    _check(consumed == len(raw), "complete records not consumed")
    expected_seqs = {r["uuid"]: ct.ItemStore._seq(offset) for offset, r in offsets}
    _check(all(i.seq == expected_seqs[i.id] for i in items), "byte-derived sequence changed")
    _check(ct.read_bytes(path, 3, min(len(raw), 79)) == raw[3:min(len(raw), 79)], "read exceeded exact byte slice")
    index = ct.SummaryIndex(path, "owned-session")
    index.refresh()
    for kind, key, expected in (("ai-title", "aiTitle", "AI 雪"), ("summary", "summary", "Summary 🙂"),
                                 ("custom-title", "customTitle", "Custom e\u0301")):
        with path.open("ab") as stream:
            stream.write(_encoded([{"type": kind, key: expected}]))
        index.refresh()
        _check(index.title == expected, "append title priority changed")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as executor:
            pages = list(executor.map(lambda _: store.page(cursor=None, before_seq=None, limit=200), range(24)))
        _check(all([(i.id, i.seq) for i in p[0]] == [(i.id, i.seq) for i in pages[0][0]] for p in pages), "parallel page observes unstable IDs/sequences")
    elif category == "stale":
        replacement = _encoded([_record(999, "new generation")])
        path.write_bytes(replacement)
        new, _, fresh = store.page(cursor=cursor, before_seq=None, limit=200)
        _check([i.id for i in new] == ["user-999"] and fresh != cursor, "stale cursor suppresses new generation")
        index.refresh()
        _check(index.title == "new generation", "summary retained stale custom title after rewrite")
    elif category == "interrupted":
        # Kill a genuine writer after fsync of an incomplete line, then complete that line.
        payload = _encoded([_record(1000, "completed after interrupted writer")])
        part = payload[:40]
        program = "import os,sys,time;f=open(sys.argv[1],'ab');f.write(bytes.fromhex(sys.argv[2]));f.flush();os.fsync(f.fileno());print('written',flush=True);time.sleep(60)"
        child = subprocess.Popen([sys.executable, "-c", program, str(path), part.hex()], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
        try:
            _check(child.stdout.readline().strip() == "written", "writer failed before durable partial line")
            child.kill(); child.wait(timeout=10)
            before, _, initial = store.page(cursor=None, before_seq=None, limit=200)
            _check("user-1000" not in [i.id for i in before], "partial interrupted line became an item")
            with path.open("ab") as stream:
                stream.write(payload[40:])
            delta, _, _ = store.page(cursor=initial, before_seq=None, limit=200)
            _check([i.id for i in delta] == ["user-1000"], "completed partial line not delivered exactly once")
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
    return {"fileBytes": path.stat().st_size, "initialRecords": count, "tailItems": len(items),
            "byteSliceExact": True, "sequenceOffsetsExact": True, "titlePriorityFromDisk": True,
            **({"oldCursor": cursor, "replacementCursor": fresh} if category == "stale" else {})}


def _aggregate(root, category):
    from .connected_sessions.claude_transcript import AgentAggregate
    count = 5000 if category == "huge" else 0 if category == "empty" else 11
    agg = AgentAggregate()
    text = TEXTS.get(category, "later observation")
    if category == "huge":
        text = text[:128]  # Thousands of unique messages, without quadratic fixture memory.
    for i in range(count):
        record = {"type": "assistant", "message": {"id": f"{text}-{i}", "content": [],
                  "usage": {"input_tokens": i+2, "cache_read_input_tokens": 3, "output_tokens": 7}}}
        agg.feed(record); agg.feed(record)
    initial = agg.summarize({})
    _check(initial["outputTokens"] == (7 * count if count else None), "duplicate blocks double counted output")
    _check(initial["inputTokens"] == (count + 4 if count else None), "input context accumulated")
    if category == "stale":
        later = agg.summarize({"syncResult": False, "totals": {"outputTokens": 999, "inputTokens": 555}})
        _check((later["outputTokens"], later["inputTokens"]) == (999, 555), "authoritative final totals retained stale partial values")
    return {"observedRecords": count * 2, "outputTokens": initial["outputTokens"], "inputTokens": initial["inputTokens"]}


def _adapter_read(root, category):
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.claude_items import collapse
    config = root / "owned-config"
    project = config / "projects" / "owned-project"
    project.mkdir(parents=True)
    sid = "owned-session"
    path = project / (sid + ".jsonl")
    peer = root / "inventory-peer.py"
    peer.write_text("print('[]')\n", encoding="utf-8")
    config.joinpath("settings.json").write_text('{"autoCompactWindow":80000}', encoding="utf-8")
    text = TEXTS.get(category, "observed prompt")
    if category == "huge":
        text = text[:12000]
    image = b"\x89PNG\r\n\x1a\n" + (b"owned" * 140000 if category == "huge" else "雪🙂".encode())
    first = _record(0, [{"type": "text", "text": text}, {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": base64.b64encode(image).decode()}}])
    first.update(cwd=str(root), gitBranch="owned-branch")
    assistant = {"type": "assistant", "uuid": "assistant-row", "sessionId": sid,
                 "timestamp": "2026-10-04T12:01:00Z", "cwd": str(root), "gitBranch": "owned-branch",
                 "message": {"id": "message-one", "model": "owned-model", "content": [{"type": "text", "text": "answer"}],
                             "usage": {"input_tokens": 8, "cache_read_input_tokens": 11,
                                       "cache_creation_input_tokens": 13, "output_tokens": 9}}}
    records = [first, assistant]
    if category == "huge":
        records += [_record(i+1, f"{text} {i}") for i in range(400)]
        # Latest usage must actually be inside the bounded observation window.
        records.append({**assistant, "uuid": "latest-assistant", "timestamp": "2026-10-04T12:02:00Z",
                        "message": {**assistant["message"], "id": "latest-message"}})
    path.write_bytes(_encoded(records))
    host = {"deviceId": "owned-device", "deviceName": "Owned fixture"}
    def make():
        return ClaudeAdapter(config_dir=config, cli_path=[sys.executable, str(peer)], host=host, context_probe=False)
    reader = make()
    page = reader.read(sid, limit=200)
    _check(page.session.cwd == str(root) and page.session.git_branch == "owned-branch"
           and page.session.model == "owned-model", "summary substituted transcript metadata")
    _check(page.session.title == (collapse(text.strip(), 120) if text.strip() else "Untitled session"), "summary title differed from first source prompt")
    _check(page.context.used_tokens == 32 and page.context.window_tokens is None
           and page.context.auto_compact_tokens == 80000, "context invented usage/window or ignored explicit threshold")
    _check(len(page.items) <= 200 and [i.seq for i in page.items] == sorted(i.seq for i in page.items)
           and len({i.id for i in page.items}) == len(page.items), "adapter page duplicated/unsorted items")
    # Huge tail paging deliberately evicts the initial image; the owner scans it on demand.
    from .connected_sessions.claude_items import image_token
    token = image_token("image/png", first["message"]["content"][1]["source"]["data"])
    media = reader.read_media(sid, token)
    _check(media is not None and media[:2] == (image, "image/png"), "opaque media handle changed source bytes")
    _check(make().read_media(sid, token)[:2] == (image, "image/png"), "fresh adapter could not resolve durable image")
    _check(reader.read_media(sid, "") is None and reader.read_media(sid, "../outside") is None
           and reader.read_media(sid, "0"*64) is None, "unknown/malformed token was substituted")
    if category == "stale":
        replacement = _record(999, "new generation prompt")
        replacement.update(cwd=str(root), gitBranch="new-branch")
        path.write_bytes(_encoded([replacement]))
        fresh = reader.read(sid, cursor=page.cursor)
        _check([i.id for i in fresh.items] == ["user-999"] and fresh.session.git_branch == "new-branch"
               and fresh.session.title == "new generation prompt" and fresh.context.used_tokens is None,
               "stale adapter observation hid replacement transcript")
        _check(reader.read_media(sid, token) is None, "old media token survived source replacement")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            reads = list(pool.map(lambda _: reader.read(sid), range(24)))
        snapshot = [(i.id, i.seq) for i in page.items]
        _check(all([(i.id, i.seq) for i in r.items] == snapshot and r.context.used_tokens == 32
                   and r.session.title == page.session.title for r in reads), "concurrent adapter reads changed observations")
        with ThreadPoolExecutor(max_workers=8) as pool:
            media_rows = list(pool.map(lambda _: reader.read_media(sid, token), range(24)))
        _check(all(r[:2] == (image, "image/png") for r in media_rows), "concurrent media lookup changed bytes")
    return {"sourceFileBytes": path.stat().st_size, "boundedPageItems": len(page.items),
            "imageBytes": len(image), "imageSha256": hashlib.sha256(image).hexdigest(),
            "metadataContextAndMediaFromRealTranscript": True, "inventoryPeerOnly": True,
            **({"oldCursor": page.cursor, "replacementCursor": fresh.cursor} if category == "stale" else {})}


def _request(root, category):
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.claude_stream import ClaudeSessionError
    from .connected_sessions.model import TurnOptions
    adapter = ClaudeAdapter(config_dir=root / "synthetic-config", cli_path=[sys.executable, "owned-peer.py"],
                            host={"deviceId": "owned-device", "deviceLabel": "Fixture"}, context_probe=False)
    text, code = ("", "empty_message") if category == "empty" else ("x" * 100001, "message_too_long")
    events = []
    try:
        adapter.start_turn(None, text, TurnOptions(), cwd=str(root), run_id="refused", emit=events.append)
    except ClaudeSessionError as exc:
        _check(exc.code == code and not events and not adapter._runs, "invalid input started a run or got wrong code")
    else:
        raise AssertionError("invalid message accepted")
    return {"refusalCode": code, "runEvents": len(events), "startedRuns": len(adapter._runs)}


def _hook(root, category):
    from .connected_sessions import claude_hook
    text = TEXTS.get(category, "person decision")
    spool = root / "spool"
    spool.mkdir(parents=True, exist_ok=True)
    data = {"tool_use_id": "owned", "literal": text}
    payload = json.dumps(data).encode()
    command = [sys.executable, str(Path(claude_hook.__file__).resolve()), str(spool), "permission" if category in {"stale", "interrupted", "permissions"} else "observed"]
    if category == "permissions":
        (spool / "decisions").mkdir()
        (spool / "decisions" / "owned.json").write_text(json.dumps({"behavior": "deny", "message": text}), encoding="utf-8")
    elif category == "stale":
        (spool / "decisions").mkdir()
        (spool / "decisions" / "old-request.json").write_text('{"behavior":"allow"}', encoding="utf-8")
    def invoke(_):
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
        if category in {"stale", "interrupted"}:
            child.stdin.write(payload); child.stdin.close()
            deadline = time.monotonic()+10
            while not list((spool / "events").glob("*.json")) and time.monotonic() < deadline:
                time.sleep(.01)
            _check(child.poll() is None, "waiting hook consumed stale decision or exited early")
            if category == "interrupted":
                child.kill()
            else:
                (spool / "closed").write_text("closed", encoding="utf-8")
            child.wait(timeout=10)
            output, errors = child.stdout.read(), child.stderr.read()
            _check(output == b"" and errors == b"", "abandoned hook emitted a person decision")
        else:
            output, errors = child.communicate(payload, timeout=15)
            _check(child.returncode == 0 and errors == b"", "hook process failed")
            if category == "permissions":
                _check(json.loads(output) == {"behavior": "deny", "message": text}, "hook changed saved explicit refusal")
            else:
                _check(output == b"", "non-waiting hook emitted decision")
        return child.returncode
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(invoke, range(16)))
    else:
        codes = [invoke(0)]
    events = list((spool / "events").glob("*.json"))
    _check(len(events) == len(codes) and all(json.loads(p.read_text(encoding="utf-8")) == {"event": command[-1], "requestId": "owned", "data": data} for p in events), "durable hook receipt differs or competing events lost")
    _check(not list((spool / "events").glob("*.tmp")), "hook retained active write temporary")
    return {"realProcesses": len(codes), "durableEvents": len(events), "exitCodes": codes}


def _process(root, category):
    from .connected_sessions.claude_stream import start_process, child_env
    text = TEXTS.get(category, "owned child")
    program = "import sys;data=sys.stdin.buffer.read();sys.stdout.buffer.write(data);sys.stderr.buffer.write(b'owned-error')"
    child = start_process([sys.executable, "-c", program], str(root), child_env())
    output, error = child.communicate(text.encode(), timeout=15)
    _check(child.returncode == 0 and output == text.encode() and error == b"owned-error", "hidden child changed piped bytes")
    return {"stdoutSha256": hashlib.sha256(output).hexdigest(), "stdoutBytes": len(output), "exitCode": child.returncode,
            "pipedStdinStdoutStderr": True, "windowsHiddenFlagsCheckedByOwner": os.name == "nt"}


def _writer_lock(root, category):
    from .connected_sessions.codex_writer import active_writer
    home = root / "owned-codex-home"
    rollout = home / "sessions" / "owned.jsonl"
    rollout.parent.mkdir(parents=True, exist_ok=True)
    rollout.write_bytes(b"owned rollout, never opened by lock observer")
    directory = home / "thread-writer-locks"
    directory.mkdir()
    identity = "雪🙂e\u0301" if category == "unicode" else "owned-thread"
    if category in {"empty", "huge"}:
        invalid = "" if category == "empty" else "x" * 600
        _check(active_writer(invalid, str(rollout)) is None, "invalid/unobservable ID was reported as writable")
        _check(not list(directory.iterdir()), "ownership probe created a lock file")
        return {"identityCharacters": len(invalid), "ownership": "unknown", "createdLocks": 0}
    path = directory / (identity + ".lock")
    path.write_bytes(b"1")
    _check(active_writer(identity, str(rollout)) is False, "released lock remained owned")
    if category == "unicode":
        _check(path.read_bytes() == b"1", "Unicode lock probe changed lock bytes")
        return {"unicodeIdentityExact": True, "ownership": "released", "unchangedLockBytes": True}
    program = ("import os,sys,time;f=open(sys.argv[1],'r+b');"
               "import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);"
               "print('locked',flush=True);time.sleep(60)") if os.name == "nt" else (
               "import sys,time,fcntl;f=open(sys.argv[1],'r+b');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);"
               "print('locked',flush=True);time.sleep(60)")
    child = subprocess.Popen([sys.executable, "-c", program, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
    try:
        _check(child.stdout.readline().strip() == "locked", "owned writer could not obtain actual OS lock")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: active_writer(identity, str(rollout)), range(24)))
            _check(results == [True] * 24, "parallel lock observations disagree")
        else:
            _check(active_writer(identity, str(rollout)) is True, "real writer not observed")
        child.kill(); child.wait(timeout=10)
        _check(active_writer(identity, str(rollout)) is False, "dead writer retained stale OS ownership")
        _check(path.read_bytes() == b"1", "ownership observer mutated lock bytes")
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
    return {"ownedWriterExit": child.returncode, "observedHeldThenReleased": True,
            "unchangedLockBytes": True, "parallelObservations": 24 if category == "concurrency" else 1}


def run(root, contracts, categories):
    root = Path(root) / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    families = [("transform", TRANSFORMS, set(TEXTS), _transform),
                ("transcript", TRANSCRIPTS, set(TEXTS) | {"stale", "concurrency", "interrupted"}, _transcript),
                ("aggregate", {"providers.claude.aggregate"}, set(TEXTS) | {"stale"}, _aggregate),
                ("adapter-read", ADAPTER_READ, set(TEXTS) | {"stale", "concurrency"}, _adapter_read),
                ("request", {"providers.claude.request"}, {"empty", "huge"}, _request),
                ("hook", {"providers.terminal.hook"}, set(TEXTS) | {"stale", "concurrency", "interrupted", "permissions"}, _hook),
                ("process", {"providers.process.hidden"}, set(TEXTS), _process),
                ("writer-lock", {"providers.codex.lock"}, set(TEXTS) | {"concurrency", "interrupted", "stale"}, _writer_lock)]
    for family, bindings, accepted, builder in families:
        bindings = sorted(bindings & set(contracts))
        if not bindings:
            continue
        for category in categories:
            if category not in accepted:
                continue
            # Transforms have distinct invariants. Stateful families exercise their shared real file once.
            groups = [[identity] for identity in bindings] if family == "transform" else [bindings]
            for group in groups:
                if family == "transcript" and category in {"concurrency", "interrupted"}:
                    group = [identity for identity in group if identity != "providers.claude.title_priority"]
                identity = group[0]
                case_root = root / family / category / identity
                case_root.mkdir(parents=True, exist_ok=True)
                row = {"id": f"provider:{family}:{category}:{identity}", "category": category,
                       "contracts": group, "boundary": "production provider owner; synthetic data; owned local files/pipes only"}
                try:
                    detail = builder(case_root, identity, category) if family == "transform" else builder(case_root, category)
                    row.update(status="passed", detail=detail)
                except Exception as exc:
                    row.update(status="failed", detail=f"{type(exc).__name__}: {exc}")
                rows.append(row)
    return rows
