"""Resident browser UI graph: normalized nodes, revisions, semantic hash, compact deltas."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from .proofs_e_sv import enforced


# Volatile presentation noise excluded from semantic identity / hash.
NOISE_STATES = frozenset({"focused", "hovered", "active", "busy", "visited"})
BOUNDS_QUANTUM = 8

_QUERY_RE = re.compile(
    r"""
    ^\s*
    (?P<role>[a-zA-Z0-9_-]+)?
    (?:\[name\s*(?P<op>~=|=)\s*"(?P<name>[^"]*)"\])?
    (?:\[id=(?P<id>[^\]]+)\])?
    \s*$
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Bounds:
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    def quantized(self, quantum: int = BOUNDS_QUANTUM) -> tuple[int, int, int, int]:
        q = max(1, int(quantum))
        return (
            int(self.x) // q * q,
            int(self.y) // q * q,
            max(0, int(self.w) // q * q),
            max(0, int(self.h) // q * q),
        )

    def compact(self) -> str:
        qx, qy, qw, qh = self.quantized()
        return f"{qx},{qy},{qw},{qh}"


@dataclass(frozen=True)
class UiNode:
    id: str
    role: str
    name: str = ""
    states: tuple[str, ...] = ()
    bounds: Bounds = field(default_factory=Bounds)
    actions: tuple[str, ...] = ()
    source: str = "browser"
    revision: int = 0
    parent_id: str = ""
    value: str = ""
    backend_ref: str = ""  # opaque Playwright/CDP handle for actions

    def stable_states(self) -> tuple[str, ...]:
        return tuple(sorted(state for state in self.states if state not in NOISE_STATES))

    @enforced("sv.ui.semantic-identity")
    def semantic_tuple(self) -> tuple[Any, ...]:
        return (
            self.id,
            self.role,
            self.name,
            self.stable_states(),
            self.bounds.quantized(),
            tuple(sorted(self.actions)),
            self.parent_id,
            self.value,
        )

    def with_revision(self, revision: int) -> UiNode:
        return replace(self, revision=revision)


@dataclass(frozen=True)
class UiDelta:
    kind: str  # added | changed | removed
    node_id: str
    before: UiNode | None = None
    after: UiNode | None = None

    def compact_line(self) -> str:
        if self.kind == "added" and self.after is not None:
            return f"+ {_format_node_line(self.after)}"
        if self.kind == "removed" and self.before is not None:
            return f"- {_format_node_line(self.before)}"
        if self.kind == "changed" and self.after is not None:
            return f"~ {_format_node_line(self.after)}"
        return f"? {self.kind} {self.node_id}"


@dataclass
class UiGraph:
    """In-memory resident UI graph with revision-gated deltas."""

    nodes: dict[str, UiNode] = field(default_factory=dict)
    revision: int = 0
    semantic_hash: str = ""
    url: str = ""
    title: str = ""
    source: str = "browser"
    last_delta: tuple[UiDelta, ...] = ()
    observed_at: str = ""

    def snapshot_nodes(self) -> dict[str, UiNode]:
        return dict(self.nodes)

    @enforced("sv.ui.graph-state")
    def replace_nodes(
        self,
        nodes: Sequence[UiNode] | Iterable[UiNode],
        *,
        url: str = "",
        title: str = "",
        source: str = "browser",
    ) -> tuple[UiDelta, ...]:
        incoming = {node.id: node for node in nodes}
        previous = self.nodes
        deltas: list[UiDelta] = []

        for node_id, node in incoming.items():
            old = previous.get(node_id)
            if old is None:
                deltas.append(UiDelta(kind="added", node_id=node_id, after=node))
            elif old.semantic_tuple() != node.semantic_tuple():
                deltas.append(UiDelta(kind="changed", node_id=node_id, before=old, after=node))

        for node_id, old in previous.items():
            if node_id not in incoming:
                deltas.append(UiDelta(kind="removed", node_id=node_id, before=old))

        self.revision += 1
        stamped = {
            node_id: node.with_revision(self.revision) for node_id, node in incoming.items()
        }
        self.nodes = stamped
        self.url = url or self.url
        self.title = title or self.title
        self.source = source or self.source
        self.semantic_hash = compute_semantic_hash(stamped.values())
        self.last_delta = tuple(deltas)
        from datetime import datetime, timezone
        self.observed_at = datetime.now(timezone.utc).isoformat()
        return self.last_delta

    def get(self, node_id: str) -> UiNode | None:
        return self.nodes.get(node_id)

    def find(self, query: str, *, limit: int = 20) -> list[UiNode]:
        return find_nodes(self.nodes.values(), query, limit=limit)

    def ls(self, *, role: str = "", limit: int = 40) -> list[UiNode]:
        rows = list(self.nodes.values())
        if role:
            role_l = role.lower()
            rows = [node for node in rows if node.role.lower() == role_l]
        rows.sort(key=lambda node: (node.role, node.name, node.id))
        return rows[: max(1, min(limit, 200))]

    def header_line(self) -> str:
        return (
            f"rev={self.revision} hash={self.semantic_hash or '-'} "
            f"nodes={len(self.nodes)} source={self.source}"
        )


def compute_semantic_hash(nodes: Iterable[UiNode]) -> str:
    digest = hashlib.sha256()
    for node in sorted(nodes, key=lambda item: item.id):
        digest.update(repr(node.semantic_tuple()).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:16]


@enforced("sv.ui.delta")
def diff_graphs(before: dict[str, UiNode], after: dict[str, UiNode]) -> list[UiDelta]:
    deltas: list[UiDelta] = []
    for node_id, node in after.items():
        old = before.get(node_id)
        if old is None:
            deltas.append(UiDelta(kind="added", node_id=node_id, after=node))
        elif old.semantic_tuple() != node.semantic_tuple():
            deltas.append(UiDelta(kind="changed", node_id=node_id, before=old, after=node))
    for node_id, old in before.items():
        if node_id not in after:
            deltas.append(UiDelta(kind="removed", node_id=node_id, before=old))
    return deltas


_KNOWN_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "searchbox",
        "checkbox",
        "radio",
        "switch",
        "combobox",
        "listbox",
        "option",
        "menuitem",
        "menu",
        "tab",
        "tablist",
        "heading",
        "img",
        "dialog",
        "alertdialog",
        "alert",
        "navigation",
        "main",
        "form",
        "table",
        "row",
        "cell",
        "gridcell",
        "treeitem",
        "slider",
        "spinbutton",
        "progressbar",
        "status",
        "toolbar",
        "tooltip",
    }
)


