"""Token and plan-usage analytics for the Usage pane (GET /api/ui/usage).

Nothing here is a new meter. Plan windows come from the limits readers that already exist
(connected_sessions.live_limits / plan_limits). Tokens come from the records the apps already keep:
Claude Code transcripts (usage block per message), Codex rollouts (token_count events), OpenCode's local
database (one row per assistant message) and Neyvia's own agent turns in the conversation store. Only usage
numbers, model names and timestamps are read, never message text, and never a credential store. Per-file
results are cached by (size, mtime) so a warm call is a dictionary slice.

Counting method (checked against the sources, 8 Oct):
- Claude Code: one count per message id across all files (a streamed message repeats; a resumed session repeats
  earlier messages in its own file). Output includes thinking tokens, as the API bills them.
- Codex: one count per model request, from the per-request token_count (repeated events are skipped). The sum
  matches each file's final running total to within 0.01 %.
- OpenCode: one count per assistant message; its input excludes cache, so cache reads and writes are added back
  to make input include cached tokens like every other source. Reasoning tokens count as output.

Money: every row that has a price on file gets an API-equivalent estimate (what the same tokens would cost at
public API list prices from config/model_prices.json: input, cache reads, cache writes and output priced
separately). Plan traffic (Claude Code, Codex and OpenCode logins) is only ever API-equivalent, never billed.
Only rows that went through an API key also carry billedUsd. A model with no price on file stays unpriced.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WINDOW_DAYS = 31
RANGES = {"day": 1, "week": 7, "month": 30}
_PRICES = Path(__file__).resolve().parents[2] / "config" / "model_prices.json"
_lock = threading.Lock()
_state: dict[str, Any] = {}
_hour_days: dict[str, str] = {}
# [input incl. cache, cache read, output, cache write 5m, cache write 1h]
_ZERO = (0, 0, 0, 0, 0)


def _prices() -> dict[str, Any]:
    try:
        return json.loads(_PRICES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"providers": {}, "opencodeBilling": {}, "models": {}, "_provenance": {}}


def _day(stamp: str) -> str | None:
    """Local calendar day of an ISO timestamp, memoised per UTC hour."""
    key = stamp[:13]
    day = _hour_days.get(key)
    if day is None:
        try:
            day = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date().isoformat()
        except ValueError:
            return None
        _hour_days[key] = day
    return day


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _scan_claude(path: str, *, timestamps: bool = False) -> dict[str, list]:
    """message id -> [day, model, input incl. cache, cache read, output, write 5m, write 1h]; the last line of a streamed message wins."""
    found: dict[str, list] = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if '"usage"' not in line or '"assistant"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            parsed = claude_usage_entry(entry, fallback_id=len(found), timestamps=timestamps)
            if parsed:
                identity, row = parsed
                found[identity] = row
    return found


def claude_usage_entry(entry: dict, *, fallback_id=0, timestamps=False):
    """Shared Usage/Night Shift interpretation of a real Claude assistant usage record."""
    message = entry.get("message")
    if entry.get("type") != "assistant" or not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
        return None
    model, usage, stamp = message.get("model"), message["usage"], entry.get("timestamp")
    if not isinstance(model, str) or model.startswith("<") or not isinstance(stamp, str):
        return None
    day = _day(stamp)
    if not day:
        return None
    read, write = _int(usage.get("cache_read_input_tokens")), _int(usage.get("cache_creation_input_tokens"))
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    write_1h = min(write, _int(split.get("ephemeral_1h_input_tokens")))
    identity = str(message.get("id") or entry.get("uuid") or fallback_id)
    row = [day, model, _int(usage.get("input_tokens")) + read + write, read,
           _int(usage.get("output_tokens")), write - write_1h, write_1h]
    return identity, row + [stamp] if timestamps else row


def _scan_codex(path: str, *, timestamps: bool = False) -> list[list]:
    """[day, model, input incl. cached, cached, output, 0, 0] per model request; repeated token_count events are skipped."""
    rows: list[list] = []
    model, previous = "unknown", None
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if '"token_count"' in line:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                payload = entry.get("payload") or {}
                info = payload.get("info")
                if payload.get("type") != "token_count" or not isinstance(info, dict):
                    continue
                total = (info.get("total_token_usage") or {}).get("total_tokens")
                if total is not None and total == previous:
                    continue
                previous = total
                last = info.get("last_token_usage") or {}
                day = _day(entry["timestamp"]) if isinstance(entry.get("timestamp"), str) else None
                if day and (last.get("input_tokens") or last.get("output_tokens")):
                    rows.append([day, model, _int(last.get("input_tokens")), _int(last.get("cached_input_tokens")), _int(last.get("output_tokens")), 0, 0])
                    if timestamps:
                        rows[-1].append(entry["timestamp"])
            elif '"turn_context"' in line:
                try:
                    found = (json.loads(line).get("payload") or {}).get("model")
                except ValueError:
                    continue
                if isinstance(found, str) and found:
                    model = found
    return rows


def _opencode_rows(database: Path, since_ms: int, *, timestamps: bool = False) -> list[list]:
    """OpenCode's assistant messages: [day, provider, model, input incl. cache, cache read, output, write, 0]. Read-only; the
    credential and account tables are never touched."""
    if not database.is_file():
        return []
    rows = []
    try:
        db = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            query = ("SELECT time_created, json_extract(data,'$.providerID'), json_extract(data,'$.modelID'), json_extract(data,'$.tokens.input'), "
                     "json_extract(data,'$.tokens.output'), json_extract(data,'$.tokens.reasoning'), json_extract(data,'$.tokens.cache.read'), "
                     "json_extract(data,'$.tokens.cache.write') FROM message WHERE time_created >= ? AND json_extract(data,'$.role')='assistant'")
            for created, provider, model, inp, out, reasoning, read, write in db.execute(query, (since_ms,)):
                read, write = _int(read), _int(write)
                total_in, total_out = _int(inp) + read + write, _int(out) + _int(reasoning)
                if not (total_in or total_out) or not model:
                    continue
                day = datetime.fromtimestamp(created / 1000, timezone.utc).astimezone().date().isoformat()
                rows.append([day, str(provider or "opencode"), str(model), total_in, read, total_out, write, 0])
                if timestamps:
                    rows[-1].append(datetime.fromtimestamp(created / 1000, timezone.utc).isoformat())
        finally:
            db.close()
    except (sqlite3.Error, OSError, ValueError):
        return []
    return rows


def _native_rows(root: Path, since: str, *, timestamps: bool = False) -> list[list]:
    """Neyvia's own agent turns: [day, provider, model, input, cached, output]. A missing store or missing usage is simply absent."""
    path = root / ".agent_control" / "crashproof.sqlite3"
    if not path.exists():
        return []
    rows = []
    try:
        db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            query = ("SELECT created_at, json_extract(metadata_json,'$.runtimeResult.route.provider'), "
                     "json_extract(metadata_json,'$.runtimeResult.route.model'), "
                     "COALESCE(json_extract(metadata_json,'$.runtimeResult.raw.usage'), json_extract(metadata_json,'$.turnReceipt.usage')) "
                     "FROM conversation_turns WHERE created_at >= ? AND json_extract(metadata_json,'$.runtimeResult.runtime')='neyvia-agent'")
            for stamp, provider, model, usage in db.execute(query, (since,)):
                try:
                    usage = json.loads(usage) if isinstance(usage, str) else None
                except ValueError:
                    usage = None
                day = _day(stamp) if isinstance(stamp, str) else None
                if not day or not isinstance(usage, dict):
                    continue
                inp, out = _int(usage.get("inputTokens")), _int(usage.get("outputTokens"))
                if inp or out:
                    rows.append([day, str(provider or "neyvia"), str(model or "unknown"), inp, min(inp, _int(usage.get("cachedInputTokens"))), out])
                    if timestamps:
                        rows[-1].append(stamp)
        finally:
            db.close()
    except sqlite3.Error:
        return []
    return rows


