"""Sidebar observation and durable preview/confirm/undo on the existing UI bus."""
from __future__ import annotations
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

S = {'type': 'string'}
IDS = {'type': 'array', 'items': S, 'maxItems': 100, 'uniqueItems': True}
LIMIT = {'type': 'integer', 'minimum': 1, 'maximum': 100}
DEFINITIONS = [
    ('sidebar.state', 'Observe transcript-based lanes, actual agent subtrees and hover text.', {'ids': IDS, 'limit': LIMIT, 'offset': {'type': 'integer', 'minimum': 0}, 'query': S}, []),
    ('sidebar.preview', 'Preview local semantic subject folders; moves nothing.', {'ids': IDS, 'limit': LIMIT, 'threshold': {'type': 'number', 'minimum': .35, 'maximum': .95}}, []),
    ('sidebar.confirm', 'Confirm an unchanged durable sidebar preview. Reuse previewId for retries.', {'previewId': S, 'confirmed': {'const': True}, 'groupIds': IDS}, ['previewId', 'confirmed']),
    ('sidebar.undo', 'Restore exact prior assignments; preserve later manual changes.', {'undoId': S}, ['undoId']),
]
COMMANDS = frozenset('sidebar_' + name.split('.')[1] + '_command' for name, *_ in DEFINITIONS)
ACTIVE = {'working', 'waiting_approval', 'waiting_input'}
SUBJECT_STOP_WORDS = frozenset('a an and are as at be build can chat conversation create for from help how i in is it me my of on please session that the this to use we with you your new fix make review implement about also describe each explain find improve into need not our should show summarize tell then these those want what when which will would write'.split())


def subject_name(rows):
    """Label an embedding-confirmed group from shared prompt words, not chat titles."""
    documents = []
    for row in rows:
        words = re.findall(r"[^\W\d_][\w'-]*", row.get('subject', '').lower(), re.UNICODE)
        phrases = set()
        for start in range(len(words)):
            for size in range(1, 4):
                phrase = words[start:start + size]
                if len(phrase) == size and all(len(word) > 2 and word not in SUBJECT_STOP_WORDS for word in phrase):
                    phrases.add(' '.join(phrase))
        documents.append(phrases)
    shared = set.intersection(*documents) if documents else set()
    if not shared:
        return 'Related conversations'
    name = min(shared, key=lambda phrase: (-len(phrase.split()), -len(phrase), phrase))[:80]
    return name[:1].upper() + name[1:]

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _plan_source_digest():
    """Bind a preview to the implementation that produced its grouping plan."""
    from . import neyvia_sidebar_semantics
    sha = hashlib.sha256()
    for path in (Path(__file__), Path(neyvia_sidebar_semantics.__file__)):
        sha.update(path.name.encode())
        sha.update(hashlib.sha256(path.read_bytes()).digest())
    return sha.hexdigest()

def _read(db, key, default=None):
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default

def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES(?,?)', (key, json.dumps(value)))

def observation(service, identity):
    broker = service.broker()
    summary = broker.find_summary(identity)
    page = broker.read(identity, limit=500)
    row = page.get('session') or (summary.public() if summary is not None else None)
    if row is None:
        raise ValueError('Session unavailable: ' + identity)
    saved_sessions = service.bus.get('sessions', {})
    saved = saved_sessions.get(identity, {})
    prompts = [str(item.get('data', {}).get('text') or '')[:1500] for item in page.get('items', []) if item.get('kind') == 'user']
    # Encode the subject, not repeated auto-titles or harness instructions.
    subjects = [re.split(r'(?<=[.!?])\s+', prompt, maxsplit=1)[0] for prompt in prompts[:4]]
    subject = '\n'.join(subjects)
    title = str(saved.get('title') or row.get('title') or '')
    if title and not any(prompt.startswith(title) for prompt in prompts):
        subjects.insert(0, title)
    text = '\n'.join(subjects)[:6000]
    run = broker.latest_run(identity)
    active = row.get('status') in ACTIVE or run and run.get('state') in {'queued', 'running', 'waiting_approval', 'waiting_input'}
    return {'id': identity, 'title': saved.get('title') or row.get('title'), 'text': text, 'subject': subject,
            'stamp': digest({'updated': row.get('updated_at'), 'cursor': page.get('cursor'), 'items': page.get('items'), 'saved': saved}),
            'before': {'present': 'project' in saved, 'value': saved.get('project')},
            'savedPresent': identity in saved_sessions,
            'active': bool(active), 'archived': bool(row.get('archived') or saved.get('archived')),
            'row': row, 'saved': saved}

