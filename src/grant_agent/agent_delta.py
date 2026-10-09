"""Typed AgentDelta for agent_nodes progress/result_summary columns.

Synthesis merges claims/evidence/artifacts/conflicts/blockers — not transcripts.
Ultra competing-candidates remain disabled until receipts are reproducible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AGENT_DELTA_SCHEMA = "neyvia.agent_delta.v1"
ULTRA_COMPETING_CANDIDATES = {"enabled": False, "reason": "receipts_not_reproducible"}

_DELTA_LIST_KEYS = ("claims", "evidence", "artifacts", "conflicts", "blockers")


@dataclass
class AgentDelta:
    claims: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    schema: str = AGENT_DELTA_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = AGENT_DELTA_SCHEMA
        return payload

    def is_empty(self) -> bool:
        return not any(getattr(self, key) for key in (*_DELTA_LIST_KEYS, "notes"))


def empty_agent_delta() -> AgentDelta:
    return AgentDelta()


def _as_item_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for raw in value:
            if isinstance(raw, dict):
                items.append(dict(raw))
            elif str(raw).strip():
                items.append({"text": str(raw).strip()})
        return items
    if isinstance(value, dict):
        return [dict(value)]
    if str(value).strip():
        return [{"text": str(value).strip()}]
    return []


def _as_note_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _item_key(item: dict[str, Any]) -> str:
    for key in ("id", "claimId", "evidenceId", "artifactId", "path", "uri", "hash", "text", "summary"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return f"{key}:{str(value).strip()}"
    return repr(sorted((str(k), str(v)) for k, v in item.items()))


def normalize_agent_delta(payload: Any) -> AgentDelta:
    """Coerce progress_json / result_summary_json (or nested delta) into AgentDelta."""
    if payload is None:
        return empty_agent_delta()
    if isinstance(payload, AgentDelta):
        return payload
    if not isinstance(payload, dict):
        return AgentDelta(notes=_as_note_list(payload))

    source = payload
    nested = payload.get("delta")
    if isinstance(nested, dict) and (
        any(key in nested for key in _DELTA_LIST_KEYS) or nested.get("schema") == AGENT_DELTA_SCHEMA
    ):
        source = nested
    elif payload.get("schema") == AGENT_DELTA_SCHEMA or any(key in payload for key in _DELTA_LIST_KEYS):
        source = payload
    else:
        # Legacy result_summary blobs: keep short structured fields, never transcripts.
        legacy_notes: list[str] = []
        for key in ("summary", "recommendation", "status", "tests"):
            if key in payload and payload[key] is not None:
                legacy_notes.append(f"{key}={payload[key]}")
        return AgentDelta(
            evidence=_as_item_list(payload.get("evidence")),
            artifacts=_as_item_list(payload.get("artifacts")),
            blockers=_as_item_list(payload.get("blockers")),
            conflicts=_as_item_list(payload.get("conflicts")),
            claims=_as_item_list(payload.get("claims")),
            notes=legacy_notes,
        )

    return AgentDelta(
        claims=_as_item_list(source.get("claims")),
        evidence=_as_item_list(source.get("evidence")),
        artifacts=_as_item_list(source.get("artifacts")),
        conflicts=_as_item_list(source.get("conflicts")),
        blockers=_as_item_list(source.get("blockers")),
        notes=_as_note_list(source.get("notes")),
    )


def merge_agent_deltas(*deltas: AgentDelta | dict[str, Any] | None) -> AgentDelta:
    """Merge deltas by stable item identity; later entries win on duplicate keys."""
    merged = empty_agent_delta()
    buckets: dict[str, dict[str, dict[str, Any]]] = {key: {} for key in _DELTA_LIST_KEYS}
    notes: list[str] = []
    seen_notes: set[str] = set()
    for raw in deltas:
        delta = normalize_agent_delta(raw)
        for key in _DELTA_LIST_KEYS:
            for item in getattr(delta, key):
                buckets[key][_item_key(item)] = item
        for note in delta.notes:
            if note not in seen_notes:
                seen_notes.add(note)
                notes.append(note)
    for key in _DELTA_LIST_KEYS:
        setattr(merged, key, list(buckets[key].values()))
    merged.notes = notes
    from .proofs_d_host import check_delta_merge
    check_delta_merge(merged, buckets, notes)
    return merged


def read_agent_delta(node: dict[str, Any] | None) -> AgentDelta:
    """Prefer resultSummary delta, then progress delta; never pull transcripts."""
    if not isinstance(node, dict):
        return empty_agent_delta()
    result = normalize_agent_delta(node.get("resultSummary") or node.get("result_summary"))
    progress = normalize_agent_delta(node.get("progress") or node.get("progress_json"))
    if result.is_empty() and progress.is_empty():
        return empty_agent_delta()
    if result.is_empty():
        return progress
    if progress.is_empty():
        return result
    return merge_agent_deltas(progress, result)


def write_agent_delta_payload(delta: AgentDelta | dict[str, Any] | None) -> dict[str, Any]:
    """Payload suitable for result_summary_json (typed delta only)."""
    normalized = normalize_agent_delta(delta)
    return {"schema": AGENT_DELTA_SCHEMA, "delta": normalized.as_dict()}


def synthesize_agent_deltas(
    nodes: list[dict[str, Any]],
    *,
    recommendation: str = "",
    rationale: str = "",
) -> dict[str, Any]:
    """Build synthesis evidence from node deltas — not conversation transcripts."""
    per_node: dict[str, Any] = {}
    merged = empty_agent_delta()
    for node in nodes:
        node_id = str(node.get("nodeId") or node.get("node_id") or "").strip()
        delta = read_agent_delta(node)
        if node_id:
            per_node[node_id] = delta.as_dict()
        merged = merge_agent_deltas(merged, delta)
    conflicts = list(merged.conflicts)
    blockers = list(merged.blockers)
    status = "blocked" if blockers else ("conflicted" if conflicts else "ready")
    result = {
        "schema": "neyvia.synthesis_from_deltas.v1",
        "status": status,
        "recommendation": str(recommendation or ""),
        "rationale": str(rationale or ""),
        "merged": merged.as_dict(),
        "byNode": per_node,
        "ultraCompetingCandidates": dict(ULTRA_COMPETING_CANDIDATES),
        "transcriptsIncluded": False,
    }
    from .proofs_d_host import check_synthesis
    check_synthesis(result)
    return result
