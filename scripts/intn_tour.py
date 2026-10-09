"""Tour all existing apps through their real controls in hidden Obscura."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(r'D:\NeyviaRuns\tour')
THEMES = ('dark', 'light', 'sunset', 'night')


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--engine', type=Path, required=True, help='Explicit admitted Obscura executable; no fallback')
    parser.add_argument('--ports', required=True, help='Explicit backend,engine pair per worker, in 48871-48889')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=1)
    parser.add_argument('--local-small-state', action='store_true')
    args = parser.parse_args()
    if not args.label.replace('-', '').isalnum(): parser.error('Invalid label')
    ports = [int(value) for value in args.ports.split(',')]
    if len(ports) != args.workers * 2 or len(set(ports)) != len(ports) or any(not 48871 <= port <= 48889 for port in ports):
        parser.error('Assign two distinct ports in 48871-48889 per worker')
    engine = args.engine.resolve()
    if not engine.is_file() or not (args.build_dir / 'index.html').is_file():
        parser.error('An existing admitted engine and built index.html are required')
    build = args.build_dir.resolve()
    manifest = build / '.neyvia-build-receipt.json'
    if not manifest.is_file():
        parser.error('Build lacks its source-bound .neyvia-build-receipt.json; run intn_check_merge.py first')
    build_proof = json.loads(manifest.read_text(encoding='utf-8'))
    if build_proof.get('schema') != 'neyvia.intn.frontend-build.v1' or build_proof.get('ok') is not True:
        parser.error('Build receipt is not a successful admitted frontend build')
    from intn_check_merge import frontend_sources
    if build_proof.get('sourceHashes') != frontend_sources():
        parser.error('Frontend sources differ from the supplied build receipt')
    actual_artifacts = {p.relative_to(build).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(build.rglob('*')) if p.is_file() and p != manifest}
    if not actual_artifacts or build_proof.get('artifactHashes') != actual_artifacts:
        parser.error('Built artifact bytes differ from the build receipt')
    folder = OUT / args.label
    folder.mkdir(parents=True, exist_ok=True)
    from placement_shots import APPS, REGISTRY_APPS
    sources = [p for p in (ROOT / 'web/src/neyvia').rglob('*') if p.is_file() and p.suffix in ('.js', '.jsx', '.ts', '.tsx', '.css')]
    sources += [p for folder in ('src/grant_agent', 'manuals', 'config') for p in (ROOT / folder).rglob('*')
                if p.is_file() and p.suffix in ('.py', '.cl', '.json')]
    sources += [ROOT / 'scripts' / name for name in ('intn_tour.py','placement_shots.py','placement_journeys.py')]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {'schema':'neyvia.intn.tour.v1', 'started':time.time(), 'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'apps':[row[0] for row in APPS], 'registry':REGISTRY_APPS, 'themes':list(THEMES),
              'workers':args.workers, 'ports':ports,
              'engine':str(engine), 'engineSha256':hashlib.sha256(engine.read_bytes()).hexdigest(),
              'build':str(build), 'buildReceipt':str(manifest),
              'buildReceiptSha256':hashlib.sha256(manifest.read_bytes()).hexdigest(), 'sourceHashes':hashes, 'runs':[]}
    # Each worker owns one port pair and executes its theme jobs sequentially.
    # This prevents a completed theme from racing another theme for the same listener.
    def tour(worker, theme):
        pair = ','.join(map(str, ports[worker * 2:worker * 2 + 2]))
        env = {**os.environ, 'NEYVIA_PLACEMENT_PORTS':pair, 'NEYVIA_OBSCURA_EXE':str(engine), 'NEYVIA_MOBILE_PROBE_DEVICES':'0'}
        target = folder / theme
        target.mkdir(exist_ok=True)
        tag = args.label + '-' + theme
        command = [sys.executable, str(ROOT / 'scripts/placement_shots.py'), '--ports',pair,
            '--tag',tag,'--theme',theme,'--output',str(target),'--scratch',str(folder / 'state'),
            '--build-dir',str(args.build_dir.resolve())]
        if args.local_small_state:
            command.append('--local-small-state')
        started = time.time()
        with (target / 'tour.log').open('wb') as stream:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        receipt = target / ('receipt-' + tag + '.json')
        value = json.loads(receipt.read_text()) if receipt.exists() else {}
        expected = {(app, viewport, place) for app in report['apps'] for viewport, places in
                    [('desktop', ['main','side','side-floating','full','bubble','bubble-peek']),
                     ('phone', ['main','side','full','bubble','bubble-peek'])] for place in places}
        observed = {(s['app'],s['viewport'],s['placement']) for s in value.get('shots',[])
                    if (target / s['file']).is_file()}
        missing = sorted(expected - observed)
        row = {'theme':theme, 'exitCode':result.returncode, 'ok':value.get('ok') is True,
               'receipt':str(receipt), 'checks':len(value.get('checks',[])), 'shots':len(value.get('shots',[])),
               'missingCoverage':missing, 'errors':value.get('errors',[]), 'failure':value.get('failure'), 'seconds':round(time.time()-started,2)}
        return row

    def worker_run(worker):
        return [tour(worker, theme) for i,theme in enumerate(THEMES) if i % args.workers == worker]

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = [executor.submit(worker_run, worker) for worker in range(args.workers)]
        for job in as_completed(jobs):
            for row in job.result():
                report['runs'].append(row)
                save(folder / 'receipt.json', report)
                print(json.dumps(row), flush=True)
    report['sourceChangedDuringRun'] = [name for name,digest in hashes.items() if not (ROOT/name).is_file() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    report['frontendSourcesChangedDuringRun'] = build_proof.get('sourceHashes') != frontend_sources()
    report['buildChangedDuringRun'] = any(not (build/name).is_file() or hashlib.sha256((build/name).read_bytes()).hexdigest()!=digest for name,digest in actual_artifacts.items())
    report['engineChangedDuringRun'] = hashlib.sha256(engine.read_bytes()).hexdigest()!=report['engineSha256']
    report['ok'] = len(report['runs'])==4 and all(r['ok'] and not r['errors'] and not r['missingCoverage'] for r in report['runs']) and not report['sourceChangedDuringRun'] and not report['frontendSourcesChangedDuringRun'] and not report['buildChangedDuringRun'] and not report['engineChangedDuringRun']
    report['finished'] = time.time()
    save(folder / 'receipt.json', report)
    cards = []
    for theme in THEMES:
        for shot in sorted((folder/theme).glob('*.png')):
            path = theme + '/' + shot.name
            cards.append('<figure><a href="'+html.escape(path,quote=True)+'"><img loading="lazy" src="'+html.escape(path,quote=True)+'"></a><figcaption>'+html.escape(theme+' / '+shot.stem)+'</figcaption></figure>')
    (folder/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Neyvia release tour</title><style>body{background:#102118;color:#f7faf6;font:15px system-ui;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}figure{margin:0}img{width:100%;height:230px;object-fit:contain;background:#19291f}figcaption{padding:8px}a{color:inherit}</style><h1>Neyvia release tour</h1><p>'+str(len(APPS))+' requested apps, four themes, desktop and phone placements. Gate: '+('PASS' if report['ok'] else 'FAIL')+'. <a href="receipt.json">Exact coverage, registry status and source receipts</a></p><main>'+''.join(cards)+'</main>',encoding='utf-8')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
