"""Transcript-backed sidebar observations; never infer work from titles or folders."""
from __future__ import annotations

import json
import re
import copy
import threading
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import unquote

READ_PAGES = 10
READ_LIMIT = 200
AGENT_TOOLS = {"agent", "task", "spawn_agent", "spawnagent", "delegate", "delegate_task",
               "send_input", "wait", "wait_agent", "close_agent", "resume_agent"}
IMAGE_TOOLS = {"imagegen", "image_gen", "generate_image", "image_generation", "imagegen.imagegen",
               "image_gen.imagegen", "image_gen__imagegen", "neyvia.images.generate", "images.generate",
               "neyvia.image.generate", "image.generate"}


class SidebarCache:
    """Bounded read snapshots; slow provider refreshes never hold up warm pages.

    Mutable assignments are still read directly from the UI bus on every request.
    Refreshes use one daemon worker per workspace and publish on its existing stream.
    Explicit IDs bypass this cache for operations requiring a fresh observation.
    """
    def __init__(self, service):
        self.service = service
        self.lock = threading.RLock()
        self.values = OrderedDict()
        self.pending = set()
        self.errors = set()
        self.queue = deque()
        self.worker = None

    def get(self, key, produce, ttl, signature=None):
        with self.lock:
            cached = self.values.get(key)
            if cached is not None:
                self.values.move_to_end(key)
                if (time.monotonic() - cached[0] >= ttl or signature != cached[1]) and key not in self.pending:
                    self.pending.add(key)
                    self.queue.append((key, produce, signature))
                    if self.worker is None or not self.worker.is_alive():
                        self.worker = threading.Thread(target=self._refresh, name="sidebar-refresh", daemon=True)
                        self.worker.start()
                return copy.deepcopy(cached[2])
        value = produce()
        with self.lock:
            self._store(key, signature, value)
        return copy.deepcopy(value)

    def has_all(self, keys):
        with self.lock:
            return all(key in self.values for key in keys)

    def _store(self, key, signature, value):
        self.errors.discard(key)
        self.values[key] = (time.monotonic(), signature, value)
        self.values.move_to_end(key)
        while len(self.values) > 512:
            dropped, _ = self.values.popitem(last=False)
            self.errors.discard(dropped)

    def _refresh(self):
        while True:
            with self.lock:
                if not self.queue or self.service.closed.is_set():
                    self.worker = None
                    self.pending.clear()
                    self.queue.clear()
                    return
                key, produce, signature = self.queue.popleft()
            try:
                value = produce()
                with self.lock:
                    old = self.values.get(key)
                    changed = old is None or old[2] != value
                    self._store(key, signature, value)
                if changed:
                    self.service.bus.emit("sidebar.refreshed", {"kind": key[0], "id": key[1]})
            except Exception:
                # Keep the last observed data when a provider is temporarily unavailable.
                with self.lock:
                    self.errors.add(key)
            finally:
                with self.lock:
                    self.pending.discard(key)

    def freshness(self, key):
        with self.lock:
            cached = self.values.get(key)
            return {"ageMs": round((time.monotonic() - cached[0]) * 1000) if cached else None,
                    "refreshing": bool(self.pending), "failedRefreshes": len(self.errors)}


def _cache_for(service):
    with service.lock:
        if not hasattr(service, "_sidebar_cache"):
            service._sidebar_cache = SidebarCache(service)
        return service._sidebar_cache


def _inventory(broker, query):
    rows, sources, offset = [], [], 0
    while True:
        page = broker.list_sessions(limit=500, offset=offset, query=query,
                                    observe=False, include_archived=True)
        rows.extend(page.get("sessions", []))
        sources = page.get("sources", sources)
        next_offset = page.get("nextOffset")
        if next_offset is None or next_offset <= offset:
            return rows, sources
        offset = next_offset


def _child_session(broker, identity):
    try:
        broker.read(identity, limit=1)
        return identity
    except Exception:
        return None


def _object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            pass
    return {}


def _tool_name(data):
    name = str(data.get("name") or "").lower()
    # MCP adapters expose the qualified server/tool separately.
    return str(data.get("tool") or name).lower() if data.get("category") == "mcp" else name