def _files(pattern: str, cutoff: float) -> list[tuple[str, int, float]]:
    out = []
    for path in glob.glob(pattern):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            out.append((path, stat.st_size, stat.st_mtime))
    return out


def _stores(home: Path | None) -> dict[str, Path]:
    from .external_chat_inventory import _paths
    return _paths(home)


def _scan(root: Path, home: Path | None) -> None:
    """Refresh per-file caches, then rebuild the aggregate. Runs on a background thread; the report never waits for it."""
    cutoff = time.time() - WINDOW_DAYS * 86400
    stores = _stores(home)
    claude = _files(str(stores["claude-code"] / "*" / "*.jsonl"), cutoff) + _files(str(stores["claude-code"] / "*" / "*" / "subagents" / "*.jsonl"), cutoff)
    codex = _files(str(stores["codex"] / "*" / "*" / "*" / "*.jsonl"), cutoff)
    progress = {"done": 0, "total": len(claude) + len(codex)}
    with _lock:
        _state["scan"] = {"active": True, **progress}
        files = _state.setdefault("files", {})
    for kind, listing in (("claude", claude), ("codex", codex)):
        for path, size, mtime in listing:
            cached = files.get(path)
            if not cached or cached[0] != size or cached[1] != mtime:
                try:
                    data = _scan_claude(path, timestamps=True) if kind == "claude" else _scan_codex(path, timestamps=True)
                except OSError:
                    data = {} if kind == "claude" else []
                files[path] = (size, mtime, kind, data)
            progress["done"] += 1
            if progress["done"] % 8 == 0:
                with _lock:
                    _state["scan"] = {"active": True, **progress}
    live = {item[0] for item in claude + codex}
    for path in [p for p in files if p not in live]:
        files.pop(path, None)
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT00:00:00")
    totals: dict[tuple, list] = {}
    timed = []
    session_tokens = {}

    def record(stamp, inp, cached, out):
        timed.append((stamp, max(0, inp - cached) + out))

    def add(day, provider, agent, model, billing, inp, cached, out, write5, write1):
        cell = totals.setdefault((day, provider, agent, model, billing), [0, 0, 0, 0, 0])
        cell[0] += inp
        cell[1] += cached
        cell[2] += out
        cell[3] += write5
        cell[4] += write1

    prices = _prices()
    seen: set[str] = set()
    for _path, (_s, _m, kind, data) in sorted(files.items()):
        if kind == "claude":
            for ident, (day, model, inp, cached, out, write5, write1, stamp) in data.items():
                if ident in seen:
                    continue
                seen.add(ident)
                record(stamp, inp, cached, out)
                # Claude Code on a Claude model runs on the Claude login; another vendor's model means it was pointed at something else.
                add(day, "anthropic" if model.startswith("claude") else "other", "claude-code", model, "plan" if model.startswith("claude") else "unknown", inp, cached, out, write5, write1)
        else:
            for day, model, inp, cached, out, write5, write1, stamp in data:
                record(stamp, inp, cached, out)
                add(day, "openai", "codex", model, "plan", inp, cached, out, write5, write1)
        values = list(data.values()) if kind == "claude" else data
        session_tokens[Path(_path).stem] = sum(max(0, r[2] - r[3]) + r[4] for r in values)
    billing = prices.get("opencodeBilling", {})
    for day, provider, model, inp, cached, out, write, _, stamp in _opencode_rows(_stores(home)["opencode"], int((time.time() - WINDOW_DAYS * 86400) * 1000), timestamps=True):
        record(stamp, inp, cached, out)
        add(day, provider, "opencode", model, billing.get(provider, "unknown"), inp, cached, out, write, 0)
    providers = prices.get("providers", {})
    for day, provider, model, inp, cached, out, stamp in _native_rows(root, since, timestamps=True):
        record(stamp, inp, cached, out)
        add(day, provider, "neyvia-agent", model, providers.get(provider, {}).get("billing", "unknown"), inp, cached, out, 0, 0)
    with _lock:
        _state.update(totals=totals, timed=timed, sessionTokens=session_tokens, built=time.time(), scan={"active": False, **progress})


