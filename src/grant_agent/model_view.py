"""What a tool result looks like to the model: the facts it needs, not the audit envelope around them.

Every tool result is replayed in every later request of a chat. The native receipt envelope (contract ids it
passed, a static boundary paragraph, absolute receipt paths, hashes) and the tool-search catalog (aliases,
capabilities, per-row call instructions, a second copy of every description) made a 6-byte file read cost 2 KB and
a tool search cost 11 KB for the rest of the conversation. The complete, unmodified result still goes to the receipt
file on disk and to every host-side check; only the string handed to the model is reduced.
Set NEYVIA_FULL_TOOL_RECEIPTS=1 to hand the model the full envelope again.
"""
from __future__ import annotations

import os
import re
from typing import Any

RECEIPT_SCHEMA = "fluxio.native_tool_receipt.v1"
SEARCH_SCHEMA = "neyvia.agent-tool-search/v1"
_ENVELOPE_DROP = {"receipt_path", "operationReceiptPath", "actionReceiptPath", "argument_snapshot_boundary",
                  "provider", "schema", "created_at", "duration_ms", "arguments", "receiptHash", "proofs"}
_EMPTY = ("", None, [], {})
DESCRIPTION_CHARS = 180
COMPILED_DESCRIPTION_CHARS = 80


def _first_sentence(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:stop + 1] if stop > limit // 2 else cut.rstrip() + "...")


def slim_receipt(value: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key in _ENVELOPE_DROP:
            continue
        if key in ("error", "failure", "artifacts") and item in _EMPTY:
            continue
        out[key] = item
    proofs = value.get("proofs")
    if isinstance(proofs, dict) and isinstance(proofs.get("checked"), list):
        out["contractsChecked"] = len(proofs["checked"])
    return out


def slim_search(value: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for tool in value.get("native") or []:
        if not isinstance(tool, dict):
            continue
        row: dict[str, Any] = {"name": tool.get("name"), "about": _first_sentence(tool.get("description"), DESCRIPTION_CHARS)}
        if tool.get("category"):
            row["category"] = tool["category"]
        if tool.get("requires_approval"):
            row["approval"] = True
        if tool.get("actionIdRequired"):
            row["actionId"] = True
        if tool.get("allowedInRun") is False:
            row["allowed"] = False
        if tool.get("available") is False:
            row["unavailable"] = tool.get("availabilityDetail") or True
        default_call = "Pass this exact name as tool_id and its schema fields as arguments_json. Use a stable action_id for mutations."
        if tool.get("callInstructions") and tool["callInstructions"] != default_call:
            row["note"] = tool["callInstructions"]
        if tool.get("capturePolicy"):
            row["capturePolicy"] = tool["capturePolicy"]
        rows.append(row)
    out: dict[str, Any] = {
        "schema": SEARCH_SCHEMA, "query": value.get("query"),
        "call": "neyvia_native_call: tool_id = name, arguments_json = its fields (neyvia_tools_describe shows them), stable action_id for mutations.",
        "native": rows}
    compiler = value.get("compiler")
    if isinstance(compiler, dict) and compiler.get("providerCalls"):
        out["compiled"] = {"callMapHash": compiler.get("callMapHash"), "calls": [
            {"providerCall": str(call.get("providerCall") or "").partition("@")[0],
             "about": _first_sentence(call.get("description"), COMPILED_DESCRIPTION_CHARS)}
            for call in compiler["providerCalls"] if isinstance(call, dict)]}
        out["compiledNote"] = "neyvia_tools_call takes providerCall as listed; if it says the name is ambiguous, append @callMapHash."
    elif isinstance(compiler, dict) and compiler.get("status") not in (None, "ready"):
        out["compiler"] = compiler.get("status")
    managed = value.get("managed")
    if isinstance(managed, dict) and managed.get("results"):
        out["managed"] = managed
    if value.get("deferredBindings"):
        out["deferredBindings"] = value["deferredBindings"]
    return out


def model_view(value: Any) -> Any:
    if os.environ.get("NEYVIA_FULL_TOOL_RECEIPTS") == "1" or not isinstance(value, dict):
        return value
    if value.get("schema") == SEARCH_SCHEMA:
        return slim_search(value)
    if value.get("schema") == RECEIPT_SCHEMA or ("receipt_id" in value and "receipt_path" in value):
        return slim_receipt(value)
    return value
