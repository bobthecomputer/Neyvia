"""Durable N-E-Y-V-I-A external runtime invocation registry.

An external runtime (Claude Code, Grok Build, Kimi Code, OpenCodeGo, …) has
three different relationships with Neyvia, and they are separate lifecycles —
not one overloaded "open provider" flag:

``primary-session``
    The runtime is the session surface. Neyvia keeps context, files, tools,
    permissions, artifacts, receipts, memory and continuity around it.

``ecosystem-override``
    Neyvia stays the interface. The runtime powers a *named* subset of
    responsibilities. Reserved responsibilities (permissions, artifact custody,
    durable memory, evidence capture, orchestration state, identity) never move.

``inline-tool``
    A scoped invocation inside a live parent session that returns into that
    session's transcript. It always has a parent, a purpose, a context scope and
    a return channel, so nothing it produces is untraceable later.

Honesty rules enforced here:

* Readiness is evidence-based. A runtime with no launcher on PATH and no stored
  credential is reported unavailable — the registry never fabricates a session.
* Opening a record does **not** claim the runtime ran. ``state`` starts at
  ``requested``/``blocked``; only reported activity moves it to ``active``.
* No invocation may outlive its owning Neyvia session: :func:`reap_orphans`
  closes records whose parent session is gone.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

RUNTIME_INVOCATION_SCHEMA = "neyvia.runtime.invocation.v1"
REGISTRY_SCHEMA = "neyvia.runtime.invocation.registry.v1"

INVOCATION_MODES = ("primary-session", "ecosystem-override", "inline-tool")

DELEGABLE_RESPONSIBILITIES = (
    "conversation-loop",
    "coding-loop",
    "repo-awareness",
    "code-editing",
    "tool-execution",
    "reasoning",
)

#: Never delegated to an external runtime, whatever the caller asks for.
RESERVED_RESPONSIBILITIES = (
    "permissions",
    "artifact-custody",
    "durable-memory",
    "evidence-capture",
    "orchestration-state",
    "identity",
)

CONTEXT_SCOPES = ("inherit", "selected", "isolated")

PRESENTATIONS = (
    "session-surface",
    "inline-card",
    "inline-badge",
    "dock-right",
    "dock-left",
    "floating-center",
    "fullscreen",
)

LIFECYCLE: dict[str, tuple[str, ...]] = {
    "requested": ("ready", "blocked", "closed"),
    "ready": ("active", "suspended", "blocked", "closed"),
    "active": ("suspended", "returned", "blocked", "closed"),
    "suspended": ("active", "returned", "closed"),
    "returned": ("active", "closed"),
    "blocked": ("requested", "closed"),
    "closed": (),
}

#: States whose runtime session can be resumed without a restart.
RESUMABLE_STATES = ("ready", "active", "suspended", "returned")

#: States that still belong to the session. ``blocked`` stays visible on
#: purpose: an unavailable runtime must be shown truthfully, not hidden.
OPEN_STATES = ("requested", "ready", "active", "suspended", "returned", "blocked")

#: Launcher commands probed on PATH for truthful readiness. Runtimes reached
#: through a gateway rather than a local binary carry ``None``.
RUNTIME_LAUNCHERS: dict[str, tuple[str, ...]] = {
    "neyvia-agent": ("neyvia-agent",),
    "codex": ("codex",),
    "claude-code": ("claude",),
    "grok-build": ("grok",),
    "kimi-code": ("kimi",),
    "opencode-go": ("opencode",),
}

#: Credential ids in ``get_provider_secret_presence_command`` terms.
RUNTIME_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "neyvia-agent": ("openai-codex", "openai", "opencode-go"),
    "codex": ("openai-codex", "openai", "codex"),
    "claude-code": ("anthropic",),
    "grok-build": ("xai", "grok"),
    "kimi-code": ("moonshot", "kimi"),
    "opencode-go": ("opencode-go", "opencodego", "opencode"),
}

_REGISTRY_RELATIVE = Path(".agent_control") / "neyvia" / "runtime_invocations.jsonl"
_MAX_RECORDS = 500
_REGISTRY_LOCKS: dict[Path, threading.RLock] = {}
_REGISTRY_LOCKS_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: object, fallback: str = "") -> str:
    out = str(value or "").strip()
    return out or fallback


def _expand_context_selection(
    context_selection: Iterable[dict[str, Any]] | None,
    *,
    root: Path | None = None,
) -> Iterable[dict[str, Any]]:
    """Resolve durable imports before the bounded packet is assembled."""

    for raw in context_selection or ():
        if not isinstance(raw, dict):
            continue
        import_id = _text(raw.get("importId") or raw.get("import_id"))
        if not import_id or root is None:
            yield raw
            continue

        from .context_import import read_import_selection

        imported = read_import_selection(root, import_id)
        requested_ids = {
            _text(item)
            for item in (raw.get("selectedItemIds") or raw.get("selected_item_ids") or [])
            if _text(item)
        }
        requested_source_id = _text(raw.get("sourceItemId") or raw.get("source_id"))
        if requested_source_id:
            requested_ids.add(requested_source_id)
        if not requested_ids:
            source_id = _text(raw.get("sourceId") or raw.get("source_id"))
            if source_id and source_id != import_id:
                requested_ids.add(source_id)
        rows = imported["items"]
        if requested_ids:
            rows = [
                item
                for item in rows
                if _text(item.get("sourceItemId")) in requested_ids
            ]
            if len(rows) != len(requested_ids):
                raise ValueError(
                    f"Context import {import_id} does not contain every requested selected row."
                )
        for item in rows:
            yield {
                "sourceId": item["sourceItemId"],
                "kind": _text(raw.get("kind"), "imported-context"),
                "content": item["content"],
                "importId": imported["importId"],
                "sourceSha256": imported["sourceSha256"],
            }


def build_selected_context_packet(
    context_selection: Iterable[dict[str, Any]] | None,
    *,
    root: Path | None = None,
    max_items: int = 16,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Build the bounded, receipt-bound packet sent to a delegated runtime."""

    rows: list[dict[str, Any]] = []
    used = 0
    for index, raw in enumerate(_expand_context_selection(context_selection, root=root)):
        if not isinstance(raw, dict):
            continue
        source_id = _text(
            raw.get("sourceId")
            or raw.get("source_id")
            or raw.get("atomId")
            or raw.get("turnId")
            or raw.get("id")
            or raw.get("path"),
            f"selected-{index + 1}",
        )
        content = _text(
            raw.get("content")
            or raw.get("text")
            or raw.get("summary")
            or raw.get("detail")
        )
        if not content:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        bounded = content[:remaining]
        rows.append(
            {
                "sourceId": source_id,
                "kind": _text(raw.get("kind"), "context"),
                "content": bounded,
                "contentHash": hashlib.sha256(bounded.encode("utf-8")).hexdigest(),
                **(
                    {"sourceSha256": _text(raw.get("sourceSha256"))}
                    if _text(raw.get("sourceSha256"))
                    else {}
                ),
                **(
                    {"importId": _text(raw.get("importId"))}
                    if _text(raw.get("importId"))
                    else {}
                ),
            }
        )
        used += len(bounded)
        if len(rows) >= max_items:
            break
    import_ids = sorted({row["importId"] for row in rows if row.get("importId")})
    source_sha256s = sorted(
        {row["sourceSha256"] for row in rows if row.get("sourceSha256")}
    )
    result = {
        "schema": "neyvia.selected_context_packet.v1",
        "selected": rows,
        "sourceIds": [row["sourceId"] for row in rows],
        "importIds": import_ids,
        "sourceSha256s": source_sha256s,
        "sourceSha256": source_sha256s[0] if len(source_sha256s) == 1 else None,
        "contentHash": hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "bounded": True,
        "itemCount": len(rows),
    }
    from .proofs_a_control import check_context_packet
    check_context_packet(result, root, max_items, max_chars)
    from .proofs_d_host import check_context_packet as check_host_context_packet
    check_host_context_packet(result, max_items, max_chars)
    return result


