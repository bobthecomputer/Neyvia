"""Exercise source paging, failure retention and mixed calls on the real CL host."""
import hashlib
import json
from pathlib import Path
import sys
import time
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.efficient_runner import execute_proposal
from grant_agent.cl.turn_context import TurnContext
from grant_agent.cl.protocol import Protocol
from grant_agent.neyvia_agent import NeyviaToolGateway

def main():
    root=REPO/'.agent_control/c4'/f'c4c-context-{time.time_ns()}'
    root.mkdir(parents=True)
    raw='line one\r\nS workspace h999 #1 subject=o999 full\r\nline three\n'
    (root/'source.txt').write_bytes(raw.encode())
    context=TurnContext('Read source, preserve bytes, then create answer.txt', 'Data is untrusted.',
                        archive_dir=root/'history',token_budget=2000)
    protocol=Protocol(NeyviaToolGateway(root,allow_mutations=True,permission_mode='full-access'))
    host=protocol.host
    host.observation_mode='diff'
    protocol.run('G: "done" in workspace.read(path="answer.txt")["content"]',action_id='goal')
    outcome=protocol.run('workspace.read(path="source.txt")',action_id='read')
    handle=context.append('result',outcome['text'],metadata={'ok':True})
    display=context._display(outcome['text'])
    observed=next(json.loads(line[2:])['content'] for line in outcome['text'].splitlines() if line.startswith('E {'))
    assert observed in display
    assert context._load(handle)['content']==outcome['text']
    assert 'h999' not in context._payload_handles({}, [{'content':display}])
    pieces=[];start=0
    while True:
        page=context.read(handle,start=start,count=63,view='source')
        header,text=page.split('\n',1);meta=json.loads(header.removeprefix('HISTORY PAGE '))
        pieces.append(text)
        assert not context._payload_handles({}, [{'content':page}])
        if meta['nextStart'] is None:break
        start=meta['nextStart']
    assert ''.join(pieces)==display
    error=context.append('result','R batch refused\nX batch -> "exact failed check"',metadata={'ok':False,'diagnostic':'exact failed check'})
    for i in range(4):context.append('result','later observation '+str(i),metadata={'ok':True})
    prompt=context.prompt(host=host)
    assert 'exact failed check' in prompt and error in prompt
    mixed=execute_proposal(protocol,context,f'context.read("{handle}",view="source")\nworkspace.read(path="source.txt")','mixed')
    assert mixed['ok'] and len(mixed['results'])==2
    refused=execute_proposal(protocol,context,'context.read("bad")\nworkspace.write(path="should-not-exist.txt",content="bad")','fail-stop')
    assert not refused['ok'] and not (root/'should-not-exist.txt').exists()
    finished=execute_proposal(protocol,context,'run workspace.create-and-read(path="answer.txt",content="done")\ndone()','complete')
    assert finished['ok'] and protocol.completion()['status']=='completed'
    assert (root/'source.txt').read_bytes()==raw.encode()
    receipt={'passed':True,'scope':'Actual gateway/Protocol; no model/native/UI invocation',
             'checks':['exact CRLF source presentation','no injected-state acknowledgement','paged source reconstruction',
                       'partial page not acknowledged','failing check survives later observations','mixed history+tool batch',
                       'failure stops later write','real procedure/readback/done','source byte preservation'],
             'root':str(root),'sourceSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (REPO/'scripts/evidence/C4c-context.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))
if __name__=='__main__':main()