def project(row: dict, page: dict | None) -> dict[str, Any]:
    """Project observed canonical transcript items. A partial transcript cannot be Quick."""
    page = page or {}
    items = [i for i in page.get("items", []) if isinstance(i, dict)]
    complete = bool(page) and not bool(page.get("has_earlier") or page.get("hasEarlier")
                                        or page.get("truncated") or page.get("readError"))
    turns = sum(i.get("kind") == "user" for i in items)
    generation, agents, seen, generation_ids = [], [], set(), set()
    for item in items:
        data = _object(item.get("data"))
        name = _tool_name(data)
        source = str(item.get("id") or "")
        if data.get("generatedImage") is True or (item.get("kind") == "tool" and
                (name in IMAGE_TOOLS or name.endswith("__imagegen"))):
            event_id = source[:-6] if data.get('generatedImage') is True and source.endswith(':image') else source
            if event_id not in generation_ids:
                generation_ids.add(event_id)
                generation.append({"id": event_id, "name": name or "imageGeneration",
                                   "status": data.get("status") or "ok", "at": item.get("at")})
        if item.get("kind") != "tool":
            continue
        agent = _object(data.get("agent"))
        if name in {"wait", "wait_agent", "send_input", "close_agent", "resume_agent"} and not agent and not data.get("agentThreadIds"):
            continue
        if not (agent or data.get("agentThreadIds") or name in AGENT_TOOLS):
            continue
        args = _object(data.get("input"))
        output = _object(data.get("output"))
        links = data.get("agentThreadIds") or [agent.get("agentId") or agent.get("sessionId") or args.get("sessionId")
                                               or output.get("sessionId")]
        for index, link in enumerate(links):
            # A transcript's actual receiver identifier is retained, but not converted
            # to a navigable session ID until the same session has been observed.
            observed = str(link) if link else None
            identity = observed or source
            if not identity:
                continue
            status = agent.get("status") or data.get("status") or "unknown"
            existing = next((a for a in agents if a["id"] == identity), None)
            if existing:
                # Closing a completed child is housekeeping, not failed work.
                if not (data.get('agentActivity') == 'interrupted' and existing['status'] in {'ok', 'error'}):
                    existing["status"] = status
                continue
            if identity in seen:
                continue
            seen.add(identity)
            agents.append({"id": identity, "title": agent.get("description") or (data.get("input") if name == 'sub_agent' else None) or data.get("title") or name,
                           "harness": row.get("app") or row.get("runtime") or "unknown",
                           "status": status, "at": item.get("at"), "sessionId": None, "children": [], "sourceItemId": source,
                           "observedSessionId": observed,
                           "parentId": agent.get("parentId") or args.get("parentAgentId")})
    by_id = {a["id"]: a for a in agents}
    if row.get("app") == "claude-code":
        from .claude_code_activity import child_status
        parent = page.get("run") or row
        for agent in agents:
            agent["status"] = child_status(agent["status"], parent, agent.get("at"))
    parents = {a['id']: a.get('parentId') for a in agents}
    roots = []
    for node in agents:
        parent = by_id.get(node.pop("parentId", None))
        visited, cursor = {node['id']}, parent
        while cursor is not None and cursor['id'] not in visited:
            visited.add(cursor['id'])
            cursor = by_id.get(parents.get(cursor['id']))
        if parent is not None and cursor is None:
            parent["children"].append(node)
        else:
            roots.append(node)
    texts = [str(_object(i.get("data")).get("text") or "") for i in items
             if i.get("kind") in ("user", "assistant")]
    return {"kind": "images" if generation else "quick" if complete and turns < 3 else "other",
            "turnCount": turns if complete else None, "complete": complete,
            "generationEvents": generation, "agents": roots,
            "preview": {"text": next((t[:500] for t in reversed(texts) if t), ""),
                        "lastActivity": next((i.get("at") for i in reversed(items) if i.get("at")),
                                             row.get("updated_at") or row.get("updatedAt"))}}


def read_transcript(broker, identity):
    """Read backwards with explicit bounds; return incomplete when the budget is exhausted."""
    combined, before, latest = {}, None, {}
    for _ in range(READ_PAGES):
        page = broker.read(identity, limit=READ_LIMIT, before_seq=before)
        if not latest:
            latest = dict(page)
        items = [i for i in page.get("items", []) if isinstance(i, dict)]
        for item in items:
            combined[str(item.get("id") or item.get("seq"))] = item
        earlier = bool(page.get("has_earlier") or page.get("hasEarlier"))
        latest["has_earlier"] = earlier
        seqs = [i["seq"] for i in items if isinstance(i.get("seq"), int)]
        if not earlier or not seqs:
            break
        next_before = min(seqs)
        if before is not None and next_before >= before:
            break
        before = next_before
    latest["items"] = sorted(combined.values(), key=lambda i: i.get("seq", 0))
    return latest


