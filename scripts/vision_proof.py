"""Plan 24 proof: recompute every number Paul looks at from the run artifacts, then evaluate the
CL checks in manuals/cl/laya-vision.cl over it (CL owns acceptance).

  * model-look rate per window (UI stream and 3D render run) and whether it falls;
  * per-type recall on the FINAL held-out groups, recomputed now: baseline eyes vs adopted lenses;
  * the lens list (registry) with provenance, pinned code and the decision receipt of each lens;
  * held-out grouping (fit / check / final surface groups never overlap);
  * self-made practice (Obscura UI injections, Blender renders) and its region-level counts;
  * every model look capped, logged with tokens, and written as an episode.

Usage: python scripts/vision_proof.py [--stream D:/NeyviaRuns/VISION/stream-1] [--render D:/NeyviaRuns/VISION/render-1]
Writes scripts/evidence/VISION-proof.json (+ VISION-curves.png).
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
EVIDENCE = ROOT / 'scripts/evidence'


def thirds(values):
    n = len(values)
    if n < 3:
        return None, None
    k = max(1, n // 3)
    return round(sum(values[:k]) / k, 3), round(sum(values[-k:]) / k, 3)


def calls(path):
    rows = [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines()] if Path(path).exists() else []
    out = {}
    for kind in ('look', 'author'):
        part = [r for r in rows if r['kind'] == kind]
        done = [r for r in part if r['status'] == 'completed']
        out[kind] = {'calls': len(part), 'completed': len(done), 'failed': len(part) - len(done),
                     'tokens': sum((r.get('tokens') or {}).get('total', 0) for r in done),
                     'medianMs': sorted(r['ms'] for r in done)[len(done) // 2] if done else None,
                     'models': sorted({r['model'] for r in part})}
    return out


def look_episodes(run, domain):
    from grant_agent.laya_instant import store, latest_episodes
    local = store(str(run))
    local.refresh()
    rows = [r for r in latest_episodes(local.rows) if r['domain'] == domain]
    shas = {Path(r['input']['image']).stem for r in rows}  # frozen copies are named by their sha256
    return len(rows), sum(1 for r in local.rows if r['domain'].startswith('scene:ui-node:') and str(r['source']).startswith('model-look:')), shas


def stream_section(run, baseline=None):
    state = json.loads((run / 'state.json').read_text(encoding='utf-8'))
    from vision_stream import window_stats
    windows = window_stats(state['records'], state.get('window') or 45)
    rates = [w['lookRate'] for w in windows if w['images'] >= 10]
    first, last = thirds(rates)
    recs = state['records']
    by = Counter(r['by'] for r in recs)
    look_recs = [r for r in recs if r['by'] == 'look' and r.get('typeAgreement') is not None]
    answered = [r for r in recs if r.get('verdictCorrect') is not None]
    final_answered = [r for r in answered if r['split'] == 'final']
    episodes, lessons, episode_shas = look_episodes(run, 'ui-look' if 'stream' in run.name else 'render-look')
    import hashlib as _h
    look_shas = {_h.sha256(Path(r['image']).read_bytes()).hexdigest() for r in recs if r['by'] == 'look'}
    c = calls(run / 'model-calls.jsonl')
    events = [e for e in state['events'] if e['event'] != 'calibrate']
    return {'run': str(run), 'images': len(recs), 'window': state.get('window'), 'windows': windows, 'lookRates': rates,
            'lookRateFirstThird': first, 'lookRateLastThird': last, 'lookRateFalls': first is not None and last < first,
            'answeredBy': dict(by), 'verdictAccuracy': round(sum(r['verdictCorrect'] for r in answered) / len(answered), 4) if answered else None,
            'finalGroupVerdictAccuracy': round(sum(r['verdictCorrect'] for r in final_answered) / len(final_answered), 4) if final_answered else None,
            'lookTypeAgreementWithLabels': round(sum(r['typeAgreement'] for r in look_recs) / len(look_recs), 4) if look_recs else None,
            'lookVerdictAccuracy': round(sum(r['verdictCorrect'] for r in look_recs if r['verdictCorrect'] is not None) /
                                         max(1, sum(1 for r in look_recs if r['verdictCorrect'] is not None)), 4) if look_recs else None,
            'modelCalls': c, 'lookEpisodes': episodes, 'lookNodeLessons': lessons,
            'lookScreenshots': len(look_shas), 'lookScreenshotsWithoutEpisode': len(look_shas - episode_shas),
            # Answers given locally where a lesson written from an earlier model look changed the glance
            # (the run's store holds no other lessons): the next similar case answered without a look.
            'localAnswersUsingLookLessons': sum(1 for r in recs if r['by'] == 'lenses' and r.get('lessons')),
            'memoryAnswers': by.get('memory', 0),
            'memoryRadius': state.get('radius'), 'events': events,
            **(baseline_section(baseline, state, windows) if baseline else {})}


def baseline_section(baseline, state, windows):
    """The same arrival order with frozen eyes (no looks, no lenses, no lessons): how many screenshots
    would have needed a model look. Looks avoided = frozen escalations - actual looks, per window."""
    from vision_stream import window_stats
    frozen = json.loads((Path(baseline) / 'state.json').read_text(encoding='utf-8'))
    size = state.get('window') or 45
    fw = window_stats(frozen['records'], size)
    rows = []
    for w, f in zip(windows, fw):
        rows.append({'window': w['window'], 'images': w['images'], 'frozenEscalations': f['unanswered'], 'looks': w['look'],
                     'memory': w['memory'], 'avoided': f['unanswered'] - w['look']})
    first, last = thirds([r['avoided'] / max(r['frozenEscalations'], 1) for r in rows])
    return {'frozenBaseline': str(baseline), 'perWindowVsFrozen': rows, 'frozenEscalationsTotal': sum(r['frozenEscalations'] for r in rows),
            'looksTotal': sum(r['looks'] for r in rows), 'avoidedShareFirstThird': first, 'avoidedShareLastThird': last}


def lens_section(registry_path):
    from grant_agent.scene_core.lenses import load, entries, validate_source
    os.environ['NEYVIA_LAYA_LENSES'] = str(registry_path)
    reg = load(registry_path)
    out = []
    for e in entries(registry_path):
        row = {'id': e['id'], 'inputType': e['inputType'], 'status': e['status'], 'builtin': bool(e.get('builtin')),
               'emits': sorted(e['emits']), 'predicates': e.get('predicates', []),
               'author': (e.get('provenance') or {}).get('author'), 'at': (e.get('provenance') or {}).get('at')}
        if not e.get('builtin'):
            path = Path(e['program']); path = path if path.is_absolute() else ROOT / path
            source = path.read_text(encoding='utf-8') if path.exists() else ''
            pinned = hashlib.sha256(source.encode('utf-8')).hexdigest() == e['programSha256']
            try:
                validate_source(source); valid = True
            except Exception:
                valid = False
            receipt = Path((e.get('decision') or {}).get('receipt') or '')
            row.update(program=e['program'], pinned=pinned, sandboxValid=valid, branch=e.get('branch'),
                       authorReceipt=(e.get('provenance') or {}).get('receipt'), decisionReceipt=str(receipt),
                       decisionReceiptExists=receipt.is_file(), decision=e.get('decision'), cost=e.get('cost'))
        out.append(row)
    return out


def recall_section(lens_entries):
    from vision_lens_eval import labelled_rows, evaluate
    rows = labelled_rows()
    groups = {s: sorted({r['group'] for r in rows if r['split'] == s}) for s in ('fit', 'check', 'final')}
    overlap = set(groups['fit']) & set(groups['check']) | set(groups['fit']) & set(groups['final']) | set(groups['check']) & set(groups['final'])
    before = evaluate([], rows)
    after = evaluate(lens_entries, rows)
    per = {}
    for split in ('check', 'final'):
        per[split] = {t: {'before': {k: before['splits'][split]['types'][t][k] for k in ('precision', 'recall', 'positives')},
                          'after': {k: after['splits'][split]['types'][t][k] for k in ('precision', 'recall', 'positives')}}
                      for t in before['splits'][split]['types']}
    by_group = {}
    for r in after['rows']:
        if r['split'] != 'final':
            continue
        g = by_group.setdefault(r['group'], Counter())
        for t, y in r['labels'].items():
            if y:
                g['positives'] += 1
                g['hits'] += int(t in r['fired'])
    return {'groups': groups, 'groupOverlap': sorted(overlap), 'perType': per,
            'finalRecallByGroup': {g: round(c['hits'] / c['positives'], 3) if c['positives'] else None for g, c in sorted(by_group.items())},
            'lenses': [e['id'] for e in lens_entries], 'cost': after['cost']}


def curves_png(sections, path):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    W, H, pad = 900, 360, 50
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((pad, 10), 'Model-look rate per window (falls as lenses, memory and practice take over)', fill=(20, 20, 20))
    d.line((pad, H - pad, W - pad, H - pad), fill=(120, 120, 120)); d.line((pad, pad, pad, H - pad), fill=(120, 120, 120))
    colors = [(30, 110, 200), (220, 110, 30)]
    for i, (name, rates) in enumerate(sections):
        if not rates:
            continue
        xs = [pad + (W - 2 * pad) * j / max(1, len(rates) - 1) for j in range(len(rates))]
        ys = [H - pad - (H - 2 * pad) * min(1.0, r) for r in rates]
        d.line(list(zip(xs, ys)), fill=colors[i], width=3)
        for x, y, r in zip(xs, ys, rates):
            d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=colors[i]); d.text((x - 8, y - 16), f'{r:.2f}', fill=colors[i])
        d.text((W - pad - 220, pad + 16 * i), name, fill=colors[i])
    for v in (0, 0.5, 1.0):
        y = H - pad - (H - 2 * pad) * v
        d.text((8, y - 6), f'{v:.1f}', fill=(90, 90, 90))
    im.save(path)
    return str(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--streams', nargs='+', default=['D:/NeyviaRuns/VISION/stream-1', 'D:/NeyviaRuns/VISION/stream-2'],
                    help='UI streams; the LAST is the primary (corrected) run')
    ap.add_argument('--renders', nargs='+', default=['D:/NeyviaRuns/VISION/render-1', 'D:/NeyviaRuns/VISION/render-2',
                                                     'D:/NeyviaRuns/VISION/render-3'], help='3D render runs in time order')
    ap.add_argument('--frozen', default='D:/NeyviaRuns/VISION/dry0', help='same order, frozen eyes, no looks')
    ap.add_argument('--practice', default='D:/NeyviaRuns/VISION/practice/practice.json')
    ap.add_argument('--registry', default=str(ROOT / 'config/laya_lenses.json'))
    a = ap.parse_args()
    proof = {'schema': 'neyvia.laya.vision-proof.v1', 'training': False, 'paidCalls': 0, 'modelRoute': 'codex exec gpt-6-luna (subscription)'}
    streams = [stream_section(Path(r), a.frozen) for r in a.streams if (Path(r) / 'state.json').exists()]
    renders = [stream_section(Path(r)) for r in a.renders if (Path(r) / 'state.json').exists()]
    stream = streams[-1]
    proof['streams'] = streams
    proof['renders'] = renders
    proof['lenses'] = lens_section(Path(a.registry))
    from grant_agent.scene_core.lenses import load
    active_ui = [e for e in load(Path(a.registry))['lenses'] if e['status'] == 'active' and e['inputType'] == 'screenshot']
    proof['recall'] = recall_section(active_ui)
    practice = json.loads(Path(a.practice).read_text(encoding='utf-8'))
    proof['practice'] = {'episodes': len(practice['episodes']), 'bases': len(practice['bases']),
                         'byType': dict(Counter(e['type'] for e in practice['episodes'])),
                         'revertFailures': sum(1 for f in practice['failures'] if 'survived' in str(f.get('error', ''))),
                         'failures': len(practice['failures']), 'engineSha256': practice['engineSha256'], 'build': practice['build']}
    try:
        from vision_practice import region_counts
        proof['practice']['regionCountsBaseline'] = region_counts(practice, [])
        proof['practice']['regionCountsWithLenses'] = region_counts(practice, active_ui)
    except Exception as exc:
        proof['practice']['regionCountsError'] = f'{type(exc).__name__}: {exc}'
    batches = sorted(Path('D:/NeyviaRuns/VISION').glob('render-*/renders.json'))
    all_renders = [r for b in batches for r in json.loads(b.read_text(encoding='utf-8'))['renders']]
    proof['renderPractice'] = {'batches': [str(b) for b in batches], 'renders': len(all_renders),
                               'subjects': len({r['subject'] for r in all_renders}),
                               'byCondition': dict(Counter(r['condition'] for r in all_renders))}
    render_rates = [x for r in renders for x in r['lookRates']]
    f3, l3 = thirds(render_rates)
    proof['render3dLookRates'] = render_rates
    ui_kept = [l for l in proof['lenses'] if not l['builtin'] and l['inputType'] == 'screenshot' and l['status'] == 'active']
    r_kept = [l for l in proof['lenses'] if not l['builtin'] and l['inputType'] == 'render' and l['status'] == 'active']
    program = [l for l in proof['lenses'] if not l['builtin']]
    fin = proof['recall']['perType']['final']
    runs = streams + renders
    proof['flat'] = {
        'uiLooks': stream['modelCalls']['look']['completed'], 'renderLooks': sum(r['modelCalls']['look']['completed'] for r in renders),
        'maxLooksPerRun': max(r['modelCalls']['look']['calls'] for r in runs),
        'uiLookEpisodesMissing': sum(r['lookScreenshotsWithoutEpisode'] for r in streams),
        'renderLookEpisodesMissing': sum(r['lookScreenshotsWithoutEpisode'] for r in renders),
        'uiLookRateFalls': stream['lookRateFalls'], 'renderLookRateFalls': f3 is not None and l3 < f3,
        'uiLooksAvoidedVsFrozen': stream.get('frozenEscalationsTotal', 0) - stream.get('looksTotal', 0),
        'lensDecisions': sum(1 for r in runs for e in r['events'] if e['event'] == 'lens-decision'),
        'keptLenses': len(ui_kept) + len(r_kept), 'keptUiLenses': len(ui_kept), 'keptRenderLenses': len(r_kept),
        'programLensesUnpinned': sum(1 for l in program if not l['pinned']),
        'programLensesInvalid': sum(1 for l in program if not l['sandboxValid']),
        'programLensesWithoutReceipt': sum(1 for l in program if not l['decisionReceiptExists']),
        'programLensesWithoutProvenance': sum(1 for l in program if not l['author']),
        'groupOverlap': len(proof['recall']['groupOverlap']),
        'finalRecallDrops': sum(1 for t, v in fin.items() if (v['after']['recall'] or 0) < (v['before']['recall'] or 0) - 1e-9),
        'finalPrecisionDrops': sum(1 for t, v in fin.items() if v['before']['precision'] is not None and v['after']['precision'] is not None
                                   and v['after']['precision'] < v['before']['precision'] - 0.02),
        'finalOverlapRecallBefore': fin['overlap']['before']['recall'], 'finalOverlapRecallAfter': fin['overlap']['after']['recall'],
        'finalOffscreenRecallBefore': fin['off-screen-control']['before']['recall'], 'finalOffscreenRecallAfter': fin['off-screen-control']['after']['recall'],
        'practiceEpisodes': proof['practice']['episodes'], 'practiceRevertFailures': proof['practice']['revertFailures'],
        'renderPracticeRenders': proof['renderPractice']['renders'], 'training': False, 'paidCalls': 0,
    }
    # VISION2 (plan 27 §7): the OCR second pass, decided on a NEW blind-labelled held-out split.
    from grant_agent import laya_glance_image
    ocr2 = json.loads((EVIDENCE / 'VISION2-ocr-decision.json').read_text(encoding='utf-8'))
    ident = json.loads((EVIDENCE / 'VISION2-text-runs-identity.json').read_text(encoding='utf-8'))
    new = ocr2['splits']['new']
    drops = [t for t in new['on'] if new['off'][t]['precision'] is not None and new['on'][t]['precision'] is not None
             and new['on'][t]['precision'] < new['off'][t]['precision'] - ocr2['rule']['precisionDrop']]
    proof['ocrSecondPass'] = {'decision': ocr2['decision'], 'latencyNew': ocr2['latencyNew'], 'images': ocr2['images'],
                              'codeDefaultOn': laya_glance_image.SECOND_PASS_ENABLED, 'precisionDropsNew': drops,
                              'textRunsIdentity': {k: ident[k] for k in ('images', 'identical', 'referenceMsPerImage', 'newMsPerImage')}}
    proof['flat'].update({
        'secondPassDefaultMatchesDecision': laya_glance_image.SECOND_PASS_ENABLED == ocr2['decision']['onByDefault'],
        'newSplitImages': ocr2['images']['new'], 'newSplitPrecisionDrops': len(drops),
        'newSplitInternalIdPrecision': new['on']['internal-id']['precision'],
        'newSplitEncodedPathRecallOff': new['off']['encoded-path']['recall'], 'newSplitEncodedPathRecallOn': new['on']['encoded-path']['recall'],
        'textRunsDiffer': len(ident['differ']),
    })
    proof['curvesPng'] = curves_png([('UI stream-2 (495 labelled screenshots)', stream['lookRates']),
                                     ('3D renders (render-1, -2, -3)', render_rates)], EVIDENCE / 'VISION-curves.png')
    from grant_agent.cl_skill import _parse_skill, _Expr
    skill = _parse_skill(ROOT / 'manuals/cl/laya-vision.cl')
    proof['checks'] = [{'name': c.name, 'expr': c.expr, 'passed': bool(_Expr(c.expr, {'proof': proof['flat']}, {}).run())} for c in skill.checks]
    proof['passed'] = all(c['passed'] for c in proof['checks'])
    (EVIDENCE / 'VISION-proof.json').write_text(json.dumps(proof, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps({'flat': proof['flat'], 'checks': proof['checks'], 'passed': proof['passed']}, indent=1, default=str))


if __name__ == '__main__':
    main()