@enforced("sv.ui.query")
def find_nodes(nodes: Iterable[UiNode], query: str, *, limit: int = 20) -> list[UiNode]:
    query = (query or "").strip()
    limit = max(1, min(int(limit), 100))
    if not query or query in {"*", "all"}:
        rows = sorted(nodes, key=lambda node: (node.role, node.name, node.id))
        return list(rows[:limit])

    parsed = _QUERY_RE.match(query)
    has_structure = "[" in query
    structured = False
    if parsed:
        role = (parsed.group("role") or "").lower()
        name = parsed.group("name")
        node_id = parsed.group("id")
        if name is not None or node_id or has_structure:
            structured = True
        elif role and role in _KNOWN_ROLES and query.lower() == role:
            # Bare known role: `ui.find("button")` lists buttons.
            structured = True

    if structured and parsed:
        role = (parsed.group("role") or "").lower()
        name = parsed.group("name") or ""
        op = parsed.group("op") or "="
        node_id = parsed.group("id") or ""
        matches: list[UiNode] = []
        for node in nodes:
            if node_id and node.id != node_id:
                continue
            if role and node.role.lower() != role:
                continue
            if name:
                if op == "~=":
                    if name.lower() not in node.name.lower():
                        continue
                elif node.name != name:
                    continue
            matches.append(node)
        matches.sort(key=lambda node: (node.role, node.name, node.id))
        return matches[:limit]

    # Free-text fallback: role/name/id substring.
    needle = query.lower()
    matches = [
        node
        for node in nodes
        if needle in node.role.lower()
        or needle in node.name.lower()
        or needle in node.id.lower()
        or any(needle in state.lower() for state in node.states)
    ]
    matches.sort(key=lambda node: (node.role, node.name, node.id))
    return matches[:limit]


def _format_node_line(node: UiNode) -> str:
    name = node.name.replace("\n", " ").strip()
    if len(name) > 80:
        name = name[:77] + "..."
    parts = [node.id, node.role]
    if name:
        parts.append(f'"{name}"')
    states = node.stable_states()
    if states:
        parts.append(f"states={','.join(states)}")
    if node.actions:
        parts.append(f"actions={','.join(node.actions)}")
    if node.bounds.w or node.bounds.h:
        parts.append(f"bounds={node.bounds.compact()}")
    return " ".join(parts)


def format_compact_listing(
    graph: UiGraph,
    nodes: Sequence[UiNode],
    *,
    label: str = "matches",
) -> str:
    lines = [graph.header_line(), f"{label}={len(nodes)}"]
    for node in nodes:
        lines.append(_format_node_line(node))
    return "\n".join(lines)


@enforced("sv.ui.compact-delta")
def format_compact_delta(
    graph: UiGraph,
    deltas: Sequence[UiDelta] | None = None,
    *,
    limit: int = 80,
) -> str:
    rows = list(deltas if deltas is not None else graph.last_delta)
    limit = max(1, min(int(limit), 200))
    truncated = len(rows) > limit
    rows = rows[:limit]
    counts = {"added": 0, "changed": 0, "removed": 0}
    for delta in rows:
        if delta.kind in counts:
            counts[delta.kind] += 1
    lines = [
        graph.header_line(),
        f"delta added={counts['added']} changed={counts['changed']} removed={counts['removed']}"
        + (f" truncated={len(graph.last_delta) - limit}" if truncated else ""),
    ]
    lines.extend(delta.compact_line() for delta in rows)
    if not rows:
        lines.append("(no changes)")
    return "\n".join(lines)


def format_compact_get(graph: UiGraph, node: UiNode | None, node_id: str) -> str:
    if node is None:
        return f"{graph.header_line()}\nmissing id={node_id}"
    return f"{graph.header_line()}\n{_format_node_line(node)}"


def stable_node_id(*, role: str, name: str, path: str, source: str = "browser") -> str:
    raw = f"{source}|{path}|{role}|{name}"
    return "n" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def infer_actions(role: str, states: Sequence[str]) -> tuple[str, ...]:
    role_l = (role or "").lower()
    state_set = {state.lower() for state in states}
    actions: list[str] = []
    if role_l in {
        "button",
        "link",
        "menuitem",
        "tab",
        "checkbox",
        "radio",
        "switch",
        "option",
        "treeitem",
        "combobox",
    }:
        actions.append("click")
    if role_l in {"textbox", "searchbox", "spinbutton", "combobox"}:
        actions.append("fill")
        actions.append("press")
    if role_l in {"combobox", "listbox"}:
        actions.append("select")
    if role_l in {"checkbox", "switch", "radio"}:
        actions.append("toggle")
    if "disabled" in state_set:
        return ()
    return tuple(actions)