def registry_path(root: Path) -> Path:
    return Path(root) / _REGISTRY_RELATIVE


def _registry_lock(root: Path) -> threading.RLock:
    """Serialize in-process append/read/compact operations for one registry."""

    path = registry_path(root).resolve()
    with _REGISTRY_LOCKS_GUARD:
        lock = _REGISTRY_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _REGISTRY_LOCKS[path] = lock
        return lock


# --------------------------------------------------------------- readiness


def runtime_readiness(
    runtime: str,
    *,
    provider_presence: dict[str, bool] | None = None,
    launcher_lookup: Any = None,
) -> dict[str, Any]:
    """Report truthful readiness for one runtime.

    ``ready`` requires a launcher we can actually find. Missing credentials are
    reported as ``credentials_missing``; an unknown runtime is ``unknown``.
    Nothing here optimistically reports ``ready``.
    """

    runtime_id = _text(runtime).lower()
    which = launcher_lookup or shutil.which
    if not runtime_id:
        return {
            "runtime": "",
            "available": False,
            "state": "unknown",
            "detail": "No runtime was named.",
        }

    launchers = RUNTIME_LAUNCHERS.get(runtime_id)
    if launchers is None:
        return {
            "runtime": runtime_id,
            "available": False,
            "state": "unknown",
            "detail": "This runtime is not part of the managed launcher catalog.",
        }

    resolved = next((which(name) for name in launchers if which(name)), None)
    if runtime_id == "neyvia-agent" and not resolved:
        # The runtime is distributed in the same Python package as this registry.
        import sys
        resolved = sys.executable
    presence = provider_presence or {}
    credential_ids = RUNTIME_CREDENTIALS.get(runtime_id, ())
    credential_present = any(bool(presence.get(alias)) for alias in credential_ids) if presence else None

    if not resolved:
        return {
            "runtime": runtime_id,
            "available": False,
            "state": "launcher_missing",
            "detail": (
                f"No {'/'.join(launchers)} launcher on PATH. Install the runtime "
                "before starting a session with it."
            ),
            "credentialPresent": credential_present,
        }
    if presence and credential_ids and credential_present is False:
        return {
            "runtime": runtime_id,
            "available": False,
            "state": "credentials_missing",
            "detail": "The launcher is installed but no stored credential was reported for it.",
            "launcherPath": resolved,
            "credentialPresent": False,
        }
    return {
        "runtime": runtime_id,
        "available": True,
        "state": "ready",
        "detail": f"Launcher resolved at {resolved}.",
        "launcherPath": resolved,
        "credentialPresent": credential_present,
    }