def observe(service, args):
    if any(isinstance(args.get(key), bool) for key in ('limit', 'offset')):
        raise ValueError('limit and offset must be integers')
    limit, offset = int(args.get("limit", 100)), int(args.get("offset", 0))
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1..100 and offset must be nonnegative")
    ids = args.get("ids")
    if ids is not None and (not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) for i in ids)):
        raise ValueError("ids must be an array of session IDs")
    broker, rows, sources = service.broker(), [], []
    cache, inventory_key = _cache_for(service), ("inventory", str(args.get("query") or ""))
    transcripts, errors = {}, []
    if ids is not None:
        # A known child/older thread may be omitted from a provider's capped
        # list. Read only the explicitly requested, paged identities directly.
        for identity in list(dict.fromkeys(ids))[offset:offset + limit]:
            try:
                transcript = read_transcript(broker, identity)
                transcripts[identity] = transcript
                rows.append(transcript['session'])
            except Exception as exc:
                errors.append({'id': identity, 'error': str(exc)[:500]})
    else:
        rows, sources = cache.get(inventory_key, lambda: _inventory(broker, inventory_key[1]), 3.0)
    saved, projects = service.bus.get("sessions", {}), service.bus.get("projects", {})
    folders = service.bus.get("sidebar:folders", {})
    folders = list(folders.values()) if isinstance(folders, dict) else folders
    folder_map = {f["id"]: {"id": f["id"], "name": f.get("name"), "path": None} for f in folders}
    project_map = {**projects, **folder_map}
    links = {str(r["id"]): str(r["id"]) for r in rows}
    for r in rows:
        if str(r["id"]).startswith("external:"):
            links[unquote(str(r["id"]).split(":", 3)[-1])] = str(r["id"])
    selected = []
    for listed in rows:
        overlay = saved.get(listed["id"], {})
        row = {**listed, **overlay}
        if row.get("archived") or (ids is not None and row["id"] not in ids):
            continue
        if "project" in overlay:
            assignment = overlay["project"]
            row["projectOverride"] = project_map.get(assignment) if isinstance(assignment, str) else assignment
        selected.append(row)
    total, result = len(ids) if ids is not None else len(selected), []
    page_rows = selected if ids is not None else selected[offset:offset + limit]
    def projection(row):
        try:
            if ids is not None:
                return project(row, transcripts.get(row['id']) or read_transcript(broker, row["id"])), None
            else:
                # Capture this loop's row in the refresh closure. Cached projections
                # contain bounded hover/agent data, never full transcript pages.
                return cache.get(("transcript", row["id"]),
                                    lambda row=row: project(row, read_transcript(broker, row["id"])),
                                    30.0, signature=(row.get("updated_at") or row.get("updatedAt"), row.get("status"))), None
        except Exception as exc:
            return project(row, {"readError": True}), {"id": row["id"], "error": str(exc)[:500]}
    # Each provider already supports concurrent reads from connected clients.
    # Bound page I/O rather than serializing up to 100 independent transcripts;
    # map preserves sidebar ordering and the same full/incomplete classifications.
    if len(page_rows) > 1 and ids is None and not cache.has_all(("transcript", row["id"]) for row in page_rows):
        with ThreadPoolExecutor(max_workers=min(8, len(page_rows)), thread_name_prefix="sidebar-page") as pool:
            projections = list(pool.map(projection, page_rows))
    else:
        projections = [projection(row) for row in page_rows]
    # A cached transcript can be served during refresh, but its live badges
    # must follow the current run immediately, including process-gone recovery.
    parents = broker._latest_runs([row["id"] for row in page_rows if row.get("app") == "claude-code"])
    for row, (sidebar, error) in zip(page_rows, projections):
        if error:
            errors.append(error)
        def resolve(nodes):
            for node in nodes:
                if row.get("app") == "claude-code":
                    from .claude_code_activity import child_status
                    node["status"] = child_status(node["status"], parents.get(row["id"]) or row, node.get("at"))
                observed = node.pop("observedSessionId", None)
                node["sessionId"] = links.get(observed)
                # The provider's list omits subagent-origin threads; the actual
                # transcript link may still address a real, readable child.
                if node['sessionId'] is None and row.get('app') == 'codex' and re.fullmatch(r'[0-9a-fA-F-]{36}', str(observed or '')):
                    from .connected_sessions.registry import parse_session_id, make_session_id
                    parsed = parse_session_id(row['id'])
                    candidate = make_session_id('codex', parsed[1], observed) if parsed else None
                    if candidate:
                        found = (_child_session(broker, candidate) if ids is not None else
                                 cache.get(("child", candidate), lambda candidate=candidate: _child_session(broker, candidate), 30.0))
                        if found:
                            links[observed] = candidate
                            node['sessionId'] = candidate
                resolve(node["children"])
        resolve(sidebar["agents"])
        result.append({**row, "sidebar": sidebar})
    used = {r.get("projectOverride", {}).get("id") for r in selected
            if isinstance(r.get("projectOverride"), dict)}
    return {"ok": True, "sessions": result, "total": total,
            "nextOffset": offset + limit if offset + limit < total else None, "sources": sources,
            "subjectFolders": [f for identity, f in folder_map.items() if identity in used], "errors": errors,
            "freshness": cache.freshness(inventory_key) if ids is None else {"ageMs": 0, "refreshing": False}}
