import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const python = resolveNeyviaPython(process.cwd()).python;
const result = spawnSync(python, ['-c', String.raw`
import json, tempfile
from pathlib import Path
from grant_agent.neyvia_conversations import NeyviaConversationStore

with tempfile.TemporaryDirectory() as root:
    store = NeyviaConversationStore(root)
    now = '2026-09-28T12:00:00Z'
    old = '2026-09-27T10:00:00Z'
    def chat(cid, *, status='completed', metadata=None, kind='chat', title='A real conversation'):
        item = store.create_conversation(conversation_id=cid, title=title, kind=kind, metadata=metadata or {}, now=old)
        if title != 'New conversation':
            store.append_turn(cid, role='user', content='Please do the task', now=old)
            store.append_turn(cid, role='assistant', content='The task is complete.', now=old)
        with store._connection() as db:
            db.execute('UPDATE conversations SET status = ?, last_meaningful_activity_at = ? WHERE conversation_id = ?', (status, old, cid))
            db.commit()
        return item

    done = chat('done')
    chat('answered', status='active')
    store.append_turn('answered', role='assistant', content='Answer delivered', metadata={'runtimeResult': {'status':'completed'}}, now=old)
    chat('unrecorded', status='active')
    running = chat('running', status='active')
    waiting = chat('waiting', metadata={'awaitingUserAnswer': True})
    recent = store.create_conversation(conversation_id='recent', title='Recent conversation', now=now)
    store.append_turn('recent', role='user', content='Keep me visible', now=now)
    with store._connection() as db:
        db.execute("UPDATE conversations SET status = 'completed' WHERE conversation_id = 'recent'")
        db.commit()
    active = chat('runtime-active')
    empty = store.create_conversation(conversation_id='empty-shell', now=old)
    named_shell = store.create_conversation(conversation_id='named-shell', title='Saved build task', now=old)
    orchestration_shell = store.create_conversation(conversation_id='orchestration-shell', kind='orchestration', now=old)
    store.set_goal_mode('running', True, now=old)
    assert store.get_conversation('running')['metadata']['goalMode'] is True
    assert store.get_conversation('running')['lastMeaningfulActivityAt'] == old
    store.set_goal_mode('recent', True, now=now)
    assert store.get_conversation('recent')['lastMeaningfulActivityAt'] == now
    goal_active = chat('goal-active')
    store.append_turn('goal-active', role='assistant', content='Still working', metadata={'runtimeResult': {'goalLoop': {'checkpoint': {'status':'active'}}}}, now=old)
    with store._connection() as db:
        db.execute("UPDATE conversations SET status = 'completed', last_meaningful_activity_at = ? WHERE conversation_id = 'goal-active'", (old,))
        db.commit()
    goal_done = chat('goal-done', status='active')
    store.append_turn('goal-done', role='assistant', content='Goal proven', metadata={'turnReceipt': {'goalLoop': {'checkpoint': {'status':'completed'}}}}, now=old)
    with store._connection() as db:
        db.execute("UPDATE conversations SET last_meaningful_activity_at = ? WHERE conversation_id = 'goal-done'", (old,))
        db.commit()
    protected_mission = store.create_conversation(conversation_id='mission', title='Unfinished mission', metadata={'objective':'Keep this mission open'}, now=old)
    store.append_turn('mission', role='user', content='Continue the mission', now=old)
    store.append_turn('mission', role='assistant', content='Mission remains unfinished', now=old)
    with store._connection() as db:
        db.execute("UPDATE conversations SET status = 'completed', last_meaningful_activity_at = ? WHERE conversation_id = 'mission'", (old,))
        db.commit()

    chat('followup', status='active')
    store.append_turn('followup', role='assistant', content='Earlier goal complete', metadata={'runtimeResult': {'goalLoop': {'checkpoint': {'status':'completed'}}}}, now=old)
    store.append_turn('followup', role='user', content='Now check the other case', now=old)

    listed = {row['conversationId'] for row in store.list_conversations(limit=100)}
    assert 'empty-shell' not in listed, 'empty composer shell must stay out of the normal roster'
    assert 'named-shell' in listed, 'named empty work items remain visible'
    assert 'orchestration-shell' in listed, 'orchestration placeholders remain visible'
    assert store.get_conversation('empty-shell')['conversationId'] == 'empty-shell', 'hidden drafts remain addressable'
    assert 'mission' in listed, f'unfinished mission remains visible: {sorted(listed)}'

    receipt = store.archive_inactive_conversations(active_conversation_ids={'runtime-active'}, now=now)
    archived = set(receipt['archived'])
    assert archived == {'done', 'goal-done', 'answered'}, repr(receipt)
    assert receipt['protected']['unrecorded'] == 'not-explicitly-complete'
    assert receipt['protected']['running'] == 'goal-mode-without-completion'
    assert receipt['protected']['waiting'] == 'unresolved-attention'
    assert receipt['protected']['runtime-active'] == 'runtime-active'
    assert receipt['protected']['mission'] == 'unfinished-mission'
    assert receipt['protected'].get('goal-active') == 'goal-active', repr(receipt)
    assert receipt['protected'].get('followup') == 'unanswered-request', repr(receipt)
    assert 'done' not in {row['conversationId'] for row in store.list_conversations(limit=100)}
    assert store.get_conversation('done')['archivedAt'] == now
    restored = store.restore_conversation('done', now=now)
    assert restored['archivedAt'] is None
    assert restored['lastMeaningfulActivityAt'] == now
    assert 'done' in {row['conversationId'] for row in store.list_conversations(limit=100)}
    assert 'done' in {row['conversationId'] for row in store.list_conversations(include_archived=True, limit=100)}
    archived_rows = store.list_conversations(archived_only=True, limit=100)
    assert {row['conversationId'] for row in archived_rows} == {'goal-done', 'answered'}
    print(json.dumps({'archived': sorted(archived), 'protected': receipt['protected'], 'draftHidden': True, 'restoreVerified': True}))
`], {cwd: process.cwd(), encoding: 'utf8', timeout: 30000, env: {...process.env, PYTHONPATH: [process.cwd() + '/src', process.env.PYTHONPATH].filter(Boolean).join(process.platform === 'win32' ? ';' : ':')}});

if (result.status !== 0) {
  throw new Error(result.stderr || result.stdout || result.error?.message || `python exited ${result.status}`);
}
console.log(result.stdout.trim());
