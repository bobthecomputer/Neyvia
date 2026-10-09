import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const run = spawnSync(resolveNeyviaPython().python, ['-c', String.raw`
import asyncio,json,tempfile
from pathlib import Path
from grant_agent.compaction_policy import resolve_policy,ContextMeter,estimate_tokens,price_threshold
from grant_agent.session_compaction import SessionCompactor,SECTIONS

async def main():
 with tempfile.TemporaryDirectory() as directory:
  root=Path(directory);(root/'.agent_control').mkdir();(root/'config').mkdir()
  cost={'input':1,'output':2,'tiers':[{'input':2,'output':3,'tier':{'type':'context','size':272000}}], 'context_over_200k':{'input':2}}
  models={'flat':{'limit':{'context':1000000,'output':128000},'cost':{'input':1}},
          'tiered':{'limit':{'context':1050000,'input':922000,'output':128000},'cost':cost}}
  (root/'.agent_control/provider_model_catalog.modelsdev.json').write_text(json.dumps({'catalog':{'fixture':{'models':models}}}))
  flat=resolve_policy(root,'fixture','flat'); tiered=resolve_policy(root,'fixture','tiered')
  assert flat.trigger==850000 and flat.price_tier is None
  assert tiered.price_tier==272000 and tiered.trigger==892500
  assert price_threshold({'input':2,'tiers':[{'input':1,'tier':{'type':'context','size':200000}}]}) is None
  assert price_threshold({'input':1,'context_over_200k':{'input':2}}) is None
  (root/'config/neyvia_context_policy.json').write_text(json.dumps({'mode':'avoid-price-increase'}))
  cheap=resolve_policy(root,'fixture','tiered');flat_cheap=resolve_policy(root,'fixture','flat')
  assert cheap.trigger==244800 and flat_cheap.trigger==flat.trigger
  assert resolve_policy(root,'other','flat').context_tokens==32768,'cross-provider metadata leakage'
  meter=ContextMeter('Exact system prompt', [{'name':'read','parameters':{'type':'object'}}])
  calls=[]
  async def summarize(previous,rows):
   calls.append(rows);result={key:[] for key in SECTIONS};result['goals']=['User request: continue the fixture audit [0]'];return json.dumps(result)
  history=[{'role':'user','content':'Continue the audit'}]+[{'role':'assistant','content':'source code record '+str(i)+' x'*900} for i in range(500)]
  original=json.dumps(history)
  compactor=SessionCompactor(root/'flat.json',summarize,policy=flat,meter=meter)
  assert await compactor.compact(history)==history and not calls,'old 240k character/400 record threshold survived'
  assert compactor.stats['estimatedReplayInputTokens']<flat.trigger
  # A real provider count supersedes estimates only for exactly matching prefixes.
  meter.observe(123456)
  assert meter.measure(history)==123456
  assert meter.measure(history+[{'role':'assistant','content':'new'}])>123456
  altered=[{'role':'user','content':'different'},*history[1:]]
  assert meter.measure(altered)!=123456
  assert estimate_tokens('漢'*1000)>estimate_tokens('a'*1000)
  # Identical history crosses the explicit price tier only in economy mode.
  economical=SessionCompactor(root/'economy.json',summarize,policy=cheap,meter=ContextMeter('System',[]))
  short=await economical.compact(history)
  assert calls and len(short)<len(history) and history[0] in short
  assert json.dumps(history)==original and economical.stats['policy']['reason']=='price_tier'
  # Changing to capacity mode restores original records despite an existing summary.
  restored=SessionCompactor(root/'economy.json',summarize,policy=tiered,meter=ContextMeter('System',[]))
  count=len(calls); assert await restored.compact(history)==history and len(calls)==count
  # Near capacity: compact complete tool groups, retain exact latest request.
  huge=[{'role':'user','content':'Keep exact request'}]
  for i in range(30):
   huge.extend([{'type':'function_call','call_id':str(i),'name':'read','arguments':'{}'},
                {'type':'function_call_output','call_id':str(i),'output':'code line '*11000}])
  near=SessionCompactor(root/'near.json',summarize,policy=flat,meter=ContextMeter('System',[]))
  result=await near.compact(huge)
  assert near.stats['status']=='compacted' and near.stats['estimatedReplayInputTokens']<flat.trigger
  assert huge[0] in result
  assert {r['call_id'] for r in result if r.get('type')=='function_call'}=={r['call_id'] for r in result if r.get('type')=='function_call_output'}
  # System/tool overhead contributes even when the conversation itself is tiny.
  assert ContextMeter('x'*30000,[{'schema':'x'*30000}]).measure([])>20000
  print(json.dumps({'passed':True,'checks':['1M context retains >400 records and >240k characters','route-specific limits','exact 272k price tier','flat/decreasing pricing does not trigger economy compaction','unchanged-prefix provider token calibration','Unicode-aware estimate','switch restores archived full history','near-capacity tool-pair-safe compaction','system/tool/output reservation'], 'flatPolicy':flat.receipt(),'economyPolicy':cheap.receipt()}))
asyncio.run(main())
`], {encoding:'utf8',timeout:60000,env:{...process.env,PYTHONPATH:'src'}});
assert.equal(run.status,0,run.stderr || run.stdout);
console.log(run.stdout.trim());
