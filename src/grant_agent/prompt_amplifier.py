"""Revision-bound rough-prompt preparation before a connected agent turn.

The unchanged original and Paul manual remain authoritative; the script tier
never invokes a model or falls through to another cascade tier.
CL-Prompt is an envelope, not executable CL code. Context pointers are data;
this module never opens the files named by a prompt or invents authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import re
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .connected_sessions.registry import ConnectedError
from .prompt_coverage import check_coverage, compile_checklist
from .paul_manual import MANUAL
from .transition_memory import atomic_json, digest

COMMANDS = frozenset({"prompt_amplify_command", "prompt_amplification_get_command", "prompt_amplification_edit_command"})
TOOLS = {"prompt.amplify": "prompt_amplify_command", "prompt.get": "prompt_amplification_get_command",
         "prompt.edit": "prompt_amplification_edit_command"}
TEXT = {"type": "string"}
DEFINITIONS = [
    ("prompt.amplify", "Prepare reversible inline mishear/reference readings; retain card checklist; zero model calls.",
     {"text": TEXT, "requestId": TEXT, "sessionId": TEXT, "context": {"type": "object"},
      "mode": {"type": "string", "enum": ["auto", "review"]},
      "variant": {"type": "string", "enum": ["raw", "minimal", "full"]}}, ["text", "requestId"]),
    ("prompt.get", "Read a saved amplified prompt and its current revision.", {"id": TEXT}, ["id"]),
    ("prompt.edit", "Save Paul's exact prompt edit with a revision guard; evidence retained without model drafting.",
     {"id": TEXT, "revision": {"type": "integer"}, "requestId": TEXT, "text": TEXT},
     ["id", "revision", "requestId", "text"]),
]
_SERVICES = {}
_LOCK = threading.RLock()
DEFAULT_VARIANT = 'minimal'


def minimal_edits(record):
    """Only audited vocabulary and resolved mentions may alter source wording.

    Every replacement includes its exact heard text; source offsets and the
    unchanged original make reversal independent of annotation punctuation.
    Uncertain negation is a card assumption, never an inline instruction.
    """
    text, edits = record['original'], []
    for item in record['checklist']['items']:
        for hint in item['readingHints']:
            if hint['rule'].startswith('uncertain negation'):
                continue
            pattern = re.compile(r'(?<![\w/\\`.-])' + re.escape(hint['heard'])
                                 + r'(?![\w/\\`-]|\.\w)', re.I)
            for match in pattern.finditer(text, *item['span']):
                edits.append({'span': [match.start(), match.end()], 'before': match.group(),
                              'reading': hint['reading'], 'kind': 'heard'})
    for ref in record.get('references', []):
        if ref.get('state') == 'resolved':
            edits.append({'span': ref['span'], 'before': text[slice(*ref['span'])],
                          'reading': ref['targetText'], 'kind': 'ref'})
    edits.sort(key=lambda row: row['span'])
    for index, edit in enumerate(edits):
        if index and edits[index-1]['span'][1] > edit['span'][0]:
            raise ConnectedError('amplification_coverage_failed', 'Inline readings overlap.', 409)
        edit['after'] = edit['reading'] + ' [' + edit['kind'] + ': ' + json.dumps(edit['before'], ensure_ascii=False) + ']'
    return edits


def render_minimal(record):
    text = record['original']
    for edit in reversed(minimal_edits(record)):
        start, end = edit['span']
        text = text[:start] + edit['after'] + text[end:]
    return text


def render_prompt(record):
    variant = record.get('variant', 'full')  # historical revisions retain their form
    if variant == 'raw':
        return record['original']
    if variant == 'minimal':
        return render_minimal(record)
    return record['original'] + "\n\n--- Added reading aid (original above is authoritative) ---\n" + (
        'M lines are assumptions, never instructions; discard any reading that contradicts the original.\n'
        + record['cl'])


def _text(body, key, limit=200, required=True):
    value = body.get(key, "")
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ConnectedError("invalid_request", f"{key} must be text of at most {limit} characters.")
    return value


def _context(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"project", "chat", "files", "decisions"}:
        raise ConnectedError("invalid_request", "Context must contain project, chat, files or decisions.")
    if len(json.dumps(value, ensure_ascii=False)) > 24000:
        raise ConnectedError("invalid_request", "Prompt context is limited to 24,000 characters.")
    result = {}
    if "project" in value:
        result["project"] = _text(value, "project", 2000)
    for key in ("chat", "files", "decisions"):
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 32:
            raise ConnectedError("invalid_request", f"Context {key} must be a list of at most 32 entries.")
        for row in rows:
            if key == "decisions":
                if not isinstance(row, str) or not row.strip() or len(row) > 4000:
                    raise ConnectedError("invalid_request", "Decisions must be bounded text.")
            elif key == "chat":
                if not isinstance(row, dict) or set(row) != {"role", "text"} or row.get("role") not in {"user", "assistant"}:
                    raise ConnectedError("invalid_request", "Chat context requires role and text.")
                _text(row, "text", 8000)
            else:
                if not isinstance(row, dict) or set(row) - {"path", "summary"}:
                    raise ConnectedError("invalid_request", "File context requires a path and optional summary.")
                _text(row, "path", 2000)
                _text(row, "summary", 4000, False)
        result[key] = rows
    return result


def _pointers(context):
    return ([{"kind": "manual", "target": "working-with-paul"}]
        + ([{"kind": "project", "target": context["project"]}] if context.get("project") else [])
        + [{"kind": "file", "target": row["path"]} for row in context.get("files", [])]
        + [{"kind": "decision", "target": str(i)} for i in range(len(context.get("decisions", [])))]
        + [{"kind": "chat", "target": str(i)} for i in range(len(context.get("chat", [])))])


def render_cl(record):
    """Source offsets carry the checklist; stored context is fetched on demand.

    The original occurs once. No generic acceptance policy or inferred action
    is inserted: sentence classification is fallible and must not narrow asks.
    """
    encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    lines = ["CL 1.1", "L prompt." + record["id"] + " r" + str(record['revision']),
             "G D original; wording and requested form govern.",
             "A spans=Unicode characters; reading coverage, not a limit on distinct asks."]
    for item in record['checklist']['items']:
        lines.append(f"A {item['number']} {item['span'][0]}:{item['span'][1]}")
        for hint in item['readingHints']:
            lines.append('M assumption ' + encode({'item': item['number'], 'heard': hint['heard'],
                                                  'reading': hint['reading']}))
    for reference in record.get('references', []):
        if reference.get('state') == 'resolved':
            lines.append('M assumption ' + encode({'span': reference['span'],
                                                   'referent': reference['targetText']}))
    for constraint in record['constraints']:
        start = record['original'].find(constraint)
        if start >= 0:
            lines.append(f"X {start}:{start + len(constraint)}")
    # Full chat/decisions/file summaries and audit maps remain in prompt.get;
    # the consumer gets a usable handle instead of another pasted conversation.
    if any(record.get('context', {}).get(key) for key in ('project', 'chat', 'files', 'decisions')):
        lines.append('R prompt.get ' + record['id'] + ' context; fetch only if needed.')
    lines += ['J ' + encode(question) for question in record['questions']]
    return "\n".join(lines)


class PromptAmplifier:
    def __init__(self, root, *, provider=None, system1=None):
        self.root = Path(root).resolve()
        self.directory = self.root / ".neyvia" / "prompt-amplification"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "store.sqlite3"
        # Compatibility injection arguments intentionally cannot enable a model.
        # This path is the cascade's script tier; failures never fall through.
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, intent TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(id TEXT, revision INTEGER, data TEXT NOT NULL, PRIMARY KEY(id,revision));
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, identity):
        identity = _text({"id": identity}, "id")
        with self.db() as db:
            row = db.execute("SELECT data FROM records WHERE id=?", (identity,)).fetchone()
        if not row:
            raise ConnectedError("amplification_not_found", "That prepared prompt was not found.", 404)
        record = json.loads(row[0])
        return {"amplification": record}

    def _retry(self, db, request_id, fingerprint):
        row = db.execute("SELECT intent,data FROM requests WHERE id=?", (request_id,)).fetchone()
        if row and row[0] != fingerprint:
            raise ConnectedError("request_conflict", "This requestId already identifies a different prompt.", 409)
        return json.loads(row[1]) if row else None

    def amplify(self, body, *, emit=None, request_identity=None):
        started = time.monotonic()
        text = _text(body, "text", 40000)
        request_id = _text(body, "requestId")
        session_id = _text(body, "sessionId", 500, False)
        mode = body.get("mode", "auto")
        if mode not in {"auto", "review"}:
            raise ConnectedError("invalid_request", "Mode must be auto or review.")
        context = _context(body.get("context"))
        variant = body.get('variant', DEFAULT_VARIANT)
        if variant not in {'raw', 'minimal', 'full'}:
            raise ConnectedError('invalid_request', 'Variant must be raw, minimal or full.')
        fingerprint = request_identity or digest({"op": "amplify", "text": text, "sessionId": session_id, "context": context, "mode": mode, 'variant': variant})
        with self.db() as db:
            saved = self._retry(db, request_id, fingerprint)
        if saved:
            return saved
        checklist, coverage, constraints, references = compile_checklist(text, context)
        if not coverage['ok']:
            raise ConnectedError('amplification_coverage_failed', 'Original text has uncovered or invalid spans.', 409,
                                 coverage=coverage)
        identity = uuid.uuid4().hex
        receipt_path = self.directory / 'receipts' / (identity + '.json')
        questions = checklist['questions']
        record = {'schema': 'neyvia.prompt-amplification.v1', 'id': identity,
            'revision': 1, 'requestId': request_id, 'sessionId': session_id, 'mode': mode, 'variant': variant, 'original': text,
            'status': 'needs_input' if questions else 'ready', 'context': context,
            'goal': next((item['ask'] for item in checklist['items']
                          if item['actionability'] == 'explicit'), text)[:240],
            'deliverable': 'The form requested in the original; preserve questions and plan-only limits.',
            'checks': [item['quote'] for item in checklist['items']
                       if item['actionability'] == 'explicit'],
            'constraints': constraints, 'contextPointers': _pointers(context), 'references': references,
            'assumptions': [],
            'questions': questions, 'checklist': checklist, 'coverage': coverage, 'route': 'script',
            'tokens': {'input': 0, 'output': 0, 'cachedInput': 0, 'total': 0}, 'receiptPath': str(receipt_path)}
        record['assumptions'] += [f"Assumption for item {ref['item']}: {ref['surface']} refers to {ref['targetText']}."
                                  for ref in references if ref.get('state') == 'resolved']
        record['assumptions'] += [f"Assumption for item {item['number']}: {hint['heard']} means {hint['reading']}."
                                  for item in checklist['items'] for hint in item['readingHints']]
        record['cl'] = render_cl(record)
        record['inlineEdits'] = minimal_edits(record)
        record['agentPrompt'] = render_prompt(record)
        from .connected_sessions.broker import MAX_MESSAGE_CHARS
        if len(record['agentPrompt']) > MAX_MESSAGE_CHARS:
            raise ConnectedError('amplification_too_large',
                                 'The original plus reading aid exceeds the connected prompt limit; split the request.', 400)
        record['elapsedMs'] = round((time.monotonic() - started) * 1000, 3)
        response = {'amplification': record}
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            saved = self._retry(db, request_id, fingerprint)
            if saved:
                return saved
            data = json.dumps(record, ensure_ascii=False)
            db.execute('INSERT INTO records VALUES(?,?)', (identity, data))
            db.execute('INSERT INTO revisions VALUES(?,?,?)', (identity, 1, data))
            db.execute('INSERT INTO requests VALUES(?,?,?)', (request_id, fingerprint, json.dumps(response, ensure_ascii=False)))
        atomic_json(receipt_path, {'schema': 'neyvia.prompt-amplification.receipt.v2', 'id': identity,
            'originalSha256': digest(text), 'agentPromptSha256': digest(record['agentPrompt']),
            'coverage': coverage, 'route': 'script', 'modelCalls': [], 'tokens': record['tokens'],
            'manualSha256': digest(MANUAL.read_text(encoding='utf-8')),
            'elapsedMs': round((time.monotonic() - started) * 1000, 3)})
        self._emit(emit, 'prompt.amplified', record)
        return response

    def _emit(self, emit, name, record):
        if emit:
            emit({"type": name, "sessionId": record["sessionId"], "amplificationId": record["id"],
                  "revision": record["revision"], "status": record["status"],
                  **({"learning": record["learning"]} if "learning" in record else {})})

    def edit(self, body, *, emit=None):
        identity = _text(body, "id")
        text = _text(body, "text", 40000)
        request_id = _text(body, "requestId")
        revision = body.get("revision")
        if type(revision) is not int or revision < 1:
            raise ConnectedError("invalid_request", "A positive revision is required.")
        fingerprint = digest({"op": "edit", "id": identity, "revision": revision, "text": text})
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            saved = self._retry(db, request_id, fingerprint)
            if saved:
                return saved
            row = db.execute("SELECT data FROM records WHERE id=?", (identity,)).fetchone()
            if not row:
                raise ConnectedError("amplification_not_found", "That prepared prompt was not found.", 404)
            record = json.loads(row[0])
            if record["revision"] != revision:
                raise ConnectedError("stale_amplification", "The prepared prompt changed. Reload it before editing.", 409)
            if 'coverage' not in record:
                # Explicit owner edits can migrate older records without a model.
                record['checklist'], record['coverage'], _, record['references'] = compile_checklist(record['original'], record.get('context', {}))
            before = record["agentPrompt"]
            record.update(revision=revision + 1, status="edited", agentPrompt=text)
            record["learning"] = {"state": "pending_gate", "lessonIds": [], "reason": "Edit evidence retained locally; automatic model drafting disabled. C9 replay and regression gate required."}
            record["editEvidence"] = {"before": before, "after": text, "requestId": request_id}
            record["cl"] = render_cl(record)
            data = json.dumps(record, ensure_ascii=False)
            response = {"amplification": record, "learning": record["learning"]}
            db.execute("UPDATE records SET data=? WHERE id=?", (data, identity))
            db.execute("INSERT INTO revisions VALUES(?,?,?)", (identity, revision + 1, data))
            db.execute("INSERT INTO requests VALUES(?,?,?)", (request_id, fingerprint, json.dumps(response, ensure_ascii=False)))
        self._queue_edit(record, emit)
        self._emit(emit, "prompt.edited", record)
        return response

    def _queue_edit(self, record, emit=None):
        # Retain evidence for the existing C9 gate without starting its model pool.
        path = self.directory / 'edit-evidence' / (record['id'] + '-' + str(record['revision']) + '.json')
        atomic_json(path, {'schema': 'neyvia.prompt-edit-evidence.v1', 'state': 'pending_gate',
                          'original': record['original'], 'edit': record['editEvidence'], 'tokens': 0})

    def consume(self, options, message, session_id="", *, emit=None):
        if not isinstance(options, dict) or not options.get("amplificationId"):
            return message
        record = self.get(options["amplificationId"])["amplification"]
        if type(options.get("amplificationRevision")) is not int or options["amplificationRevision"] != record["revision"]:
            raise ConnectedError("stale_amplification", "Review the latest prepared prompt before sending.", 409)
        if record["sessionId"] != session_id or message != record["original"]:
            raise ConnectedError("amplification_conflict", "This prepared prompt belongs to a different message or chat.", 409)
        if record["status"] == "needs_input":
            raise ConnectedError("amplification_needs_input", "Answer or edit the question before sending.", 409)
        coverage = check_coverage(record['original'], record['checklist'])
        if not coverage['ok']:
            raise ConnectedError('amplification_coverage_failed', 'Prepared prompt lost original sentence coverage.', 409)
        if record['status'] != 'edited' and record['agentPrompt'] != render_prompt(record):
            raise ConnectedError('amplification_coverage_failed', 'Prepared prompt differs from its source-bound readings.', 409)
        self._emit(emit, "prompt.consumed", record)
        return record["agentPrompt"]


def service_for(root):
    key = str(Path(root).resolve())
    with _LOCK:
        if key not in _SERVICES:
            _SERVICES[key] = PromptAmplifier(root)
        return _SERVICES[key]


def handle_command(backend, command, body):
    from .connected_sessions.broker import broker_for
    broker = broker_for(backend.root, backend)
    service = service_for(backend.root)
    if command == "prompt_amplify_command":
        body = dict(body)
        request_id = _text(body, "requestId")
        original_context = _context(body.get("context"))
        request_identity = digest({"op": "amplify", "text": _text(body, "text", 40000),
            "sessionId": _text(body, "sessionId", 500, False), "context": original_context,
            "mode": body.get("mode", "auto"), 'variant': body.get('variant', DEFAULT_VARIANT)})
        # Freeze auto-collected context on the first request; retries must not
        # change meaning or spend another model call as a chat gains new items.
        with service.db() as db:
            saved = service._retry(db, request_id, request_identity)
        if saved:
            return saved
        session_id = body.get("sessionId")
        if session_id:
            broker._host_check(session_id)
            page = broker.read(session_id, limit=12)
            context = _context(body.get("context"))
            # Read only the broker's already projected chat text; no filesystem scans.
            chat = []
            for item in page.get("items", []):
                role = item.get("kind")
                text = (item.get("data") or {}).get("text")
                if role in {"user", "assistant"} and isinstance(text, str) and text.strip():
                    chat.append({"role": role, "text": text[:1500]})
            context["chat"] = (chat + context.get("chat", []))[-12:]
            context.setdefault("project", broker.session_cwd(session_id) or "")
            if not context["project"]:
                context.pop("project")
            body["context"] = context
        return service.amplify(body, emit=broker._publish, request_identity=request_identity)
    if command == "prompt_amplification_get_command":
        return service.get(_text(body, "id"))
    if command == "prompt_amplification_edit_command":
        return service.edit(body, emit=broker._publish)
    raise ConnectedError("unknown_command", "Unknown prompt command.", 404)


def call(service, name, args):
    from types import SimpleNamespace
    return handle_command(service.backend or SimpleNamespace(root=service.bus.root), TOOLS[name], args)