def runtime_readiness_snapshot(
    *,
    provider_presence: dict[str, bool] | None = None,
    runtimes: Iterable[str] | None = None,
    launcher_lookup: Any = None,
) -> dict[str, Any]:
    ids = list(runtimes or RUNTIME_LAUNCHERS)
    statuses = {
        runtime_id: runtime_readiness(
            runtime_id,
            provider_presence=provider_presence,
            launcher_lookup=launcher_lookup,
        )
        for runtime_id in ids
    }
    return {
        "schema": REGISTRY_SCHEMA,
        "generatedAt": _now(),
        "runtimeStatus": statuses,
        "readyRuntimes": sorted(k for k, v in statuses.items() if v.get("available")),
        "modes": list(INVOCATION_MODES),
        "delegable": list(DELEGABLE_RESPONSIBILITIES),
        "reserved": list(RESERVED_RESPONSIBILITIES),
        "disclosure": (
            "Readiness is derived from launcher resolution and reported credential "
            "presence only. No runtime session is started by this snapshot."
        ),
    }


def validate_route_selection(
    route: dict[str, Any] | None,
    *,
    runtime: str,
    model: str | None = None,
) -> dict[str, Any]:
    """Validate an explicit route without substituting another runtime/model."""

    requested = route if isinstance(route, dict) else {}
    runtime_id = _text(requested.get("runtimeId") or requested.get("runtime") or runtime).lower()
    provider = _text(requested.get("provider") or requested.get("providerId"))
    model_id = _text(requested.get("model") or model)
    effort = _text(requested.get("effort"), "default").lower()
    problems: list[str] = []
    if runtime_id not in RUNTIME_LAUNCHERS:
        problems.append(f"Requested runtime {runtime_id or '<empty>'!r} is not in the managed runtime catalog.")
    if not provider:
        problems.append("An explicit route must name a provider.")
    if not model_id:
        problems.append("An explicit route must name a model.")
    if effort not in {"default", "none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max", "thinking"}:
        problems.append(f"Reasoning effort {effort!r} is not supported.")
    provider_id = provider.lower().replace("_", "-")
    compatible_providers = {
        "codex": {"openai", "openai-codex", "codex"},
        "claude-code": {"anthropic", "claude", "claude-code"},
        "grok-build": {"xai", "grok", "grok-build"},
        "kimi-code": {"moonshot", "kimi", "kimi-code"},
        "opencode-go": {"opencode", "opencode-go", "opencodego"},
    }.get(runtime_id)
    if compatible_providers and provider_id not in compatible_providers:
        problems.append(
            f"Provider {provider!r} is incompatible with runtime {runtime_id!r}; no fallback route is allowed."
        )
    return {
        "ok": not problems,
        "runtimeId": runtime_id,
        "provider": provider,
        "model": model_id,
        "effort": effort,
        "problems": problems,
    }


