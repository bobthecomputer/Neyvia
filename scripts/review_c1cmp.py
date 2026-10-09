"""Re-read the frozen comparison receipts and preserve compact artifact proof."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from c1_comparison_checker import check_fixture, load, ROOT
from run_c1_comparison import verify, DEFAULT


def prepare_lead_commands():
    python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe'
    for path in (ROOT / 'scripts/evidence/C1-claude-arm').glob('*.json'):
        task = load(path)
        task['executionEvidenceFields'] = {'fixtureToken': 'Exact prepared token', 'model': 'Actual Claude model and version',
            'startedUnixNs': 'Real task start', 'endedUnixNs': 'Real task finish', 'actions': 'Actual action count',
            'tokens': 'Provider usage or null with reason', 'cost': 'Actual billed cost or null with reason',
            'currency': 'Provider currency or null', 'metricsReason': 'Why unavailable metrics are null',
            'ownedDisposableTarget': 'Boolean with process and frame evidence', 'cleanupOnlyOwnedTarget': 'Boolean',
            'ownershipEvidence': 'Exact executable, process birth, HWND and frame evidence'}
        task['desktopAuthorization'] = 'Visible competition is authorized during this current run only; fixture files do not extend authorization'
        for fixture in task['attempts']:
            command = '& "' + python + '" "' + str(ROOT / 'scripts/record_c1cmp_provider.py') + '"'
            fixture['recordCommand'] = command + ' --fixture "' + fixture['manifest'] + '" --execution "' + str(Path(fixture['fixturePaths']['root']) / 'execution.json') + '"'
            fixture['watchCommand'] = fixture['checkerCommand'] + ' --watch'
            if task['id'] == 'charmap-compose':
                fixture['watchCommand'] = '& "' + python + '" "' + str(ROOT / 'scripts/c1cmp_visible_checker.py') + '" --fixture "' + fixture['manifest'] + '" --hwnd <owned HWND> --pid <new PID> --watch'
        path.write_text(json.dumps(task, indent=2) + '\n', encoding='utf-8')


def review():
    evidence = ROOT / 'scripts/evidence'
    path = evidence / 'C1CMP.json'
    result = load(path)
    preflight = verify(DEFAULT)
    errors = []
    rows = result['attempts']
    keys = [(r.get('series', 'baseline'), r['arm'], r['id'], r['repetition']) for r in rows]
    if len(keys) != len(set(keys)):
        errors.append('Duplicate frozen attempt identity')
    expected = {(t['id'], repetition) for t in load(DEFAULT)['tasks'] for repetition in range(1, 6)}
    for series, arms in (('baseline', ['neyvia']), ('repaired', ['neyvia', 'openai_computer_use', 'claude_computer_use']),
            ('paired', ['neyvia', 'openai_computer_use', 'claude_computer_use'])):
        for arm in arms:
            actual = {(r['id'], r['repetition']) for r in rows if r['arm'] == arm and r.get('series', 'baseline') == series}
            if actual != expected:
                errors.append(series + '/' + arm + ' does not contain the exact 75 frozen identities')
    frozen = load(DEFAULT)
    checker_sha = hashlib.sha256((ROOT / 'scripts/c1_comparison_checker.py').read_bytes()).hexdigest()
    saved_artifacts = []
    for row in rows:
        fixture = load(row['fixture'])
        task = next(t for t in frozen['tasks'] if t['id'] == row['id'])
        if fixture['instruction'] != task['instruction'] or fixture['phrases'] != frozen['fixtures']['phrases'] or fixture['timeBudgetSeconds'] != 60:
            errors.append('Frozen instruction/phrases/budget differs: ' + str(keys[rows.index(row)]))
        if fixture['postcondition'] != task['postcondition'] or fixture['freezeSha256'] != preflight['frozenPanelSha256']:
            errors.append('Frozen postcondition/hash differs: ' + row['fixture'])
        checked = check_fixture(fixture)
        if row['ok'] and (not checked['ok'] or not row.get('guard', {}).get('ok') or row.get('sourceDrift') or row['elapsedMs'] > 60000):
            errors.append('Accepted attempt failed independent reread/certification: ' + row['fixture'])
        if row['arm'] != 'neyvia' and row['ok'] and not row.get('executionSha256'):
            errors.append('Provider task success recorded despite no actual provider execution')
        row['reviewedChecker'] = checked
        row['comparisonEligibleSeries'] = row.get('series') == 'paired'
        if row.get('series') == 'paired' and row['arm'] == 'neyvia' and task['category'] != 'editor' and task['category'] != 'accessory' and task['id'] not in {'chrome-form', 'edge-form'}:
            seed = row.get('initialFixtureReadback', {})
            if not seed.get('nativeLoadedPairedSeed') or seed.get('value') != fixture['token'] or seed.get('initialSeedSha256') != seed.get('preparedSeedSha256'):
                errors.append('Initial native state not certified against exact paired seed: ' + row['fixture'])
        if row['ok']:
            folder = evidence / 'C1CMP-artifacts' / row.get('series', 'baseline') / row['id'] / ('rep-' + str(row['repetition']))
            for kind in ('input', 'artifact', 'observations'):
                source = fixture['fixturePaths'].get(kind)
                if source and Path(source).is_file():
                    source = Path(source)
                    folder.mkdir(parents=True, exist_ok=True)
                    destination = folder / (kind + source.suffix)
                    shutil.copyfile(source, destination)
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()
                    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                        errors.append('Artifact preservation hash mismatch')
                    saved_artifacts.append({'attempt': list((row.get('series', 'baseline'), row['id'], row['repetition'])),
                        'kind': kind, 'path': destination.relative_to(ROOT).as_posix(), 'sha256': digest})
    probe = load(evidence / 'C1-openai-probe/result.json')
    events = [json.loads(line) for line in (evidence / 'C1-openai-probe/stdout.jsonl').read_text(encoding='utf-8').splitlines()]
    calls = [e.get('item', {}) for e in events if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'mcp_tool_call']
    probe['confirmedImport'] = any(c.get('status') == 'completed' and 'C1_IMPORT_OK' in json.dumps(c.get('result')) for c in calls)
    probe['actualListAppsError'] = next((b.get('text') for c in calls if 'list_apps' in str(c.get('arguments'))
        for b in (c.get('result') or {}).get('content', []) if 'NODE_REPL_TRUSTED_SERVICES' in b.get('text', '')), None)
    probe['modelReason'] = 'Codex exec JSONL does not expose the CLI default model; no substitute or exact model identity claimed'
    sky_source = Path('C:/Users/user/AppData/Local/OpenAI/Codex/runtimes/cua_node/45309f9050f7314b/bin/node_modules/@oai/sky/dist/project/cua/sky_js/src/sky.js')
    probe['trustedServiceMechanism'] = {'source': str(sky_source), 'sha256': hashlib.sha256(sky_source.read_bytes()).hexdigest(),
        'observed': 'When nodeRepl exists, sky requires nodeRepl.rpc and calls its trusted sky service; standalone MCP exec did not receive that service',
        'policy': 'No helper executable, custom protocol, app-session capability or credentials were substituted'}
    pause = Path('C:/Users/user/Projects/plans/logs/window-guard.pause')
    if pause.exists():
        errors.append('OpenAI arm left window guard pause in place')
    result['openaiProbe'] = probe
    result['artifactProof'] = saved_artifacts
    result['review'] = {'ok': not errors, 'errors': errors, 'checkerSha256': checker_sha,
        'frozenPanelSha256': preflight['frozenPanelSha256'], 'rows': len(rows), 'pauseRemoved': not pause.exists(),
        'boundary': 'Failed baseline attempts retained; provider arms remain unavailable/pending and are not benchmark successes'}
    result['timingLimitations'] = 'Full task time includes failures. Historical baseline/repaired exception exits lack some atomic failed-step samples. Paired series captures phase exception timing, but native persistence is in full task time rather than atomic edit samples; no full atomic latency target is certified. Launch-to-actionable observation exceeds the 500 ms target.'
    result['historyLimitations'] = 'Baseline and repaired native setup created equivalent new documents instead of loading exact paired seeds; retain these as diagnostic history. Paired series loads and verifies the prepared seed bytes. PowerPoint seed overwrite failed twice; saving a new token-owned final output fixed later attempts. Source versions are recorded per attempt and never changed during an attempt.'
    result['neyviaRemaining'] = [{'id': r['id'], 'repetition': r['repetition'], 'error': r.get('error'),
        'checkerErrors': r.get('checker', {}).get('errors'), 'violations': r.get('guard', {}).get('violations')}
        for r in rows if r.get('series') == 'paired' and r['arm'] == 'neyvia' and not r['ok']]
    from verify_c1c_apps import percentile
    latest = [r for r in rows if r.get('series') == 'paired' and r['arm'] == 'neyvia']
    result['pairedNeyviaMetrics'] = {'passed': sum(r['ok'] for r in latest), 'attempts': len(latest),
        'taskP50Ms': percentile([r['elapsedMs'] for r in latest], .5), 'taskP95Ms': percentile([r['elapsedMs'] for r in latest], .95),
        'actions': sum(r['actions'] for r in latest), 'tokens': 0, 'cost': 0,
        'attributedForegroundChanges': sum(r.get('guard', {}).get('foreground_changes', 0) for r in latest),
        'attributedCursorMoves': sum(r.get('guard', {}).get('cursor_moves', 0) for r in latest),
        'ownedVisibleInputWindows': sum(r.get('guard', {}).get('new_visible_windows', 0) for r in latest),
        'zeroDisturbanceCertifiedAllAttempts': all(r.get('guard', {}).get('ok') for r in latest)}
    result['status'] = 'blocked_openai_runtime_and_pending_claude_lead'
    result['missing'] = ['OpenAI trusted Sky service unavailable through tested codex exec', 'Claude lead must execute prepared 75 fresh attempts']
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'review': result['review'], 'seriesSummary': result['seriesSummary']}))
    return not errors


if __name__ == '__main__':
    prepare_lead_commands()
    if '--handoff-only' in sys.argv:
        raise SystemExit(0)
    raise SystemExit(0 if review() else 1)
