"""Authenticated Memory UI commands and the same scope-bound agent tools."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import json
import logging
import os
import re
from .cue_memory import CueMemoryStore, MemoryContext, MemoryRefusal, require_context
from .memory_recall import recall

TEXT = {'type': 'string', 'minLength': 1}
CUES = {'type': 'object', 'additionalProperties': False, 'properties': {
    key: {'type': 'array', 'items': {'type': 'string', 'maxLength': 160}, 'maxItems': 12}
    for key in ('intent', 'app', 'layer', 'files', 'task', 'entities')}}
FIELDS = {'key': {**TEXT, 'maxLength': 160}, 'content': {**TEXT, 'maxLength': 2000},
          'kind': {'type': 'string', 'enum': ['fact', 'preference', 'procedure', 'pitfall']}, 'cues': CUES,
          'expiresAt': {'type': ['string', 'null']}, 'exportPolicy': {'type': 'string', 'enum': ['local', 'provider']}}
WRITE = {**FIELDS, 'requestId': TEXT}
TARGET = {'id': TEXT, 'expectedRevision': {'type': 'integer', 'minimum': 1}, 'requestId': TEXT}
DEFINITIONS = [
    ('memory.remember', 'Save explicit teaching; ordinary agent suggestions stay pending. Local-only by default.', WRITE, ['key', 'content', 'requestId']),
    ('memory.correct', 'Correct one scoped memory with its current revision; revoke old context.', {**WRITE, **TARGET}, ['id', 'expectedRevision', 'key', 'content', 'requestId']),
    ('memory.forget', 'Erase scoped content and cues; revoke prior provider context.', TARGET, ['id', 'expectedRevision', 'requestId']),
    ('memory.list', 'Read active and pending memories in the authenticated project.', {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}}, []),
    ('memory.inspect', 'Read one scoped memory with lifecycle and provenance.', {'id': TEXT}, ['id']),
    ('memory.recall', 'Recall cue matches as untrusted M data under an exact o200k budget; no recent fallback.',
     {'situation': CUES | {'properties': {**CUES['properties'], **{key: {'type': 'string'} for key in ('intent', 'app', 'layer', 'task')}}},
      'budget': {'type': 'integer', 'minimum': 0, 'maximum': 1024}, 'destination': {'type': 'string', 'enum': ['local', 'provider']}}, ['situation']),
]
COMMANDS = frozenset('memory_' + op + '_command' for op in ('remember', 'correct', 'forget', 'list', 'inspect', 'recall'))


def operate(context, op, body):
    context = require_context(context)
    store = CueMemoryStore(context)
    if op == 'list':
        result = store.snapshot(include_pending=True, limit=body.get('limit', 100))
        if context.channel == 'provider':
            result['memories'] = [row for row in result['memories'] if row['exportPolicy'] == 'provider']
        return result
    if op == 'inspect':
        row = store.inspect(body['id'])
        if context.channel == 'provider' and row.get('exportPolicy', 'local') != 'provider' and row['status'] != 'deleted':
            raise MemoryRefusal('memory_export_refused', 'This memory is local-only.', 403)
        return {'memory': row, 'generation': store.generation()}
    if op == 'recall':
        return recall(context, body['situation'], budget=body.get('budget', 256),
                      destination='provider' if context.channel == 'provider' else body.get('destination', 'local'))
    if op in ('correct', 'forget') and not context.explicit_write:
        raise MemoryRefusal('memory_write_unapproved', 'Correction or forgetting needs an explicit user request.', 403)
    return store.mutate(op, body)


def context_for_backend(backend, body, user):
    """The HTTP session supplies user; session cwd comes from the owning broker."""
    if not isinstance(user, str) or not user:
        raise MemoryRefusal('memory_scope_unbound', 'An authenticated account is required.', 403)
    project = backend.root
    session_id = body.get('sessionId')
    if session_id:
        from .connected_sessions.broker import broker_for
        broker = broker_for(backend.root, backend)
        broker._host_check(session_id)
        summary = broker.find_summary(session_id)
        if summary is None or not summary.cwd:
            raise MemoryRefusal('memory_project_unbound', 'Select a chat with a project folder.', 403)
        project = Path(summary.cwd)
    return MemoryContext(backend.root, user, project, source_id=str(body.get('requestId', '')),
                         source_kind='user_action', explicit_write=True, provider_export_authorized=True)


def handle_command(backend, command, body, *, user):
    expected = body.get('_expectedStateRoot')
    if expected and Path(expected).resolve() != Path(backend.root).resolve():
        raise MemoryRefusal('memory_root_mismatch', 'Memory belongs to another host state folder.')
    # Client identity, root and provenance flags are deliberately not consumed.
    return operate(context_for_backend(backend, body, user), command.removeprefix('memory_').removesuffix('_command'), body)


def call(service, name, args):
    return operate(require_context(), name.removeprefix('memory.'), args)


def chat_context(root, user, project, message, source_id):
    if message.startswith('<neyvia-memory>') and '</neyvia-memory>' in message:
        message = message.split('</neyvia-memory>', 1)[1].lstrip()
    explicit = bool(re.match(r'(?is)^\s*(?:/?remember\b|/?correct\b|correction\b|/?forget\b)', message))
    shared = bool(re.search(r'(?i)(?:--share|allow provider context)', message))
    return MemoryContext(root, user, Path(project), source_id, 'user_turn', explicit, shared, 'provider')


def launcher_scope(context):
    """Private parent-to-child binding. Never consumed from tool arguments."""
    return json.dumps({key: str(getattr(context, key)) if key in ('root', 'project_path') else getattr(context, key)
        for key in ('root', 'owner', 'project_path', 'source_id', 'source_kind', 'explicit_write', 'provider_export_authorized', 'channel')})


def launcher_context(root, *, project=None):
    """Admit the private host binding; optional memory must not break a chat.

    The host owns the store, while root may be a chat's separate runtime folder.
    Only the trusted parent environment supplies the host root and account.
    """
    raw = os.environ.get('NEYVIA_MEMORY_SCOPE')
    if not raw:
        return None
    try:
        context = MemoryContext(**json.loads(raw))
        host_root = Path(os.environ.get('NEYVIA_MEMORY_HOST_ROOT') or root).resolve()
        if context.root != host_root:
            reason = 'host_root_mismatch'
        elif project is not None and context.project_path != Path(project).resolve():
            reason = 'project_mismatch'
        else:
            return context
    except (TypeError, ValueError, OSError):
        reason = 'invalid_launcher_scope'
    # Keep scope contents (including account and private paths) out of logs.
    logging.getLogger(__name__).warning('Memory disabled for this chat: %s', reason)
    return None


def ingest_teaching(context, message):
    """A small explicit syntax; no transcript scraping or inferred preference writes.

    /remember [--share] subject = claim; /correct subject = replacement;
    /forget subject. Natural 'Remember: subject = claim' also works.
    """
    match = re.fullmatch(r'(?is)\s*/?(remember|correct|correction|forget)\s*:?[ \t]*(--share[ \t]+)?(.+?)\s*', message)
    if not match:
        return None
    operation, shared, value = match.groups()
    operation = operation.casefold()
    operation = 'correct' if operation == 'correction' else operation
    if operation != 'forget' and '=' not in value:
        return None  # The agent can use a typed action for less structured teaching.
    key, _, content = value.partition('=')
    store = CueMemoryStore(context)
    rows = store.snapshot(include_pending=True, limit=10000)['memories']
    old = next((row for row in rows if row['key'].casefold() == key.strip().casefold()), None)
    body = {'requestId': 'chat:' + context.source_id, 'key': key.strip(), 'content': content.strip(),
            'cues': {'intent': [key.strip()]}, 'kind': 'fact', 'exportPolicy': 'provider' if shared else 'local'}
    if operation != 'remember':
        if old is None:
            raise MemoryRefusal('memory_not_found', 'No active memory has that subject in this project.', 404)
        body.update(id=old['id'], expectedRevision=old['revision'])
        if operation == 'correct' and not shared:
            body['exportPolicy'] = old['exportPolicy']
            context = replace(context, provider_export_authorized=old['exportPolicy'] == 'provider')
    result = operate(context, operation, body)
    return {'operation': operation, 'id': result['memory']['id'], 'revision': result['memory']['revision'], 'generation': result['generation']}


def capture_outcome(context, run):
    """A completed CL observer receipt can propose a local-only procedure.

    Provider prose and process exit status cannot promote an outcome. The user
    reviews a pending proposal with the same revision-checked panel correction.
    """
    if run.get('state') != 'completed' or run.get('doneStatus') != 'ok':
        return None
    if Path(run.get('workspaceRoot') or '').resolve() != context.project_path:
        raise MemoryRefusal('memory_project_unbound', 'Outcome belongs to another project.', 403)
    source = str(run['runId'])
    task = str(run.get('taskText') or '').strip()[:600]
    if not task:
        return None
    context = replace(context, source_id=source, source_kind='task_outcome', explicit_write=False,
                      provider_export_authorized=False, channel='local')
    result = operate(context, 'remember', {'key': 'Outcome ' + source[:100],
        'content': 'CL observers confirmed completion of this task: ' + task,
        'kind': 'procedure', 'cues': {'intent': [task[:160]]}, 'exportPolicy': 'local', 'requestId': 'outcome:' + source})
    return {'id': result['memory']['id'], 'revision': result['memory']['revision'], 'status': 'pending'}
