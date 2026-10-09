import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const result=spawnSync(resolveNeyviaPython(root).python,['-c',`
import json, tempfile, types, sys
from pathlib import Path
from grant_agent import delivery_receipt as d
calls=[]
def transport(**kwargs):
    calls.append(kwargs)
sys.modules['pywebpush']=types.SimpleNamespace(webpush=transport,WebPushException=Exception)
d._web_push_public_key=lambda root,**kwargs:'test-public'
d._web_push_private_key=lambda root,**kwargs:'test-private'
d._web_push_dependency_available=lambda:True
with tempfile.TemporaryDirectory(prefix='neyvia-push-check-') as folder:
    root=Path(folder)
    sub={'endpoint':'https://push.example.invalid/test','keys':{'auth':'test','p256dh':'test'}}
    d.record_web_push_subscription(root,subscription=sub)
    d.record_web_push_subscription(root,subscription=sub)
    assert len(d.load_web_push_subscriptions(root))==1
    first=d.send_chat_completion_web_push(root,turn_id='turn-1',session_id='chat-1')
    assert first['deliveredCount']==1 and len(calls)==1
    d.send_chat_completion_web_push(root,turn_id='turn-1',session_id='chat-1')
    assert len(calls)==1
    payload=json.loads(calls[0]['data'])
    assert 'chatSessionId=chat-1' in payload['url'] and 'surface=agent' in payload['url']
    assert calls[0]['timeout']==2
    d.send_chat_completion_web_push(root,turn_id='cancelled',status='cancelled')
    assert len(calls)==1
    d.record_web_push_subscription(root,subscription=sub,status='unsubscribed')
    assert d.load_web_push_subscriptions(root)==[]
    assert d.send_chat_completion_web_push(root,turn_id='turn-2')['status']=='not_ready'
    print(json.dumps({'ok':True,'transport':'offline test double','deduplicated':True,'unsubscribeHonored':True,'completionDeepLink':True,'cancelledSkipped':True}))
`],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')},encoding:'utf8',timeout:30000});
assert.equal(result.status,0,result.stderr||String(result.error));
console.log(result.stdout.trim());
