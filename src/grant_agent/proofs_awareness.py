"""Work-board and impact-graph manual contracts checked by the local host."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


CONTRACTS = (
    "awareness.paths.overlap", "awareness.claim.persisted", "awareness.claim.refresh",
    "awareness.claim.overlaps", "awareness.release.persisted", "awareness.list.projection",
    "awareness.claim.staleness", "awareness.impact.gaps", "awareness.impact.command",
)


def _require(condition, identity, message):
    if not condition:
        raise ValueError(f"Contract {identity}: {message}")


def _relation(left, right):
    """Path components make prefix/suffix boundaries explicit in the contract."""
    a, b = (str(p).casefold().rstrip("/*") for p in (left, right))
    aa, bb = a.split("/"), b.split("/")
    if aa == bb or aa == bb[:len(aa)] or bb == aa[:len(bb)]:
        return True
    absolute_a, absolute_b = ":" in a[:3] or a.startswith("/"), ":" in b[:3] or b.startswith("/")
    if absolute_a != absolute_b:
        long, short = (aa, bb) if absolute_a else (bb, aa)
        return any(long[index:index + len(short)] == short for index in range(1, len(long)))
    return False


def check_overlap(left, right, result):
    _require(isinstance(result, bool) and result == _relation(left, right),
             "awareness.paths.overlap", "case-insensitive path component relation differs")


def _view_contract(record, view, root=None):
    from .neyvia_awareness import STALE_HOURS
    _require(all(view.get(k) == v for k, v in record.items()),
             "awareness.list.projection", "observer changed a persisted claim field")
    observed = datetime.now(timezone.utc)
    def minutes(timestamp):
        try:
            return max(0, int((observed - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds() // 60))
        except ValueError:
            return 0
    age = minutes(record.get("since", ""))
    inactivity = minutes(record.get("updatedAt") or record.get("since", ""))
    _require(isinstance(view.get("ageMinutes"), int) and abs(view["ageMinutes"] - age) <= 1,
             "awareness.claim.staleness", "claim age must retain the original start")
    # Observation can cross a minute boundary while the contract is executing.
    from .neyvia_awareness import _owner_live
    live = _owner_live(root, record) if root is not None else None
    allowed = {not live if live is not None else inactivity >= STALE_HOURS * 60}
    if live is None and inactivity == STALE_HOURS * 60:
        allowed.add(False)
    _require(view.get("stale") in allowed, "awareness.claim.staleness", "staleness must use latest refresh time")


def before(tool, args, root, *, locked=False):
    """Only inline callers holding the file lock take a mutation snapshot.

    Registry callers check response invariants; the definitive mutation proof
    runs inside the existing transaction to avoid racing another writer.
    """
    from . import neyvia_awareness as a
    return {"board": a._read(a.board_path(root))} if locked else {}


def after(tool, args, result, root, capture):
    from . import neyvia_awareness as a
    tool = tool.removeprefix("neyvia.")
    if tool == "work.list":
        if capture.get("board") is not None:
            check_list(args, result, capture["board"], root)
        else:
            _require(result.get("count") == len(result.get("claims", [])), "awareness.list.projection", "wrong claim count")
        return
    if tool not in {"work.claim", "work.release"}:
        return
    previous = capture.get("board")
    if previous is None:
        _require(result.get("ok") is True, "awareness.claim.persisted", "action did not report success")
        return
    current = a._read(a.board_path(root))
    if tool == "work.claim":
        raw = args.get("files")
        raw = [raw] if isinstance(raw, str) else raw
        files = list(dict.fromkeys(a._norm(value) for value in raw))
        agent = " ".join(str(args.get("agent") or "").split())[:80] or "agent"
        chat = str(args.get("chat") or "").strip()[:200] or None
        matching = next((r for r in previous["claims"] if r["agent"] == agent and r.get("chat") == chat
                         and {p.casefold().rstrip("/*") for p in r["files"]} == {p.casefold().rstrip("/*") for p in files}), None)
        view = result["claim"]
        record = next((r for r in current["claims"] if r["id"] == view["id"]), None)
        _require(record is not None, "awareness.claim.persisted", "returned claim was not persisted")
        _view_contract(record, view, root)
        _require(record["agent"] == agent and record.get("chat") == chat
                 and record["intent"] == " ".join(str(args.get("intent") or "").split()),
                 "awareness.claim.persisted", "persisted claimant or intent differs")
        refreshed_at = datetime.fromisoformat(record["updatedAt"].replace("Z", "+00:00"))
        _require(abs((datetime.now(timezone.utc) - refreshed_at).total_seconds()) < 60,
                 "awareness.claim.refresh", "successful claim did not refresh its activity timestamp")
        _require(result.get("refreshed") is (matching is not None),
                 "awareness.claim.refresh", "refresh must reuse a matching agent/chat/path claim")
        if matching:
            _require(record["id"] == matching["id"] and record["since"] == matching["since"]
                     and record["files"] == matching["files"],
                     "awareness.claim.refresh", "refresh changed identity, start or original file spelling")
            expected_rows = [record if r["id"] == matching["id"] else r for r in previous["claims"]]
        else:
            _require(record["files"] == files and not any(r["id"] == record["id"] for r in previous["claims"]),
                     "awareness.claim.persisted", "new claim has incorrect files or reused identity")
            expected_rows = previous["claims"] + [record]
        _require(current["claims"] == expected_rows and current["released"] == previous["released"],
                 "awareness.claim.persisted", "claim changed unrelated board entries")
        expected_overlaps = []
        for row in previous["claims"]:
            if a._view(row, root)["stale"]:
                continue
            if matching and row["id"] == matching["id"] or row["agent"] == agent and row.get("chat") == chat:
                continue
            shared = [p for p in row["files"] if any(_relation(p, f) for f in files)]
            if shared:
                expected_overlaps.append({"id": row["id"], "agent": row["agent"], "chat": row.get("chat"),
                                          "intent": row["intent"], "since": row["since"], "files": shared})
        _require(result.get("overlaps") == expected_overlaps, "awareness.claim.overlaps", "overlap receipts omitted or invented a claimant")
    else:
        identity = str(args.get("id") or "").strip()
        original = next((r for r in previous["claims"] if r["id"] == identity), None)
        _require(original is not None and current["claims"] == [r for r in previous["claims"] if r["id"] != identity],
                 "awareness.release.persisted", "release did not remove exactly one claim")
        _require(current["released"] and all(current["released"][0].get(k) == v for k, v in original.items())
                 and current["released"][1:] == previous["released"][:29],
                 "awareness.release.persisted", "release archive lost or changed claim history")
        _require(result.get("released") == identity and result.get("files") == original["files"],
                 "awareness.release.persisted", "release receipt differs from removed claim")


def check_list(args, result, board, root=None):
    from . import neyvia_awareness as a
    args = args or {}
    files = [a._norm(value) for value in (args.get("files") or [])]
    expected = [r for r in board["claims"] if (not files or any(_relation(p, f) for p in r["files"] for f in files))
                and (not args.get("agent") or r["agent"] == args["agent"])]
    expected.sort(key=lambda r: r["since"], reverse=True)
    views = result.get("claims", [])
    _require([r["id"] for r in views] == [r["id"] for r in expected] and result.get("count") == len(expected),
             "awareness.list.projection", "observer filter/order/count differs from persisted board")
    for row, view in zip(expected, views):
        _view_contract(row, view, root)
    _require(result.get("stale") == sum(r["stale"] for r in views)
             and result.get("recentlyReleased") == board["released"][:5]
             and result.get("staleAfterHours") == a.STALE_HOURS,
             "awareness.list.projection", "stale count or release history differs")


def check_gaps(idx, result):
    handled = set(idx["handled"]) | set(idx["bridgeFast"])
    ui, tauri = set(idx["ui"]), set(idx["tauri"])
    unused = set(idx["handled"]) - ui - tauri
    static_calls = set(idx["scripts"]) | set(idx["tests"])
    expected = {
        "uiWithoutHandler": ui - handled - tauri - set(idx["tauriDeclared"]),
        "nextUiMissingFromBridge": set(idx["nextUi"]) & handled - set(idx["bridge"]) - tauri,
        "bridgeWithoutHandler": set(idx["bridge"]) - handled,
        "tauriNotRegistered": set(idx["tauriDeclared"]) - tauri,
        "handlerWithoutCaller": unused - static_calls,
        "handlerOnlyScriptsOrTests": unused & static_calls,
    }
    for key, commands in expected.items():
        _require(result.get(key, {}).get("items") == sorted(commands), "awareness.impact.gaps", f"wrong wiring relation: {key}")


def check_command(idx, command, result):
    handler = idx["handled"].get(command) or ("desktop_bridge fastpath" if command in idx["bridgeFast"] else None)
    callers = sorted(idx["ui"].get(command, ()))
    bridge, tauri = command in idx["bridge"], command in idx["tauri"]
    expected = {"command": command, "ui": callers, "handler": handler, "bridge": bridge, "tauri": tauri,
                "tests": sorted(idx["tests"].get(command, ())), "manuals": sorted(idx["manuals"].get(command, ()))}
    missing = []
    if callers and not handler and not tauri:
        missing.append("no handler")
    if handler and not callers and not tauri:
        missing.append("no UI calls it")
    if command in idx["nextUi"] and handler and not bridge and not tauri:
        missing.append("not in the desktop bridge")
    _require(result == {**expected, "missing": missing}, "awareness.impact.command", "command receipt differs from wiring graph")


def self_check(root):
    from . import neyvia_awareness as a
    from . import neyvia_impact as i
    started = time.perf_counter()
    root = Path(root) / "awareness"
    _require(a.state_root(root) == root.resolve(), "awareness.claim.persisted",
             "scratch self-check requires NEYVIA_UI_STATE_ROOT to be unset")
    root.mkdir(parents=True, exist_ok=True)
    # The host supplies a scratch state root. Existing state is deliberately
    # retained, and distinct chat ids isolate these procedure claims.
    chat = "proof-" + str(time.time_ns())
    checks = []
    samples = [
        ("src/grant_agent/", "src/grant_agent/web_backend.py", True),
        ("C:/Users/user/Projects/nx/src/a.py", "src/a.py", True),
        ("Web/Src/X.jsx", "web/src/x.jsx", True),
        ("src/a.py", "src/ab.py", False),
        ("src/grant", "src/grant_agent/x.py", False),
    ]
    for left, right, expected in samples:
        _require(a.overlaps(left, right) is expected, "awareness.paths.overlap", "path grammar goal failed")
    checks.append({"contract": "awareness.paths.overlap", "ok": True, "calls": len(samples)})
    first = a.claim(root, {"files": ["src/x.py"], "intent": "first procedure", "agent": "proof-a", "chat": chat})
    second = a.claim(root, {"files": ["src/"], "intent": "overlapping procedure", "agent": "proof-b", "chat": chat})
    _require(first["claim"]["id"] in [r["id"] for r in second["overlaps"]], "awareness.claim.overlaps", "other claimant missing")
    again = a.claim(root, {"files": ["src/x.py"], "intent": "refreshed procedure", "agent": "proof-a", "chat": chat})
    _require(again["refreshed"] and again["claim"]["id"] == first["claim"]["id"], "awareness.claim.refresh", "refresh created duplicate")
    _require(a.board_list(root, {"files": ["src/x.py"], "agent": "proof-a"})["count"] == 1,
             "awareness.list.projection", "file/agent projection did not select claim")
    path = a.board_path(root)
    board = json.loads(path.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    next(r for r in board["claims"] if r["id"] == first["claim"]["id"]).update(since=old, updatedAt=old)
    path.write_text(json.dumps(board), encoding="utf-8")
    _require(a.board_list(root, {"agent": "proof-a"})["stale"] == 1, "awareness.claim.staleness", "old claim was not stale")
    refreshed = a.claim(root, {"files": ["src/x.py"], "intent": "still working", "agent": "proof-a", "chat": chat})
    _require(refreshed["claim"]["since"] == old and refreshed["claim"]["ageMinutes"] >= 780
             and not refreshed["claim"]["stale"], "awareness.claim.staleness", "refresh lost age or remained stale")
    a.release(root, {"id": first["claim"]["id"]})
    _require(a.board_list(root, {"agent": "proof-a"})["count"] == 0, "awareness.release.persisted", "released claim remained active")
    a.release(root, {"id": second["claim"]["id"]})
    checks += [{"contract": identity, "ok": True} for identity in CONTRACTS[1:7]]
    repo = root / "impact-repository"
    fixture = {
        "src/grant_agent/web_backend.py": "from .feature import FEATURE_COMMANDS\nclass B:\n    def dispatch(self, command, payload):\n        if command in FEATURE_COMMANDS:\n            from .feature import run\n            return run()\n        if command == 'orphan_command':\n            return 1\n",
        "src/grant_agent/feature.py": "FEATURE_COMMANDS = frozenset({'feature_list_command'})\n",
        "src/grant_agent/desktop_bridge.py": "ALLOWED_DESKTOP_COMMANDS = frozenset({'ghost_command'})\n",
        "src-tauri/src/lib.rs": "#[tauri::command]\nfn lonely_command() {}\ntauri::generate_handler![other]\n",
        "web/src/neyvia/next/nxFeature.js": "callNx('feature_list_command'); callNx('missing_command');\n",
    }
    for rel, text in fixture.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    idx = i._build(repo)
    gaps = i.find_gaps(idx)
    wanted = {"nextUiMissingFromBridge": ["feature_list_command"], "uiWithoutHandler": ["missing_command"],
              "bridgeWithoutHandler": ["ghost_command"], "tauriNotRegistered": ["lonely_command"],
              "handlerWithoutCaller": ["orphan_command"]}
    for category, commands in wanted.items():
        _require(gaps[category]["items"] == commands, "awareness.impact.gaps", f"real parser missed {category}")
    observed = i.impact(["src/grant_agent/feature.py"], gaps=False, repo=repo)
    row = observed["files"][0]["commands"][0]
    _require(row["command"] == "feature_list_command" and "not in the desktop bridge" in row["missing"],
             "awareness.impact.command", "impact call did not follow imported command set to UI/bridge")
    checks += [{"contract": identity, "ok": True} for identity in CONTRACTS[7:]]
    rejections = []
    bad_gaps = {**gaps, "uiWithoutHandler": {**gaps["uiWithoutHandler"], "items": []}}
    try:
        check_gaps(idx, bad_gaps)
    except ValueError:
        rejections.append({"contract": "awareness.impact.gaps", "rejected": True})
    else:
        raise ValueError("Contract awareness.impact.gaps: omitted gap was accepted")
    try:
        check_command(idx, row["command"], {**row, "bridge": True})
    except ValueError:
        rejections.append({"contract": "awareness.impact.command", "rejected": True})
    else:
        raise ValueError("Contract awareness.impact.command: invented bridge was accepted")
    return {"ok": True, "contracts": list(CONTRACTS), "checks": checks, "rejections": rejections,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "frontier": []}
