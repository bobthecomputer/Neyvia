"""Seal current host-run observations; hashes preserve evidence, not UI proof."""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,required=True)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.port not in range(48741,48750): p.error('Explicit assigned port required')
    source,target=a.input.resolve(),a.output.resolve()
    for path in (source,target): path.relative_to(REPO/'scripts/evidence')
    if source==target or source.stat().st_size>128*1024*1024: raise ValueError('Distinct bounded source required')
    raw=source.read_bytes(); full=json.loads(raw)
    from grant_agent.proof_contracts import source_digest
    from grant_agent.edge_fixture_catalog import completed_receipts, BUILDERS
    for name,sha in full['sourceBindings'].items():
        path=(REPO/name).resolve();path.relative_to(REPO)
        if source_digest(path)!=sha: raise ValueError('Stale source: '+name)
    if not full['ok'] or not full['sourceStable'] or full['explicitPort']!=a.port: raise ValueError('Unsuccessful or unstable campaign')
    arrays={'schema':'schemaCases','postconditions':'postconditionCases','journeys':'journeys','semanticCoverage':'semanticCoverage'}
    counts={key:dict(Counter(row['status'] for row in full[value])) for key,value in arrays.items()}
    if counts!=full['counts'] or full['failures']: raise ValueError('Observation counts differ')
    families=completed_receipts(Path(full['root'])/'semantic-fixtures')
    if families!=full['familyReceipts']: raise ValueError('Completed family index differs')
    if {row['family'] for row in families}!=set(BUILDERS):raise ValueError('A registered family did not complete')
    baseline=json.loads((REPO/'scripts/evidence/C7.json').read_text(encoding='utf-8'))
    actual={(r['contract'],r['category']):r for r in full['semanticCoverage']}
    if len(actual)!=len(full['semanticCoverage']): raise ValueError('Duplicate obligations')
    if any((r['contract'],r['category']) not in actual for r in baseline['semanticCoverage']): raise ValueError('Original obligation dropped')
    formerly=Counter(actual[(r['contract'],r['category'])]['status'] for r in baseline['semanticCoverage'] if r['status']=='blocked')
    if dict(formerly)!=full['baseline']['formerlyBlocked']: raise ValueError('Original reconciliation differs')
    host=full['hostProof']; host_path=(REPO/host['path']).resolve();host_path.relative_to(REPO/'scripts/evidence')
    if hashlib.sha256(host_path.read_bytes()).hexdigest()!=host['sha256']: raise ValueError('Host evidence changed')
    host_data=json.loads(host_path.read_text(encoding='utf-8'))
    if not host_data['ok'] or not all(r['passed'] for r in host_data['manualChecks']): raise ValueError('Host/manual journey failed')
    archive=target.with_name(target.stem+'-full.json.gz')
    with archive.open('wb') as stream:
        with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0,filename='') as writer: writer.write(raw)
    blocked=[r for r in actual.values() if r['status']=='blocked']
    kinds=dict(Counter(r['blockerKind'] for r in blocked))
    if set(kinds)-{'not_applicable','authority_boundary'}:raise ValueError('Unresolved applicable fixture or proof obligation remains')
    previous=json.loads((REPO/'scripts/evidence/C7c.json').read_text(encoding='utf-8'))
    previous_archive=REPO/previous['fullMatrix']['path']
    if hashlib.sha256(previous_archive.read_bytes()).hexdigest()!=previous['fullMatrix']['sha256']:raise ValueError('C7c baseline archive changed')
    previous_matrix=json.loads(gzip.decompress(previous_archive.read_bytes()))
    pending=[r for r in previous_matrix['semanticCoverage'] if r['status']=='blocked' and r.get('blockerKind') in {'fixture_gap','fixture_not_implemented'}]
    if len(pending)!=4870:raise ValueError('Original fixture denominator changed')
    fixture_closure=dict(Counter(actual[(r['contract'],r['category'])]['status'] if actual[(r['contract'],r['category'])]['status']!='blocked' else actual[(r['contract'],r['category'])]['blockerKind'] for r in pending))
    references=[]
    for name in ('C7d-aggregation.json','C7d-authority.json','C7d-retention.json','C7d-retained.zip','C7d-manual-compile.json','C7d-native-build.json','C7d-observation-recovery.json','C7d-current-retention.json','C7d-native-admission.json','C7d-mesh-loader.json','C7d-scheduler-utf8.json','C7d-cache-race.json','C7d-installer-contention.json','C7d-http-concurrency.json','C7d-loopback-policy.json','C7d-stale-native-mutation.json','C7d-claude-idle.json'):
        path=REPO/'scripts/evidence'/name
        if not path.is_file(): raise ValueError('Missing proof: '+name)
        references.append({'path':path.relative_to(REPO).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    authority=json.loads((REPO/'scripts/evidence/C7d-authority.json').read_text(encoding='utf-8'))
    original_authority=authority['originalAuthorityBlockers']
    if len(original_authority)!=8 or any(actual[(r['contract'],r['category'])]['blockerKind']!='authority_boundary' for r in original_authority): raise ValueError('Original authority boundary changed')
    additional_authority=authority['additionalAuthorityBlockers']
    declared_authority=original_authority+additional_authority
    if {(r['contract'],r['category']) for r in blocked if r['blockerKind']=='authority_boundary'}!={(r['contract'],r['category']) for r in declared_authority}:raise ValueError('An authority obligation lacks an exact review')
    commits=subprocess.run(['git','log','a6714b89..HEAD','--format=%h %s'],cwd=REPO,capture_output=True,text=True,encoding='utf-8',check=True).stdout.splitlines()
    report={'schema':'neyvia.c7d-receipt.v1','ok':True,'complete':full['complete'],'sourceCurrent':True,'sourceStable':True,'explicitPort':a.port,
        'durationMs':full['durationMs'],'inventory':full['inventory'],'counts':counts,'baseline':full['baseline'],'semanticSummary':full['semanticSummary'],'original4870FixtureClosure':fixture_closure,
        'blockedKinds':kinds,'remaining':[{'contract':r['contract'],'category':r['category'],'kind':r['blockerKind'],'reason':r['reason']} for r in blocked if not r.get('accountedNotApplicable')],
        'originalAuthorityBlockers':original_authority,'additionalAuthorityBlockers':additional_authority,'evidenceReferences':references,'familyReceipts':families,'hostProof':host,'sourceBindings':full['sourceBindings'],
        'fullMatrix':{'path':archive.relative_to(REPO).as_posix(),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'compressedBytes':archive.stat().st_size,'uncompressedBytes':len(raw),'uncompressedSha256':hashlib.sha256(raw).hexdigest()},
        'commitsBeforeReceipt':commits,'completionGate':'Every applicable matched case must pass its actual proof boundary. Audited invariant-specific exclusions remain blocked/accounted, never passed; authority is never inferred.',
        'boundaries':['Owned state, assigned loopback ports, isolated homes; no credential reads, NAS sync, protected trees or live services.','Rendered proof requires fresh native observations in the registered campaign; hashes and frontend model diagnostics do not supply observations.','No physical device or live provider execution claim; no push, merge or public promotion.']}
    target.write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':True,'formerlyBlocked':dict(formerly),'blockedKinds':kinds,'compressedBytes':archive.stat().st_size}))

if __name__=='__main__': main()
