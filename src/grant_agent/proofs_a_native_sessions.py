"""Native connected-session action contracts and confined provider journeys.

The procedure runs the real backend dispatcher, persistence and run control.
Only the provider transport and completion notifications are finite boundaries;
account initialization, installed CLIs and public services are never invoked.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import functools
import inspect
import json
import time
from contextvars import ContextVar
from pathlib import Path

from .proofs_a_sessions import require, checked_result

_observed = None
_admission = ContextVar('native_manual_turn_admission', default=None)


def checked(condition, identity, message):
    require(condition, identity, message)
    if _observed is not None:
        _observed.add(identity)


def check_options(arguments, result):
    adapter, sid = arguments['self'], arguments['session_id']
    models, runtimes, modes = result['models'], result['runtimes'], result['permissionModes']
    from .connected_sessions.neyvia_options import runtime_rows, permission_mode_rows, model_rows
    checked(runtimes == runtime_rows() and modes == permission_mode_rows()
            and [r['id'] for r in runtimes[:3]] == ['neyvia-agent', 'codex', 'claude-code']
            and not {'rook', 'wallbreaker'} & {r['id'] for r in runtimes},
            'native.options', 'picker order, security exclusions or permission catalogue changed')
    defaults = [row for row in models if row.get('default')]
    catalogue = model_rows(adapter._root())
    expected_rows = {row['id']: {key: value for key, value in row.items() if key != 'default'} for row in catalogue}
    checked(all({key: value for key, value in row.items() if key != 'default'} == expected_rows[row['id']]
                for row in models if row['id'] in expected_rows)
            and set(expected_rows) <= {row['id'] for row in models},
            'native.options', 'catalogue labels, groups, effort limits or supported routes changed during projection')
    checked(len(defaults) == 1 and all('ultra' not in row.get('efforts', [])
            for row in models if row['provider'] == 'openai-codex')
            and any(row['runtime'] == 'hermes' and row['model'] == '' for row in models),
            'native.options', 'default uniqueness, effort bounds or model-free fallback differs')
    if sid:
        try:
            route = adapter._last_route(adapter._conversation_id(sid))
        except FileNotFoundError:
            route = None
        if route:
            eligible = [row for row in models if (row['runtime'], row['provider'], row['model']) == route[:3]]
            if not eligible:
                eligible = [row for row in models if (row['runtime'], row['model']) == (route[0], route[2])]
            if eligible:
                checked(defaults[0]['id'] == eligible[0]['id'], 'native.options', 'last stored route is not the selected default')
    else:
        desired = next(row['defaultModel'] for row in runtimes if row['id'] == 'neyvia-agent')
        matches = [row for row in models if row['runtime'] == 'neyvia-agent' and row['provider'] == 'openai-codex' and row['model'] == desired]
        if matches:
            checked(defaults[0]['id'] == matches[0]['id'], 'native.options', 'fresh session lost Native configured default')


def check_route(arguments, result):
    from .connected_sessions.neyvia_options import parse_route_id, normalize_runtime, runtime_rows
    adapter, cid, options = arguments['self'], arguments['conversation_id'], arguments['options']
    last = adapter._last_route(cid) if cid else None
    picked = parse_route_id(options.model)
    runtime = normalize_runtime(picked[0] if picked else last[0] if last else 'neyvia-agent') or 'neyvia-agent'
    model = picked[2] if picked else options.model or (last[2] if last else '')
    if not model and runtime == 'neyvia-agent' and not picked:
        model = next(row['defaultModel'] for row in runtime_rows() if row['id'] == runtime) or ''
    checked(result[0] == runtime and result[2] == model and result[3] == (options.effort or 'default'),
            'native.route', 'explicit model, inherited runtime or effort was lost')
    if picked and picked[1]:
        checked(result[1] == picked[1], 'native.route', 'explicit provider was lost')
    elif last and last[0] == runtime and last[1]:
        checked(result[1] == last[1], 'native.route', 'conversation provider was lost')


def check_permission(arguments, result):
    from .connected_sessions.neyvia_options import runtime_permission_modes
    checked(result == (arguments['options'].permission_mode or 'read-only')
            and result in runtime_permission_modes(arguments['runtime']),
            'native.permission', 'selected/default mode is not supported by this runtime')
    state = _admission.get()
    if state is not None:
        state['permission'] = True


def admitted_attachments():
    state = _admission.get()
    if state is not None:
        state['attachments'] = True


def before_conversation_mutation():
    state = _admission.get()
    if state is not None:
        checked(state['permission'] and state['attachments'], 'native.refusal',
                'conversation mutation preceded successful permission and attachment admission')


def check_payload(arguments, result):
    adapter, row = arguments['self'], arguments['row']
    expected_keys = {'message', 'attachments', 'permissionMode', 'workspaceToolsAllowed', 'runtime', 'route',
        'workspaceId', 'workspacePath', 'history', 'sessionId', 'conversationId', 'userTurnId', 'assistantTurnId',
        'systemContext', 'requestStartedAt'}
    metadata = row.get('metadata') or {}
    workspace = adapter._workspaces().get(str(row.get('workspaceId') or ''), {})
    path = arguments['cwd'] or metadata.get('workspacePath') or metadata.get('executionRoot') or workspace.get('root_path') or ''
    context = '\n'.join(line for line in (f"Workspace: {workspace['name']}." if workspace.get('name') else '',
                                         f'Workspace path: {path}.' if path else '') if line)
    with adapter._store()._connection() as db:
        history = list(db.execute("SELECT role, content FROM conversation_turns WHERE conversation_id=? AND meaningful=1 "
            "AND role IN ('user','assistant') AND turn_kind='dialogue' ORDER BY created_at DESC, turn_id DESC LIMIT 8",
            (arguments['conversation_id'],)))
    expected_history = [{'role': role, 'text': text} for role, text in reversed(history) if str(text).strip()]
    checked(set(result) == expected_keys and result['workspacePath'] == str(path)
            and result['systemContext'] == context and result['history'] == expected_history
            and result['workspaceId'] == str(row.get('workspaceId') or '')
            and result['userTurnId'] != result['assistantTurnId'],
            'native.payload', 'classic payload field set, durable history, workspace or unique identities changed')
    checked(True, 'sessions.neyvia.payload', 'existing attachment and payload observers execute before this guard')


def turn_contract(function):
    signature = inspect.signature(function)
    @functools.wraps(function)
    def call(*args, **kwargs):
        values = signature.bind(*args, **kwargs).arguments
        adapter, run_id = values['self'], values['run_id']
        events = []
        emit = values['emit']
        def forward(event):
            events.append(event)
            emit(event)
        kwargs['emit'] = forward
        token = _admission.set({'permission': False, 'attachments': False})
        try:
            result = function(*args, **kwargs)
        except Exception as error:
            from .connected_sessions.broker import ConnectedError
            if isinstance(error, ConnectedError) and error.code in {
                'invalid_permission_mode', 'permission_not_supported', 'invalid_image', 'cannot_continue', 'session_not_found'}:
                checked(not events, 'native.refusal', 'invalid request emitted a conversation or turn before refusal')
            raise
        finally:
            _admission.reset(token)
            checked(run_id not in adapter._runs, 'native.lifecycle', 'finished/refused run retained mutable live ownership')
        checked(events and events[-1]['type'] == 'session.updated'
                and events[-1]['session']['id'] == result
                and any(event['type'] == 'item.added' and event['item']['kind'] == 'user' for event in events)
                and all(event.get('sessionId', result) == result for event in events),
                'native.lifecycle', 'turn events lost user, terminal summary or session identity')
        if values['session_id'] is None:
            cid = adapter._conversation_id(result)
            row = adapter._row(cid)
            checked(events[0]['type'] == 'session.updated' and row['kind'] == 'chat'
                    and (not values['cwd'] or row['metadata']['workspacePath'] == values['cwd']),
                    'native.create', 'new conversation was not announced before its first item or lost workspace')
        else:
            checked(not adapter._row(adapter._conversation_id(result)).get('archivedAt'),
                    'native.restore', 'sending did not restore archived conversation')
        return result
    return call


def finish_contract(function):
    @functools.wraps(function)
    def call(run, outcome, emit):
        events = []
        result = function(run, outcome, lambda event: (events.append(event), emit(event)))
        raw = outcome.get('result') or {}
        status = str(raw.get('status') or 'completed').lower()
        expected = 'cancelled' if status == 'cancelled' else 'interrupted' if status == 'stop_unconfirmed' else (
            'failed' if status in ('failed', 'error', 'timeout') or raw.get('ok') is False else None)
        if outcome.get('error') is not None:
            from .connected_sessions.broker import ConnectedError
            checked(isinstance(result, ConnectedError) and len(result.message) <= 500,
                    'native.outcome', 'backend exception did not become bounded broker refusal')
        else:
            expected_text = None if expected == 'cancelled' else (raw.get('error') or (
                'Stop was requested, but the runtime could not be confirmed stopped.' if expected == 'interrupted'
                else 'The runtime failed before a readable reply.')) if expected else None
            checked(result is None and len(events) == (1 if expected else 0)
                    and (not events or (events[0]['state'] == expected and events[0]['runId'] == run.run_id
                         and events[0].get('error') == (str(expected_text)[:500] if expected_text else None))),
                    'native.outcome', 'terminal run status or error bounds differ from backend outcome')
        return result
    return call


def check_cancel(arguments, result):
    run = arguments['run']
    checked(run.cancel_sent > 0 and isinstance(run.cancel_ok, bool),
            'native.cancel', 'stop attempt did not record retry timestamp and acknowledgement')


def check_cancel_result(run, result):
    checked(run.cancel_ok is (result.get('status') in {'stop_requested', 'already_finished', 'interrupted'}),
            'native.cancel', 'stop acknowledgement does not match real dispatcher status')


def unsupported_contract(function):
    signature = inspect.signature(function)
    @functools.wraps(function)
    def call(*args, **kwargs):
        from .connected_sessions.broker import ConnectedError
        values = signature.bind(*args, **kwargs).arguments
        expected = function.__name__ == 'answer'
        if function.__name__ == 'goal':
            adapter = values['self']
            from .connected_sessions.neyvia import classify, conversation_runtime
            try:
                row = adapter._row(adapter._conversation_id(values['session_id']))
                expected = row['kind'] != 'chat' or classify(conversation_runtime(row))[0] != 'native'
            except (FileNotFoundError, KeyError):
                pass
        try:
            result = function(*args, **kwargs)
        except ConnectedError as error:
            if error.code == 'not_supported':
                checked(error.status == 409 and bool(error.message), 'native.unsupported', 'unsupported action lost a readable 409 refusal')
            raise
        checked(not expected, 'native.unsupported', 'unsupported question or hybrid goal was accepted')
        return result
    return call


def check_goal(arguments, result):
    adapter = arguments['self']
    row = adapter._row(adapter._conversation_id(arguments['session_id']))
    enabled = row['metadata'].get('goalMode') is True
    checked(result == ({'state': 'set', 'text': None, 'goalMode': True} if enabled else None)
            and (arguments['action'] not in ('set', 'clear') or enabled is (arguments['action'] == 'set')),
            'native.goal', 'goal switch did not match durable metadata or stored free text')


def goal_contract(function):
    @functools.wraps(function)
    def call(self, session_id, action, text=None):
        before = self._row(self._conversation_id(session_id)).get('metadata') or {}
        result = function(self, session_id, action, text)
        after = self._row(self._conversation_id(session_id)).get('metadata') or {}
        checked({key: value for key, value in before.items() if key != 'goalMode'}
                == {key: value for key, value in after.items() if key != 'goalMode'},
                'native.goal', 'goal action changed metadata beyond its boolean switch')
        return result
    return call


def check_context(arguments, result):
    from .chat_stream import last_stream_event
    adapter = arguments['self']
    rows = adapter._query("SELECT turn_id FROM conversation_turns WHERE conversation_id=? AND role='assistant' "
        "ORDER BY created_at DESC, turn_id DESC LIMIT 3", (arguments['conversation_id'],))
    expected = None
    for row in rows:
        try:
            event = last_stream_event(adapter._root(), row[0], 'context.usage')
        except (OSError, ValueError):
            continue
        if event and type(event['data'].get('inputTokens')) is int:
            expected = event
            break
    if expected:
        data = expected['data']
        checked(result.used_tokens == data['inputTokens'] and result.source == 'provider-usage'
                and result.window_tokens == (data.get('contextTokens') if type(data.get('contextTokens')) is int and data['contextTokens'] > 0 else None)
                and result.auto_compact_tokens == (data.get('triggerTokens') if type(data.get('triggerTokens')) is int and data['triggerTokens'] > 0 else None),
                'native.context', 'context is not the last recorded provider usage')
    else:
        checked(result.used_tokens is None, 'native.context', 'context invented a provider usage')


def check_foreign(arguments, result):
    adapter = arguments['self']
    checked(len(set(result.values())) == len(result), 'native.foreign', 'foreign run assigned to multiple conversations')
    for cid, turn in result.items():
        rows = adapter._query("SELECT role, created_at FROM conversation_turns WHERE conversation_id=? AND meaningful=1 "
            "ORDER BY created_at DESC, turn_id DESC LIMIT 1", (cid,))
        state = json.loads((adapter._root() / '.agent_control/chat_runs' / f'{turn}.json').read_text())
        from .connected_sessions.neyvia import _epoch
        checked(rows and rows[0][0] == 'user' and abs(_epoch(rows[0][1]) - state['startedAt']) <= 300
                and all(run.turn_id != turn for run in adapter._runs.values()),
                'native.foreign', 'foreign owner does not match an awaiting durable user turn and live run')


def check_factory(arguments, result):
    checked(result._backend is arguments['backend'], 'native.registry', 'registry factory lost backend identity')


def live_contract(function):
    @functools.wraps(function)
    def call(self, events):
        out = []
        for event in events if isinstance(events, list) else []:
            old = {key: item.public() for key, item in self.items.items()}
            old_identity = self._identity
            produced = function(self, [event])
            out.extend(produced)
            checked(all(row.get('sessionId') == self.session_id for row in produced)
                    and all(item.id == key and (key not in old or item.seq == old[key]['seq']) for key, item in self.items.items())
                    and all(item.seq // 100 == self.ordinal + 1 for item in self.items.values()),
                    'native.live', 'stream event identity or stable sequence changed')
            if not isinstance(event, dict):
                continue
            kind, message = event.get('kind'), str(event.get('message') or '')
            data = event.get('data') if isinstance(event.get('data'), dict) else {}
            if kind == 'runtime.thinking_delta' and data.get('source') != 'provider.reasoning_content':
                checked(not produced and old == {key: item.public() for key, item in self.items.items()},
                        'native.live', 'private reasoning changed public items')
            elif kind == 'runtime.answer_delta' and message:
                before = old.get(self.turn_id, {}).get('data', {}).get('text', '')
                checked(self.items[self.turn_id].data['text'] == before + message
                        and self.items[self.turn_id].seq % 100 == 99,
                        'native.live', 'answer delta did not append exactly at the text slot')
            elif kind == 'runtime.answer_start' and self._identity != old_identity and self.turn_id in old:
                checked(self.items[self.turn_id].data['text'] == '', 'native.live', 'new response identity retained draft text')
            elif kind == 'runtime.stream_error':
                checked(any(row['type'] == 'item.added' and row['item']['kind'] == 'notice'
                    and row['item']['data'] == {'text': (message or 'The provider stream ended before the reply completed.')[:1000], 'level': 'error'}
                    for row in produced) or self._slot >= 99, 'native.live', 'stream failure lost readable bounded notice')
        return out
    return call


def self_check(root: Path):
    return _journey(Path(root))


def _journey(parent):
    import base64
    import http.client
    import os
    import subprocess
    import sys
    import threading
    import uuid
    from contextlib import ExitStack
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace
    from unittest.mock import patch
    from . import web_backend as wb, model_catalog
    from .chat_run_control import active_chat_run, chat_cancellation_requested, ChatRunCancelled, note_runtime_process
    from .chat_stream import append_chat_stream, begin_chat_stream
    from .neyvia_conversations import NeyviaConversationStore
    from .connected_sessions import neyvia as n
    from .connected_sessions.model import TurnOptions
    from .connected_sessions.neyvia_items import LiveTurn
    from .connected_sessions.broker import ConnectedBroker, ConnectedError
    global _observed
    _observed = set()
    started = time.monotonic()
    root = parent / ('native-' + uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    store = NeyviaConversationStore(root)
    backend = object.__new__(wb.FluxioWebBackend)
    backend.root = root
    backend._neyvia_mcp = SimpleNamespace(conversations=store)
    backend._lazy_services_lock = threading.RLock()
    backend._agent_chat_persistence_lock = threading.RLock()
    backend._agent_chat_persistence_inflight = {}
    backend._provider_env = lambda: {}
    provider_requests, dispatches, process_receipts = [], [], []
    checks = []
    finite_started = threading.Event()
    release_dispatch = threading.Event()
    scenario = {'mode': 'reply', 'delay': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            provider_requests.append(body)
            events = [
                {'kind': 'runtime.reasoning_summary_delta', 'message': 'A short plan'},
                {'kind': 'runtime.tool', 'message': 'terminal.exec', 'data': {'callId': 'c1', 'tool': 'terminal.exec', 'toolStatus': 'started', 'input': 'echo hi'}},
                {'kind': 'runtime.tool', 'message': 'terminal.exec', 'data': {'callId': 'c1', 'tool': 'terminal.exec', 'toolStatus': 'completed', 'output': json.dumps({'tool': 'terminal.exec', 'ok': True, 'duration_ms': 12, 'result': {'exit_code': 0, 'stdout': 'hi'}})}},
                {'kind': 'runtime.progress', 'message': 'Compacting', 'data': {'eventType': 'context.compaction.started', 'policy': {'contextTokens': 200000, 'triggerTokens': 170000}}},
                {'kind': 'runtime.progress', 'message': 'Compacted', 'data': {'eventType': 'context.compaction.completed'}},
                {'kind': 'runtime.answer_start', 'data': {'responseId': 'finite-r1', 'itemId': 'finite-m1', 'outputIndex': 0}},
                {'kind': 'runtime.answer_delta', 'message': 'Hello'},
                {'kind': 'runtime.answer_delta', 'message': ' there'},
            ]
            raw = json.dumps({'reply': 'Hello there', 'events': events}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', proof_port(48468)), Handler)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    def provider(payload):
        if scenario['mode'] == 'error':
            raise RuntimeError('The finite executor exploded.')
        if scenario['mode'] in ('hold', 'unconfirmed'):
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
            try:
                note_runtime_process(child.pid)
                finite_started.set()
                deadline = time.monotonic() + 8
                while not chat_cancellation_requested() and time.monotonic() < deadline:
                    time.sleep(0.02)
                require(chat_cancellation_requested(), 'native.cancel', 'confined cancellation request never reached child owner')
                child.terminate()
                child.wait(timeout=5)
                exc = ChatRunCancelled()
                exc.process_tree_stopped = scenario['mode'] != 'unconfirmed'
                exc.process_reaped = scenario['mode'] != 'unconfirmed'
                process_receipts.append({'pid': child.pid, 'exitCode': child.returncode,
                    'confirmationAvailable': scenario['mode'] != 'unconfirmed'})
                raise exc
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)
        connection = http.client.HTTPConnection('127.0.0.1', proof_port(48468), timeout=5)
        try:
            body = json.dumps({'message': payload['message'], 'route': payload['route'], 'runtime': payload['runtime'],
                'permissionMode': payload['_permissionMode'], 'attachmentCount': len(payload.get('_validatedChatAttachments') or [])})
            connection.request('POST', '/finite-provider', body, {'Content-Type': 'application/json'})
            response = connection.getresponse()
            require(response.status == 200, 'native.lifecycle', 'finite provider refused request')
            parsed = json.loads(response.read())
        finally:
            connection.close()
        for event in parsed['events']:
            append_chat_stream(root, payload['assistantTurnId'], event)
        return {'reply': parsed['reply'], 'runtime': payload['runtime'], 'sessionId': payload['sessionId'],
            'route': payload['route'], 'status': 'completed', 'elapsedMs': 5,
            'toolTimeline': [{'kind': 'runtime.reasoning_summary', 'at': n._now(), 'summary': 'A short plan', 'output': 'A short plan'},
                {'kind': 'runtime.tool', 'at': n._now(), 'summary': 'terminal.exec', 'callId': 'c1',
                'tool': 'terminal.exec', 'input': 'echo hi', 'output': json.dumps({'tool': 'terminal.exec', 'ok': True,
                'duration_ms': 12, 'result': {'exit_code': 0, 'stdout': 'hi'}}), 'status': 'completed'}], 'filesChanged': []}
    backend._run_neyvia_chat = provider
    backend._run_codex_chat = provider
    dispatch = backend.dispatch
    def recorded_dispatch(command, payload):
        dispatches.append((command, json.loads(json.dumps(payload))))
        if command == 'send_agent_chat_command' and scenario['delay']:
            finite_started.set()
            require(release_dispatch.wait(4), 'native.cancel', 'delayed registration was never released')
        return dispatch(command, payload)
    backend.dispatch = recorded_dispatch
    def check(name, condition, **evidence):
        require(condition, 'native.self-check', name)
        checks.append({'name': name, 'ok': True, **evidence})
    def seed(cid, runtime='neyvia-agent', model='gpt-5.6-sol', provider='openai-codex'):
        store.create_conversation(conversation_id=cid, title=cid, metadata={'workspacePath': str(root)})
        store.append_turn(cid, role='user', content='Prior question', metadata={'runtime': runtime})
        store.append_turn(cid, role='assistant', content='Prior answer', metadata={'runtimeResult': {
            'runtime': runtime, 'route': {'provider': provider, 'model': model, 'effort': 'high'}, 'status': 'completed'}})
        return n.NeyviaAdapter._sid(cid)

    def refusal_checks(adapter, native):
        def refuse(target, sid, options, expected, *, oversized=False):
            before = store.list_conversations(include_archived=True)
            with store._connection() as database:
                turns_before = database.execute('SELECT COUNT(*) FROM conversation_turns').fetchone()[0]
            sends, requests, events = len(dispatches), len(provider_requests), []
            try:
                adapter.start_turn(sid, 'refused image or request', options, cwd=str(root),
                    run_id='native-refusal-' + target, emit=events.append)
            except ConnectedError as error:
                with store._connection() as database:
                    turns_after = database.execute('SELECT COUNT(*) FROM conversation_turns').fetchone()[0]
                check('refuse before mutation: ' + target,
                    error.code == expected and (not oversized or '5 MiB' in error.message)
                    and store.list_conversations(include_archived=True) == before and turns_after == turns_before
                    and len(dispatches) == sends and len(provider_requests) == requests and not events and not adapter._runs,
                    code=error.code, message=error.message, target=target,
                    dispatched=len(dispatches) - sends, providerCalls=len(provider_requests) - requests,
                    emitted=len(events), turnsAdded=turns_after - turns_before)
            else:
                raise RuntimeError('invalid request accepted: ' + target)

        for target, request, expected in (
            ('invalid-mode', TurnOptions(permission_mode='root'), 'invalid_permission_mode'),
            ('unsupported-permission', TurnOptions(model='opencode||', permission_mode='workspace'), 'permission_not_supported'),
            ('malformed-image', TurnOptions(images=[{'mime': 'image/png', 'data': 'not base64!'}]), 'invalid_image')):
            refuse(target, None, request, expected)
        store.create_conversation(conversation_id='plan', kind='orchestration', title='plan')
        refuse('orchestration', adapter._sid('plan'), TurnOptions(), 'cannot_continue')
        refuse('missing-session', adapter._sid('absent'), TurnOptions(), 'session_not_found')
        # The shared decoder refuses oversize images during admission, before
        # create/restore, dispatch or a visible/durable turn.
        huge = TurnOptions(permission_mode='workspace', images=[{'mime': 'image/png',
            'data': base64.b64encode(b'x' * (31 * 1024 * 1024)).decode()}])
        archived = seed('oversized-archived')
        with store._connection() as database:
            database.execute('UPDATE conversations SET archived_at=? WHERE conversation_id=?', (n._now(), 'oversized-archived'))
            database.commit()
        for target, sid in (('oversized-new', None), ('oversized-existing', native), ('oversized-archived', archived)):
            refuse(target, sid, huge, 'invalid_image', oversized=True)
        # Preserve the separate backend-exception projection guarantee with an
        # actual decoder error and the production outcome projector.
        try:
            wb._decode_chat_attachments([{'name': 'oversized.png', 'mime': 'image/png',
                'size': 31 * 1024 * 1024, 'dataBase64': huge.images[0]['data']}])
        except wb.ChatAttachmentValidationError as decoder_error:
            events = []
            run = n._Run('native-decoder-error', 'native', 'decoder-error', n.LiveTurn(native, 'decoder-error', 0))
            error = adapter._finish(run, {'error': decoder_error}, events.append)
            check('backend decoder exception becomes refusal',
                error.code == 'send_failed' and '5 MiB' in error.message and error.status == 502 and not events,
                code=error.code, message=error.message, boundary='shared decoder to backend outcome projector')
        else:
            raise RuntimeError('oversized decoder request accepted')

    with ExitStack() as boundary:
        # Scope every replacement to forbidden account/notification initialization
        # or finite provider discovery. Application orchestration stays real.
        boundary.enter_context(patch.object(wb, '_resolve_codex_cli', lambda: None))
        boundary.enter_context(patch.object(wb, '_send_chat_completion_web_push_safely', lambda **kwargs: None))
        boundary.enter_context(patch.object(model_catalog, 'codex_model_cache_candidates', lambda *_: [root / 'models-cache.json']))
        try:
            adapter = n.create_adapter(backend)
            native = seed('native')
            hybrid = seed('hybrid', 'codex')
            alternate = seed('alternate', model='deepseek-v4.1-flash', provider='opencode-go')
            claude = seed('claude-last', runtime='claude-code', provider='claude-code', model='opus')
            options = adapter.options()
            defaults = [row for row in options['models'] if row.get('default')]
            check('ordered picker and permissions', len(defaults) == 1 and options['defaultPermissionMode'] == 'read-only'
                and defaults[0]['id'] == 'neyvia-agent|openai-codex|gpt-5.6-sol'
                and options['runtimes'][0]['label'] == 'Neyvia Native' and options['runtimes'][0]['category'] == 'native'
                and [m['id'] for m in options['permissionModes']] == ['read-only', 'workspace', 'full-access']
                and [m['label'] for m in options['permissionModes']] == ['Read only', 'Workspace', 'Full access'])
            labels = {row['id']: row for row in options['models']}
            check('catalogue model labels and supported efforts', labels['neyvia-agent|openai-codex|gpt-5.6-sol']['label'] == 'GPT-5.6 Sol'
                and labels['neyvia-agent|opencode-go|deepseek-v4.1-flash']['label'] == 'DeepSeek V4.1 Flash'
                and labels['claude-code|claude-code|sonnet']['label'] == 'Sonnet'
                and labels['neyvia-agent|opencode-go|deepseek-v4.1-flash']['efforts'] == ['low', 'high', 'max']
                and labels['neyvia-agent|opencode-go|deepseek-v4.1-flash']['group'] == 'Neyvia Native · OpenCode Go'
                and 'high' in labels['neyvia-agent|openai-codex|gpt-5.6-sol']['efforts']
                and not any(row['runtime'] == 'neyvia-agent' and row['model'] == 'minimax-m3' for row in options['models']))
            modes = {row['id']: row['permissionModes'] for row in options['runtimes']}
            check('runtime permission support', modes['neyvia-agent'] == ['read-only', 'workspace', 'full-access']
                and modes['hermes'] == ['read-only', 'full-access'] and modes['opencode'] == ['read-only'])
            check('durable picker route', [row['id'] for row in adapter.options(alternate)['models'] if row.get('default')]
                == ['neyvia-agent|opencode-go|deepseek-v4.1-flash'])
            check('durable Claude picker route', [row['id'] for row in adapter.options(claude)['models'] if row.get('default')]
                == ['claude-code|claude-code|opus'])
            selected = TurnOptions(model='neyvia-agent|openai-codex|gpt-5.6-sol', effort='high', permission_mode='workspace')
            requested = set(json.loads(os.environ.get('NEYVIA_GATE_CONTRACTS','[]')))
            if requested == {'native.refusal'}:
                refusal_checks(adapter, native)
                check('requested refusal observer actually ran', requested <= _observed)
                return {'ok': True, 'contracts': sorted(requested), 'checks': checks,
                    'elapsedMs': round((time.monotonic() - started) * 1000),
                    'boundary': 'Real admission refusals and decoder outcome projection; no provider turn or full native lifecycle claim'}
            if requested and requested <= {'native.options','native.route','native.permission'}:
                check('explicit native route preserved', adapter._route('native', selected)
                      == ('neyvia-agent','openai-codex','gpt-5.6-sol','high'))
                check('workspace authority preserved', adapter._permission_mode(selected,'neyvia-agent') == 'workspace')
                check('omitted authority stays read-only', adapter._permission_mode(TurnOptions(),'neyvia-agent') == 'read-only')
                try:adapter._permission_mode(TurnOptions(permission_mode='full-access'),'opencode')
                except ConnectedError as error:check('unsupported authority refused',error.code == 'permission_not_supported')
                else:check('unsupported authority refused',False)
                check('requested observers actually ran',requested <= _observed)
                return {'ok':True,'contracts':sorted(requested),'checks':checks,
                        'elapsedMs':round((time.monotonic()-started)*1000),
                        'boundary':'Real catalogue, route and authority outputs; no provider turn or native full journey'}
            events = []
            adapter.start_turn(native, 'hello', selected, cwd=str(root), run_id='native-send', emit=events.append)
            payload = next(payload for command, payload in dispatches if command == 'send_agent_chat_command')
            page = adapter.read(native)
            added = [event['item'] for event in events if event['type'] == 'item.added']
            check('exact composer payload, durable history and stream order', payload['history'] == [
                {'role': 'user', 'text': 'Prior question'}, {'role': 'assistant', 'text': 'Prior answer'}]
                and payload['permissionMode'] == 'workspace' and payload['workspaceToolsAllowed'] is True
                and payload['route']['effort'] == 'high' and [item['kind'] for item in added[:5]] == ['user', 'reasoning', 'tool', 'compaction', 'assistant']
                and added[4]['data']['text'] == 'Hello' and any(event.get('textDelta') == ' there' for event in events)
                and page.items[-1].data['text'] == 'Hello there' and not adapter._runs)
            live_ids = {item['id'] for item in added if item['kind'] in ('user', 'assistant', 'reasoning', 'tool')}
            check('saved/live identities reconcile and tools preserve readable result', live_ids <= {item.id for item in page.items}
                and any(item.kind == 'tool' and item.data.get('status') == 'ok' and item.data.get('input') == 'echo hi'
                    and item.data.get('durationMs') == 12 for item in page.items)
                and any(event['type'] == 'context.updated' and event['context']['window_tokens'] == 200000 for event in events)
                and not any(event['type'] == 'run.state' and event['state'] == 'completed' for event in events))
            live = {row['id']: row for row in added}
            saved = {item.id: item for item in page.items}
            assistant_id = payload['assistantTurnId']
            tool_id = assistant_id + '#tool-c1'
            check('tool live state, compaction completion and saved sequence', live[tool_id]['data']['status'] == 'running'
                and live[tool_id]['data']['input'] == 'echo hi' and saved[tool_id].data['output'] == 'hi'
                and saved[tool_id].data['exitCode'] == 0 and saved[tool_id].seq == live[tool_id]['seq']
                and saved[assistant_id].seq == live[assistant_id]['seq']
                and any(e['type'] == 'item.updated' and e['item']['id'] == tool_id and e['item']['data']['status'] == 'ok'
                    and e['item']['data']['exitCode'] == 0 for e in events)
                and [e['item']['data']['state'] for e in events if e['type'] == 'item.updated' and e['item']['kind'] == 'compaction'] == ['completed']
                and any(e['type'] == 'context.updated' and e['context']['auto_compact_tokens'] == 170000 for e in events))
            events = []
            dispatch_before = len(dispatches)
            created = adapter.start_turn(None, 'Start something', selected, cwd=str(root), run_id='native-create', emit=events.append)
            check('create before first item and automatic title', events[0]['type'] == 'session.updated'
                and adapter._row(adapter._conversation_id(created))['title'] == 'Start something'
                and dispatches[dispatch_before][0] == 'create_neyvia_conversation_command'
                and next(row for row in adapter.list_sessions() if row.id == created).cwd == str(root))
            check('explicit and inherited runtime routes', adapter._route('hybrid', TurnOptions(model='codex|openai-codex|gpt-6-luna', effort='low'))
                == ('codex', 'openai-codex', 'gpt-6-luna', 'low')
                and adapter._route('hybrid', TurnOptions(model='gpt-5.6-terra')) == ('codex', 'openai-codex', 'gpt-5.6-terra', 'default'))
            route_sid = seed('route-choice')
            offset = len(dispatches)
            for index, selection in enumerate((TurnOptions(model='codex|openai-codex|gpt-5.6-luna', effort='low', permission_mode='full-access'),
                                               TurnOptions(model='gpt-5.6-terra'), TurnOptions())):
                adapter.start_turn(route_sid, 'selected route', selection, cwd=str(root), run_id='native-route-' + str(index), emit=lambda event: None)
            routed = [body for command, body in dispatches[offset:] if command == 'send_agent_chat_command']
            check('selected runtime executes and bare/default models inherit durable route',
                (routed[0]['runtime'], routed[0]['permissionMode'], routed[0]['workspaceToolsAllowed'], routed[0]['route']['effort'])
                    == ('codex', 'full-access', True, 'low') and routed[0]['route']['model'] == 'gpt-5.6-luna'
                and (routed[1]['runtime'], routed[1]['route']['model'], routed[1]['permissionMode']) == ('codex', 'gpt-5.6-terra', 'read-only')
                and routed[2]['route']['model'] == 'gpt-5.6-terra' and routed[2]['route']['effort'] == 'default')
            image = {'mime': 'image/png', 'data': base64.b64encode(b'\x89PNG\r\n\x1a\n').decode(), 'name': 'shot.png'}
            image_options = TurnOptions(model=selected.model, permission_mode='workspace', images=[image])
            events = []
            adapter.start_turn(native, 'inspect image', image_options, cwd=str(root), run_id='native-image', emit=events.append)
            check('image transport and durable descriptors', provider_requests[-1]['attachmentCount'] == 1
                and next(body for command, body in reversed(dispatches) if command == 'send_agent_chat_command')['attachments']
                    == [{'name': 'shot.png', 'mime': 'image/png', 'size': 8, 'dataBase64': 'iVBORw0KGgo='}]
                and next(e['item'] for e in events if e['type'] == 'item.added')['data']['attachments'][0]['label'] == 'shot.png'
                and any(item.kind == 'user' and item.data.get('attachments') and item.data['attachments'][0]['kind'] == 'image'
                    for item in adapter.read(native).items))
            with store._connection() as database:
                database.execute('UPDATE conversations SET archived_at=? WHERE conversation_id=?', (n._now(), 'native'))
                database.commit()
            adapter.start_turn(native, 'restore me', selected, cwd=str(root), run_id='native-restore', emit=lambda event: None)
            check('archived send restores listing', adapter._row('native')['archivedAt'] is None
                and any(row.id == native for row in adapter.list_sessions()))
            scenario['mode'] = 'error'
            events = []
            adapter.start_turn(native, 'fail visibly', selected, cwd=str(root), run_id='native-failed', emit=events.append)
            check('runtime failure saved and emitted', any(e['type'] == 'run.state' and e['state'] == 'failed'
                and e['error'] == 'The finite executor exploded.' for e in events)
                and adapter.read(native).items[-1].kind == 'notice' and adapter.read(native).items[-1].data['level'] == 'error')
            scenario['mode'] = 'reply'
            refusal_checks(adapter, native)
            for mode, delayed in (('hold', False), ('unconfirmed', False), ('hold', True)):
                scenario.update(mode=mode, delay=delayed)
                finite_started.clear()
                release_dispatch.clear()
                events, errors = [], []
                cancellations_before = len([row for row in dispatches if row[0] == 'cancel_agent_chat_command'])
                run_id = f'native-stop-{mode}-{delayed}'
                def run_turn():
                    try:
                        adapter.start_turn(native, 'bounded wait', selected, cwd=str(root), run_id=run_id, emit=events.append)
                    except Exception as error:
                        errors.append(str(error))
                worker = threading.Thread(target=run_turn, daemon=True)
                worker.start()
                check('owned turn entered ' + run_id, finite_started.wait(5))
                check('live ownership and mid-turn read', adapter.live_status().get(native) == ('working', 'neyvia')
                    and any(item.kind == 'user' and item.data['text'] == 'bounded wait' for item in adapter.read(native).items)
                    and next(row for row in adapter.list_sessions() if row.id == native).live_owner == 'neyvia')
                adapter.interrupt(run_id)
                if delayed:
                    # Real first cancellation has not_running. Registration now
                    # proceeds, and the unchanged _follow retry reaches its owner.
                    release_dispatch.set()
                worker.join(7)
                check('stop settles and clears owned process ' + run_id, not worker.is_alive() and not errors
                    and native not in adapter.live_status() and any(e['type'] == 'run.state'
                    and e['state'] == ('interrupted' if mode == 'unconfirmed' else 'cancelled') for e in events))
                check('durable cancellation severity ' + run_id, adapter.read(native).items[-1].data['level'] == ('warning' if mode == 'unconfirmed' else 'info'))
                if mode == 'hold':
                    check('confirmed stop saves user-facing outcome', adapter.read(native).items[-1].data['text'] == 'Stopped by you.')
                else:
                    check('unconfirmed stop explicitly reports missing termination evidence', any(e['type'] == 'run.state' and e['state'] == 'interrupted'
                        and 'could not be confirmed' in e['error'] for e in events)
                        and 'could not be confirmed' in adapter.read(native).items[-1].data['text'])
                if delayed:
                    check('stop retried after real not_running response', len([row for row in dispatches
                        if row[0] == 'cancel_agent_chat_command']) - cancellations_before >= 2)
            scenario.update(mode='reply', delay=False)
            store.create_conversation(conversation_id='elsewhere', title='elsewhere')
            store.append_turn('elsewhere', role='user', content='Awaiting app response', now=n._now())
            foreign_ready, foreign_release = threading.Event(), threading.Event()
            def foreign():
                with active_chat_run(root, 'foreign-turn'):
                    foreign_ready.set()
                    foreign_release.wait(5)
            foreign_worker = threading.Thread(target=foreign, daemon=True)
            foreign_worker.start()
            check('foreign registration entered', foreign_ready.wait(3))
            foreign_sid = adapter._sid('elsewhere')
            check('foreign run attributed once to awaiting conversation', adapter.live_status().get(foreign_sid) == ('working', 'app')
                and native not in adapter.live_status() and next(row for row in adapter.list_sessions() if row.id == foreign_sid).live_owner == 'app')
            foreign_release.set()
            foreign_worker.join(3)
            check('foreign terminal clears ownership', foreign_sid not in adapter.live_status())
            check('native goal switch persists without free text', adapter.goal(native, 'get') is None
                and adapter.goal(native, 'set', 'ignored free text') == {'state': 'set', 'text': None, 'goalMode': True}
                and adapter._row('native')['metadata']['goalMode'] is True and adapter.goal(native, 'clear') is None
                and adapter._row('native')['metadata']['goalMode'] is False)
            for action in (lambda: adapter.goal(hybrid, 'set'), lambda: adapter.answer('unused', 'question', {'answer': 'x'})):
                try:
                    action()
                except ConnectedError as error:
                    check('native-only goal or unsupported question refusal', error.code == 'not_supported')
                else:
                    raise RuntimeError('unsupported action accepted')
            _live_procedure(check)
            turn_id = store.get_conversation('native', include_turns=True)['turns'][-1]['turnId']
            begin_chat_stream(root, turn_id)
            append_chat_stream(root, turn_id, {'kind': 'runtime.progress', 'data': {'eventType': 'context.usage', 'inputTokens': 11656}})
            for _ in range(400):
                append_chat_stream(root, turn_id, {'kind': 'runtime.reasoning_summary_delta', 'message': 'word ' * 100})
            append_chat_stream(root, turn_id, {'kind': 'runtime.progress', 'data': {'eventType': 'context.usage', 'inputTokens': 248092,
                'contextTokens': 1000000, 'triggerTokens': 850000}})
            context = adapter.read(native).context
            check('long stream uses final context receipt', (context.used_tokens, context.window_tokens, context.auto_compact_tokens)
                == (248092, 1000000, 850000))
            broker = ConnectedBroker(root, backend=backend, adapters={}, load_defaults=True, autostart=False, start_cursor=0, list_ttl=0)
            try:
                registered, reason = broker.registry.get('neyvia')
                check('actual registry factory loads native adapter', registered.available() == (True, None) and reason is None)
                listing = broker.list_sessions(app='neyvia')
                check('broker lists filters and reads durable native sessions', any(row['id'] == native for row in listing['sessions'])
                    and any(row['id'] == hybrid for row in broker.list_sessions(app='neyvia', category='hybrid')['sessions'])
                    and broker.read(native)['session']['app'] == 'neyvia')
                sent = broker.send(native, 'broker send', 'native-request-0001', {'model': selected.model, 'permissionMode': 'workspace'})
                _await_broker(broker, sent['runId'], check)
                created = broker.new('neyvia', str(root), 'broker new', 'native-request-0002', {'model': selected.model, 'permissionMode': 'workspace'})
                _await_broker(broker, created['runId'], check)
                check('broker ledger relays actual adapter events', any(event['type'] == 'item.added' and event['item']['kind'] == 'assistant'
                    for event in broker.events_since(0)[0]) and broker.get_run(created['runId'])['sessionId'].startswith('external:neyvia:'))
            finally:
                broker.close()
            rejections = _reject_procedure(adapter, selected, native)
            contracts = sorted(_observed)
            return {'ok': True, 'contracts': contracts, 'checks': checks,
                'rejections': rejections,
                'elapsedMs': round((time.monotonic() - started) * 1000), 'providerRequests': len(provider_requests),
                'processReceipts': process_receipts, 'boundary': proof_text('real dispatcher/SQLite/broker/run control; finite provider HTTP48468 and owned child processes; account construction and completion notifications excluded')}
        finally:
            _observed = None
            server.shutdown()
            server.server_close()
            server_thread.join(3)


def _await_broker(broker, run_id, check):
    deadline = time.monotonic() + 6
    while broker.get_run(run_id)['state'] not in {'completed', 'failed', 'cancelled', 'interrupted'} and time.monotonic() < deadline:
        time.sleep(0.02)
    check('broker durable completed ' + run_id, broker.get_run(run_id)['state'] == 'completed')


def _reject_procedure(adapter, selected, sid):
    from .proof_contracts import ContractViolation
    from .connected_sessions.model import ContextUsage, Item
    from .connected_sessions.neyvia_items import LiveTurn
    row = adapter._row(adapter._conversation_id(sid))
    values = {'self': adapter, 'conversation_id': row['conversationId'], 'message': 'manual guard rejection',
        'mode': 'workspace', 'attachments': [], 'route': adapter._route(row['conversationId'], selected),
        'cwd': str(adapter._root()), 'row': row, 'ids': ('manual-user', 'manual-answer'), 'started': '2026-10-04T00:00:00Z'}
    payload = adapter._payload(**{key: value for key, value in values.items() if key != 'self'})
    invalid_live = LiveTurn(sid, 'manual-corrupt', 0)
    invalid_live.items['manual-corrupt'] = Item('manual-corrupt', 42, 'assistant', data={'text': ''})
    actions = [
        ('native.options', lambda: check_options({'self': adapter, 'session_id': None},
            {**adapter.options(), 'models': [{**row, 'default': False} for row in adapter.options()['models']]})),
        ('native.route', lambda: check_route({'self': adapter, 'conversation_id': '', 'options': selected}, ('opencode', '', 'wrong', 'low'))),
        ('native.payload', lambda: check_payload(values, {key: value for key, value in payload.items() if key != 'history'})),
        ('native.context', lambda: check_context({'self': adapter, 'conversation_id': row['conversationId']}, ContextUsage(used_tokens=-1))),
        ('native.live', lambda: live_contract(lambda self, events: [])(invalid_live, [{'kind': 'runtime.progress'}])),
    ]
    rejected = []
    for identity, action in actions:
        try:
            action()
        except ContractViolation as error:
            require(str(error).startswith(identity + ':'), identity, 'wrong observer rejected deliberately corrupt receipt')
            rejected.append({'contract': identity, 'ok': True})
        else:
            raise RuntimeError(identity + ': deliberately corrupt receipt accepted')
    return rejected


def _live_procedure(check):
    from .connected_sessions.neyvia_items import LiveTurn
    live = LiveTurn('external:neyvia:proof:live', 'manual-live', 0)
    def event(kind, message='', **data):
        return {'kind': kind, 'message': message, 'data': data, 'at': time.time()}
    out = live.apply([event('runtime.answer_start', responseId='draft'), event('runtime.answer_delta', 'Draft'),
        event('runtime.reasoning_summary_delta', 'First '), event('runtime.reasoning_summary_delta', 'thought.'),
        event('runtime.thinking_delta', 'Private text', source='private'),
        event('runtime.thinking_delta', 'Provider text', source='provider.reasoning_content'),
        event('runtime.thinking_delta', ' continues', source='provider.reasoning_content'),
        event('runtime.tool', 'read_file', tool='read_file', input={'path': 'a.txt'}, toolStatus='started'),
        event('runtime.tool', 'read_file', tool='read_file', toolStatus='completed'),
        event('runtime.stream_error', 'finite stream error'), event('runtime.answer_start', responseId='final'),
        event('runtime.answer_delta', 'Final')])
    check('live public/private reasoning, new answer identity and unpaired tools', live.items['manual-live'].data['text'] == 'Final'
        and [item.kind for item in live.items.values()] == ['assistant', 'reasoning', 'reasoning', 'tool', 'tool', 'notice']
        and [e['item']['kind'] for e in out if e['type'] in ('item.added', 'item.updated')]
            == ['assistant', 'reasoning', 'reasoning', 'tool', 'tool', 'notice', 'assistant']
        and live.context is None and sorted(item.seq % 100 for item in live.items.values()) == [0, 1, 2, 3, 4, 99])
    tools = [item for item in live.items.values() if item.kind == 'tool']
    check('adjacent reasoning deltas merge and unpaired tool files stay local', live.items['manual-live#reasoning-1'].data['summary'] == 'First thought.'
        and live.items['manual-live#reasoning-2'].data['summary'] == 'Provider text continues'
        and [(item.data['status'], item.data['files']) for item in tools] == [('running', ['a.txt']), ('ok', [])])
