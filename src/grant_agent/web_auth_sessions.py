"""Durable storage for web account sessions.

Only SHA-256 digests of bearer tokens are written to disk. Each session is bound
to a fingerprint of its account: changing an account's password or removing it ends
that account's sessions only. Without a per-account fingerprint (``user_identity``)
the store falls back to one fingerprint for every account, as it used to.

Rows also keep what the account screen shows about a device: a short user-agent
string, the address it signed in from, and when it was last used.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


# A session stays valid while it is used: each use (at most once a day) moves its
# expiry to 180 days from then, so a device someone keeps using never asks to sign
# in again. It ends on sign-out, after 180 days unused, or when the account
# identity changes (a new password, or the account is removed).
WEB_AUTH_SESSION_TTL_SECONDS = 180 * 24 * 60 * 60
WEB_AUTH_SESSION_RENEW_AFTER_SECONDS = 24 * 60 * 60
_ALLOWED_ROLES = {"account", "operator", "admin"}
# Last use is written at most this often, so a page polling every few seconds
# does not turn every request into a database write.
LAST_SEEN_RESOLUTION_SECONDS = 5 * 60
_SESSION_ID_LENGTH = 16


def session_id(token_hash: str) -> str:
    """A public handle for a session: a prefix of its token's digest, never the token."""
    return str(token_hash)[:_SESSION_ID_LENGTH]