def preview(service, args):
    from .neyvia_sidebar_semantics import encode, similarity
    from .connected_sessions.sidebar_cleanup import SidebarSafetyObserver
    started = time.monotonic()
    limit = args.get('limit', 100)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    threshold = args.get('threshold', .5)
    if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not .35 <= threshold <= .95:
        raise ValueError('threshold must be .35..95')
    ids = args.get('ids')
    if ids is not None and (not isinstance(ids, list) or len(ids) > 100 or not all(isinstance(i, str) for i in ids)):
        raise ValueError('ids must contain at most 100 session IDs')
    listing = None if ids is not None else service.broker().list_sessions(limit=limit, observe=False)
    ids = ids if ids is not None else [row['id'] for row in listing['sessions']]
    projects = service.bus.get('projects', {})
    observer = SidebarSafetyObserver(projects.values())
    rows, skipped = [], []
    for identity in dict.fromkeys(ids):
        try:
            row = observation(service, identity)
            known = observer.observe(row['row'].get('cwd')).get('project_known')
            reason = 'active' if row['active'] else 'archived' if row['archived'] else 'already_filed' if row['before']['value'] or not row['before']['present'] and known else None
            if reason:
                skipped.append({'id': identity, 'reason': reason})
            elif row['text'].strip():
                rows.append(row)
        except Exception as exc:
            skipped.append({'id': identity, 'reason': str(exc)[:200]})
    project_rows = [(path, project) for path, project in projects.items()]
    try:
        vectors, model = encode(service, [row['text'] for row in rows] +
                                [str(p.get('name', '')) + '. ' + str(p.get('description', '')) for _, p in project_rows])
    except Exception as exc:
        return {'ok': False, 'status': 'model_unavailable', 'error': str(exc)[:300], 'skipped': skipped}
    identity = uuid.uuid4().hex
    groups, assigned = [], set()
    for index, row in enumerate(rows):
        scores = sorted([(similarity(vectors[index], vectors[len(rows)+n]), path, p) for n, (path, p) in enumerate(project_rows)], key=lambda v: v[0], reverse=True)
        if scores and scores[0][0] >= threshold and (len(scores) == 1 or scores[0][0] - scores[1][0] >= .05):
            score, path, p = scores[0]
            group = next((g for g in groups if g['target']['id'] == path), None)
            if group is None:
                group = {'id': uuid.uuid4().hex, 'name': p['name'], 'ids': [], 'confidence': score, 'reason': 'Local sentence embeddings match the project subject', 'target': {'id': path, 'name': p['name'], 'path': path}}
                groups.append(group)
            group['ids'].append(row['id']); group['confidence'] = min(score, group['confidence']); assigned.add(index)
    # Complete-link clusters: every pair must match; no similarity chaining.
    clusters = []
    for index in range(len(rows)):
        if index in assigned: continue
        group = next((c for c in clusters if all(similarity(vectors[index], vectors[n]) >= threshold for n in c)), None)
        if group is None: clusters.append([index])
        else: group.append(index)
    for indices in clusters:
        if len(indices) < 2: continue
        name = subject_name([rows[index] for index in indices])
        target = {'id': 'subject:' + uuid.uuid4().hex, 'name': name, 'path': None}
        score = min(similarity(vectors[a], vectors[b]) for n,a in enumerate(indices) for b in indices[n+1:])
        groups.append({'id': uuid.uuid4().hex, 'name': name, 'ids': [rows[n]['id'] for n in indices], 'confidence': score, 'reason': 'Local sentence embeddings agree across every conversation pair', 'target': target})
    suggestions = [{'id': row['id'], 'title': row['title'], 'before': row['before'], 'project': group['target']['id'], 'confidence': group['confidence'], 'reason': group['reason']} for group in groups for row in rows if row['id'] in group['ids']]
    result = {'ok': True, 'status': 'preview', 'previewId': identity, 'expiresAt': time.time()+1800, 'groups': groups, 'suggestions': suggestions, 'skipped': skipped, 'model': model, 'planSourceDigest': _plan_source_digest(), 'ms': round((time.monotonic()-started)*1000), 'nextOffset': listing.get('nextOffset') if listing else None}
    service.bus.put('sidebar:preview:' + identity, {'result': result, 'rows': {row['id']: {'stamp': row['stamp'], 'before': row['before'], 'savedPresent': row['savedPresent']} for row in rows}})
    return result