def overview_usage(root: Path) -> dict[str, Any]:
    """Last-hour new tokens from Usage's existing file caches and shared scan."""
    _ensure(Path(root), None, 0)
    with _lock:
        timed, built = list(_state.get("timed") or []), _state.get("built")
        session_tokens = dict(_state.get("sessionTokens") or {})
    cutoff, total = time.time() - 3600, 0
    for stamp, tokens in timed:
        try:
            if cutoff <= datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() <= time.time():
                total += tokens
        except (TypeError, ValueError):
            continue
    return {"newTokensLastHour": total if built else None, "usageObservedAt": built, "sessionNewTokens": session_tokens,
            "usageScope": "This PC; the same transcript and receipt scan as Usage"}


def _ensure(root: Path, home: Path | None, wait: float) -> None:
    with _lock:
        thread = _state.get("thread")
        running = thread is not None and thread.is_alive()
        if not running and time.time() - _state.get("started", 0) > 120:
            thread = threading.Thread(target=_scan, args=(root, home), name="usage-scan", daemon=True)
            _state.update(thread=thread, started=time.time())
            thread.start()
        have = "totals" in _state
    if wait and thread is not None and not have:
        thread.join(wait)


_DATE = re.compile(r"-\d{8}$")


def base_model(model: str, table: dict[str, Any] | None = None) -> str:
    """Spelling-independent id: vendor prefix, [1m], a date suffix and a -free tier suffix are dropped; aliases resolve through the price file."""
    name = model.lower().split("[", 1)[0].lstrip("~").rsplit("/", 1)[-1]
    name = _DATE.sub("", name)
    name = name.removesuffix(":free").removesuffix("-free")
    if table:
        for ident, record in table.items():
            if name == ident or name in [alias.lower() for alias in record.get("aliases", [])]:
                return ident
    return name


