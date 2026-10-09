"""CL 1.1 acceptance journey through owned production stdio, Notes and board."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import sys
import uuid

from prove_cl import Client, REPO
from grant_agent.neyvia_notes_tools import call_notes
from grant_agent.neyvia_awareness import claim
from grant_agent.cl.tokens import count_tokens


def main():
    root = REPO / '.agent_control/cl/proof' / ('cl11-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    folder = root / 'notes'
    call_notes(root,'folder',{'folder':str(folder)},source='ui')
    call_notes(root,'write',{'path':'proof.md','body':'original'},source='ui')
    claim(root,{'files':[str(folder/'proof.md')],'intent':'Concurrent writer reviewing this note','agent':'proof-other-writer'})
    clients, checks, error = [], {}, None
    def record(name,condition):
        checks[name] = bool(condition)
        if not condition: raise RuntimeError('Acceptance gate failed: '+name)
    def act(client,lines,identity=''):
        args = {'lines':lines}
        if identity: args['actionId'] = identity
        return client.request('tools/call',{'name':'neyvia.cl','arguments':args})['structuredContent']
    try:
        client = Client(root); clients.append(client)
        client.request('initialize',{'protocolVersion':'2024-11-05','clientInfo':{'name':'CL11-proof','version':'1.1'},'capabilities':{}})
        cold = client.request('tools/call',{'name':'neyvia.cl.describe','arguments':{'primer':True}})['structuredContent']['text']
        primer = (REPO/'docs/standard/1.1/primer.md').read_text(encoding='utf-8').strip()
        record('L0_only_cold_start',count_tokens(primer)<=300 and not any(line.startswith(('A ','P ','C ','I ','K ','Q ')) for line in cold.splitlines()))
        unverified = act(client,'done("early")')
        record('done_without_goal_unverified',unverified['status']=='unverified')
        blocked = act(client,'notes.write(path="proof.md", body="forbidden")')
        record('no_mutation_without_goal',blocked['status']=='refused' and call_notes(root,'read',{'path':'proof.md'},source='ui')['body']=='original')
        invalid = act(client,'G: notes.write(path="proof.md", body="forbidden").ok == true')
        record('mutation_goal_refused',invalid['status']=='refused')
        accepted = act(client,'G: notes.read(path="proof.md").body == "final" and notes.read(path="proof.md").pinned == true')
        record('observer_goal_accepted',accepted['ok'])
        observed = act(client,'notes.read(path="proof.md")')
        record('first_touch_L1_once',observed['ok'] and 'A notes.read(' not in observed['text'])
        auto = act(client,'notes.write(path="proof.md", body="forbidden", expectedModified="invented")')
        record('agent_stamp_refused',auto['status']=='refused' and 'Host-filled' in auto['text'])
        changed = act(client,'Here is the call:\n```cl\nnotes.write(path="proof.md", body="final")\n```','write-final')
        note = call_notes(root,'read',{'path':'proof.md'},source='ui')
        record('host_CAS_check_I_K_events',changed['ok'] and note['body']=='final' and '+body-saved' in changed['text'] and '\nK ' in '\n'+changed['text'] and '\nI ' in '\n'+changed['text'] and 'notes.changed' in changed['text'])
        record('stamp_hidden_in_model_response','expectedModified' not in json.dumps(changed) and note['modified'] not in json.dumps(changed))
        early = act(client,'done("local body check passes")')
        record('whole_goal_refuses_missing_pin',early['status']=='refused' and '-G' in early['text'])
        pin = act(client,'notes.pin(path="proof.md")')
        done = act(client,'done("saved and pinned")')
        record('whole_goal_done_observed',pin['ok'] and done['ok'] and done['doneStatus']=='ok')
        # A retained read stamp observes another writer; host reports fresh D,
        # preserves their bytes and leaves retry to the agent.
        act(client,'notes.read(path="proof.md")')
        call_notes(root,'write',{'path':'proof.md','body':'other writer'},source='ui')
        stale = act(client,'notes.write(path="proof.md", body="retry decision")')
        record('CAS_conflict_preserves_other_writer',stale['status']=='stale' and 'D notes other-writer' in stale['text'] and call_notes(root,'read',{'path':'proof.md'},source='ui')['body']=='other writer')
        retry = act(client,'notes.write(path="proof.md", body="final")')
        record('host_reread_allows_explicit_retry',retry['ok'])
        append = act(client,'notes.write(path="proof.md", body="once", mode="append")','append-once')
        replay = act(client,'notes.write(path="proof.md", body="once", mode="append")','append-once')
        record('stable_action_identity_suppresses_repeat',append['ok'] and replay['ok'] and call_notes(root,'read',{'path':'proof.md'},source='ui')['body'].count('once')==1)
        paused = act(client,'run notes.write-and-pin(path="proof.md", body="final")')
        before = call_notes(root,'read',{'path':'proof.md'},source='ui')['body']
        resumed = act(client,'run notes.write-and-pin(path="proof.md", body="final", replace_note="replace")','procedure-complete')
        again = act(client,'run notes.write-and-pin(path="proof.md", body="final", replace_note="replace")','procedure-complete')
        record('procedure_J_pause_resume_G_and_identity',paused['status']=='ask' and before.endswith('once') and resumed['ok'] and '+G' in resumed['text'] and again['ok'])
        frontier = act(client,'notes.open(path="proof.md")')
        record('observerless_mutation_frontier',frontier['status']=='frontier')
        call_notes(root,'write',{'path':'large.md','body':'x'*5000},source='ui')
        large = act(client,'notes.read(path="large.md")')
        handle = re.search(r'S notes (h[0-9]+)',large['text']).group(1)
        projected = act(client,'project('+handle+', "body", 0, 20)')
        record('host_Q_truncation_and_bounded_projection',large['ok'] and 'Q projection truncated' in large['text'] and projected['ok'] and '"'+('x'*20)+'"' in projected['text'])
        readonly = Client(root,True); clients.append(readonly)
        act(readonly,'G: notes.read(path="proof.md").body == "denied"')
        denied = act(readonly,'notes.write(path="proof.md", body="denied")')
        record('original_permissions_preserved',denied['status']=='ask' and 'K ' in denied['text'] and call_notes(root,'read',{'path':'proof.md'},source='ui')['body']=='final')
    except Exception as exc:
        error = str(exc)
    finally:
        for client in clients: client.close()
        receipt = {'schema':'neyvia.cl11.production-proof.v1','root':str(root),'allPassed':bool(checks) and all(checks.values()) and error is None,
                   'checks':checks,'error':error,'transcripts':[client.rows for client in clients],
                   'finalNoteSha256':hashlib.sha256((folder/'proof.md').read_bytes()).hexdigest(),
                   'boundary':'Actual production stdio MCP, host Protocol, Notes bytes and bus events, work board, read-only grants; no public service or native/browser claims'}
        target = REPO/'scripts/evidence/CL11-production.json'
        target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'allPassed':receipt['allPassed'],'checks':checks,'error':error,'receipt':str(target)}))
    return 0 if receipt['allPassed'] else 1


if __name__ == '__main__': raise SystemExit(main())