def confirm(service, args):
    if args.get('confirmed') is not True:
        return {'ok': False, 'status': 'confirmation_required', 'moved': [], 'undoId': None, 'conflicts': []}
    identity = str(args.get('previewId') or '')
    key = 'sidebar:preview:' + identity
    record = service.bus.get(key)
    if not record: raise ValueError('Unknown previewId')
    result = record['result']
    if result.get('planSourceDigest') != _plan_source_digest():
        return {'ok': False, 'status': 'stale_preview', 'moved': [], 'undoId': None,
                'conflicts': [{'id': identity, 'reason': 'plan_changed'}]}
    # A preview is a decision over both conversation state and the exact local
    # model bytes. Refuse a changed or missing model before replay or any write.
    try:
        from .neyvia_sidebar_semantics import source_identity
        model_current = source_identity()[2]
    except Exception:
        model_current = None
    if not model_current or model_current != result.get('model', {}).get('sourceDigest'):
        return {'ok': False, 'status': 'stale_preview', 'moved': [], 'undoId': None,
                'conflicts': [{'id': identity, 'reason': 'model_changed'}]}
    if record.get('receipt'): return {**record['receipt'], 'replayed': True}
    group_ids = args.get('groupIds', [g['id'] for g in result['groups']])
    if not isinstance(group_ids, list) or not set(group_ids) <= {g['id'] for g in result['groups']}:
        raise ValueError('Unknown groupIds')
    groups = [g for g in result['groups'] if g['id'] in group_ids]
    conflicts = []
    if time.time() > result['expiresAt']: conflicts.append({'id': identity, 'reason': 'expired'})
    for group in groups:
        for sid in group['ids']:
            try:
                fresh = observation(service, sid)
                if fresh['active'] or fresh['archived'] or fresh['stamp'] != record['rows'][sid]['stamp']:
                    conflicts.append({'id': sid, 'reason': 'conversation_changed'})
            except Exception:
                conflicts.append({'id': sid, 'reason': 'session_unavailable'})
    if conflicts:
        # A concurrent successful retry atomically saves its receipt with the
        # assignment writes. Read it again before calling those writes stale.
        latest = service.bus.get(key)
        if latest and latest.get('receipt'):
            return {**latest['receipt'], 'replayed': True}
        return {'ok': False, 'status': 'stale_preview', 'moved': [], 'undoId': None, 'conflicts': conflicts}
    events = []
    with service.bus.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = _read(db, key)
        if current.get('receipt'): return {**current['receipt'], 'replayed': True}
        sessions, folders, projects = _read(db, 'sessions', {}), _read(db, 'sidebar:folders', {}), _read(db, 'projects', {})
        moves = {}
        for group in groups:
            target = group['target']
            if target['path'] is not None and target['id'] not in projects:
                conflicts.append({'id': target['id'], 'reason': 'project_removed'})
            for sid in group['ids']:
                before = record['rows'][sid]['before']; saved = sessions.get(sid, {})
                if before != {'present': 'project' in saved, 'value': saved.get('project')}:
                    conflicts.append({'id': sid, 'reason': 'assignment_changed'})
                moves[sid] = {'before': before, 'after': target['id'],
                              'beforeSavedPresent': record['rows'][sid].get('savedPresent', True)}
        if conflicts: return {'ok': False, 'status': 'stale_preview', 'moved': [], 'undoId': None, 'conflicts': conflicts}
        for group in groups:
            if group['target']['path'] is None: folders[group['target']['id']] = group['target']
        for sid, move in moves.items():
            sessions[sid] = {**sessions.get(sid, {}), 'project': move['after']}
            events.append({'id': sid, 'project': move['after']})
        undo_id = uuid.uuid4().hex if moves else None
        receipt = {'ok': True, 'status': 'completed', 'moved': list(moves), 'undoId': undo_id, 'conflicts': []}
        _put(db, 'sessions', sessions); _put(db, 'sidebar:folders', folders)
        if undo_id: _put(db, 'sidebar:undo:' + undo_id, {'moves': moves})
        _put(db, key, {**current, 'receipt': receipt})
        for event in events:
            from .ui_command_bus import now
            db.execute('INSERT INTO events(ts,action,payload) VALUES(?,?,?)', (now(), 'session.moved', json.dumps(event)))
    with service.bus.changed: service.bus.changed.notify_all()
    return receipt

