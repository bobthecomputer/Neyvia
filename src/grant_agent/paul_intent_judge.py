"""Deterministic judge for reading Paul's long messages into intent checklists.

Gold cases are written from the message text alone. The judge never calls a
model: an ask counts as found when every regex group matches one checklist
item's ask+quote; a misread is a known mishear left in an ask, a correction the
item ignores, or a scope he narrowed that the checklist widens. ``foundStrict``
additionally requires a distinct item per ask (added after the two no-manual
arms ran and before the manual existed, because long quotes let one item
cover several asks).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CASES = REPO / "config/paul_intent/cases.json"
SYSTEM_KINDS = ("build", "fix", "remove", "check", "explain", "plan", "decide")

# Strict transport for structured output: every field required, nothing extra.
TEXT = {"type": "string"}
CHECKLIST_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items", "dropped", "questions"],
    "properties": {
        "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["ask", "quote", "kind", "doneWhen", "status", "needsPaul"],
                                             "properties": {"ask": TEXT, "quote": TEXT, "kind": {"type": "string", "enum": list(SYSTEM_KINDS)},
                                                            "doneWhen": TEXT, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                                            "needsPaul": {"type": "boolean"}}}},
        "dropped": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["quote", "why"],
                                               "properties": {"quote": TEXT, "why": TEXT}}},
        "questions": {"type": "array", "items": TEXT}}}


def load_cases(path: Path = CASES) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {case["id"]: case for case in data["cases"]}


def _rx(pattern: str):
    return re.compile(pattern, re.I)


def _all(groups, text):
    return all(_rx(group).search(text) for group in groups)


def judge(case: dict, answer: dict) -> dict:
    """Score one checklist against one gold case; returns counts and the evidence for each decision."""
    items = [row for row in (answer.get("items") or []) if isinstance(row, dict)]
    asks_text = [str(row.get("ask", "")) for row in items]
    full_text = [str(row.get("ask", "")) + " || " + str(row.get("quote", "")) for row in items]
    found, missing, candidates = {}, [], {}
    for ask in case["asks"]:
        candidates[ask["id"]] = [index for index, text in enumerate(full_text) if _all(ask["groups"], text)
                                 and not (ask.get("not") and _rx(ask["not"]).search(asks_text[index]))]
        if candidates[ask["id"]]:
            found[ask["id"]] = candidates[ask["id"]][0]
        else:
            missing.append(ask["id"])
    # Strict reading: one checklist item per ask (maximum bipartite matching),
    # so one long item quoting half the message cannot cover several asks.
    owner = {}

    def assign(ask_id, seen):
        for index in candidates[ask_id]:
            if index in seen:
                continue
            seen.add(index)
            if index not in owner or assign(owner[index], seen):
                owner[index] = ask_id
                return True
        return False
    strict = sum(assign(ask["id"], set()) for ask in case["asks"])
    mishears = []
    for row in case.get("mishears", []):
        bad = [index for index, text in enumerate(asks_text) if _rx(row["wrong"]).search(text)]
        if bad:
            mishears.append({"heard": row["heard"], "items": bad})
    honoured, violated = [], []
    for row in case.get("corrections", []):
        kind = row["type"]
        ok = True
        if kind in ("absent", "absent_unless"):
            offenders = [i for i, text in enumerate(asks_text) if _all(row["match"], text)
                         and not (kind == "absent_unless" and _rx(row["unless"]).search(text))]
            ok = not offenders
        elif kind in ("scope", "scope_any"):
            related = [i for i, text in enumerate(full_text) if _all(row["match"], text)]
            def scoped(i):
                return ((kind == "scope" and items[i].get("kind") in row.get("kinds", []))
                        or bool(_rx(row["or_text"]).search(asks_text[i])))
            ok = bool(related) and all(scoped(i) for i in related) if kind == "scope" else all(scoped(i) for i in related)
        elif kind == "max_items":  # a repeated passage must not double the checklist
            ok = bool(items) and len(items) <= row["limit"]
        elif kind == "kinds_share":
            share = sum(item.get("kind") in row["kinds"] for item in items) / max(len(items), 1)
            ok = bool(items) and share >= row["min_share"]
        else:
            raise ValueError("Unknown correction type " + kind)
        (honoured if ok else violated).append(row["id"])
    return {"case": case["id"], "asks": len(case["asks"]), "found": len(found), "foundStrict": strict, "missing": missing,
            "emptyChecklist": not items,
            "items": len(items), "corrections": len(case.get("corrections", [])), "honoured": len(honoured),
            "violated": violated, "mishearMisreads": len(mishears), "mishears": mishears,
            "misreads": len(mishears) + len(violated), "dropped": len(answer.get("dropped") or []),
            "questions": len(answer.get("questions") or [])}
