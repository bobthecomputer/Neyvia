"""Background ridge distillation with independent holdout veto; episodes survive."""
from __future__ import annotations
import json
from pathlib import Path
import time
import threading
import numpy as np
from .laya_instant import canonical, store
_LOCK = threading.Lock()


def consolidate(root):
    with _LOCK:
        return _consolidate(root)


def _consolidate(root):
    started = time.perf_counter()
    local = store(str(root))
    with local.lock:
        local.refresh()
        rows = list(local.rows)
        version = local.version
    results = []
    for domain, user, layer, identity in sorted({(r['domain'], r['user'], r['layer'], r['encoder']) for r in rows}):
        if domain == 'ui-glance' or domain.startswith('scene:'):
            continue  # Scene glance is write-only learning; never create a head.
        region = [r for r in rows if (r['domain'], r['user'], r['layer'], r['encoder']) == (domain, user, layer, identity)]
        latest = {(r['key'], r['source']): r for r in region}
        region = list(latest.values())
        train = [r for r in region if r['split'] == 'train']
        held = [r for r in region if r['split'] == 'holdout']
        labels = list({canonical(r['label']): r['label'] for r in train}.values())
        result = {'domain': domain, 'user': user, 'layer': layer, 'train': len(train), 'heldout': len(held), 'promoted': False}
        results.append(result)
        if len(train) < 25 or len(held) < 10 or len(labels) < 2:
            result['reason'] = 'need-25-train-10-independent-holdout-and-two-labels'
            continue
        x = np.asarray([r['vector'] for r in train], dtype=np.float32)
        y = np.asarray([[float(r['label'] == label) for label in labels] for r in train])
        weights = x.T @ np.linalg.solve(x @ x.T + np.eye(len(train)), y)
        probe = np.asarray([r['vector'] for r in held], dtype=np.float32)
        ticks = time.perf_counter()
        head = [labels[i] for i in (probe @ weights).argmax(axis=1)]
        head_ms = (time.perf_counter()-ticks)*1000
        ticks = time.perf_counter()
        nearest = []
        for vector in probe:
            p, _, _ = local.scores(vector, train, labels)
            nearest.append(json.loads(max(p, key=p.get)))
        neighbour_ms = (time.perf_counter()-ticks)*1000
        head_correct = sum(a == r['label'] for a, r in zip(head, held))
        prior_correct = sum(a == r['label'] for a, r in zip(nearest, held))
        result.update(headCorrect=head_correct, neighbourCorrect=prior_correct, headMs=head_ms,
                      neighbourMs=neighbour_ms, headBytes=weights.nbytes, episodeVectorBytes=x.nbytes)
        result['promoted'] = head_correct >= prior_correct
        result['reason'] = 'heldout-no-regression' if result['promoted'] else 'heldout-regression-veto'
        if result['promoted']:
            with local.lock:
                local.refresh()
                if local.version != version:
                    result.update(promoted=False, reason='source-changed-during-consolidation')
                    continue
            import hashlib
            name = hashlib.sha256(canonical([domain, user, layer, identity]).encode()).hexdigest()
            target = local.path.parent / 'heads' / (name + '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {**result, 'encoder': identity, 'labels': labels, 'weights': weights.tolist(),
                       'trainingVersion': version, 'episodesRetained': True}
            pending = target.with_suffix('.pending')
            pending.write_text(canonical(payload), encoding='utf-8')
            pending.replace(target)
    return {'regions': results, 'ms': (time.perf_counter()-started)*1000, 'episodesRetained': True}
