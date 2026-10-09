"""Frozen local CLIP pixels with separate, reversible corrective/personal heads.

No taste label is inferred from an identity vote. No uncalibrated head answers.
Training pairs and frozen held-out cases retain their source and image hashes.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from functools import wraps, lru_cache
from pathlib import Path
import sys
import threading

REPO = Path(__file__).resolve().parents[2]
_LOCAL_ASSETS = REPO / '.agent_control/c13h-assets'
_EXISTING_TASTE = REPO.parent / 'nx-c13-taste'
ASSETS = Path(os.environ.get('NEYVIA_TASTE_ASSETS', _LOCAL_ASSETS if _LOCAL_ASSETS.exists() else _EXISTING_TASTE / '.agent_control/c13h-assets'))
STATE = Path(os.environ.get('NEYVIA_TASTE_STATE', REPO / 'proof/r11/learning'))
DEPS = Path(os.environ.get('NEYVIA_TASTE_DEPS', REPO / '.agent_control/c13h-deps' if (REPO / '.agent_control/c13h-deps').exists() else _EXISTING_TASTE / '.agent_control/c13h-deps'))
READ_CACHE = Path(os.environ.get('NEYVIA_TASTE_READ_CACHE', STATE / 'embeddings'))
if str(DEPS) not in sys.path:
    sys.path.insert(0, str(DEPS))
import numpy as np
from PIL import Image, ImageOps

_SESSION = None
_SESSION_MODEL_SHA = None
_SESSION_LOCK = threading.Lock()


@lru_cache(maxsize=4)
def encoder_digest(version):
    return sha(ASSETS/'clip/vision.onnx')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.' + str(os.getpid()) + '.pending')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def preload():
    """Load the frozen CPU encoder once, also used by host background warmup."""
    global _SESSION, _SESSION_MODEL_SHA
    model_stat = (ASSETS/'clip/vision.onnx').stat()
    model_sha = encoder_digest((model_stat.st_size,model_stat.st_mtime_ns))
    with _SESSION_LOCK:
        if _SESSION is None:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            _SESSION = ort.InferenceSession(str(ASSETS / 'clip/vision.onnx'), options,
                                          providers=['CPUExecutionProvider'])
            _SESSION_MODEL_SHA = model_sha
        if _SESSION_MODEL_SHA != model_sha:
            raise RuntimeError('Frozen encoder changed; restart and recalibrate before inference')
    return model_sha


def embedding(path, *, cache_root=None):
    model_stat = (ASSETS/'clip/vision.onnx').stat()
    model_sha = encoder_digest((model_stat.st_size,model_stat.st_mtime_ns))
    identity = sha(path)
    cached = READ_CACHE / (identity + '.json')
    if not cached.exists():
        cached = Path(cache_root or STATE / 'embeddings') / (identity + '.json')
    if cached.exists():
        value = json.loads(cached.read_text())
        if value['modelSha256']==model_sha:return np.array(value['embedding'])
    preload()
    with Image.open(path) as image:
        image = image.convert('RGB')
        # Read multiple legible crops, not a squeezed full-page screenshot.
        height = min(image.height, image.width)
        starts = sorted({0, max(0, (image.height - height) // 2), max(0, image.height - height)})
        vectors = []
        for y in starts:
            crop = ImageOps.fit(image.crop((0, y, image.width, y + height)), (224, 224),
                                method=Image.Resampling.BICUBIC)
            pixels = np.asarray(crop, dtype=np.float32) / 255
            pixels = (pixels - np.array([.48145466, .4578275, .40821073])) / np.array([.26862954, .26130258, .27577711])
            outputs = _SESSION.run(None, {'pixel_values': pixels.transpose(2, 0, 1)[None].astype(np.float32)})
            index = next(i for i, output in enumerate(_SESSION.get_outputs()) if output.name == 'image_embeds')
            vector = outputs[index].reshape(-1)
            vectors.append(vector / max(float(np.linalg.norm(vector)), 1e-8))
        result = np.mean(vectors, axis=0)
        result /= max(float(np.linalg.norm(result)), 1e-8)
    save(Path(cache_root or STATE / 'embeddings') / (identity + '.json'), {'imageSha256': identity, 'modelSha256': model_sha,
                  'cropStarts': starts, 'embedding': result.tolist()})
    return result


def cases(layer):
    path = STATE / (layer + '-cases.json')
    return [r for r in json.loads(path.read_text()) if not r.get('excludedFromTraining')] if path.exists() else []


def serialized(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        import msvcrt
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / 'learning.lock').open('a+b') as lock:
            if not lock.tell():
                lock.write(b'0'); lock.flush()
            while True:
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.05)
            try:
                return function(*args, **kwargs)
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    return guarded


@serialized
def append_pair(layer, before, after, *, preferred, group, source, reason='', split=None):
    if layer not in ('corrective', 'personal') or preferred not in (-1, 1):
        raise ValueError('Explicit layer and actual preference required')
    path = STATE / (layer + '-cases.json')
    rows = json.loads(path.read_bytes()) if path.exists() else []
    if split is None:
        known = {r['split'] for r in rows if r['group']==group and not r.get('excludedFromTraining')}
        bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%5
        split = next(iter(known)) if known else ('heldout' if layer=='personal' and bucket==0 and not (STATE/(layer+'-head.json')).exists() else 'calibration' if bucket in (0,1) else 'train')
    if split not in ('train','calibration','heldout'):raise ValueError('Known split required')
    row = {'before': str(before), 'after': str(after), 'beforeSha256': sha(before),
           'afterSha256': sha(after), 'preferred': preferred, 'group': group,
           'source': source, 'reason': reason, 'split': split}
    row['id'] = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
    if row['beforeSha256'] == row['afterSha256']:
        row.update(excludedFromTraining=True, exclusionReason='Identical captured pixels cannot supply a visual preference label; runtime evidence retained')
    if not any(r['id'] == row['id'] for r in rows):
        rows.append(row)
        save(STATE / (layer + '-cases.json'), rows)
    return row


def wilson_lower(correct, total):
    if not total:
        return 0
    p, z = correct / total, 1.96
    return (p + z*z/(2*total) - z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))) / (1 + z*z/total)


def calibrate(weights, rows):
    """Count independent scene groups, not their correlated perturbations."""
    values = {'calibratedMargin':None,
              'calibrationCaseHash':hashlib.sha256(json.dumps(sorted(r['id'] for r in rows)).encode()).hexdigest()}
    if not rows:return values
    scores = np.array([(embedding(r['after'])-embedding(r['before']))@weights for r in rows])
    correct = np.sign(scores)==np.array([r['preferred'] for r in rows])
    for margin in sorted(set(abs(scores))):
        selected = [i for i,score in enumerate(scores) if abs(score)>=margin]
        groups = {}
        for i in selected:groups.setdefault(rows[i]['group'],[]).append(bool(correct[i]))
        count, wins = len(groups), sum(all(v) for v in groups.values())
        if count>=30 and wilson_lower(wins,count)>=.95:
            dimensions = [Image.open(rows[i][side]).size for i in selected for side in ('before','after')]
            values.update(calibratedMargin=float(margin),calibrationLowerBound=wilson_lower(wins,count),
                          calibrationCases=len(selected),calibrationGroups=count,
                          calibrationSimilarityFloor=min(float(embedding(rows[i]['before'])@embedding(rows[i]['after'])) for i in selected),
                          calibrationWidthRange=[min(w for w,h in dimensions),max(w for w,h in dimensions)],
                          calibrationAspectRange=[min(h/w for w,h in dimensions),max(h/w for w,h in dimensions)])
            break
    return values


@serialized
def train(layer):
    rows = cases(layer)
    train_rows = [r for r in rows if r['split'] == 'train']
    held = [r for r in rows if r['split'] == 'heldout']
    calibration = [r for r in rows if r['split'] == 'calibration']
    features = lambda rows: np.array([embedding(r['after']) - embedding(r['before']) for r in rows])
    old_path = STATE / (layer + '-head.json')
    previous = json.loads(old_path.read_text()) if old_path.exists() else None
    result = {'layer': layer, 'cases': len(rows), 'trainCases': len(train_rows), 'heldoutCases': len(held),
              'heldoutAccuracy': None, 'admitted': False, 'answerGate': .95, 'calibratedMargin': None,
              'sourceCounts': {s: sum(r['source'] == s for r in rows) for s in sorted({r['source'] for r in rows})}}
    if len(train_rows) < 8 or len(held) < 8:
        result['reason'] = 'Insufficient independently grouped train/heldout labels'
        save(STATE / (layer + '-candidate.json'), result)
        return result
    x, y = features(train_rows), np.array([r['preferred'] for r in train_rows])
    # Dual ridge is small, deterministic and keeps the vision encoder frozen.
    weights = x.T @ np.linalg.solve(x @ x.T + np.eye(len(x)) * .2, y)
    held_scores = features(held) @ weights
    correct = np.sign(held_scores) == np.array([r['preferred'] for r in held])
    result['heldoutAccuracy'] = float(np.mean(correct))
    baseline = previous['heldoutAccuracy'] if previous else .5
    benchmark = REPO / 'proof/r11/jevbench-after.json'
    if not benchmark.exists():
        benchmark = REPO / 'proof/r11/jevbench-before.json'
    benchmark_ok = benchmark.exists() and json.loads(benchmark.read_text()).get('correct', 0) >= 138
    held_ids = [r['id'] for r in held]
    result['heldoutSetUnchanged'] = not previous or held_ids == previous['heldoutCaseIds']
    # An objective pixel audit may remove impossible visual labels. Re-evaluate
    # both heads on the same remaining pixels; never compare different denominators.
    result['heldoutPixelAuditPassed'] = False
    if previous and not result['heldoutSetUnchanged']:
        raw = {r['id']:r for r in json.loads((STATE/(layer+'-cases.json')).read_bytes())}
        removed = set(previous['heldoutCaseIds']) - set(held_ids)
        added = set(held_ids) - set(previous['heldoutCaseIds'])
        audited = bool(removed) and not added and all(raw.get(i,{}).get('beforeSha256') == raw.get(i,{}).get('afterSha256') and i in raw for i in removed)
        if audited:
            baseline = float(np.mean(np.sign(features(held) @ np.array(previous['weights'])) == np.array([r['preferred'] for r in held])))
            result.update(heldoutPixelAuditPassed=True, removedIdenticalPixelCaseIds=sorted(removed),
                          previousHeadAccuracyOnCurrentHeldout=baseline, previousReportedHeldoutAccuracy=previous['heldoutAccuracy'])
            save(STATE/(layer+'-heldout-pixel-audit.json'), {
                 'previousHeadSha256':sha(old_path), 'removedIdenticalPixelCaseIds':sorted(removed),
                 'previousReportedCases':len(previous['heldoutCaseIds']), 'currentCases':len(held),
                 'previousReportedAccuracy':previous['heldoutAccuracy'],
                 'previousAccuracyOnCurrentPixels':baseline, 'candidateAccuracyOnCurrentPixels':result['heldoutAccuracy'],
                 'rule':'Only objectively identical-image labels removed; both heads evaluated on the same remaining pixels'})
    result['regressionPassed'] = result['heldoutAccuracy'] >= baseline and (result['heldoutSetUnchanged'] or result['heldoutPixelAuditPassed'])
    result['jevbenchPassed'] = benchmark_ok
    result.update(calibrate(weights,calibration))
    result['admitted'] = result['regressionPassed'] and benchmark_ok
    result['weights'] = weights.tolist()
    result['heldoutCaseIds'] = held_ids
    result['reason'] = 'Regression admitted; abstain unless calibrated margin exists' if result['admitted'] else 'Regression veto; retain previous head'
    save(STATE / (layer + '-candidate.json'), result)
    if result['admitted']:
        if previous:
            save(STATE / 'history' / (layer + '-' + sha(old_path)[:16] + '.json'), previous)
        save(old_path, result)
    elif previous and previous.get('calibrationCaseHash')!=result['calibrationCaseHash']:
        # New validation labels may qualify unchanged weights after a rejected fit.
        updated = {**previous,**calibrate(np.array(previous['weights']),calibration)}
        save(STATE/'history'/(layer+'-'+sha(old_path)[:16]+'.json'),previous)
        save(old_path,updated)
    return result


def compare(before, after, layer='corrective', *, head_path=None):
    a, b = embedding(before), embedding(after)
    result = {'layer': layer, 'beforeSha256': sha(before), 'afterSha256': sha(after),
              'similarity': float(a @ b), 'answer': None, 'escalate': True,
              'reason': 'No admitted calibrated head'}
    path = Path(head_path) if head_path is not None else STATE / (layer + '-head.json')
    if path.exists():
        head = json.loads(path.read_text())
        score = float((b - a) @ np.array(head['weights']))
        gate = head.get('calibratedMargin')
        result.update(score=score, heldoutAccuracy=head['heldoutAccuracy'], headSha256=sha(path))
        width_range, aspects = head.get('calibrationWidthRange'), head.get('calibrationAspectRange')
        dimensions = [Image.open(path).size for path in (before,after)]
        supported = bool(width_range and aspects) and all(width_range[0]*.9<=w<=width_range[1]*1.1 and aspects[0]*.9<=h/w<=aspects[1]*1.1 for w,h in dimensions)
        result['calibratedScopeSupported'] = supported
        if gate is not None and abs(score) >= gate and supported and result['similarity']>=head['calibrationSimilarityFloor']:
            result.update(answer='after' if score > 0 else 'before', escalate=False,
                          confidenceLowerBound=head['calibrationLowerBound'], reason='Above calibrated gate')
    return result


def compare_variants(report, anchor, previous=None):
    references = {(s['viewport'],s['theme']):s for s in anchor['screenshots']}
    prior = {(s['viewport'],s['theme']):s for s in previous['interaction']['screenshots']} if previous else {}
    values = []
    for shot in report['screenshots']:
        key = (shot['viewport'],shot['theme'])
        reference = references[key]
        item = {'viewport':key[0],'theme':key[1], 'screenshotSha256':sha(shot['path']),
                'reference':compare(reference['path'],shot['path']),
                'personalReference':compare(reference['path'],shot['path'],'personal')}
        if key in prior:item['previous'] = compare(prior[key]['path'],shot['path'])
        values.append(item)
    if len(values)!=4:raise ValueError('Four complete rendered variants required for pixel triage')
    return values


def review(root, report, checks, anchor, folder, previous=None):
    import time
    from .laya_hooks import triage_taste, verify
    from .laya_ledger import record
    started = time.monotonic()
    triage = triage_taste(root, checks)
    confirmation = verify('taste_triage', triage.get('decision') or 'ask_critic', checks, root=root)
    if triage.get('route') == 'unavailable' or confirmation.get('source') == 'URLError':
        raise RuntimeError('LAYA must be running for this arm')
    shot = next(r['path'] for r in report['screenshots'] if r['viewport'] == 'desktop' and r['theme'] == 'light')
    variants = compare_variants(report,anchor,previous)
    primary = next(v for v in variants if v['viewport']=='desktop' and v['theme']=='light')
    values = {'triage': triage, 'verify': confirmation, 'variants':variants,
              'reference':primary['reference'],'personalReference':primary['personalReference']}
    if previous:
        old = next(r['path'] for r in previous['interaction']['screenshots'] if r['viewport'] == 'desktop' and r['theme'] == 'light')
        values['previous'] = primary['previous']
        before_checks = {c['check']: c for c in previous['pageChecks']['checks']}
        common = [c for c in checks['checks'] if c['check'] in before_checks and c['level'] == 'block']
        old_blocks = sum(not before_checks[c['check']]['passed'] for c in common)
        new_blocks = sum(not c['passed'] for c in common)
        same_protocol = previous['interaction'].get('observer_sha256') == report.get('observer_sha256')
        values['repairPair'] = {'beforeSha256':sha(old), 'afterSha256':sha(shot),
                               'sameProtocol':same_protocol, 'commonChecks':[c['check'] for c in common],
                               'oldBlocks':old_blocks, 'newBlocks':new_blocks,
                               'label':(1 if new_blocks < old_blocks else -1) if same_protocol and old_blocks != new_blocks else None,
                               'reason':'Ties and changed observer protocols are retained without invented preference labels'}
        if same_protocol and old_blocks != new_blocks:
            append_pair('corrective', old, shot, preferred=1 if new_blocks < old_blocks else -1,
                        group=str(Path(root).resolve()), source='deterministic-repair',
                        reason=f'Common blocking checks {old_blocks} -> {new_blocks}; same renderer protocol')
            values['onlineLearning'] = train('corrective')
    values['elapsedMs'] = (time.monotonic() - started) * 1000
    # Learning from an already-required render is not time saved by a skipped model call.
    record(root, task='taste-triage', path='laya.taste_pixels', decision='compare',
           outcome='answered' if not values['reference']['escalate'] else 'escalated',
           latency_ms=values['elapsedMs'], detail='Frozen CLIP; separate corrective/personal calibration', tokensSavedEstimate=0)
    save(Path(folder) / 'laya-vision.json', values)
    return values
