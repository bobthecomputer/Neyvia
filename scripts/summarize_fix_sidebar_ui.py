from pathlib import Path
import hashlib
import json
REPO=Path('.').resolve()
def sha(p): return hashlib.sha256((REPO/p).read_bytes()).hexdigest()
def load(p): return json.loads((REPO/p).read_text())
paths=['scripts/evidence/FIX-sidebar-ui-before.json','scripts/evidence/FIX-sidebar-ui-after-dedup.json','scripts/evidence/FIX-sidebar-ui-after-tcp-retained.json','scripts/evidence/FIX-sidebar-ui-policy-first.json','scripts/evidence/FIX-sidebar-ui-owner-trace.json','scripts/evidence/FIX-sidebar-ui-owner-phases.json','scripts/evidence/FIX-sidebar-ui.json','scripts/evidence/FIX-sidebar-network.json','scripts/evidence/FIX-sidebar-runs.json']
out={'schema':'neyvia.FIX.sidebar-ui-mechanism.v1','primaryDefinition':load(paths[6])['definition'],'budgetMs':2000,'runs':[],'causalEvidence':{},'scope':'Real native WebView2 full NxShell navigation to six default rows, real300 summary page of900 durable chats. Process startup and background transcript sorting remain separate and explicitly reported. No protected provider histories or public release claim.'}
for p in paths:
 r=load(p)
 row={'path':p,'sha256':sha(p),'ok':r.get('ok'),'cleanup':r.get('cleanup')}
 if 'samples' in r:
  row['samples']=[{'navigationToDefaultRenderMs':s.get('navigationToDefaultRenderMs'),'IPCServiceMs':s.get('serviceMs'),'initialListCalls':s.get('initialListCalls'),'hostStartToDefaultMs':s.get('hostStartToDefaultMs'),'nativeStartToDefaultMs':s.get('nativeStartToDefaultMs'),'expansionTo300RenderMs':s.get('expansionTo300RenderMs')} for s in r['samples']]
 out['runs'].append(row)
phase=load(paths[5])
raw=Path(phase['samples'][0]['root'])/'owner-phases.json'
out['causalEvidence']['runStatePhase']={'path':str(raw.relative_to(REPO)).replace('\\','/'),'sha256':sha(raw),'timings':json.loads(raw.read_text()),'finding':'300 latest_run calls took5961ms; native inventory707ms, safety cached11.7ms, seen baseline9ms. Batchpage removes per-row DB opens while keeping scoped recovery and fresh archive checks.'}
for label,p in [('beforePolicy',paths[2]),('afterPolicyBeforeBatch',paths[5]),('final',paths[6])]:
 r=load(p)
 out['causalEvidence'][label]=[]
 for s in r['samples']:
  raw=Path(s['root'])/'body-timings.jsonl'
  if raw.exists():
   rows=[json.loads(line) for line in raw.read_text().splitlines()]
   out['causalEvidence'][label].append({'path':str(raw.relative_to(REPO)).replace('\\','/'),'sha256':sha(raw),'assets':[v for v in rows if v['path'].startswith('/assets/')]})
final=load(paths[6])
checks=[]
for category,entries in [('sources',final['sources']),('pictures',final['pictures']),('buildArtifacts',final['buildArtifacts'])]:
 for entry in entries:
  checks.append({'category':category,'path':entry['path'],'matches':sha(entry['path'])==entry['sha256']})
checks.append({'category':'nativeBinary','path':final['nativeBinary']['path'],'matches':sha(final['nativeBinary']['path'])==final['nativeBinary']['sha256']})
out['finalHashAudit']=checks
out['finalHashAuditPassed']=all(x['matches'] for x in checks)
out['budgetPassed']=final['budgetPassed']
out['remaining']='Backend/WebView process startup is4.00–7.41s host-start or1.30–3.73s native-start; transcript sort observations are still background work at first paint. Bounded native-only900 fixture and copied compiled proof host are not installed desktop/public release or external provider history proof.'
(REPO/'scripts/evidence/FIX-sidebar-ui-mechanism.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'budgetPassed':out['budgetPassed'],'finalHashAuditPassed':out['finalHashAuditPassed'],'mismatches':[x for x in checks if not x['matches']]}))
