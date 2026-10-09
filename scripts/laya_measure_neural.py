"""Measure actual frozen LAYA over learned candidates and separate few-shot taste."""
import json
import os
from pathlib import Path
import sys
import time
import hashlib
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train')
sys.path.insert(0, str(ROOT / 'src'))
os.environ['NEYVIA_LAYA_URL'] = 'http://127.0.0.1:48994'
from grant_agent.laya_curriculum import route
from grant_agent.laya_components import feel


def main():
    history = RUN / 'neural-history'
    history.mkdir(parents=True, exist_ok=True)
    for old in (RUN / 'neural-routing.json', ROOT / 'scripts/evidence/LAYAT-neural-metrics.json'):
        if old.exists():
            content = old.read_bytes()
            saved = history / (old.stem + '-' + hashlib.sha256(content).hexdigest()[:12] + '.json')
            if not saved.exists():
                saved.write_bytes(content)
    artifact = ROOT / 'tools/laya/capabilities/manual-router.json'
    fingerprint = hashlib.sha256(artifact.read_bytes()).hexdigest()
    layers = json.loads(artifact.read_bytes())['layers']
    benchmark = json.loads((ROOT / 'config/cl_benchmark_1.1_tasks.json').read_text())['tasks']
    rows = [{'id':r['id'], 'text':r['text'], 'layer':r['layer'], 'area':'benchmark'} for r in benchmark if r.get('layer') in layers]
    rows += [{'id':r['id'], 'text':r['text'], 'layer':r['label'], 'area':'real-panel'}
             for r in json.loads((RUN / 'manual-real-cases.json').read_text())]
    results = []
    cache = {}
    for row in rows:
        if not row.get('layer') or not row.get('text'):
            continue
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != fingerprint:
            raise RuntimeError('Routing artifact changed during the evaluation')
        repeated = row['text'] in cache
        value = cache.get(row['text']) or route(row['text'], consult_laya=True, timeout_s=90)
        if value.get('reason') == 'manuals-changed-refit-required':
            raise RuntimeError('Manuals changed; refit before a neural evaluation')
        cache[row['text']] = value
        results.append({'id': row['id'], 'truth': row['layer'], 'area':row['area'], 'repeatedPrompt':repeated, 'prediction': value})
        (RUN / 'neural-routing.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(row['id'], value['candidate'], value.get('modelSelection', {}).get('available'), flush=True)
    page = (RUN / 'invented/rehearsal-shelf.html').read_text(encoding='utf-8')
    result = feel(code=page, intent='A calm useful decision preview with plain specific writing, motion and real themes', consult_laya=True)
    (RUN / 'personal-fewshot.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    summary = {'cases': len(results), 'accuracy': sum(r['truth'] == r['prediction']['candidate'] for r in results)/len(results),
               'answerRate': sum(not r['prediction']['escalate'] for r in results)/len(results),
               'actualNeuralCalls': sum(r['prediction'].get('modelSelection', {}).get('available') is True and not r['repeatedPrompt'] for r in results),
               'artifactSha256':fingerprint,
               'areas': {area:{'cases':len(selected), 'accuracy':sum(r['truth']==r['prediction']['candidate'] for r in selected)/len(selected),
                              'answerRate':0, 'uniquePrompts':sum(not r['repeatedPrompt'] for r in selected)}
                         for area in ('benchmark','real-panel') if (selected := [r for r in results if r['area']==area])},
               'personalFewShotAvailable': result['personal'].get('fewShotDecision', {}).get('available'),
               'scope': 'Training-unseen exploratory replay. Architecture revised after earlier panel observations; not a pristine validation panel. No calibration admission.'}
    (ROOT / 'scripts/evidence/LAYAT-neural-metrics.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    from grant_agent.laya_host import LayaHost, load_config
    root = ROOT / '.agent_control/laya-train-runtime/neural-host'
    host = LayaHost(root, {**load_config(root), 'port': 48994, 'device': 'cpu'}).start()
    try:
        deadline = time.monotonic() + 240
        while not host.ready() and time.monotonic() < deadline:
            if host.state in {'unavailable', 'disabled'}:
                raise RuntimeError(host.reason)
            time.sleep(1)
        if not host.ready():
            raise RuntimeError('Owned neural evaluation service did not become ready')
        main()
    finally:
        host.stop()
        shutil.copytree(root, RUN / 'neural-host-checkpoint', dirs_exist_ok=True)