def price_for(model: str, prices: dict[str, Any]) -> dict[str, Any] | None:
    record = prices.get("models", {}).get(base_model(model, prices.get("models", {})))
    if not record or record.get("input") is None or record.get("output") is None:
        return None
    return record


def api_equivalent(model: str, inp: int, cached: int, out: int, write5: int, write1: int, prices: dict[str, Any]) -> dict[str, float] | None:
    """What these tokens would cost at API list price, each kind priced separately; None when the model has no price on file."""
    price = price_for(model, prices)
    if price is None:
        return None
    cached_rate = price.get("cached") if price.get("cached") is not None else price["input"]
    write5_rate = price.get("cacheWrite") if price.get("cacheWrite") is not None else price["input"]
    write1_rate = price.get("cacheWrite1h") if price.get("cacheWrite1h") is not None else write5_rate
    fresh = max(0, inp - cached - write5 - write1)
    parts = {"input": fresh * price["input"] / 1e6, "cached": cached * cached_rate / 1e6,
             "cacheWrite": (write5 * write5_rate + write1 * write1_rate) / 1e6, "output": out * price["output"] / 1e6}
    parts["total"] = sum(parts.values())
    return {key: round(value, 4) for key, value in parts.items()}


def _plans(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from .connected_sessions.live_limits import existing_service
    from .connected_sessions.plan_limits import all_limits
    live = existing_service(root)
    if live is not None:
        snap = live.snapshot()
        rows, providers = snap["limits"], snap["providers"]
    else:
        rows, providers = all_limits(root), []
    keys = ("app", "window", "label", "usedPercent", "resetsAt", "source", "status", "stale", "availability", "at")
    now = datetime.now(timezone.utc)

    def passed(row):  # a window whose reset time is behind us has reset since it was read: the percentage no longer describes it
        try:
            return datetime.fromisoformat(str(row.get("resetsAt")).replace("Z", "+00:00")) <= now
        except ValueError:
            return False

    return [{**{key: row.get(key) for key in keys}, "stale": bool(row.get("stale")) or passed(row), "resetPassed": passed(row)} for row in rows], \
           [{key: item.get(key) for key in ("app", "status", "checkedAt", "error")} for item in providers]


_TOP = ("ok", "range", "days", "generatedAt", "scan", "plans", "providers", "totals", "byDay", "rows", "cost", "savings", "windowDays")
_ROW = ("agent", "provider", "model", "billing", "input", "cached", "cacheWrite", "output", "cacheShare", "apiEquivUsd", "billedUsd")


def check_report(value: dict[str, Any]) -> None:
    """Contracts usage.endpoint.shape and usage.plan.api-equivalent-only. Raises ``ValueError`` naming the first breach."""
    missing = [key for key in _TOP if key not in value]
    if missing:
        raise ValueError(f"usage report is missing {', '.join(missing)}")
    if value["range"] not in RANGES or len(value["byDay"]) != RANGES[value["range"]]:
        raise ValueError("usage report: byDay must hold one entry per day of the range")
    cost = value["cost"]
    if cost.get("estimate") is not True or not cost.get("pricesChecked"):
        raise ValueError("usage report: cost must be flagged as an estimate with the date the prices were taken")
    api_rows = [row for row in value["rows"] if row["billing"] == "api"]
    for row in value["rows"]:
        if any(key not in row for key in _ROW):
            raise ValueError("usage report: a model row lacks a field")
        if row["billing"] != "api" and row["billedUsd"] is not None:
            raise ValueError(f"usage report: {row['agent']} {row['model']} is {row['billing']} traffic and must never be shown as billed")
        if row["billing"] == "api" and row["billedUsd"] != row["apiEquivUsd"]:
            raise ValueError(f"usage report: {row['agent']} {row['model']} is billed to a key and must be billed at its list price")
        if row["cached"] + row["cacheWrite"] > row["input"]:
            raise ValueError("usage report: cached and cache-write tokens are subsets of input tokens")
    if cost.get("billedTotalUsd") is not None and not api_rows:
        raise ValueError("usage report: a billed total with no API-key traffic")
    billed = round(sum(row["billedUsd"] or 0 for row in api_rows), 4)
    if cost.get("billedTotalUsd") is not None and abs(cost["billedTotalUsd"] - billed) > 0.01:
        raise ValueError("usage report: the billed total is not the sum of the API-key rows")
    equivalent = round(sum(row["apiEquivUsd"] or 0 for row in value["rows"]), 4)
    if cost.get("apiEquivalentTotalUsd") is not None and abs(cost["apiEquivalentTotalUsd"] - equivalent) > 0.01:
        raise ValueError("usage report: the API-equivalent total is not the sum of the rows")
    for plan in value["plans"]:
        percent = plan.get("usedPercent")
        if percent is not None and not 0 <= percent <= 100:
            raise ValueError("usage report: a plan window percentage outside 0 to 100")


def report(root: Any, range_name: str = "week", *, home: Path | None = None, wait: float = 0.0) -> dict[str, Any]:
    root = Path(root)
    range_name = range_name if range_name in RANGES else "week"
    days = RANGES[range_name]
    _ensure(root, home, wait)
    plans, provider_status = _plans(root)
    with _lock:
        totals = dict(_state.get("totals") or {})
        scan = dict(_state.get("scan") or {"active": True, "done": 0, "total": 0})
        built = _state.get("built")
    return assemble(totals, plans, provider_status, range_name, scan, built)


def assemble(totals: dict[tuple, list], plans: list[dict[str, Any]], provider_status: list[dict[str, Any]], range_name: str,
             scan: dict[str, Any], built: float | None) -> dict[str, Any]:
    """Turn (day, provider, agent, model, billing) -> token counts into the endpoint reply and check it. The capture scripts use it with
    injected counts; the product only ever feeds it what the scans found."""
    range_name = range_name if range_name in RANGES else "week"
    days = RANGES[range_name]
    prices = _prices()
    today = datetime.now().astimezone().date()
    by_day: dict[str, dict[str, list[int]]] = {(today - timedelta(days=i)).isoformat(): {} for i in range(days)}
    rows: dict[tuple, list[int]] = {}
    for (day, provider, agent, model, billing), (inp, cached, out, write5, write1) in totals.items():
        if day not in by_day:
            continue
        cell = by_day[day].setdefault(agent, [0, 0, 0])
        cell[0] += inp
        cell[1] += cached
        cell[2] += out
        row = rows.setdefault((agent, provider, model, billing), [0, 0, 0, 0, 0])
        for index, amount in enumerate((inp, cached, out, write5, write1)):
            row[index] += amount
    table, unpriced, saved_equiv, saved_billed = [], set(), 0.0, 0.0
    for (agent, provider, model, billing), (inp, cached, out, write5, write1) in rows.items():
        parts = api_equivalent(model, inp, cached, out, write5, write1, prices)
        price = price_for(model, prices)
        if parts is None:
            unpriced.add(model)
        else:
            saved = cached * (price["input"] - (price.get("cached") if price.get("cached") is not None else price["input"])) / 1e6
            saved_equiv += saved
            saved_billed += saved if billing == "api" else 0.0
        table.append({"agent": agent, "provider": provider, "model": model, "billing": billing, "input": inp, "cached": cached,
                      "cacheWrite": write5 + write1, "output": out, "cacheShare": round(cached / inp, 4) if inp else None,
                      "apiEquivUsd": parts["total"] if parts else None, "apiEquivParts": parts,
                      "billedUsd": parts["total"] if parts and billing == "api" else None,
                      "price": {key: price.get(key) for key in ("input", "cached", "cacheWrite", "cacheWrite1h", "output", "sourceUrl", "checked")} if price else None})
    table.sort(key=lambda row: (-(row["apiEquivUsd"] or 0), -(row["input"] + row["output"])))
    inp_sum, cached_sum, out_sum = (sum(row[key] for row in table) for key in ("input", "cached", "output"))
    priced_tokens = sum(row["input"] + row["output"] for row in table if row["apiEquivUsd"] is not None)
    all_tokens = inp_sum + out_sum
    api_rows = [row for row in table if row["billing"] == "api"]
    meta = prices.get("_provenance", {})
    share = round(cached_sum / inp_sum, 4) if inp_sum else None
    priced = [row for row in table if row["apiEquivUsd"] is not None]
    result = {
        "ok": True, "range": range_name, "days": days, "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scan": {**scan, "builtAt": built}, "plans": plans, "providers": provider_status,
        "totals": {"input": inp_sum, "cached": cached_sum, "output": out_sum, "cacheShare": share},
        "byDay": [{"day": day, "agents": {name: {"input": v[0], "cached": v[1], "output": v[2]} for name, v in sorted(cells.items())}}
                  for day, cells in sorted(by_day.items())],
        "rows": table,
        "cost": {"estimate": True, "currency": "USD", "unit": "USD per million tokens, public API list price", "pricesChecked": meta.get("checked"),
                 "apiEquivalentTotalUsd": round(sum(row["apiEquivUsd"] for row in priced), 4) if priced else None,
                 "apiEquivalentParts": {key: round(sum(row["apiEquivParts"][key] for row in priced), 4) for key in ("input", "cached", "cacheWrite", "output")} if priced else None,
                 "billedTotalUsd": round(sum(row["billedUsd"] or 0 for row in api_rows), 4) if api_rows else None, "apiRows": len(api_rows),
                 "pricedShare": round(priced_tokens / all_tokens, 4) if all_tokens else None,
                 "unpricedModels": sorted(unpriced), "note": meta.get("note")},
        "savings": {"cacheShare": share, "cachedTokens": cached_sum,
                    "apiEquivalentSavedUsd": round(saved_equiv, 4) if priced else None,
                    "billedSavedUsd": round(saved_billed, 4) if api_rows else None},
        "windowDays": WINDOW_DAYS,
        "notes": ["Tokens come from Claude Code transcripts, Codex session logs, OpenCode's local database and Neyvia agent turns on this PC (last 31 days).",
                  "Plan traffic is only ever API-equivalent: what the same tokens would cost at public API list prices. It is not billed to you."],
    }
    check_report(result)
    return result
