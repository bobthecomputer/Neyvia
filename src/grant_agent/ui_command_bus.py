"""Durable backend-to-UI commands shared by the web service and model workers."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def state_root(root: Path) -> Path:
    return Path(os.environ.get("NEYVIA_UI_STATE_ROOT") or root).resolve()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class UICommandBus:
    def __init__(self, root: Path):
        self.root = state_root(root)
        self.path = self.root / ".agent_control" / "ui_commands.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.changed = threading.Condition()
        self.receivers_enabled = False
        self._receivers = set()
        self._connections = threading.local()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
                    action TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS acks (
                    event_id INTEGER NOT NULL, client TEXT NOT NULL, ok INTEGER NOT NULL,
                    error TEXT, ts TEXT NOT NULL, PRIMARY KEY(event_id, client));
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def receiver(self, alive):
        """An owned stream's live socket, checked at dispatch rather than on a timer."""
        with self.changed:
            self._receivers.add(alive)
        try:
            yield
        finally:
            with self.changed:
                self._receivers.discard(alive)

    def require_renderer(self, *, probe=False, principal=""):
        with self.changed:
            receivers = tuple(self._receivers)
        if self.receivers_enabled and not any(alive() for alive in receivers):
            raise ValueError("Open Neyvia first; no page is connected to the command bus. Nothing was queued.")
        shell = self.get('renderer:shell', {})
        age = time.time() - shell.get('observedAt', 0)
        if not probe and not (0 <= age <= 2.5 and shell.get('dom', {}).get('mounted') is True):
            raise ValueError("Open Neyvia first; a fresh mounted shell is required. Nothing was queued.")
        if probe:
            started = time.time()
            event = self.emit('renderer.probe', {'runtimeId': shell.get('runtimeId'),
                                                 'clientId': shell.get('clientId')})
            deadline = time.monotonic() + 1.5
            retried = False
            with self.changed:
                while True:
                    with self.connect() as db:
                        row = db.execute('SELECT ok FROM acks WHERE event_id=? AND client=?',
                                         (int(event['id']), principal + ':' + str(shell.get('clientId')))).fetchone()
                    if row is not None and row['ok'] == 1:
                        break
                    # A report received after this request is an independent
                    # witness from the actual mounted page, not cached liveness.
                    current = self.get('renderer:shell', {})
                    if (current.get('observedAt', 0) > started
                            and current.get('dom', {}).get('mounted') is True
                            and any(alive() for alive in receivers)):
                        return current
                    remaining = deadline - time.monotonic()
                    if not retried and remaining < 1:
                        shell = current or shell
                        event = self.emit('renderer.probe', {'runtimeId': shell.get('runtimeId'),
                                                             'clientId': shell.get('clientId')})
                        retried = True
                    if remaining <= 0:
                        raise ValueError("Open Neyvia first; the mounted page did not answer its readiness probe. Nothing was queued.")
                    self.changed.wait(min(.05, remaining))
        return shell

    @contextmanager
    def connect(self):
        scope = getattr(self._connections, 'scope', None)
        shared = scope is not None and not scope['in_use']
        db = scope['db'] if shared else sqlite3.connect(self.path, timeout=15)
        if shared:
            scope['in_use'] = True
        else:
            db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if shared:
                scope['in_use'] = False
            else:
                db.close()

    @contextmanager
    def connection_scope(self):
        """Reuse an idle connection during one request, never its read results.

        Each connect operation still commits or rolls back independently. A
        nested operation gets its own connection, preserving existing nesting.
        The request releases its connection even when dispatch or checks fail.
        """
        if getattr(self._connections, 'scope', None) is not None:
            yield
            return
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        self._connections.scope = {'db': db, 'in_use': False}
        try:
            yield
        finally:
            self._connections.scope = None
            db.close()

    def emit(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = now()
        with self.connect() as db:
            cursor = db.execute("INSERT INTO events(ts,action,payload) VALUES(?,?,?)",
                                (ts, action, json.dumps(payload)))
            identity = str(cursor.lastrowid)
        with self.changed:
            self.changed.notify_all()
        return {"id": identity, "ts": ts, "action": action, "payload": payload}

    def since(self, cursor: int = 0) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE id>? ORDER BY id LIMIT 200", (cursor,)).fetchall()
        return [{"id": str(row["id"]), "ts": row["ts"], "action": row["action"],
                 "payload": json.loads(row["payload"])} for row in rows]

    def ack(self, payload: dict, client: str):
        if not isinstance(payload.get("ok"), bool):
            raise ValueError("ok must be a boolean")
        identity = int(payload["id"])
        with self.connect() as db:
            row = db.execute("SELECT * FROM events WHERE id=?", (identity,)).fetchone()
            if not row:
                raise ValueError("Unknown event id")
            from .cl.renderer_effects import admit_ack
            event = {"id": str(identity), "action": row["action"], "payload": json.loads(row["payload"])}
            observation = admit_ack(event, payload, client)
            db.execute("INSERT OR REPLACE INTO acks VALUES(?,?,?,?,?)",
                       (identity, client, payload["ok"], str(payload.get("error") or "")[:1000], now()))
            if observation is not None:
                db.execute("INSERT OR REPLACE INTO state VALUES(?,?)",
                           ("renderer:pane:" + str(identity), json.dumps(observation)))
        with self.changed:
            self.changed.notify_all()
        return {"id": str(identity), "ok": payload["ok"],
                **({"observation": observation} if observation is not None else {})}

    def get(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value)))

    def update(self, key: str, patch: dict) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            value = {**(json.loads(row[0]) if row else {}), **patch}
            db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value)))
        return value

    def snapshot(self):
        with self.connect() as db:
            rows = db.execute("SELECT key,value FROM state WHERE key NOT LIKE 'approval:%'").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}


_buses: dict[str, UICommandBus] = {}
_lock = threading.Lock()


def bus_for(root: Path) -> UICommandBus:
    key = str(state_root(root))
    with _lock:
        if key not in _buses:
            _buses[key] = UICommandBus(Path(key))
        return _buses[key]
