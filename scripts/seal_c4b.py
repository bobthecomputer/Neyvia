"""Seal a bounded paired C4b panel, retaining raw provider events and failures."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.provider11 import usage_counts
from seal_c4 import summary, sum_tokens, price

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel', required=True)
    parser.add_argument('--append-ledger', action='store_true')
    parser.add_argument('--attempts', nargs='*', default=[])
    parser.add_argument('--t7-repair', help='Fresh paired continuation after independent arithmetic rejection')
    parser.add_argument('--t1-repair', help='Fresh paired continuation after the multiline parser repair')
    args = parser.parse_args()
    if Path(args.panel).name != args.panel or args.panel in {'.','..'}:
        raise ValueError('One panel folder name required')
    panel = REPO / '.agent_control/c4' / args.panel
    tasks = read(Path('C:/Users/user/Projects/nx-r4-blind/proof/r4-blind-20261004/tasks.json'))
    rows = []
    repair = None
    if args.t7_repair:
        if Path(args.t7_repair).name != args.t7_repair or args.t7_repair in {'.','..',args.panel}:
            raise ValueError('One distinct repair folder name required')
        repair = REPO / '.agent_control/c4' / args.t7_repair
    ui_repair = None
    if args.t1_repair:
        if Path(args.t1_repair).name != args.t1_repair or args.t1_repair in {'.','..',args.panel,args.t7_repair}:
            raise ValueError('One distinct UI repair folder name required')
        ui_repair = REPO / '.agent_control/c4' / args.t1_repair
    for task in tasks:
        for arm in ('efficient','control'):
            selected_panel = repair if repair and task['id']=='t7-explain' else ui_repair if ui_repair and task['id']=='t1-ui' else panel
            path = selected_panel / arm / task['id'] / 'result.json'
            if selected_panel != panel:
                if read(path)['taskSha256'] != read(panel / arm / task['id'] / 'result.json')['taskSha256']:
                    raise ValueError('Repair changed the task')
            row = summary(path)
            for name, expected in row['sourceSha256'].items():
                if digest(REPO / name) != expected:
                    bound = REPO / 'scripts/evidence/C4b/sources' / (expected + Path(name).suffix)
                    if name not in {'src/grant_agent/cl/host.py','src/grant_agent/cl/efficient_runner.py'} or not bound.is_file() or digest(bound) != expected:
                        raise ValueError('Source changed after run without exact preserved bytes: ' + name)
                    row.setdefault('archivedSource',{})[name] = bound.relative_to(REPO).as_posix()
            for provider_path in sorted((path.parent / 'run').glob('turn-*/receipt.json')):
                provider = read(provider_path)
                if provider['requestedModel'] != 'gpt-6-luna' or provider['effort'] != 'medium':
                    raise ValueError('Model/effort route drift')
                if provider.get('passed') and (provider.get('errors') or not provider.get('instructionOverrideApplied')):
                    raise ValueError('Invalid provider acceptance')
            rows.append(row)
    from c4_quality import check
    for row in rows:
        if row['task'] == 't7-explain':
            recheck = check(row['task'],REPO / Path(row['receipt']).parent / 'workspace')
            row['independentRecheck'] = recheck
            row['accepted'] = row['accepted'] and recheck['passed']
    # Previous attempts remain adverse evidence, including incomplete processes.
    # Sum only usage actually reported by the provider, never impute missing turns.
    attempts = []
    roots = [panel] + ([repair] if repair else []) + ([ui_repair] if ui_repair else [])
    for name in args.attempts:
        if Path(name).name != name or name in {'.','..',args.panel}:
            raise ValueError('Distinct attempt folder names required')
        previous = REPO / '.agent_control/c4' / name
        if not previous.is_dir(): raise ValueError('Missing attempt: '+name)
        roots.append(previous)
        reported = []
        incomplete = []
        for path in sorted(previous.glob('*/*/run/turn-*/events.jsonl')):
            events = []
            for line in path.read_text(encoding='utf-8').splitlines():
                try: events.append(json.loads(line))
                except ValueError: continue
            completed = [event['usage'] for event in events if event.get('type')=='turn.completed']
            if completed: reported.append(usage_counts(completed[-1]))
            else: incomplete.append(path.relative_to(previous).as_posix())
        attempts.append({'panel':name,'observedTokens':sum_tokens(reported),'incompleteInvocations':incomplete,
                         'usageScope':'Actual completed events only; interrupted usage is an observed lower bound'})
    all_reported=[]
    for selected in roots:
        for path in selected.glob('*/*/run/turn-*/events.jsonl'):
            completed=[]
            for line in path.read_text(encoding='utf-8').splitlines():
                try: event=json.loads(line)
                except ValueError: continue
                if event.get('type')=='turn.completed': completed.append(event['usage'])
            if completed: all_reported.append(usage_counts(completed[-1]))
    all_observed = sum_tokens(all_reported)
    arms = {}
    for arm in ('efficient','control'):
        selected = [row for row in rows if row['arm'] == arm]
        tokens = sum_tokens([row['tokens'] for row in selected])
        arms[arm] = {'tokens':tokens,'costUsd':price(tokens),
                     'accepted':sum(row['accepted'] for row in selected),
                     'turns':sum(row['turns'] for row in selected)}
    matched_tasks = [task['id'] for task in tasks if all(
        row['accepted'] for row in rows if row['task'] == task['id'])]
    matched = {}
    for arm in arms:
        tokens = sum_tokens([row['tokens'] for row in rows if row['arm'] == arm and row['task'] in matched_tasks])
        matched[arm] = {'tokens':tokens,'costUsd':price(tokens)}
    def reduction(field):
        left,right = matched['efficient'],matched['control']
        a,b = (left['costUsd'],right['costUsd']) if field == 'cost' else (left['tokens'][field],right['tokens'][field])
        return 100*(1-a/b) if b else None
    evidence = REPO / 'scripts/evidence/C4b'
    evidence.mkdir(parents=True,exist_ok=True)
    archive = evidence / (args.panel + '.zip')
    if archive.exists():
        raise FileExistsError('Archive is immutable; choose a new panel')
    files = [(selected,path) for selected in roots for path in sorted(selected.rglob('*')) if path.is_file() and
             not any(part in {'.neyvia','.agent_control','__pycache__'} for part in path.relative_to(selected).parts)]
    size = sum(path.stat().st_size for _,path in files)
    if size > 64*1024*1024:
        raise ValueError('Panel exceeds 64 MiB raw-evidence bound; do not create a large archive')
    manifest = []
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for selected,path in files:
            name = selected.name+'/'+path.relative_to(selected).as_posix()
            bundle.write(path,name)
            manifest.append({'path':name,'bytes':path.stat().st_size,'sha256':digest(path)})
    (evidence / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    (evidence / 'rows.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    host = read(REPO / 'scripts/evidence/C4-host.json')
    production = read(REPO / 'scripts/evidence/C4-production.json')
    native = read(REPO / 'scripts/evidence/C4-native.json')
    budget_ok = all(all(n <= 8000 for n in row['hostPromptTokens']) for row in rows if row['arm']=='efficient')
    limits = [
        'One trial per task and arm; no population gain or blind aesthetic quality claim.',
        'Both arms share procedures and batching; comparison isolates diff observations and host context compaction.',
        '8000-token cap covers exact host text, not hidden CLI system context or reasoning.',
        'Native task requires an existing owner-granted Character Map window; absence is a blocker, not success.',
        'Quality checks cover task constraints; subjective prose, teaching and design quality need independent preference review.',
        'CL model projection filters reserved transport identifiers; lossless diffs apply to that projection, while raw receipts retain source data.',
        'Costs are recorded list-price equivalents, not subscription invoices.',
        'Interrupted historical panels are not silently repaired, counted as fresh runs, or sealed as complete.',
        'Earlier free-form t7 control incurred extra turns from a false negative in the prefix-language checker. The final typed panel uses the corrected checker for both arms; earlier tokens remain adverse overhead.',
        'No public deployment, default chat change, push, merge or NAS operation.'
        ,'First typed t1/t7 pairs precede the scratch-only impact-index bypass; exact earlier host bytes are preserved, and each run carries its actual source hashes. Later pairs use the bypass in both arms.'
    ]
    sources = ['src/grant_agent/cl/'+name for name in ('efficient_runner.py','host.py','parser.py','turn_context.py','benchmark_provider.py','protocol.py','integration.py')]
    sources += ['scripts/'+name for name in ('verify_c4.py','verify_c4_host.py','verify_c4_production.py','verify_c4_native.py','verify_c4_browse.py','verify_c4_ui.cjs','c4_quality.py','run_c4_cohort.py','seal_c4b.py')]
    receipt = {'schema':'neyvia.c4b-evidence.v1','panel':args.panel,'model':'gpt-6-luna','effort':'medium',
        'mechanismVerified':host['ok'] and production['passed'] and budget_ok,
        'allTasksAccepted':all(row['accepted'] for row in rows),'rows':rows,'arms':arms,
        'matchedAcceptedTasks':matched_tasks,'matchedAccepted':matched,
        'matchedTotalReductionPercent':reduction('total'),'matchedCachedReductionPercent':reduction('cachedInput'),
        'matchedCostReductionPercent':reduction('cost'),'hostBudgetVerified':budget_ok,
        'earlierAttempts':attempts,'earlierAttemptObservedTokens':sum_tokens([row['observedTokens'] for row in attempts]),
        'pairedArithmeticContinuation':args.t7_repair,
        'pairedUIContinuation':args.t1_repair,
        'allRecoveryObservedTokens':all_observed,'allRecoveryObservedCostUsd':price(all_observed),
        'comparisonScope':'Latest reviewed paired continuations; all earlier, rejected and interrupted invocation costs reported separately and archived',
        'nativePreflight':{'targetPresent':native['targetPresent'],'blocker':native['blocker']},
        'sourceSha256':{name:digest(REPO / name) for name in sources},
        'proofReceipts':{name:digest(REPO / 'scripts/evidence' / name) for name in ('C4-host.json','C4-production.json','C4-native.json')},
        'archive':{'path':archive.relative_to(REPO).as_posix(),'sha256':digest(archive),'rawBytes':size,'compressedBytes':archive.stat().st_size,'files':len(files)},
        'limits':limits,'plan15C4bPresent':False,'acceptanceBasis':'Plan20 C4 and explicit C4b user scope'}
    target = REPO / 'scripts/evidence/C4b.json'
    target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.append_ledger:
        from efficiency_log import validate,ledger_lock
        rawpath = evidence / 'rows.json'
        spec = {'schema':'neyvia.efficiency-result.v1','id':'C4b-'+args.panel,'study':'C4b recovered bounded Luna CL on R4',
            'evidence_status':'raw-verified','method':'Paired actual production-gateway runs with identical fixtures, goals, exact Luna route, medium effort and independent acceptance; failures retained.',
            'models':['gpt-6-luna via Codex CLI, medium effort'],
            'tasks':{'description':'Eight R4 tasks, including native refusal if target absent','repetitions':1,'independent_unit':'task'},
            'receipts':[{'id':'runs','path':rawpath.relative_to(REPO).as_posix(),'sha256':digest(rawpath),'kind':'raw'}],
            'metrics':[],'limitations':limits}
        for arm in arms:
            for field,unit in (('/tokens/total','tokens'),('/tokens/cachedInput','tokens'),('/costUsd','USD equivalent'),('/accepted','count')):
                spec['metrics'].append({'name':arm+'_'+field.rsplit('/',1)[-1],'unit':unit,
                    'calculation':{'op':'sum','args':[{'receipt':'runs','where':{'/arm':arm},'field':field}]},
                    'ci_request':{'method':'not-estimable','reason':'One trial per fixed task; no population inference'}})
        validate(spec,prepare=True)
        ledger = REPO / 'docs/research/results.jsonl'
        with ledger_lock(ledger):
            before = ledger.read_bytes()
            if any(json.loads(line)['id']==spec['id'] for line in before.decode('utf-8').splitlines()):
                raise ValueError('Ledger ID already exists')
            with ledger.open('ab') as stream:
                stream.write((('' if before.endswith(b'\n') else '\n')+json.dumps(spec,ensure_ascii=False)+'\n').encode('utf-8'))
            if not ledger.read_bytes().startswith(before): raise ValueError('Prior ledger rows changed')
        validate(spec)
    print(json.dumps({'mechanismVerified':receipt['mechanismVerified'],'allTasksAccepted':receipt['allTasksAccepted'],
                     'arms':arms,'matchedTotalReductionPercent':receipt['matchedTotalReductionPercent'],
                     'archiveBytes':archive.stat().st_size}),flush=True)

if __name__ == '__main__':
    main()
