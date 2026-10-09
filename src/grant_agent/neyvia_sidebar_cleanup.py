"""One backend policy and archive guard shared by people, tools and maintenance."""

from __future__ import annotations

import time
from pathlib import Path

from .connected_sessions.sidebar_cleanup import (
    DEFAULT_POLICY, SidebarSafetyObserver, archive_blocker, normalize_policy, stale, updated_epoch,
)


def session_row(service, identity, observer=None):
    summary = service.broker().find_summary(identity)
    saved = service.bus.get("sessions", {}).get(identity, {})
    if summary is None:
        return {**saved, "id": identity, "cleanup_safety": {"status": "session_unavailable"}}
    row = {**summary.public(), **saved}
    row.update(service.broker().sidebar_observation(summary, observer=observer))
    if "project" in saved:
        row["projectOverride"] = saved["project"]
    return row


def _observe_folders(observer, folders):
    """Check each distinct folder once, a few at a time (git and the process scan dominate)."""
    from concurrent.futures import ThreadPoolExecutor
    folders = [folder for folder in folders if folder]
    if not folders:
        return
    observer._jobs(Path(folders[0]))  # take the one process snapshot before the threads share it
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(observer.observe, folders))


def _observed_row(broker, listed, saved, observer):
    """A listed chat plus the person's overlay and a fresh folder/process observation."""
    row = {**listed, **saved}
    if "project" in saved:
        row["projectOverride"] = saved["project"]
    summary = broker.find_summary(listed["id"], refresh=False)
    if summary is None:
        row["cleanup_safety"] = {"status": "session_unavailable"}
    else:
        row.update(broker.sidebar_observation(summary, observer=observer))
    return row


def _archive(service, identity):
    """The same reversible overlay session.archive writes; checked by the caller moments ago."""
    with service.lock:
        current = service.bus.get("sessions", {}).get(identity, {})
        service.bus.update("sessions", {identity: {**current, "archived": True}})
        return service.result("session.archived", {"id": identity, "archived": True})


def guard_archive(service, identity):
    row = session_row(service, identity)
    reason = archive_blocker(row)
    if reason:
        return {"ok": False, "status": "archive_protected", "id": identity,
                "reason": reason, "observation": row.get("cleanup_safety"),
                "error": "Kept this chat: " + reason.replace("_", " ")}
    return None


def call(service, name, args):
    if name == "sidebar.policy":
        if "policy" not in args:
            return {"ok": True, "policy": normalize_policy(service.bus.get("cleanupPolicy", DEFAULT_POLICY)),
                    "lastArchive": service.bus.get("cleanupLastArchive")}
        policy = normalize_policy(args["policy"])
        from .neyvia_settings import update
        update(service, {"cleanup": policy})
        service.start_timers()
        service.wake.set()
        return service.result("sidebar.policy", {"policy": policy})
    if name != "sidebar.tidy":
        raise ValueError("Unknown sidebar operation")
    if args.get("undoLast") is True:
        return _undo_last(service)
    policy = normalize_policy(service.bus.get("cleanupPolicy", DEFAULT_POLICY))
    dry_run = bool(args.get("dryRun")) or args.get("confirmed") is not True
    candidates, protected, archived, now = [], [], [], time.time()
    archive_levels = []
    broker = service.broker()
    observer = SidebarSafetyObserver(service.bus.get("projects", {}).values())
    saved_rows = service.bus.get("sessions", {})
    # A chat younger than the shorter rule can't be stale under either one: skip it
    # before the folder and process checks, which are the slow part.
    youngest = min(policy["noFolderDays"], policy["projectDays"]) * 86400
    offset, old = 0, []
    while True:
        # One fresh listing; summaries are read from it, never refetched per chat.
        page = broker.list_sessions(include_archived=True, limit=500, offset=offset, force=offset == 0, observe=False)
        for listed in page["sessions"]:
            saved = saved_rows.get(listed["id"], {})
            if not (listed.get("archived") or saved.get("archived") or now - updated_epoch(listed) <= youngest):
                old.append((listed, saved))
        if page.get("nextOffset") is None:
            break
        offset = page["nextOffset"]
    _observe_folders(observer, {listed.get("cwd") for listed, _ in old})
    for listed, saved in old:
        row = _observed_row(broker, listed, saved, observer)
        if not stale(row, policy, now):
            continue
        blocker = archive_blocker(row, now)
        if blocker:
            protected.append({"id": row["id"], "reason": blocker})
            continue
        candidates.append(row["id"])
        if args.get("automatic") is True:
            from .neyvia_settings import effective_initiative
            level = effective_initiative(service, row.get("projectOverride") or row.get("cwd"))
            if level == "suggest":
                continue
        if not dry_run:
            _archive(service, row["id"])
            archived.append(row["id"])
            if args.get("automatic") is True:
                archive_levels.append(level)
    result = {"ok": True, "policy": policy, "candidates": candidates, "archived": archived,
              "protected": protected, "dryRun": dry_run, "observedAt": now,
              "status": "confirmation_required" if args.get("confirmed") is not True and not args.get("dryRun") else "preview" if dry_run else "completed"}
    if not dry_run:
        service.bus.put("cleanupLastRun", result)
        if archived:  # kept until undone or replaced, so an automatic tidy can be undone later too
            service.bus.put("cleanupLastArchive", {"archived": archived, "at": now, "automatic": args.get("automatic") is True})
            if args.get("automatic") is True:
                if "act-and-tell" in archive_levels:
                    service.bus.emit("notify", {"level": "info", "message": f"Tidied {len(archived)} stale chat{'s' if len(archived) != 1 else ''} into Fallen leaves. Settings can undo it."})
        elif candidates and args.get("automatic") is True:
            suggested = sorted(candidates)
            if service.bus.get("cleanupSuggestedIds") != suggested:
                service.bus.emit("notify", {"level": "info", "message": f"Archive {len(candidates)} stale chats? Review in Settings.", "action": "settings", "target": "tidy"})
                service.bus.put("cleanupSuggestedIds", suggested)
    return result


def _undo_last(service):
    """Restore every chat the last tidy archived (one write, not one call per chat)."""
    last = service.bus.get("cleanupLastArchive") or {}
    restored = []
    with service.lock:
        rows = service.bus.get("sessions", {})
        for identity in last.get("archived", []):
            if rows.get(identity, {}).get("archived"):
                rows[identity] = {**rows[identity], "archived": False}
                restored.append(identity)
        if restored:
            service.bus.update("sessions", {identity: rows[identity] for identity in restored})
        service.bus.put("cleanupLastArchive", None)
    for identity in restored:
        service.bus.emit("session.archived", {"id": identity, "archived": False})
    return {"ok": True, "restored": restored, "status": "restored"}


def automatic_tick(service):
    policy = normalize_policy(service.bus.get("cleanupPolicy", DEFAULT_POLICY))
    if not policy["autoArchive"]:
        return None
    last = service.bus.get("cleanupAutomaticAt", 0)
    remaining = 60 - (time.time() - last)
    if remaining <= 0:
        try:
            call(service, "sidebar.tidy", {"confirmed": True, "automatic": True})
        except Exception as error:
            service.bus.put("cleanupLastRun", {"observedAt": time.time(), "error": str(error)})
        service.bus.put("cleanupAutomaticAt", time.time())
        return 60
    return remaining
