"""Import attributed public defects and genuine Paul preferences into separate layers."""
from pathlib import Path
import ast
import csv
import hashlib
import itertools
import json
import re
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.taste_vision import ASSETS, STATE, append_pair, save, train


def public_cases():
    images = ASSETS / 'public/enrico-images'
    images.mkdir(exist_ok=True)
    annotations = {}
    with (ASSETS / 'public/uicrit.csv').open(encoding='utf-8') as source:
        for row in csv.DictReader(source):
            human = [text for text, origin in zip(ast.literal_eval(row['comments']), ast.literal_eval(row['comments_source']))
                     if origin == 'human']
            defects = [text for text in human if re.search(r'contrast|align|overlap|overflow|cramp|spelling|typo|too small|too close|hard to read|difficult to read', text, re.I)]
            annotations.setdefault(row['rico_id'], []).append({'defects': len(defects), 'reasons': defects})
    with zipfile.ZipFile(ASSETS / 'public/enrico-screenshots.zip') as archive:
        for entry in archive.infolist():
            identifier = Path(entry.filename).stem
            if identifier in annotations and entry.filename.endswith('.jpg'):
                target = images / (identifier + '.jpg')
                target.write_bytes(archive.read(entry))
    rows = []
    rendered_path = ROOT/'proof/r11/public-render-pairs.json'
    rendered_split = {r['group'].split(':')[-1]:r['split'] for r in json.loads(rendered_path.read_bytes())['pairs']} if rendered_path.exists() else {}
    for path in sorted(images.glob('*.jpg')):
        records = annotations[path.stem]
        # Human-only corrective critiques, not the overall subjective aesthetics score.
        count = sum(r['defects'] for r in records) / len(records)
        bucket = int(hashlib.sha256(path.stem.encode()).hexdigest()[:8], 16) % 5
        split = 'heldout' if bucket == 0 else 'calibration' if bucket == 1 else 'train'
        split = rendered_split.get(path.stem, split)
        rows.append({'path': path, 'count': count, 'split': split, 'id': path.stem})
    for split in ('train', 'calibration', 'heldout'):
        eligible = [(a, b) for a, b in itertools.combinations([r for r in rows if r['split'] == split], 2)
                    if abs(a['count'] - b['count']) >= 2]
        for a, b in eligible[:150]:
            append_pair('corrective', a['path'], b['path'], preferred=1 if b['count'] < a['count'] else -1,
                        group='public:' + a['id'] + ':' + b['id'], source='UICrit-human-Enrico', split=split,
                        reason=f'Human corrective critique counts {a["count"]:.2f} -> {b["count"]:.2f}')
    save(STATE / 'public-import.json', {'matchedScreens': len(rows), 'annotationScreens': len(annotations),
         'humanOnly': True, 'limitations': 'Different mobile screens, not matched repairs; only explicit corrective comment categories. No claim of web defect generalization.',
         'licenses': {'UICrit': 'CC-BY-4.0', 'Enrico': 'MIT'}, 'screens': [{**r, 'path': str(r['path'])} for r in rows]})


def historical_cases():
    count = 0
    for run in ('r6', 'r7', 'r8', 'r9', 'r10'):
        for path in sorted((ROOT / 'proof' / run).glob('*/T*/evidence/rounds.json')):
            document = json.loads(path.read_text(encoding='utf-8'))
            rounds = next(iter(document.values()), [])
            for before, after in zip(rounds, rounds[1:]):
                if 'pageChecks' not in before or 'pageChecks' not in after:
                    continue
                a, b = before['pageChecks']['blocks'], after['pageChecks']['blocks']
                if a == b:
                    continue
                shots = lambda row: next((s['path'] for s in row['interaction']['screenshots'] if s['viewport'] == 'desktop' and s['theme'] == 'light'), None)
                old, new = shots(before), shots(after)
                if old and new and Path(old).exists() and Path(new).exists():
                    append_pair('corrective', old, new, preferred=1 if b < a else -1,
                                group=str(path.parent), source='historical-deterministic', reason=f'Blocks {a} -> {b}')
                    count += 1
    return count


def public_render_cases():
    path = ROOT / 'proof/r11/public-render-pairs.json'
    if path.exists():
        for row in json.loads(path.read_bytes())['pairs']:
            append_pair('corrective', row['before'], row['after'], preferred=row['preferred'], group=row['group'],
                        source=row['source'], reason=row['reason'], split=row['split'])


def last_shot(run, arm, task):
    path = ROOT / 'proof' / run / arm / task / 'evidence/rounds.json'
    rows = next(iter(json.loads(path.read_text(encoding="utf-8")).values()))
    return next(s['path'] for s in rows[-1]['interaction']['screenshots'] if s['viewport'] == 'desktop' and s['theme'] == 'light')


def personal_cases():
    votes = json.loads((ROOT / 'proof/r10/paul-votes.json').read_text())
    key = json.loads((ROOT / 'proof/r10/blind-shots-key.SPOILER.json').read_text())
    # r4/r5 identity-only votes remain contextual reasons, never numerical quality labels.
    identity = json.loads((ROOT / 'proof/preference-pairs.json').read_bytes())
    save(STATE / 'personal-context.json', {'votes': votes, 'blindKey': key,
         'identityReasons': identity.get('identityReasons'), 'identityOnlyLabelsExcluded': sum(v.get('identityVotes', 0) for v in identity.get('summary', {}).values())})
    for vote in votes['votes']:
        if vote.get('qualityPreference') == 'C' and 'landing' in vote['pair']:
            candidate = last_shot('r10', 'arm-luna', 'T1')
            reference = ROOT / 'proof/r6-blind/arm-c/render/landing/desktop-light.png'
            # Use the actual reference render sealed by the r10 host, not a guessed file.
            path = ROOT / 'proof/r10/arm-luna/T1/evidence/rounds.json'
            row = next(iter(json.loads(path.read_text(encoding="utf-8")).values()))[-1]
            anchor = json.loads(Path(row['anchorReportPath']).read_text(encoding='utf-8'))
            reference = next(s['path'] for s in anchor['screenshots'] if s['viewport'] == 'desktop' and s['theme'] == 'light')
            append_pair('personal', reference, candidate, preferred=-1, group='paul-r10-landing', source='Paul-quality-vote', reason=vote['reason'])
    # The lead's latest comments do not bind exact before/after screenshots.
    # Retain their guidance without inventing a temporal preference label.
    context = json.loads((STATE/'personal-context.json').read_bytes())
    context['latestLeadComments'] = ['Luna landing was a cleaned-up and better version', 'Luna rare UI regressed']
    context['commentBaselineUnbound'] = True
    save(STATE/'personal-context.json', context)


if __name__ == '__main__':
    public_cases()
    public_render_cases()
    historical_cases()
    personal_cases()
    for layer in ('corrective', 'personal'):
        result = train(layer)
        print(json.dumps({k: v for k, v in result.items() if k != 'weights'}), flush=True)
