"""Private cue memory. The caller must supply a server-bound scope, never tool args.

Legacy retrieval and mission working memory intentionally retain their contracts.
This store persists small claims and content-free lifecycle receipts, not chats.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid


BOUND_MEMORY = ContextVar('neyvia_bound_memory', default=None)
KINDS = ('fact', 'preference', 'procedure', 'pitfall')
CUE_FIELDS = ('intent', 'app', 'layer', 'files', 'task', 'entities')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class MemoryRefusal(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class MemoryContext:
    root: Path
    owner: str
    project_path: Path
    source_id: str = ''
    source_kind: str = 'agent_suggestion'
    explicit_write: bool = False
    provider_export_authorized: bool = False
    channel: str = 'local'

    def __post_init__(self):
        if not self.owner or not isinstance(self.owner, str):
            raise MemoryRefusal('memory_scope_unbound', 'Memory needs an authenticated user.', 403)
        object.__setattr__(self, 'root', Path(self.root).resolve())
        object.__setattr__(self, 'project_path', Path(self.project_path).resolve())
        object.__setattr__(self, 'owner', self.owner.casefold())

    @property
    def project(self):
        return fingerprint(str(self.project_path).casefold())[:24]

    @property
    def identity(self):
        return self.owner, self.project


def require_context(context=None):
    context = context or BOUND_MEMORY.get()
    if not isinstance(context, MemoryContext):
        raise MemoryRefusal('memory_scope_unbound', 'This launcher has no authenticated memory scope.', 403)
    return context


def private_sessions(root, user):
    """Server-only account fence for chats which received private memory.

    This reads content-free bindings; legacy unbound chats keep their policy.
    """
    path = Path(root).resolve() / '.agent_control/private_memory/store.sqlite3'
    if not path.exists():
        return set()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
        return {row[0] for row in db.execute('SELECT DISTINCT session FROM sessions WHERE owner<>?', (str(user).casefold(),))}


def text(body, key, maximum, required=True):
    value = body.get(key, '')
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise MemoryRefusal('invalid_memory', f'{key} must be text of at most {maximum} characters.', 400)
    return value.strip()


def claim_fields(body):
    key, content = text(body, 'key', 160), text(body, 'content', 2000)
    kind = body.get('kind', 'fact')
    if kind not in KINDS:
        raise MemoryRefusal('invalid_memory', 'Choose fact, preference, procedure or pitfall.', 400)
    # Explicitly labelled credentials and common credential formats are refused,
    # including manually taught credentials; this is not a general PII classifier.
    if re.search(r'(?i)(?:password|passwd|api.?key|access.?token|private.?key|bearer\s+|sk-[a-z0-9]{16}|-----BEGIN.*PRIVATE)', key + '\n' + content):
        raise MemoryRefusal('sensitive_memory', 'Keep credentials in protected storage, outside memory.', 400)
    cues = body.get('cues', {'intent': [key]})
    if not isinstance(cues, dict) or set(cues) - set(CUE_FIELDS):
        raise MemoryRefusal('invalid_cues', 'Use intent, app, layer, files, task or entities cues.', 400)
    normalized = {}
    for field, values in cues.items():
        if not isinstance(values, list) or len(values) > 12 or any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in values):
            raise MemoryRefusal('invalid_cues', 'Each cue is a short string; at most 12 per field.', 400)
        if field == 'files' and any(Path(v).is_absolute() or '..' in v.replace('\\', '/').split('/') for v in values):
            raise MemoryRefusal('invalid_cues', 'File cues must stay relative to this project.', 400)
        normalized[field] = list(dict.fromkeys(v.strip().casefold() for v in values))
    if not any(normalized.values()):
        raise MemoryRefusal('invalid_cues', 'Give the memory at least one situation cue.', 400)
    expiry = body.get('expiresAt')
    if expiry is not None:
        try:
            parsed = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError()
            expiry = parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        except (AttributeError, TypeError, ValueError):
            raise MemoryRefusal('invalid_expiry', 'Use an expiry date with timezone.', 400) from None
    export = body.get('exportPolicy', 'local')
    if export not in ('local', 'provider'):
        raise MemoryRefusal('invalid_memory', 'Choose local or provider context.', 400)
    return {'key': key, 'content': content, 'kind': kind, 'cues': normalized, 'expiresAt': expiry, 'exportPolicy': export}


class CueMemoryStore:
    def __init__(self, context):
        self.context = require_context(context)
        self.path = self.context.root / '.agent_control/private_memory/store.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS scopes(owner TEXT,project TEXT,path TEXT,generation INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(owner,project));
                CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,owner TEXT,project TEXT,key TEXT,status TEXT,revision INTEGER,data TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS active_memory_key ON memories(owner,project,key) WHERE status IN ('active','pending');
                CREATE TABLE IF NOT EXISTS requests(owner TEXT,project TEXT,request TEXT,intent TEXT,id TEXT,PRIMARY KEY(owner,project,request));
                CREATE TABLE IF NOT EXISTS events(owner TEXT,project TEXT,generation INTEGER,operation TEXT,id TEXT,revision INTEGER,at TEXT,previous_hash TEXT);
                CREATE TABLE IF NOT EXISTS sessions(owner TEXT,project TEXT,session TEXT,generation INTEGER,PRIMARY KEY(owner,project,session));
            ''')
            db.execute('INSERT OR IGNORE INTO scopes(owner,project,path) VALUES(?,?,?)', (*self.context.identity, str(self.context.project_path)))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA secure_delete=ON')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _row(self, db, identity):
        row = db.execute('SELECT * FROM memories WHERE owner=? AND project=? AND id=?', (*self.context.identity, identity)).fetchone()
        if row is None:
            raise MemoryRefusal('memory_not_found', 'This memory is unavailable in your project.', 404)
        return json.loads(row['data'])

    def inspect(self, identity):
        with self.connect() as db:
            return self._row(db, identity)

    def generation(self, db=None):
        if db is None:
            with self.connect() as conn:
                return self.generation(conn)
        return db.execute('SELECT generation FROM scopes WHERE owner=? AND project=?', self.context.identity).fetchone()[0]

    def snapshot(self, include_pending=False, limit=100):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise MemoryRefusal('invalid_memory', 'Invalid bounded memory scan.', 400)
        with self.connect() as db:
            db.execute('BEGIN')
            rows = db.execute('SELECT data FROM memories WHERE owner=? AND project=? AND status IN (?,?) ORDER BY id LIMIT ?',
                (*self.context.identity, 'active', 'pending' if include_pending else 'active', limit)).fetchall()
            current = now()
            return {'generation': self.generation(db), 'memories': [data for row in rows
                if (data := json.loads(row[0])) and (include_pending or not data.get('expiresAt') or data['expiresAt'] > current)],
                'scope': {'projectId': self.context.project, 'project': str(self.context.project_path), 'user': self.context.owner}}

    def mutate(self, operation, body):
        if operation not in ('remember', 'correct', 'forget'):
            raise MemoryRefusal('invalid_memory', 'Unknown memory operation.', 400)
        request = text(body, 'requestId', 200)
        fields = claim_fields(body) if operation != 'forget' else None
        if fields and fields['exportPolicy'] == 'provider' and not self.context.provider_export_authorized:
            raise MemoryRefusal('memory_export_refused', 'Allow provider context explicitly for this memory.', 403)
        intent = fingerprint([operation, body])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            retry = db.execute('SELECT intent,id FROM requests WHERE owner=? AND project=? AND request=?', (*self.context.identity, request)).fetchone()
            if retry:
                if retry['intent'] != intent:
                    raise MemoryRefusal('memory_request_conflict', 'This request ID was already used for a different change.')
                return {'memory': self._row(db, retry['id']), 'generation': self.generation(db), 'replayed': True}
            previous = None
            if operation == 'remember':
                existing = db.execute("SELECT id FROM memories WHERE owner=? AND project=? AND key=? AND status IN ('active','pending')",
                    (*self.context.identity, fields['key'].casefold())).fetchone()
                if existing:
                    raise MemoryRefusal('memory_key_exists', 'That subject already exists. Correct it using its current revision.')
                count = db.execute("SELECT count(*) FROM memories WHERE owner=? AND project=? AND status IN ('active','pending')", self.context.identity).fetchone()[0]
                if count >= 10000:
                    raise MemoryRefusal('memory_full', 'Review and forget unused memories before adding more.')
                identity, revision = 'mem_' + uuid.uuid4().hex, 1
            else:
                identity = text(body, 'id', 80)
                previous = self._row(db, identity)
                expected = body.get('expectedRevision')
                if type(expected) is not int or expected != previous['revision'] or previous['status'] == 'deleted':
                    raise MemoryRefusal('memory_revision_conflict', 'Memory changed. Refresh before editing or deleting.')
                revision = expected + 1
            if fields:
                collision = db.execute("SELECT id FROM memories WHERE owner=? AND project=? AND key=? AND status IN ('active','pending') AND id<>?",
                    (*self.context.identity, fields['key'].casefold(), identity)).fetchone()
                if collision:
                    raise MemoryRefusal('memory_key_exists', 'Another memory already has that subject. Choose a different subject.')
            at = now()
            row = {'id': identity, 'revision': revision, 'status': 'deleted' if operation == 'forget' else
                   'active' if self.context.explicit_write else 'pending', 'updatedAt': at}
            if operation != 'forget':
                row.update(fields, createdAt=previous.get('createdAt', at) if previous else at,
                    provenance={'kind': self.context.source_kind, 'sourceId': self.context.source_id},
                    confidence={'value': 1 if self.context.explicit_write else None, 'basis': 'explicit-user' if self.context.explicit_write else 'unverified-candidate'},
                    supersedes={'id': identity, 'revision': previous['revision'], 'hash': fingerprint(previous)} if previous else None)
                if previous:
                    source = previous['provenance']
                    row['provenance']['origin'] = source.get('origin') or {key: source[key] for key in ('kind', 'sourceId')}
            # Deletion rewrites the body and cue fields. Requests/events never retain bodies.
            db.execute('INSERT OR REPLACE INTO memories VALUES(?,?,?,?,?,?,?)',
                (identity, *self.context.identity, fields['key'].casefold() if fields else '', row['status'], revision, canonical(row)))
            db.execute('UPDATE scopes SET generation=generation+1 WHERE owner=? AND project=?', self.context.identity)
            generation = self.generation(db)
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)', (*self.context.identity, generation, operation, identity, revision, at, fingerprint(previous) if previous else ''))
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)', (*self.context.identity, request, intent, identity))
            return {'memory': row, 'generation': generation, 'replayed': False}

    def mark_session(self, session, generation):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.generation(db) != generation:
                raise MemoryRefusal('memory_context_revoked', 'Memory changed before submission. Start a fresh turn.')
            db.execute('INSERT OR IGNORE INTO sessions VALUES(?,?,?,?)', (*self.context.identity, session, generation))

    def session_valid(self, session):
        with self.connect() as db:
            row = db.execute('SELECT generation FROM sessions WHERE owner=? AND project=? AND session=?', (*self.context.identity, session)).fetchone()
            return row is None or row[0] == self.generation(db)

    def events_since(self, generation):
        with self.connect() as db:
            rows = db.execute('SELECT generation,operation,id,revision FROM events WHERE owner=? AND project=? AND generation>? ORDER BY generation',
                (*self.context.identity, generation)).fetchall()
            return [dict(row) for row in rows]