class WebAuthSessions:
    """Process-safe, persistent session store rooted in an application's data dir."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        auth_identity: str,
        user_identity: Callable[[str], str | None] | None = None,
        ttl_seconds: int = WEB_AUTH_SESSION_TTL_SECONDS,
        clock: Any = time.time,
    ) -> None:
        if not isinstance(auth_identity, str) or not auth_identity:
            raise ValueError("auth_identity must be a non-empty account fingerprint")
        if int(ttl_seconds) < 1:
            raise ValueError("ttl_seconds must be positive")
        self.directory = Path(root).resolve() / ".neyvia"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._restrict_permissions(self.directory, directory=True)
        self.path = self.directory / "web-auth-sessions.sqlite3"
        self._identity_hash = hashlib.sha256(auth_identity.encode("utf-8")).hexdigest()
        self._user_identity = user_identity
        self.ttl_seconds = int(ttl_seconds)
        self._clock = clock
        self._initialise()

    @staticmethod
    def _restrict_permissions(path: Path, *, directory: bool = False) -> None:
        # POSIX permissions are enforced where available. On Windows, the
        # directory inherits the user's private application-data ACL.
        try:
            path.chmod(0o700 if directory else 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout = 15000")
            # journal_mode changes do not consistently honor busy_timeout.
            # Warm connections must not compete for a journal transition;
            # cold concurrent initializers retain the same 15-second bound.
            deadline = time.monotonic() + 15
            while True:
                try:
                    if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                        db.execute("PRAGMA journal_mode = WAL")
                    break
                except sqlite3.OperationalError as error:
                    code = getattr(error, 'sqlite_errorcode', 0) & 255
                    if code not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or time.monotonic() >= deadline:
                        raise
                    time.sleep(.05)
            db.execute("PRAGMA synchronous = FULL")
            self._restrict_permissions(self.path)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists():
                    self._restrict_permissions(sidecar)
        except BaseException:
            db.close()
            raise
        return db

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialise(self) -> None:
        with self._connection() as db:
            # Serialize the column snapshot and migration across processes.
            # Autocommit DDL otherwise lets several cold writers see missing
            # columns, then race to add the same column.
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """CREATE TABLE IF NOT EXISTS web_auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    identity_hash TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS web_auth_sessions_expiry "
                "ON web_auth_sessions(expires_at)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(web_auth_sessions)")}
            for name, kind in (
                ("user_agent", "TEXT NOT NULL DEFAULT ''"),
                ("address", "TEXT NOT NULL DEFAULT ''"),
                ("last_seen", "REAL NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE web_auth_sessions ADD COLUMN {name} {kind}")
        self._restrict_permissions(self.path)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _timestamp(epoch: float) -> str:
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")

    def _identity_for(self, username: str) -> str | None:
        """The fingerprint a session of ``username`` must carry; None once the account is gone."""
        if self._user_identity is None:
            return self._identity_hash
        identity = self._user_identity(username)
        if not identity:
            return None
        return hashlib.sha256(f"user:{identity}".encode("utf-8")).hexdigest()

    def _valid_identity(self, stored: str, expected: str | None) -> bool:
        if expected is None:
            return False
        if hmac.compare_digest(str(stored), expected):
            return True
        # A session issued before fingerprints were per account carries the shared one.
        return self._user_identity is not None and hmac.compare_digest(str(stored), self._identity_hash)

    def issue(
        self,
        user: dict[str, object],
        fallback_username: str = "",
        *,
        user_agent: str = "",
        address: str = "",
    ) -> str:
        username = str(user.get("username") or fallback_username).strip()
        role = str(user.get("role") or "account").strip().lower()
        if not username or role not in _ALLOWED_ROLES:
            raise ValueError("A valid account user and role are required")
        identity_hash = self._identity_for(username)
        if identity_hash is None:
            raise ValueError("This account no longer exists")
        now = float(self._clock())
        token = secrets.token_urlsafe(32)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM web_auth_sessions WHERE expires_at <= ?", (now,))
            from .proofs_e_wz import check_session_issued, session_snapshot
            live_before = session_snapshot(db)
            db.execute(
                """INSERT INTO web_auth_sessions
                   (token_hash, identity_hash, username, display_name, role, created_at, expires_at,
                    user_agent, address, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._token_hash(token),
                    identity_hash,
                    username,
                    str(user.get("displayName") or username),
                    role,
                    now,
                    now + self.ttl_seconds,
                    str(user_agent or "")[:300],
                    str(address or "")[:80],
                    now,
                ),
            )
            check_session_issued(db, self._token_hash(token),
                                 (identity_hash, username, str(user.get("displayName") or username), role,
                                  now, now + self.ttl_seconds, str(user_agent or "")[:300], str(address or "")[:80], now),
                                 live_before)
            db.commit()
        return token

    def lookup(self, token: str | None) -> dict[str, str] | None:
        if not isinstance(token, str) or not token:
            return None
        now = float(self._clock())
        token_hash = self._token_hash(token)
        # Ordinary UI polls/ACKs read a snapshot concurrently. A required
        # write reopens under the writer lock and rereads the principal; it
        # cannot renew a revoked or changed session using the earlier row.
        for writing in (False, True):
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
                row = db.execute(
                    """SELECT identity_hash, username, display_name, role, created_at, expires_at, last_seen
                       FROM web_auth_sessions WHERE token_hash = ?""",
                    (token_hash,),
                ).fetchone()
                if row is None:
                    return None
                identity_hash, username, display_name, role, created_at, expires_at, last_seen = row
                expected = self._identity_for(str(username))
                invalid = (
                    float(expires_at) <= now
                    or not self._valid_identity(str(identity_hash), expected)
                    or str(role) not in _ALLOWED_ROLES
                )
                upgrade = not hmac.compare_digest(str(identity_hash), str(expected))
                renew = float(expires_at) - now < self.ttl_seconds - WEB_AUTH_SESSION_RENEW_AFTER_SECONDS
                updated = upgrade or renew or now - float(last_seen or 0) >= LAST_SEEN_RESOLUTION_SECONDS
                if (invalid or updated) and not writing:
                    continue
                if invalid:
                    db.execute("DELETE FROM web_auth_sessions WHERE token_hash = ?", (token_hash,))
                    from .proofs_e_wz import check_session_rejected
                    check_session_rejected(db, token_hash)
                    return None
                if updated:
                    db.execute(
                        "UPDATE web_auth_sessions SET identity_hash = ?, expires_at = ?, last_seen = ? "
                        "WHERE token_hash = ?",
                        (expected, now + self.ttl_seconds if renew else float(expires_at), now, token_hash),
                    )
                from .proofs_e_wz import check_session_lookup
                check_session_lookup(db, token_hash, row, expected, now, self.ttl_seconds, renew,
                                     updated)
                result = {
                    "username": str(username),
                    "displayName": str(display_name),
                    "role": str(role),
                    "createdAt": self._timestamp(float(created_at)),
                    "sessionId": session_id(token_hash),
                }
                from .proofs_d_neyvia import account_session
                account_session(db, token_hash, expected, str(username), result)
            return result

    def sessions(self, username: str | None = None) -> list[dict[str, object]]:
        """Live sessions, most recently used first; only ``username``'s when given."""
        now = float(self._clock())
        query = (
            "SELECT token_hash, identity_hash, username, created_at, expires_at, user_agent, address, last_seen "
            "FROM web_auth_sessions WHERE expires_at > ?"
        )
        args: tuple[object, ...] = (now,)
        if username is not None:
            query += " AND username = ? COLLATE NOCASE"
            args = (now, username)
        with self._connection() as db:
            rows = db.execute(query + " ORDER BY last_seen DESC, created_at DESC", args).fetchall()
        found = []
        for token_hash, identity_hash, name, created_at, expires_at, user_agent, address, last_seen in rows:
            if not self._valid_identity(str(identity_hash), self._identity_for(str(name))):
                continue
            found.append({
                "id": session_id(token_hash),
                "username": str(name),
                "userAgent": str(user_agent or ""),
                "address": str(address or ""),
                "createdAt": self._timestamp(float(created_at)),
                "lastSeenAt": self._timestamp(float(last_seen or created_at)),
                "expiresAt": self._timestamp(float(expires_at)),
            })
        return found

    def revoke_where(
        self,
        *,
        username: str | None = None,
        session: str | None = None,
        keep: str | None = None,
    ) -> int:
        """End sessions by account and/or public id, except the one whose public id is ``keep``."""
        if username is None and session is None:
            raise ValueError("Say whose sessions to end")
        clauses: list[str] = []
        args: list[object] = []
        if username is not None:
            clauses.append("username = ? COLLATE NOCASE")
            args.append(username)
        if session is not None:
            if len(str(session)) != _SESSION_ID_LENGTH:
                return 0
            clauses.append("substr(token_hash, 1, ?) = ?")
            args.extend([_SESSION_ID_LENGTH, str(session)])
        if keep:
            clauses.append("substr(token_hash, 1, ?) != ?")
            args.extend([_SESSION_ID_LENGTH, str(keep)])
        with self._connection() as db:
            cursor = db.execute("DELETE FROM web_auth_sessions WHERE " + " AND ".join(clauses), tuple(args))
            return int(cursor.rowcount or 0)

    def revoke(self, token: str | None) -> None:
        if not isinstance(token, str) or not token:
            return
        with self._connection() as db:
            db.execute(
                "DELETE FROM web_auth_sessions WHERE token_hash = ?",
                (self._token_hash(token),),
            )
            from .proofs_e_wz import check_session_rejected
            check_session_rejected(db, self._token_hash(token))
