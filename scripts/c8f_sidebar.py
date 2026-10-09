"""Real stored conversations, sidebar bus effects and reversible cleanup."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from c8e_sidebar import _seed, _state
from c8e_ui_effects import _skip_setup, _fresh_summary
from c8e_prerequisites import approve_request


def witness(worker, effect, root):
    root = Path(root)
    _skip_setup(worker)
    records = _seed(worker, [('C8f image title is ordinary text', 'An ordinary saved user note.'),
                             ('C8f longer discussion', 'First saved user question.')])
    quick, other = records
    provider_path = Path(__file__).resolve().parents[1] / 'scripts/evidence/C8f-provider.json'
    provider = json.loads(provider_path.read_text(encoding='utf-8'))
    if not provider['passed'] or provider['model'] != 'gpt-6.1-sol':
        raise RuntimeError('A genuine requested Codex provider return is required')
    worker.tool('backend:append_neyvia_conversation_turn_command', {
        'conversationId': quick['conversationId'], 'role': 'assistant',
        'content': provider['answer'], 'source': 'C8f-official-Codex-CLI-return'})
    for text in ('Second saved user question.', 'Third saved user question.'):
        worker.tool('backend:append_neyvia_conversation_turn_command', {
            'conversationId': other['conversationId'], 'role': 'user', 'content': text,
            'source': 'C8f-authored-user-fixture'})
    ids = [r['id'] for r in records]
    states = _state(worker, ids)
    checks, contracts = [], []
    coverage = json.loads((Path(__file__).resolve().parents[1] /
                          'config/proofs/proofs-e-shell.json').read_text())['coverage']

    def check(name, passed, observed):
        row = {'id': 'c8f.sidebar.' + name, 'passed': bool(passed), 'fresh': True,
               'boundary': 'real-persisted-source-and-mounted-consumer', 'observed': observed}
        checks.append(row)
        if not passed:
            raise RuntimeError('Sidebar effect failed: ' + name + ': ' + str(observed))
        return row

    def contract(name, actions, reason=None):
        identity = 'proofs-e.shell.' + name
        contracts.append({'id': identity, 'passed': bool(actions) and not reason,
            'fresh': True, 'boundary': 'real-persisted-source-and-mounted-consumer',
            'observed': {'sourceCases': [c for c in coverage if identity in c['contracts']],
                'actions': actions, **({'unprovedReason': reason} if reason else {})}})

    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-os').wait_for(timeout=20000)
    _skip_setup(worker)
    for identity in ids:
        worker.page.locator('[data-session-id=' + json.dumps(identity) + ']').wait_for(timeout=20000)
    quick_leaf = worker.page.locator('[data-session-id=' + json.dumps(quick['id']) + ']')
    other_leaf = worker.page.locator('[data-session-id=' + json.dumps(other['id']) + ']')
    lanes = check('transcript-lanes', states[quick['id']]['sidebar']['kind'] == 'quick'
        and states[other['id']]['sidebar']['kind'] == 'other', states)
    worker.page.wait_for_function('id=>document.querySelector(`[data-session-id="${id}"]`)?.closest(".nx-nofolder-group")?.querySelector(".nx-nofolder-head")?.textContent.includes("Quick")', arg=quick['id'])
    # Canonical states, not imported frontend objects, are the lane producer.
    contract('kindOf', [lanes], 'The genuine image-tool transcript variant remains unvisited')
    before_project = check('scratch-stays-no-folder', quick_leaf.locator('xpath=ancestor::*[@aria-label="No folder"]').count() > 0,
                           {'id': quick['id'], 'cwd': states[quick['id']].get('cwd')})
    project = root / 'c8' / 'C8f named project'
    arguments = {'name': 'C8f named project', 'path': str(project), 'template': 'empty'}
    approve_request(worker, 'neyvia.project.create', arguments)
    worker.tool('neyvia.project.create', arguments)
    worker.tool('neyvia.session.move', {'id': quick['id'], 'project': str(project)})
    worker.tool('neyvia.session.rename', {'id': quick['id'], 'title': 'C8f renamed through real bus'})
    quick_leaf.get_by_text('C8f renamed through real bus', exact=True).wait_for(timeout=20000)
    placed = check('explicit-move-to-named-project', quick_leaf.locator('xpath=ancestor::*[contains(@class,"nx-branch")]').count() > 0,
                   _state(worker, [quick['id']]))
    contract('placeSession', [before_project, placed], 'Dated/generated/temp folders and independent project-marker variants remain unvisited')
    worker.tool('neyvia.session.pin', {'id': quick['id'], 'pinned': True})
    quick_leaf.locator('xpath=ancestor::*[@aria-label="Pinned"]').wait_for(timeout=20000)
    pinned = check('bus-pin-and-title', quick_leaf.get_by_role('button', name='Unpin', exact=True).count() == 1,
                   {'renderedTitle': quick_leaf.inner_text(), 'state': _state(worker, [quick['id']])})
    worker.tool('neyvia.session.pin', {'id': quick['id'], 'pinned': False})
    # Use actual canonical historical fixture timestamps; never mutate renderer time or model outputs.
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with sqlite3.connect(root / '.agent_control/crashproof.sqlite3') as db:
        db.execute('UPDATE conversations SET updated_at=?, last_meaningful_activity_at=? WHERE conversation_id=?',
                   (old, old, other['conversationId']))
    worker.tool('neyvia.sidebar.policy', {'policy': {'noFolderDays': 7, 'projectDays': 30,
                        'tidyThreshold': 1, 'autoArchive': False}})
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-os').wait_for(timeout=20000)
    _skip_setup(worker)
    worker.page.get_by_role('button', name='Tidy\u2026', exact=True).wait_for(timeout=25000)
    dry = worker.tool('neyvia.sidebar.tidy', {'dryRun': True})
    stale = check('real-historical-candidate', other['id'] in dry.get('candidates', []), dry)
    offered = check('rendered-tidy-offer', worker.page.get_by_role('button', name='Tidy\u2026', exact=True).is_visible(),
                    {'total': 2, 'stale': dry.get('candidates'), 'policy': 'Persisted workspace cleanup rule'})
    worker.page.get_by_role('button', name='Tidy\u2026', exact=True).click()
    archive = worker.page.get_by_role('button', name='Archive 1', exact=True)
    archive.wait_for(timeout=10000)
    archive.click()
    worker.page.get_by_text('Done. The chats are in Fallen leaves; restore one there, or put them all back.', exact=True).wait_for(timeout=20000)
    archive_artifact = worker.screenshot('effect-c8f-sidebar-archive')
    archived = worker.tool('backend:connected_sessions_list_command', {'app': 'neyvia', 'includeArchived': True, 'limit': 100})
    absent = worker.tool('neyvia.sidebar.state', {'ids': [other['id']]})
    check('archive-actual-overlay', not absent.get('sessions') and not absent.get('errors'),
          {'activeProjection': absent, 'listing': archived})
    worker.page.get_by_role('button', name='Undo this tidy', exact=True).click()
    other_leaf.wait_for(timeout=20000)
    restored = check('rendered-and-canonical-undo', other['id'] in _state(worker, [other['id']]),
                     {'id': other['id'], 'visible': other_leaf.inner_text()})
    contract('overrides', [pinned, restored], 'clearOverride semantic undo and malformed-event rejection still require their exact source cases')
    contract('staleCandidates', [stale, restored], 'Pinned/running/needs-you, 7/30-day boundaries and unavailable/failed safety cases remain to be visited')
    contract('shouldOfferTidy', [offered], 'Zero-candidate and default threshold source cases remain to be visited')
    contract('agentSummary', [], 'No genuine nonempty agent transcript was produced; this task prohibits spawning sub-agents')
    contract('buildTree', [placed, pinned], 'Nonempty genuine agent-child folding, needs-you and archived/empty branch source cases remain to be visited')
    artifact = worker.screenshot('effect-c8f-sidebar')
    return checks, {'contractEffects': contracts, 'rendered': {'artifact': artifact,
        'archiveArtifact': archive_artifact, 'url': worker.page.url},
        'preparation': {'historicalTimestamp': old, 'database': 'Owned disposable canonical conversation fixture'},
        'provider': {'receipt': str(provider_path), 'threadId': provider['threadId'],
                     'usage': provider['usage'], 'persistedReply': provider['answer']},
        'unprovedReason': 'Named unvisited source cases remain blocked; no synthetic frontend or agent tree is counted'}