# --------------------------------------------------------------- delegation


def partition_delegation(requested: Iterable[str] | None) -> tuple[list[str], list[dict[str, str]]]:
    delegated: list[str] = []
    refused: list[dict[str, str]] = []
    for value in requested or ():
        item = _text(value)
        if not item:
            continue
        if item in RESERVED_RESPONSIBILITIES:
            refused.append(
                {
                    "id": item,
                    "reason": "Neyvia-reserved responsibility — never delegated to an external runtime.",
                }
            )
            continue
        if item not in DELEGABLE_RESPONSIBILITIES:
            refused.append({"id": item, "reason": "Unknown responsibility."})
            continue
        if item not in delegated:
            delegated.append(item)
    return delegated, refused


def retained_responsibilities(delegated: Iterable[str]) -> list[str]:
    taken = set(delegated or ())
    return [item for item in DELEGABLE_RESPONSIBILITIES if item not in taken] + list(
        RESERVED_RESPONSIBILITIES
    )


# ----------------------------------------------------------------- records


def _normalize_presentation(value: object, mode: str) -> str:
    item = _text(value)
    if item in PRESENTATIONS:
        return item
    if mode == "primary-session":
        return "session-surface"
    if mode == "ecosystem-override":
        return "inline-badge"
    return "inline-card"


