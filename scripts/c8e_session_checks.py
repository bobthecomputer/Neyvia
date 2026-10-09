"""Real stored Neyvia conversations prove reversible session overlays."""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TITLE = 'C8e owned garden conversation'
PROMPT = 'Keep the garden watering schedule and summer tomato harvest notes together.'


def apply(bindings):
    overlay = json.loads((ROOT / 'config/inception_c8e_sessions.json').read_text(encoding='utf-8'))
    result = copy.deepcopy(bindings)
    for identity, values in overlay['bindings'].items():
        result[identity].update(copy.deepcopy(values))
    return result


def _read(worker, identity):
    page = worker.tool('backend:connected_session_read_command', {'id': identity, 'limit': 100})
    if page.get('session', {}).get('id') != identity:
        raise RuntimeError('Canonical conversation read did not retain its actual identity')
    users = [item['data'].get('text') for item in page.get('items', []) if item.get('kind') == 'user']
    if users != [PROMPT] or any(item.get('kind') == 'assistant' for item in page.get('items', [])):
        raise RuntimeError('Stored authored user transcript changed or an unauthored assistant response appeared')
    return page


def _observe(worker, identity):
    durable = worker.tool('neyvia.state', {})
    projected = worker.tool('neyvia.sidebar.state', {'ids': [identity]})
    if projected.get('errors') or len(projected.get('sessions', [])) != 1 or projected['sessions'][0]['id'] != identity:
        raise RuntimeError('Fresh sidebar projection did not observe the real selected conversation')
    return {'overlay': durable['sessions'].get(identity, {}), 'projected': projected['sessions'][0],
            'projects': durable['projects'], 'canonical': _read(worker, identity)}


def _reload(worker):
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-root').wait_for(timeout=45000)


def prepare(worker, binding, inputs, root):
    if not binding.get('c8eSession'):
        return
    created = worker.tool('backend:create_neyvia_conversation_command',
                          {'kind': 'chat', 'title': TITLE, 'titleMode': 'off'})
    cid = created['conversationId']
    worker.tool('backend:append_neyvia_conversation_turn_command',
                {'conversationId': cid, 'role': 'user', 'content': PROMPT,
                 'source': 'C8e-authored-user-fixture'})
    from c8e_ui_effects import _fresh_summary
    summary = _fresh_summary(worker, cid)
    if summary.get('origin') != 'user':
        raise RuntimeError('Actual Neyvia adapter misclassified the owned user conversation')
    identity = summary['id']
    inputs['id'] = identity
    if binding['id'].endswith('/move-chat'):
        from c8e_prerequisites import approve_request
        target = (Path(root) / 'c8/session-project').resolve()
        target.relative_to(Path(root).resolve())
        approve_request(worker, 'neyvia.project.create',
                        {'name': 'Garden notes', 'path': str(target), 'template': 'empty'})
        worker.tool('neyvia.project.create',
                    {'name': 'Garden notes', 'path': str(target), 'template': 'empty'})
        registered = worker.tool('neyvia.folder.list', {})['folders']
        if not target.is_dir() or not any(row['path'] == str(target) for row in registered):
            raise RuntimeError('Product project creation did not create and register the disposable directory')
        inputs['project'] = str(target)
    else:
        inputs['title'] = 'C8e reviewed garden watering notes'
    worker.step_results['c8eSessionPrerequisite'] = {
        'conversationId': cid, 'id': identity, 'prompt': PROMPT,
        'canonicalSummary': summary, 'before': _observe(worker, identity)}


def check(worker, binding, inputs, root):
    if not binding.get('c8eSession'):
        return []
    context = worker.step_results['c8eSessionPrerequisite']
    identity = context['id']
    moving = binding['id'].endswith('/move-chat')
    field, tool = ('project', 'neyvia.session.move') if moving else ('title', 'neyvia.session.rename')
    expected = inputs[field]
    before = context['before']
    checks = []

    def verify(label, expected_value):
        observed = _observe(worker, identity)
        if observed['overlay'].get(field) != expected_value or observed['projected'].get(field) != expected_value:
            raise RuntimeError('Fresh durable/projected session ' + field + ' differs from the reviewed action')
        if observed['canonical']['session'].get('title') != TITLE or observed['canonical']['session'].get('project') != before['canonical']['session'].get('project'):
            raise RuntimeError('Sidebar mutation overwrote the genuine provider conversation metadata')
        if moving and expected_value is not None and expected_value not in observed['projects']:
            raise RuntimeError('Moved conversation points to an unregistered project')
        checks.append({'id': 'c8e.session.' + label, 'passed': True, 'fresh': True, 'observed': observed})

    _reload(worker)
    verify('persisted-after-reload', expected)
    durable_before = worker.tool('neyvia.state', {})['sessions']
    invalid = identity + '-nonexistent-C8e-challenge'
    refusal = None
    try:
        worker.tool(tool, {'id': invalid, field: expected})
    except Exception as error:
        if 'Unknown session' not in str(error):
            raise
        refusal = worker.calls[-1]
    durable_after = worker.tool('neyvia.state', {})['sessions']
    if refusal is None or durable_after != durable_before or invalid in durable_after:
        raise RuntimeError('Unknown session mutation was not refused without side effects')
    checks.append({'id': 'c8e.session.unknown-session-refusal', 'passed': True, 'fresh': True,
                   'observed': {'refusal': refusal, 'assignmentsPreserved': durable_after == durable_before}})
    original = before['projected'].get(field)
    worker.tool(tool, {'id': identity, field: original})
    _reload(worker)
    verify('reversed-after-reload', original)
    worker.tool(tool, {'id': identity, field: expected})
    _reload(worker)
    verify('reviewed-effect-restored-after-reload', expected)
    return checks