def undo(service, args):
    identity = str(args.get('undoId') or '')
    with service.bus.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        record = _read(db, 'sidebar:undo:' + identity)
        if not record: raise ValueError('Unknown undoId')
        if record.get('receipt'): return {**record['receipt'], 'replayed': True}
        sessions = _read(db, 'sessions', {})
        restored, conflicts = [], []
        for sid, move in record['moves'].items():
            saved = sessions.get(sid, {})
            if saved.get('project') != move['after']:
                conflicts.append({'id': sid, 'reason': 'assignment_changed'}); continue
            saved = dict(saved)
            if move['before']['present']: saved['project'] = move['before']['value']
            else: saved.pop('project', None)
            if not move.get('beforeSavedPresent', True) and not saved:
                sessions.pop(sid, None)
            else:
                sessions[sid] = saved
            restored.append(sid)
            from .ui_command_bus import now
            db.execute('INSERT INTO events(ts,action,payload) VALUES(?,?,?)', (now(), 'session.moved', json.dumps({'id': sid, 'project': move['before']['value'], 'clearOverride': not move['before']['present']})))
        receipt = {'ok': True, 'status': 'restored', 'restored': restored, 'conflicts': conflicts, 'undoId': identity}
        _put(db, 'sessions', sessions); _put(db, 'sidebar:undo:' + identity, {**record, 'receipt': receipt})
    with service.bus.changed: service.bus.changed.notify_all()
    return receipt

def call(service, name, args):
    if name == 'sidebar.state':
        from .neyvia_sidebar_projection import observe
        return observe(service, args)
    if name == 'sidebar.preview': return preview(service, args)
    if name == 'sidebar.confirm': return confirm(service, args)
    if name == 'sidebar.undo': return undo(service, args)
    raise ValueError('Unknown sidebar action')

def handle_command(backend, command, payload):
    from .neyvia_workspace_tools import workspace_for
    if command not in COMMANDS: raise ValueError('Unknown sidebar command')
    inner = payload.get('payload') if isinstance(payload.get('payload'), dict) else payload
    if inner.get('_expectedStateRoot') and Path(inner['_expectedStateRoot']).resolve() != backend.root.resolve():
        raise ValueError('Sidebar service belongs to a different workspace')
    return call(workspace_for(backend.root, backend), 'sidebar.' + command.split('_')[1], inner)

def forward_command(root, command, payload):
    from .connected_sessions.forward import forward_connected_command
    return forward_connected_command(root, command, payload)

def respond_command(handler, backend, command, payload):
    from .web_backend import _json_response
    session = backend.authenticated_session(handler)
    if str((session or {}).get('username') or '').casefold() != backend.username.casefold():
        _json_response(handler, 403, {'ok': False, 'error': "The PC owner's account is required"})
        return
    try:
        result = handle_command(backend, command, payload or {})
        _json_response(handler, 200, {'ok': result.get('ok', True), 'data': result})
    except (ValueError, KeyError, TypeError) as exc:
        _json_response(handler, 400, {'ok': False, 'error': str(exc)[:500]})