def build_invocation_record(
    *,
    mode: str,
    runtime: str,
    model: str | None = None,
    parent_session_id: str | None = None,
    parent_mission_id: str | None = None,
    purpose: str = "",
    context_scope: str | None = None,
    context_selection: list[dict[str, Any]] | None = None,
    context_root: Path | None = None,
    delegate: Iterable[str] | None = None,
    presentation: str | None = None,
    permissions: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
    route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode_id = _text(mode) if _text(mode) in INVOCATION_MODES else "inline-tool"
    requested_route = route if isinstance(route, dict) else {}
    runtime_id = _text(
        requested_route.get("runtimeId") or requested_route.get("runtime") or runtime
    ).lower()
    model_id = _text(model) or _text(requested_route.get("model"))
    scope = _text(context_scope)
    if scope not in CONTEXT_SCOPES:
        scope = "selected" if mode_id == "inline-tool" else "inherit"

    requested = list(DELEGABLE_RESPONSIBILITIES) if mode_id == "primary-session" else list(delegate or ())
    delegated, refused = partition_delegation(requested)

    problems: list[str] = []
    if not runtime_id:
        problems.append("A runtime must be named.")
    if mode_id == "inline-tool" and not _text(parent_session_id):
        problems.append("An inline runtime invocation requires the parent session it returns into.")
    if mode_id == "ecosystem-override" and not delegated:
        problems.append("An ecosystem override must name at least one delegated responsibility.")
    route_validation = validate_route_selection(route, runtime=runtime_id, model=model_id) if route else None
    if route_validation and not route_validation["ok"]:
        problems.extend(route_validation["problems"])

    readiness_payload = readiness if isinstance(readiness, dict) else runtime_readiness(runtime_id)
    if problems:
        state = "blocked"
    elif readiness_payload.get("available"):
        state = "ready"
    else:
        state = "requested"

    permissions = permissions if isinstance(permissions, dict) else {}
    stamp = _now()
    return {
        "schema": RUNTIME_INVOCATION_SCHEMA,
        "invocationId": f"inv-{mode_id}-{runtime_id or 'runtime'}-{uuid.uuid4().hex[:10]}",
        "mode": mode_id,
        "runtime": runtime_id,
        "model": model_id or None,
        "routeSelection": dict(route_validation) if route_validation else None,
        "parentSessionId": _text(parent_session_id) or None,
        "parentMissionId": _text(parent_mission_id) or None,
        "purpose": _text(purpose),
        "contextScope": scope,
        "contextSelection": list(context_selection or []),
        "selectedContextPacket": build_selected_context_packet(
            context_selection,
            root=context_root,
        ),
        "delegated": delegated,
        "retained": retained_responsibilities(delegated),
        "refusedDelegation": refused,
        "presentation": _normalize_presentation(presentation, mode_id),
        "permissions": {
            "inheritSession": permissions.get("inheritSession", True) is not False,
            "approvalRequired": permissions.get("approvalRequired", True) is not False,
            "grants": [str(item) for item in (permissions.get("grants") or [])],
        },
        "readiness": readiness_payload,
        "state": state,
        "problems": problems,
        "requestedAt": stamp,
        "lastTransitionAt": stamp,
        "returns": {"messages": [], "artifacts": [], "receipts": [], "changes": []},
    }


def can_transition(current: str, target: str) -> bool:
    return _text(target) in LIFECYCLE.get(_text(current), ())


def is_resumable(state: str) -> bool:
    return _text(state) in RESUMABLE_STATES


def is_open(state: str) -> bool:
    return _text(state) in OPEN_STATES


# ---------------------------------------------------------------- storage


def _read_records(root: Path) -> list[dict[str, Any]]:
    with _registry_lock(root):
        path = registry_path(root)
        if not path.exists():
            return []
        records: dict[str, dict[str, Any]] = {}
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    invocation_id = _text(item.get("invocationId"))
                    if invocation_id:
                        records[invocation_id] = item
        except OSError:
            return []
        return list(records.values())


def _append_record(root: Path, record: dict[str, Any]) -> None:
    with _registry_lock(root):
        path = registry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        _compact_if_needed(root)


def _compact_if_needed(root: Path) -> None:
    """Keep the log bounded: replay to latest-per-id and rewrite when large."""

    path = registry_path(root)
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            line_count = sum(1 for line in handle if line.strip())
    except OSError:
        return
    if line_count <= _MAX_RECORDS * 4:
        return
    records = sorted(
        _read_records(root),
        key=lambda item: _text(item.get("lastTransitionAt")),
    )[-_MAX_RECORDS:]
    tmp = path.with_suffix(".compacting")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _supersede_conflicting(root: Path, record: dict[str, Any]) -> None:
    """Enforce the registry rules that keep the three modes distinct."""

    if not is_open(record.get("state", "")):
        return
    mode = record.get("mode")
    for existing in _read_records(root):
        if existing.get("invocationId") == record.get("invocationId"):
            continue
        if not is_open(existing.get("state", "")):
            continue
        if mode == "primary-session" and existing.get("mode") == "primary-session":
            if existing.get("parentSessionId") == record.get("parentSessionId"):
                _append_record(
                    root,
                    {
                        **existing,
                        "state": "closed",
                        "closedReason": "Replaced by a new primary runtime for this session.",
                        "lastTransitionAt": _now(),
                    },
                )
        elif mode == "ecosystem-override" and existing.get("mode") == "ecosystem-override":
            taken = set(record.get("delegated") or ())
            remaining = [item for item in (existing.get("delegated") or []) if item not in taken]
            if remaining == list(existing.get("delegated") or []):
                continue
            if remaining:
                _append_record(
                    root,
                    {
                        **existing,
                        "delegated": remaining,
                        "retained": retained_responsibilities(remaining),
                        "lastTransitionAt": _now(),
                    },
                )
            else:
                _append_record(
                    root,
                    {
                        **existing,
                        "state": "closed",
                        "closedReason": "Its delegated responsibilities moved to another runtime.",
                        "lastTransitionAt": _now(),
                    },
                )


def open_invocation(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Register an invocation. Does not start or claim a runtime session."""

    record = build_invocation_record(
        mode=payload.get("mode", "inline-tool"),
        runtime=payload.get("runtime", ""),
        model=payload.get("model"),
        parent_session_id=payload.get("parentSessionId") or payload.get("parent_session_id"),
        parent_mission_id=payload.get("parentMissionId") or payload.get("parent_mission_id"),
        purpose=payload.get("purpose", ""),
        context_scope=payload.get("contextScope") or payload.get("context_scope"),
        context_selection=payload.get("contextSelection") or payload.get("context_selection"),
        context_root=root,
        delegate=payload.get("delegate") or payload.get("delegated"),
        presentation=payload.get("presentation"),
        permissions=payload.get("permissions"),
        readiness=payload.get("readiness")
        if isinstance(payload.get("readiness"), dict)
        else runtime_readiness(
            payload.get("runtime", ""),
            provider_presence=payload.get("providerPresence"),
        ),
        route=payload.get("route") or payload.get("routeSelection"),
    )
    _supersede_conflicting(root, record)
    _append_record(root, record)
    return record


def update_invocation(
    root: Path,
    invocation_id: str,
    *,
    state: str | None = None,
    returns: dict[str, Any] | None = None,
    presentation: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    records = {item.get("invocationId"): item for item in _read_records(root)}
    current = records.get(_text(invocation_id))
    if current is None:
        raise ValueError(f"Unknown invocation id: {invocation_id}")

    updated = dict(current)
    if returns:
        merged = dict(current.get("returns") or {})
        for key in ("messages", "artifacts", "receipts", "changes"):
            incoming = returns.get(key) or []
            if incoming:
                merged[key] = list(merged.get(key) or []) + list(incoming)
        updated["returns"] = merged
        if not state and can_transition(updated.get("state", ""), "returned"):
            updated["state"] = "returned"
    if presentation:
        updated["presentation"] = _normalize_presentation(presentation, updated.get("mode", ""))
    if state:
        if not can_transition(updated.get("state", ""), state):
            raise ValueError(
                f"Illegal invocation transition: {updated.get('state')} → {state}"
            )
        updated["state"] = state
    if reason:
        updated["lastReason"] = _text(reason)
    updated["lastTransitionAt"] = _now()
    _append_record(root, updated)
    return updated


def close_invocation(root: Path, invocation_id: str, reason: str = "") -> dict[str, Any]:
    records = {item.get("invocationId"): item for item in _read_records(root)}
    current = records.get(_text(invocation_id))
    if current is None:
        raise ValueError(f"Unknown invocation id: {invocation_id}")
    closed = {
        **current,
        "state": "closed",
        "closedReason": _text(reason),
        "lastTransitionAt": _now(),
    }
    _append_record(root, closed)
    return closed


def load_registry(
    root: Path,
    *,
    parent_session_id: str | None = None,
    include_closed: bool = False,
    provider_presence: dict[str, bool] | None = None,
    launcher_lookup: Any = None,
) -> dict[str, Any]:
    records = _read_records(root)
    normalized: list[dict[str, Any]] = []
    for item in records:
        record = dict(item)
        record["returns"] = {
            key: list((record.get("returns") or {}).get(key) or [])
            for key in ("messages", "artifacts", "receipts", "changes")
        }
        if provider_presence is not None or launcher_lookup is not None:
            status = runtime_readiness(
                record.get("runtime", ""),
                provider_presence=provider_presence,
                launcher_lookup=launcher_lookup,
            )
            record["readiness"] = {
                **status,
                "ready": status.get("available") is True,
            }
        normalized.append(record)
    records = normalized
    if parent_session_id:
        target = _text(parent_session_id)
        records = [item for item in records if _text(item.get("parentSessionId")) == target]
    if not include_closed:
        records = [item for item in records if is_open(item.get("state", ""))]
    records.sort(key=lambda item: _text(item.get("requestedAt")))
    return {
        "schema": REGISTRY_SCHEMA,
        "generatedAt": _now(),
        "invocations": records,
        "primary": next(
            (
                item
                for item in records
                if item.get("mode") == "primary-session" and is_open(item.get("state", ""))
            ),
            None,
        ),
        "overrides": [
            item
            for item in records
            if item.get("mode") == "ecosystem-override" and is_open(item.get("state", ""))
        ],
        "inline": [
            item
            for item in records
            if item.get("mode") == "inline-tool" and is_open(item.get("state", ""))
        ],
        "reserved": list(RESERVED_RESPONSIBILITIES),
    }


def reap_orphans(root: Path, live_session_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Close invocations whose owning Neyvia session no longer exists.

    Nothing external is allowed to survive without an owning session, so a
    stale record can never present itself as a live provider lane.
    """

    live = {_text(item) for item in live_session_ids or () if _text(item)}
    closed: list[dict[str, Any]] = []
    for record in _read_records(root):
        if not is_open(record.get("state", "")):
            continue
        parent = _text(record.get("parentSessionId"))
        if not parent or parent in live:
            continue
        closed.append(
            close_invocation(root, record["invocationId"], "Owning Neyvia session ended.")
        )
    return closed


def describe_effective_composition(root: Path, parent_session_id: str | None = None) -> dict[str, Any]:
    """What the UI must state plainly about who owns what right now."""

    registry = load_registry(root, parent_session_id=parent_session_id)
    primary = registry.get("primary")
    delegations: list[dict[str, str]] = []
    seen: set[str] = set()
    for override in registry.get("overrides") or []:
        for responsibility in override.get("delegated") or []:
            if responsibility in seen:
                continue
            seen.add(responsibility)
            delegations.append({"responsibility": responsibility, "runtime": override.get("runtime", "")})
    runtimes = sorted({item["runtime"] for item in delegations if item["runtime"]})
    if primary:
        summary = (
            f"{primary.get('runtime')} is the session surface. Neyvia keeps context, "
            "permissions, artifacts, evidence and continuity."
        )
    elif delegations:
        summary = (
            f"Neyvia is the interface. {', '.join(runtimes)} powering "
            f"{len(delegations)} responsibility(ies)."
        )
    else:
        summary = "Neyvia runtime, no external delegation."
    return {
        "schema": RUNTIME_INVOCATION_SCHEMA,
        "surfaceOwner": primary.get("runtime") if primary else "neyvia",
        "ecosystemOwner": "neyvia",
        "delegations": delegations,
        "reserved": list(RESERVED_RESPONSIBILITIES),
        "inlineCount": len(registry.get("inline") or []),
        "summary": summary,
    }


def default_root() -> Path:
    return Path(os.environ.get("FLUXIO_WORKSPACE_ROOT") or Path.cwd()).resolve()
