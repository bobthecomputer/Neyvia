"""Retain current FIXCL7 evidence and costs without promoting partial goals."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / 'scripts/evidence'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(name): return json.loads((OUT / name).read_bytes())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-log', type=Path, required=True)
    args = parser.parse_args()
    branch = subprocess.check_output(['git','branch','--show-current'],cwd=REPO,text=True).strip()
    if branch != 'track/fix-cl': raise ValueError('Wrong authorized branch')
    audit = read('FIXCL7-AUD4-after.json')
    snapshot = read('FIXCL7-AUD4-after-snapshots.json')
    sdk = read('FIXCL7-sdk-mount.json')
    scheduler = read('FIXCL7-regeneration.json')
    cache = read('FIXCL7-cache-proof.json')
    current = {}
    for name, row in scheduler['probes'].items():
        receipt = OUT / ('FIXCL7-' + ('evaluations' if name == 'evaluation' else name) + '.json')
        mismatches = []
        for path, digest in row['sourceHashes'].items():
            if path.startswith('executable:'):
                target = Path(__import__('sys').executable) if path.endswith('python') else REPO/'.agent_control/fixcl7/obscura-target/release/obscura.exe'
            elif path.startswith('dist:'): target = REPO/'.agent_control/fixcl7/render-dist'/path[5:]
            else: target = REPO/path
            if not target.is_file() or sha(target) != digest: mismatches.append(path)
        current[name] = {'sourceCurrent':not mismatches,'mismatches':mismatches,
            'receiptCurrent':receipt.is_file() and sha(receipt) == row['receiptSha256'],
            'exitCode':row['exitCode'],'failedChecks':row['failedChecks']}
    checks = {
        'all185CellsFreshlyAssessed':sum(audit['counts'].values()) == 185 and all(audit['checks'].values()),
        'allProbeSourcesCurrent':all(row['sourceCurrent'] for row in current.values()),
        'allProbeReceiptsCurrent':all(row['receiptCurrent'] for row in current.values()),
        'snapshotSourcesCurrent':snapshot['sourceHashesAtStart'] == snapshot['sourceHashesAtEnd'] and
            all(sha(REPO/path) == digest for path,digest in snapshot['sourceHashesAtStart'].items()),
        'compiledManualsMatch':all(row.get('equal') is True for row in read('FIXCL7-manual-check.json')['results']),
        'unchangedCommandUsesCache':cache.get('allProbesCached') is True,
        'actualMountedSdkWorks':sdk.get('ok') is True,
        'faithfulPdfContractPassed':read('FIXCL7-renderer-pdf.json').get('ok') is True,
        'sdkScreenshotHashMatches':sha(Path(sdk['screenshot']['path'])) == sdk['screenshot']['sha256'],
        'goalAll185Green':audit['counts'].get('G') == 185,
        'boundedC7CacheContractPassed':read('FIXCL7-C7-cases.json')['cases'][0]['result'].get('ok') is True,
    }
    required = ('all185CellsFreshlyAssessed','allProbeSourcesCurrent','allProbeReceiptsCurrent',
                'snapshotSourcesCurrent','compiledManualsMatch','unchangedCommandUsesCache','sdkScreenshotHashMatches',
                'boundedC7CacheContractPassed','actualMountedSdkWorks','faithfulPdfContractPassed')
    # These are observer measurements. The executable C7 case below admits
    # the evidence receipt; incomplete product goals remain explicitly false.
    usage = None
    with args.session_log.open(encoding='utf-8') as stream:
        for line in stream:
            if '"token_count"' not in line: continue
            event = json.loads(line)
            if event.get('type') == 'event_msg' and event.get('payload',{}).get('type') == 'token_count':
                info = event['payload'].get('info')
                if info: usage = info.get('total_token_usage')
    provider_runs = {}
    candidates = [OUT/'FIXCL7-provider.json', *(REPO/'.agent_control/fixcl7/previous').glob('*/FIXCL7-provider.json')]
    for path in candidates:
        if not path.is_file(): continue
        proof = json.loads(path.read_bytes())
        run = proof.get('retainedRun',{})
        if run.get('runId'):
            tokens = run.get('tokens',0)
            provider_runs[proof['root']+'#'+run['runId']] = tokens.get('total',0) if isinstance(tokens,dict) else tokens
    provider_tokens = sum(provider_runs.values())
    sys.path.insert(0,str(REPO/'scripts'))
    from fixcl7_model_usage import conductor_usage
    conductor_sessions = conductor_usage(REPO)
    conductor_tokens = sum(row['totalTokens'] for row in conductor_sessions.values())
    remaining = [{'surface':row['surface'],'axis':cell['axis'],'status':cell['status'],'finding':cell['finding']}
        for row in audit['matrix'] for cell in row['cells'] if cell['status'] != 'G']
    files = ['FIXCL7-AUD4-after.json','FIXCL7-AUD4-after-snapshots.json','FIXCL7-regeneration.json',
        'FIXCL7-cache-proof.json','FIXCL7-C7-cases.json','FIXCL7-sdk-mount.json','FIXCL7-sdk-phone.png','FIXCL7-renderer-build.json',
        'FIXCL7-renderer-patch.json','FIXCL7-manual-check.json','FIXCL7-harness-gaps.md']
    files += ['FIXCL7-renderer-pdf.json','FIXCL7-faithful-pdf.png']
    report = {'schema':'neyvia.FIXCL7.v1','createdAt':datetime.now(timezone.utc).isoformat(),
        'branch':branch,'baseline':read('FIXCL7-AUD4-baseline.json')['counts'],'counts':audit['counts'],
        'checks':checks,'probes':current,'remainingCells':remaining,'files':{name:sha(OUT/name) for name in files},
        'regenerateCommand':'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe scripts/fixcl7_regenerate.py --port 48781',
        'cacheSeconds':cache['seconds'],'usage':{'agent':usage,'providerRuns':provider_runs,
            'providerTokens':provider_tokens,'conductorSessions':conductor_sessions,'conductorTokens':conductor_tokens,
            'totalTokensAsOfSeal':(usage or {}).get('total_tokens',0)+provider_tokens+conductor_tokens,
            'cachedInputTokens':(usage or {}).get('cached_input_tokens',0)+sum(row['cachedInputTokens'] for row in conductor_sessions.values()),
            'boundary':'Includes root counters and actual product provider/conductor replays; local text-only evolution token estimates are not billed model usage.'},
        'commits':subprocess.check_output(['git','log','--first-parent','f5379859d^1..HEAD','--format=%h %s'],cwd=REPO,text=True).splitlines(),
        'boundary':'Owned local source, disposable fixtures, hidden Obscura and portable offline native patch. No push, release promotion, physical phone, remote machine, NAS, or visible desktop proof.',
        'goalComplete':all(checks.values())}
    import time
    root = REPO/'.agent_control/proofs'/('FIXCL7-seal-contract-'+str(time.time_ns())); root.mkdir(parents=True,exist_ok=True)
    observation = root/'current-evidence.json'
    observation.write_text(json.dumps(checks,indent=2)+'\n',encoding='utf-8')
    source = 'G: matches(workspace.read(path='+json.dumps(str(observation))+')["content"], '+json.dumps({
        'type':'string','allOf':[{'pattern':'"'+key+'"\\s*:\\s*true'} for key in required]
    })+')\ndone()'
    sys.path[:0] = [str(REPO/'scripts'),str(REPO/'src')]
    from fixcl_verify import environment, guards
    environment(root,48781); guards(root)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    gateway = NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL7-seal-contract',permission_mode='workspace')
    answer = Protocol(gateway).run(source,action_id='FIXCL7-seal-contract',scope_tools=['workspace.read'])
    if answer.get('ok') is not True: raise ValueError('C7 current-evidence contract refused the seal: '+repr(checks))
    cases = read('FIXCL7-C7-cases.json')
    cases['cases'] = [case for case in cases['cases'] if case['name'] != 'current-evidence-can-be-sealed']
    cases['cases'].append({'name':'current-evidence-can-be-sealed','source':source,'result':answer,
        'measuredObservationSha256':sha(observation),'boundary':'Current source/receipt/hash admission; no all-green release claim.'})
    (OUT/'FIXCL7-C7-cases.json').write_text(json.dumps(cases,indent=2)+'\n',encoding='utf-8')
    report['files']['FIXCL7-C7-cases.json'] = sha(OUT/'FIXCL7-C7-cases.json')
    report['evidenceAdmissionContract'] = 'FIXCL7-C7-cases.json#/cases/1'
    (OUT/'FIXCL7.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'counts':audit['counts'],'checks':checks,'usage':report['usage']}))

if __name__ == '__main__': main()
