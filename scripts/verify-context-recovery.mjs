import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
import {createHash} from 'node:crypto';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-context-recovery-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import hashlib,json,sys,subprocess
from pathlib import Path
from grant_agent.context_engine import DurableContextEngine,estimate_tokens
from grant_agent.context_microkernel import ModelVisibleContext
from grant_agent.neyvia_agent import NeyviaToolGateway
root=Path(sys.argv[1])
engine=DurableContextEngine(root,'mission',max_context_tokens=4096,reserve_tokens=128,protect_recent_tokens=128)
original=engine.append('user','Keep the original install paused. Do not reopen it.',kind='instruction')
contract=engine.append('user','Use Codex / openai-codex / gpt-5.6-luna. Finance is outside scope.',kind='contract')
accepted=engine.append('system','Native action A completed with receipt R. Controller input remains unverified.',kind='acceptance',source='fixture')
custom=engine.append('user','Preserve this operator checkpoint verbatim.',kind='checkpoint',pinned=True,source='operator')
for i in range(50):
    engine.append('tool',f'diagnostic {i}: '+('noise '*100),kind='observation')
for _ in range(3):
    receipt=engine.compact(focus='remaining documentation',target_ratio=0.1)
    assert original.event_id not in receipt['archivedEventIds']
    assert contract.event_id not in receipt['archivedEventIds']
    assert accepted.event_id not in receipt['archivedEventIds']
    assert custom.event_id not in receipt['archivedEventIds']
# Reopen from disk, with no in-memory transcript.
probe="from grant_agent.context_engine import DurableContextEngine; import json,sys; print(json.dumps(DurableContextEngine(sys.argv[1],'mission',max_context_tokens=4096,reserve_tokens=128).build_bundle(token_budget=1200)))"
reopened=json.loads(subprocess.check_output([sys.executable,'-c',probe,str(root)],text=True))
for event in (original,contract,accepted,custom):
    assert any(row['eventId']==event.event_id and row['content']==event.content for row in reopened['items'])
fresh=DurableContextEngine(root,'mission',max_context_tokens=4096,reserve_tokens=128)
bundle=fresh.build_bundle('unrelated lookup',token_budget=1200)
by_id={row['eventId']:row for row in bundle['items']}
assert set(bundle['protectedContext']['eventIds'])=={original.event_id,contract.event_id,accepted.event_id,custom.event_id}
assert bundle['protectedContext']['complete'] is True
for event in (original,contract,accepted,custom):
    assert by_id[event.event_id]['content']==event.content
    assert not by_id[event.event_id]['truncated']
assert bundle['ledger_estimated_tokens']<=bundle['token_budget']
assert bundle['estimated_tokens']==estimate_tokens(json.dumps(bundle,ensure_ascii=False,separators=(',',':'),sort_keys=True))
assert bundle['contextBudget']['exceeded']==(bundle['estimated_tokens']>bundle['token_budget'])
assert next(e for e in fresh._events() if e.event_id==custom.event_id).pinned
try:
    fresh.build_bundle(token_budget=1)
    raise AssertionError('Protected instruction silently omitted or truncated')
except ValueError as exc:
    assert 'Protected context requires' in str(exc)
# Older ledgers may already contain archived critical instructions.
with fresh._connection() as db:
    db.execute('UPDATE context_events SET active=0 WHERE event_id=?',(original.event_id,))
assert any(r['eventId']==original.event_id and r['content']==original.content for r in fresh.build_bundle(token_budget=1200)['items'])
# Cache identities must differ when the same event is truncated differently.
cache=DurableContextEngine(root,'cache',max_context_tokens=10000,reserve_tokens=64)
event=cache.append('tool','a'*20000,kind='observation',reported_tokens=1)
small=cache.build_bundle(token_budget=3000)
large=cache.build_bundle(token_budget=4000)
assert small['items'][0]['eventId']==large['items'][0]['eventId']==event.event_id
assert small['cache_key']!=large['cache_key']
for b in (small,large):
    item=b['items'][0]
    assert item['truncated']
    assert item['includedContentSha256']==hashlib.sha256(item['content'].encode()).hexdigest()
    assert item['contentSha256']==event.content_sha256
    assert b['ledger_estimated_tokens']==estimate_tokens(item['content'])<b['estimated_tokens']<=b['token_budget']
# The model-facing facade must propagate refusal rather than fall back to a
# shorter context manager that dropped the authority boundary.
facade=ModelVisibleContext(root,'facade',max_tokens=256)
facade.record('user','Preserve every authority boundary. '*80,kind='contract')
try:
    facade.model_messages()
    raise AssertionError('Facade silently fell back after protected overflow')
except ValueError as exc:
    assert 'Protected context requires' in str(exc)
# Exercise the actual tool handler and saved-action path, not just engine calls.
gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='context-fixture')
request={'sessionId':'mission','maxContextTokens':4096,'focus':'remaining work','targetRatio':0.1}
first=gateway.call_native('context.compact',request,action_id='compact-v1')
second=gateway.call_native('context.compact',request,action_id='compact-v1')
assert first['ok'] and second['ok'] and second['duplicateSuppressed']
assert first['receipt_id']==second['receipt_id']
read=gateway.call_native('context.bundle',{'sessionId':'mission','maxContextTokens':4096,'tokenBudget':1200})
assert read['ok']
assert any(row['content']==contract.content for row in read['result']['items'])
refused=gateway.call_native('context.bundle',{'sessionId':'mission','maxContextTokens':4096,'tokenBudget':1})
assert not refused['ok']
print('CONTEXT_RECOVERY_VERIFIED: repeated compaction, fresh-process reconstruction, authority preservation, overflow refusal, and delivered-content cache identity')
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, encoding: 'utf8', timeout: 30000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const evidence = result.stdout.trim();
  console.log(JSON.stringify({status:'verified', evidence, sha256:createHash('sha256').update(evidence).digest('hex')}));
} finally {
  rmSync(root, {recursive: true, force: true});
}
