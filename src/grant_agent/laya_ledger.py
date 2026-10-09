"""Receipts for every routine decision LAYA answered or handed up, plus computer-use activity.

One append-only JSON-lines file per workspace (.neyvia/laya/decisions.jsonl). Rows are written at the
point a decision is made (cascade System 1 stage, browser decide, taste triage, the Laya native
computer-use workflow), never reconstructed, and the report only aggregates what was recorded.
Token savings are an estimate and are labelled as one.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTCOMES = ("answered", "escalated", "unavailable", "bypassed", "deterministic")
MAX_BYTES = 6 * 1024 * 1024
KEEP_BYTES = 2 * 1024 * 1024
OUTPUT_TOKENS_AVOIDED = 80  # a small structured answer from the big model
_LOCK = threading.Lock()

# Where LAYA sits in each gate. "consulted" rows are recorded here; the rest are stated honestly.
WIRING = [
    {"gate": "Cascade routine decisions", "laya": "consulted", "decisions": "System 1 stage before the cache and the small/big model; exact-value prompts bypass it"},
    {"gate": "Browser decide (page_done, relevance, next_action)", "laya": "consulted", "decisions": "typed advisory answer from the attached LAYA service; unavailable falls back to the checked model"},
    {"gate": "Taste review (check triage)", "laya": "consulted", "decisions": "warn/note findings: model repair needed or ship as is; blocking findings stay deterministic"},
    {"gate": "Computer use (named Laya workflow)", "laya": "consulted", "decisions": "neyvia_desktop_navigation run, receipt-verified; arbitrary driver actions are deterministic and not routed"},
    {"gate": "Computer use (cua driver actions)", "laya": "not-consulted", "decisions": "deterministic driver calls with the zero-disturbance guard; counted below, no model decision to answer"},
    {"gate": "Connected Language host", "laya": "consulted", "decisions": "verified learned intent/layer routing preloads manual help; translation and validation retain their checks"},
]


def _dir(root) -> Path:
    return Path(root).resolve() / ".neyvia" / "laya"


def estimate_tokens(chars: int) -> int:
    return max(0, math.ceil(chars / 4)) + OUTPUT_TOKENS_AVOIDED


def record(root, *, task: str, path: str, decision: str, outcome: str, latency_ms: float = 0.0,
           confidence: float | None = None, prompt_chars: int = 0, detail: str = "", **extra: Any) -> dict:
    """Append one decision receipt. Never raises: a broken ledger must not break the gate."""
    if outcome not in OUTCOMES:
        outcome = "unavailable"
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "task": str(task)[:80] or "unscoped",
           "path": str(path)[:80], "decision": str(decision)[:120], "outcome": outcome,
           "latencyMs": round(float(latency_ms), 2),
           "confidence": None if confidence is None else round(float(confidence), 4),
           "tokensSavedEstimate": estimate_tokens(prompt_chars) if outcome == "answered" else 0,
           "detail": str(detail)[:200], **extra}
    try:
        folder = _dir(root)
        with _LOCK:
            folder.mkdir(parents=True, exist_ok=True)
            file = folder / "decisions.jsonl"
            if file.is_file() and file.stat().st_size > MAX_BYTES:
                data = file.read_bytes()[-KEEP_BYTES:]
                data = data[data.find(b"\n") + 1:]
                file.write_bytes(data)
            with file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def classify_browser(result: Any) -> tuple[str, float | None, str]:
    """Outcome of a browser decide result without trusting its shape."""
    if not isinstance(result, dict):
        return "unavailable", None, "no result"
    if result.get("available") is False:
        return "unavailable", None, str(result.get("reason") or result.get("status") or "")[:160]
    decision = result.get('decision')
    if isinstance(decision, dict):
        policy = decision.get('browser_policy') or decision.get('decision_policy')
        if isinstance(policy, dict) and policy.get('policy') not in {'answer', 'answer+postcheck'}:
            return 'escalated', policy.get('confidence'), str(policy.get('reason', ''))
        if isinstance(decision.get('answers'), dict):
            return classify_browser(decision)
    answers = result.get("answers")
    if isinstance(answers, dict) and answers:
        policies = [a.get("policy") for a in answers.values() if isinstance(a, dict)]
        probs = [a.get("top_probability") for a in answers.values() if isinstance(a, dict) and isinstance(a.get("top_probability"), (int, float))]
        # "answer+postcheck" is an answer the caller verifies afterwards; "escalate" is handed up.
        outcome = "answered" if policies and all(isinstance(p, str) and p.startswith("answer") for p in policies) else "escalated"
        return outcome, (min(probs) if probs else None), "postcheck required" if any(p == "answer+postcheck" for p in policies) else ""
    decision = result.get("decision")
    if decision is None:
        return "escalated", None, "no decision returned"
    if isinstance(decision, dict) and (decision.get("escalate") is True or decision.get("policy") not in (None, "answer")):
        return "escalated", None, ""
    return "answered", None, ""


def rows(root, limit: int = 5000) -> list[dict]:
    file = _dir(root) / "decisions.jsonl"
    if not file.is_file():
        return []
    with file.open("rb") as stream:
        stream.seek(max(0, file.stat().st_size - 3 * 1024 * 1024))
        text = stream.read().decode("utf-8", errors="replace")
    out = []
    for line in text.splitlines()[-limit:]:
        try:
            value = json.loads(line)
            if isinstance(value, dict) and "outcome" in value:
                out.append(value)
        except ValueError:
            continue
    return out


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _group(items: list[dict]) -> dict:
    counts = {name: sum(1 for r in items if r["outcome"] == name) for name in OUTCOMES}
    laya_asked = counts["answered"] + counts["escalated"]
    latencies = [r["latencyMs"] for r in items if r["outcome"] in {"answered", "escalated"} and isinstance(r.get("latencyMs"), (int, float))]
    return {**counts, "total": len(items), "answerRate": round(counts["answered"] / laya_asked, 4) if laya_asked else None,
            "p50Ms": _percentile(latencies, .5), "p95Ms": _percentile(latencies, .95),
            "tokensSavedEstimate": sum(int(r.get("tokensSavedEstimate") or 0) for r in items),
            "lastAt": items[-1]["at"] if items else None}


def computer_use(root) -> dict:
    """Aggregate the computer-use receipts the CUA service already writes; nothing is invented."""
    base = Path(root).resolve()
    receipts = base / ".neyvia" / "cua" / "receipts.jsonl"
    summary: dict[str, Any] = {"driver": _driver(), "actions": 0, "byAgent": 0, "byPaul": 0, "refused": 0, "disturbances": 0,
                               "avgMs": None, "lastAt": None, "topTools": [], "apps": [], "sessions": 0, "activeSessions": 0,
                               "agentDesktop": {"backgroundSessions": 0, "foregroundSessions": 0}, "layaWorkflowRuns": 0,
                               "layaWorkflowVerified": 0}
    actions = {"click", "double_click", "right_click", "type_text", "press_key", "hotkey", "scroll", "drag", "set_value", "invoke_menu", "launch_app"}
    if receipts.is_file():
        with receipts.open("rb") as stream:
            stream.seek(max(0, receipts.stat().st_size - 3 * 1024 * 1024))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()[-2000:]
        tools: dict[str, int] = {}
        apps: dict[str, int] = {}
        times: list[float] = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("tool") not in actions:
                continue
            summary["actions"] += 1
            if row.get("by") == "agent":
                summary["byAgent"] += 1
            elif row.get("by") in {"paul", "remote"}:
                summary["byPaul"] += 1
            if row.get("status") in {"refused", "failed"}:
                summary["refused"] += 1
            pres = row.get("preservation")
            if isinstance(pres, dict) and (pres.get("foregroundPreserved") is False or pres.get("cursorPreserved") is False):
                summary["disturbances"] += 1
            if isinstance(row.get("ms"), (int, float)) and row["ms"] > 0:
                times.append(row["ms"])
            tools[row["tool"]] = tools.get(row["tool"], 0) + 1
            if row.get("app"):
                apps[str(row["app"])] = apps.get(str(row["app"]), 0) + 1
            summary["lastAt"] = row.get("at")
        summary["avgMs"] = round(sum(times) / len(times), 1) if times else None
        summary["topTools"] = [{"tool": k, "count": v} for k, v in sorted(tools.items(), key=lambda kv: -kv[1])[:5]]
        summary["apps"] = [{"app": k, "count": v} for k, v in sorted(apps.items(), key=lambda kv: -kv[1])[:5]]
    sessions_file = base / ".neyvia" / "cua" / "sessions.json"
    if sessions_file.is_file():
        try:
            sessions = json.loads(sessions_file.read_text(encoding="utf-8")).get("sessions", [])
        except (OSError, ValueError):
            sessions = []
        summary["sessions"] = len(sessions)
        summary["activeSessions"] = sum(1 for s in sessions if s.get("status") == "active")
        summary["agentDesktop"] = {"backgroundSessions": sum(1 for s in sessions if not s.get("foreground")),
                                   "foregroundSessions": sum(1 for s in sessions if s.get("foreground"))}
    runs = base / ".agent_control" / "laya_runs"
    if runs.is_dir():
        for file in list(runs.glob("*.json"))[-200:]:
            summary["layaWorkflowRuns"] += 1
            try:
                value = json.loads(file.read_text(encoding="utf-8"))
                if value.get("status") == "completed" and value.get("reason") == "postcondition_verified":
                    summary["layaWorkflowVerified"] += 1
            except (OSError, ValueError):
                pass
    return summary


_DRIVER_CACHE: dict[str, Any] = {"at": 0.0, "value": None}


def _driver() -> dict:
    """Driver readiness by presence of both pinned executables (hash proof lives in cua_upstream)."""
    if time.monotonic() - _DRIVER_CACHE["at"] < 30 and _DRIVER_CACHE["value"] is not None:
        return _DRIVER_CACHE["value"]
    from .cua_upstream import MISSING_REASON, runtime_candidates
    present = any(all((directory / name).is_file() for name in ("cua-driver.exe", "cua-driver-uia.exe"))
                  for directory in runtime_candidates())
    value = {"name": "cua-driver (MIT Windows)", "available": present,
             "reason": None if present else MISSING_REASON}
    _DRIVER_CACHE.update(at=time.monotonic(), value=value)
    return value


def service_status() -> dict:
    """Is a LAYA service running and answering, and if not, why. Never raises."""
    import urllib.request
    from .laya_host import status as host_status
    host = host_status()
    url = os.environ.get("NEYVIA_LAYA_URL", "").rstrip("/") or (f"http://127.0.0.1:{host['port']}" if host.get("ready") else "")
    base = {"host": host, "owned": bool(host.get("owned"))}
    if not url:
        state = host.get("state")
        return {**base, "configured": state not in {"disabled", "not-started"}, "ready": False,
                "status": {"starting": "starting", "restarting": "restarting"}.get(state, "unavailable" if state != "disabled" else "disabled"),
                "reason": host.get("reason") or "LAYA is not running"}
    try:
        with urllib.request.urlopen(url + "/v1/health", timeout=2) as response:
            ready = json.load(response).get("status") == "ready"
        return {**base, "configured": True, "ready": ready, "status": "ready" if ready else "service_unavailable", "endpoint": url,
                "reason": "" if ready else "The service answered but is not ready"}
    except Exception:
        return {**base, "configured": True, "ready": False, "status": "service_unavailable", "endpoint": url,
                "reason": "The LAYA service is not answering on " + url}


def report(root, *, recent: int = 12, probe_service: bool = True) -> dict:
    from .laya_host import WARMING_UP, instant_ready
    if instant_ready():
        from .laya_instant import store
        if probe_service:
            from .laya_instant_ingest import watch
            watch(root)
        instant = store(str(root)).status()
    else:
        # The report never waits on the background warmup (it holds the store while loading).
        instant = {"warming": True, "reason": WARMING_UP}
    items = rows(root)
    by_task: dict[tuple[str, str], list[dict]] = {}
    for row in items:
        by_task.setdefault((row["task"], row["path"]), []).append(row)
    tasks = sorted(({"task": task, "path": path, **_group(group)} for (task, path), group in by_task.items()),
                   key=lambda t: t["lastAt"] or "", reverse=True)
    gates = []
    for gate in WIRING:
        gates.append({**gate})
    return {"ok": True, "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "service": service_status() if probe_service else None,
            "totals": _group(items), "tasks": tasks[:20], "recent": items[-recent:][::-1], "wiring": gates,
            "computerUse": computer_use(root), "instant": instant,
            "boundary": "Counts come from receipts written when each decision was made. Token savings are an estimate "
                        "(prompt length / 4 plus a small answer the larger model did not have to write); latency is LAYA's own round trip."}
