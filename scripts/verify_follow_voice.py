"""Real owner voice approval and executable manual acceptance on FOLLOW ports."""
import urllib.request,json,pathlib,uuid,time,sys
BASE='http://127.0.0.1:48447'; cookie=''; receipt={'schema':'neyvia.FOLLOW.voice.v1','at':time.time(),'base':BASE,'checks':[],'limitations':[]}
if pathlib.Path('scripts/evidence/FOLLOW-voice.json').exists():
 receipt=json.loads(pathlib.Path('scripts/evidence/FOLLOW-voice.json').read_text(encoding='utf-8-sig'))
 receipt['limitations']=['Chrome plugin unavailable: phone Voice rendered journey is not proved.', 'Physical microphone and packed desktop audio not exercised.']
def request(path,body=None):
 global cookie
 headers={'Content-Type':'application/json'}
 if cookie: headers['Cookie']=cookie
 req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
 with urllib.request.urlopen(req,timeout=100) as response:
  if path=='/api/auth/local-session': cookie=response.headers.get('Set-Cookie','').split(';')[0]
  result=json.load(response)
  if result.get('ok') is False: raise RuntimeError(str(result))
  return result.get('data',result)
def call(command,payload={}): return request('/api/backend',{'command':command,'payload':payload})
def tool(name,args={}): return request('/api/ui/tools/call',{'tool':'neyvia.'+name,'arguments':args})['result']
def check(name,data):
 receipt['checks']=[row for row in receipt['checks'] if row['name']!=name]
 receipt['checks'].append({'name':name,'passed':True,'data':data});print('PASS',name,flush=True)
def save(): pathlib.Path('scripts/evidence/FOLLOW-voice.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
request('/api/auth/local-session',{})
if '--approval' in sys.argv:
 cwd=pathlib.Path('.agent_control/FOLLOW-voice/approval').resolve();cwd.mkdir(parents=True,exist_ok=True)
 target=cwd/('approved-'+uuid.uuid4().hex[:8]+'.txt')
 options=call('connected_provider_options_command',{'app':'codex'})
 if not any(row['id']=='gpt-6-luna' for row in options['models']): raise RuntimeError('Requested Luna unavailable; no substitution')
 prompt=f'Controlled approval acceptance in this disposable folder only. Request exactly one shell exec_command with sandbox_permissions=require_escalated to write APPROVED_BY_VOICE into {target.name} in the current folder. You must request permission before the command. Do not read parent folders or other files, do not delegate, no network. After it runs reply VOICE_APPROVED_DONE.'
 receipt['cursor']=call('connected_events_poll_command',{'waitSeconds':0})['cursor']
 run=call('connected_session_new_command',{'app':'codex','cwd':str(cwd),'message':prompt,'requestId':str(uuid.uuid4()),'options':{'model':'gpt-6-luna','permissionMode':'ask'}})
 runid=run.get('runId') or run.get('id');sid=run.get('sessionId');began=time.monotonic();approved=False;finished=False
 try:
  while time.monotonic()-began<240:
   poll=call('connected_events_poll_command',{'cursor':receipt.get('cursor',0),'waitSeconds':2});receipt['cursor']=poll['cursor']
   for event in poll.get('events',[]):
    if event.get('runId')!=runid:continue
    sid=event.get('sessionId') or sid
    pending=event.get('pendingRequest')
    if pending and pending.get('kind')=='approval' and not approved:
     check('Actual Codex chat waiting approval',{'runId':runid,'sessionId':sid,'event':event})
     voice=request('/api/ui/voice',{'text':'approve','context':{'sessionId':sid,'view':'chat','clientId':'FOLLOW-proof'},'requestId':str(uuid.uuid4())})
     assert voice['status']=='done',voice
     check('Owner voice answered real Codex pending request',voice);approved=True;save()
    if event.get('type')=='run.state' and event.get('state') in ['completed','failed','interrupted','cancelled']:
     assert approved and event['state']=='completed',event
     assert target.read_text().strip()=='APPROVED_BY_VOICE'
     finished=True
     check('Approved CLI command completed and actual file content agrees',{'runId':runid,'sessionId':sid,'content':target.read_text(),'terminal':event});save();sys.exit(0)
   save()
  raise RuntimeError('Real approval turn exceeded 240 seconds')
 finally:
  if not finished: call('connected_session_stop_command',{'runId':runid})
else:
 check('Voice grammar live route',request('/api/ui/voice/commands'))
 try:
  validated=tool('manual.validate',{'id':'voice'});assert validated.get('grounded') is True or validated.get('ok') is True,validated;check('Executable voice manual grounded in live tools',validated)
  procedure=tool('manual.run',{'id':'voice','procedure':'inspect-command','inputs':{'text':'open notes'}})
  assert procedure['status']=='completed' and all(row['passed'] for row in procedure['checks']),procedure
  check('Executable voice procedure real run',procedure)
 except Exception as error:
  receipt['limitations'].append(str(error));save();raise
 save()
