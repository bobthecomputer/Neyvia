"""VISION2: a NEW held-out split for the OCR second-pass decision (plan 27 §7, 7 Oct).

The plan-24 final groups were read while lenses and the minimum-evidence rule were decided, so
they are contaminated for those lens types. This script fixes a new split from captures that were
never labelled, never judged and never opened by the predicate author, BEFORE any of them is
labelled or measured. Membership is decided by file path and a name hash only (no pixels, no OCR,
no glance output):

  unseen-surface  -- captures of app surfaces that appear nowhere in the 495 labelled episodes
                     (library, settings, primitives gallery, GUI failure screens);
  unseen-capture  -- unlabelled captures (other builds, other themes incl. night/sunset, other fix
                     rounds) of the six old FINAL surfaces; never fit or check surfaces, so no
                     lens author or predicate edit saw these surfaces' examples. Up to PER_SURFACE
                     per surface, by name hash.

Byte-identical copies of labelled images are dropped. Output: D:/NeyviaRuns/VISION2/new-split.json
and labelling batches D:/NeyviaRuns/VISION2/labels/batch-NN.list.json (labelled blind, with
D:/NeyviaRuns/laya-labels/RUBRIC.md, by vision sub-agents exactly like the original 495).

Usage: python scripts/vision2_new_split.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from laya_glance_eval import surface_group  # noqa: E402
from vision_lens_eval import labelled_rows  # noqa: E402

RUNS = Path('D:/NeyviaRuns')
OUT = RUNS / 'VISION2'
SOURCES = ('tour', 'ui-fix', 'ui-fix2', 'gui')
NEW_SURFACES = ('library', 'settings', 'primitives', 'gui-failure')
PER_SURFACE = 20
BATCH = 24
SALT = 'vision2-new-split:'


def app_surface(path):
    """The app surface a capture shows, from its path (new naming schemes included)."""
    rel = Path(path).relative_to(RUNS).as_posix()
    name = Path(path).stem
    if rel.startswith('ui-fix/probe') or 'xournal' in name or '/state/' in rel or '/icons/' in rel or 'neyvia-apps' in rel:
        return None  # crops, external reference apps, app state folders
    if rel.startswith('gui/'):
        if name.startswith('failure-'):
            return 'gui-failure'
        for s in ('primitives', 'settings', 'app-factory', 'files', 'notes'):
            if name.startswith(s):
                return s
        if name.startswith('shell'):
            return 'home'
        return None
    if 'library' in rel:
        return 'library'
    if rel.startswith('ui-fix/hill-climb'):
        return 'hill-climb'
    if rel.startswith('ui-fix/image-studio'):
        return 'image-studio'
    if name == 'probe-home':
        return 'home'
    if name == 'pdf-debug':
        return 'pdf'
    if rel.startswith('ui-fix2/pairs/'):
        return surface_group(re.sub(r'^\d+-(before|after)(-light|-dark)?-', '', name) + '.png')
    return surface_group(path)


def name_rank(path):
    return hashlib.sha256((SALT + Path(path).relative_to(RUNS).as_posix()).encode()).hexdigest()


def build():
    rows = labelled_rows()
    split = {r['group']: r['split'] for r in rows}
    old_final = sorted(g for g, s in split.items() if s == 'final')
    seen_bytes = {hashlib.sha256(Path(r['image']).read_bytes()).hexdigest() for r in rows}
    labelled = {str(Path(r['image'])).lower() for r in rows}
    pools, excluded = {}, {}
    for src in SOURCES:
        for p in sorted((RUNS / src).rglob('*.png')):
            if str(p).lower() in labelled:
                continue
            s = app_surface(p)
            if s is None or s not in NEW_SURFACES + tuple(old_final):
                excluded[s or 'not-an-app-capture'] = excluded.get(s or 'not-an-app-capture', 0) + 1
                continue
            pools.setdefault(s, []).append(p)
    chosen = []
    for s, paths in sorted(pools.items()):
        kind = 'unseen-surface' if s in NEW_SURFACES else 'unseen-capture'
        taken, digests = [], set()
        for p in sorted(paths, key=name_rank):
            d = hashlib.sha256(p.read_bytes()).hexdigest()
            if d in seen_bytes or d in digests:
                continue
            digests.add(d)
            taken.append(p)
            if kind == 'unseen-capture' and len(taken) >= PER_SURFACE:
                break
        chosen += [{'image': str(p), 'surface': s, 'kind': kind, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in taken]
    chosen.sort(key=lambda r: name_rank(r['image']))  # batches mix surfaces
    return {'schema': 'neyvia.vision2.new-split.v1', 'salt': SALT, 'perSurface': PER_SURFACE,
            'oldFinalSurfaces': old_final, 'newSurfaces': list(NEW_SURFACES),
            'excludedBySurface': dict(sorted(excluded.items(), key=lambda kv: -kv[1])),
            'counts': {k: sum(1 for r in chosen if r['kind'] == k) for k in ('unseen-surface', 'unseen-capture')},
            'bySurface': {s: sum(1 for r in chosen if r['surface'] == s) for s in sorted({r['surface'] for r in chosen})},
            'images': chosen}


def main():
    split = build()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'new-split.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        if [r['image'] for r in old['images']] != [r['image'] for r in split['images']]:
            raise SystemExit('new-split.json exists with different members: the split is frozen once written')
    path.write_text(json.dumps(split, indent=1), encoding='utf-8')
    labels = OUT / 'labels'
    labels.mkdir(exist_ok=True)
    images = [r['image'] for r in split['images']]
    for k in range(0, len(images), BATCH):
        (labels / f'batch-{k // BATCH:02d}.list.json').write_text(json.dumps(images[k:k + BATCH], indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in split.items() if k != 'images'}, indent=1))


if __name__ == '__main__':
    main()
