"""Frozen text judges; visual taste still requires an image critic.

Two judges, never mixed (taste_labels.py): a quality judge trained only on genuine qualityPreference labels,
and an identity judge trained on identityGuess labels ("which side reads as Claude"). Training uses only content
features, never arm/model identity or a held-out vote. Lesson admission accepts hash-bound evidence, not a
model's claim of success, and stays quarantined until taste_labels.promotion_status clears.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from pathlib import Path

from . import taste_labels

FEATURES = ('structure', 'specificity', 'sources', 'placeholder', 'no_slop', 'brief_coverage')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def features(task, text):
    words = re.findall(r'\b[a-z][a-z0-9-]*\b', text.lower())
    count = max(1, len(words))
    structure = len(re.findall(r'(?m)^#{1,4}\s|<h[1-4]\b|^\|.*\|\s*$', text))
    specificity = len(re.findall(r'\b\d+(?:\.\d+)?\b|`[^`]+`|\b[A-Z][a-z]+[A-Z]\w*\b', text))
    sources = len(re.findall(r'https?://[^\s"<>]+', text))
    placeholder = len(re.findall(r'(?i)lorem ipsum|\bTODO\b|\bTBD\b|\[insert', text))
    slop = len(re.findall(r'(?i)\b(delves?|leverage|foster|seamless|cutting.edge|revolutionary|game.changer)\b|—', text))
    brief = set(re.findall(r'\b[a-z]{5,}\b', task.lower()))
    coverage = len(brief & set(words)) / max(1, len(brief))
    return [min(structure, 12) / 12, min(specificity, 30) / 30,
            min(sources, 12) / 12, -min(placeholder, 5) / 5,
            -min(slop / count * 100, 5) / 5, coverage]


def _text(arm):
    return '\n'.join(str(row.get('text') or '') for name, row in sorted(arm['files'].items()))


def _train(rows):
    weights = [0.0] * len(FEATURES)
    # Fixed algorithm and hyperparameters, including in every held-out fold.
    for _ in range(600):
        gradient = [0.02 * w for w in weights]
        for delta, label in rows:
            score = max(-30, min(30, sum(w * x for w, x in zip(weights, delta))))
            error = (1 / (1 + math.exp(-score))) - label
            for i, x in enumerate(delta):
                gradient[i] += error * x / len(rows)
        weights = [w - 0.15 * g for w, g in zip(weights, gradient)]
    return weights


def compare(task_text, candidate_text, anchor_text, frozen):
    expected = frozen.get('modelSha256')
    core = {k: v for k, v in frozen.items() if k not in {'modelSha256', 'calibration'}}
    if expected != digest(core) or frozen.get('features') != list(FEATURES):
        raise ValueError('Frozen judge hash or feature contract mismatch')
    delta = [a - b for a, b in zip(features(task_text, candidate_text), features(task_text, anchor_text))]
    contributions = {name: x * w for name, x, w in zip(FEATURES, delta, frozen['weights'])}
    margin = sum(contributions.values())
    if not math.isfinite(margin):
        raise ValueError('Non-finite preference score')
    epsilon = frozen['tieEpsilon']
    side = 'candidate' if margin > epsilon else 'anchor' if margin < -epsilon else 'tie'
    kind = frozen.get('labelKind', 'qualityPreference')
    result = {'labelKind': kind, 'margin': margin, 'contributions': contributions, 'judgeSha256': expected,
              'trained': bool(frozen.get('trainedLabels')),
              'scope': 'text features only; image critique required for visual quality'}
    if kind == 'identityGuess':
        # Recognizability, not quality: which side Paul would more likely call Claude.
        return {**result, 'readsAsClaude': side}
    return {**result, 'winner': side}


def calibrate(pairs_path, target='quality'):
    """Leave-one-out calibration on one label kind. With fewer than two labels of that kind the judge is untrained:
    zero weights, every comparison a tie, agreement None. It never borrows the other kind's labels."""
    raw = Path(pairs_path).read_bytes()
    data = taste_labels.load(json.loads(raw))
    labelled = taste_labels.rows(data, target)
    kind = 'qualityPreference' if target == 'quality' else 'identityGuess'
    rows, pairs = [], []
    for pair, label in labelled:
        a, b = features(pair['taskText'], _text(pair['arms']['C'])), features(pair['taskText'], _text(pair['arms']['L']))
        rows.append(([x - y for x, y in zip(a, b)], int(label == 'C')))
        pairs.append(pair)
    folds = []
    if len(rows) >= 2:
        for heldout, (delta, label) in enumerate(rows):
            training = [row for i, row in enumerate(rows) if i != heldout]
            weights = _train(training)
            margin = sum(w * x for w, x in zip(weights, delta))
            prediction = 'C' if margin > 0.025 else 'L' if margin < -0.025 else 'tie'
            folds.append({'pairId': pairs[heldout]['pairId'], 'trainingPairIds': [p['pairId'] for i, p in enumerate(pairs) if i != heldout],
                          'prediction': prediction, 'label': 'C' if label else 'L', 'margin': margin,
                          'agrees': prediction == ('C' if label else 'L')})
    weights = _train(rows) if len(rows) >= 2 else [0.0] * len(FEATURES)
    core = {'schema': 'neyvia.text-preference-judge.v2' if target == 'quality' else 'neyvia.text-identity-judge.v1',
            'labelKind': kind, 'trainedLabels': len(rows) if len(rows) >= 2 else 0,
            'features': list(FEATURES), 'weights': weights,
            'tieEpsilon': 0.025, 'dataSha256': hashlib.sha256(raw).hexdigest(),
            'algorithm': 'fixed logistic gradient descent 600 steps lr=.15 ridge=.02; no identity features'}
    majority = max(sum(label for _, label in rows), sum(1 - label for _, label in rows)) / len(rows) if rows else None
    calibration = {'method': 'leave-one-out', 'labelKind': kind, 'folds': folds,
                   'agreement': sum(f['agrees'] for f in folds) / len(folds) if folds else None,
                   'agreed': sum(f['agrees'] for f in folds), 'total': len(folds),
                   'ties': sum(f['prediction'] == 'tie' for f in folds), 'abstentionsCountAsMisses': True,
                   'majorityBaseline': majority, 'labels': taste_labels.counts(data)}
    if target == 'quality':
        calibration['promotion'] = taste_labels.promotion_status(data, calibration)
    return {**core, 'modelSha256': digest(core), 'calibration': calibration}


def admit_lesson(evidence):
    """Require immutable case/suite evidence and strict measured improvement.

    Each observation is {path,sha256,score}; its JSON artifact must contain
    the identical finite score and frozen judge/suite hashes. Incomplete or
    tampered evidence returns a rejection rather than promoting a lesson.
    """
    reasons = []
    try:
        hashes = {key: evidence[key] for key in ('judgeSha256', 'suiteSha256')}
        if any(not re.fullmatch('[a-f0-9]{64}', value) for value in hashes.values()):
            raise ValueError('Invalid frozen hashes')
        judge = json.loads(Path(evidence['judgePath']).read_bytes())
        compare('', '', '', judge)
        if judge['modelSha256'] != hashes['judgeSha256']:
            raise ValueError('Frozen judge differs from evidence')
        if judge.get('dataSha256') != hashes['suiteSha256']:
            raise ValueError('Frozen suite must match the judge calibration dataset')
        if hashlib.sha256(Path(evidence['suitePath']).read_bytes()).hexdigest() != hashes['suiteSha256']:
            raise ValueError('Frozen suite bytes changed')
        # Quarantine: only a judge trained on enough genuine quality labels may promote a taste lesson.
        # Recalibrate from the hash-checked suite instead of trusting the stored (unhashed) calibration block.
        fresh = calibrate(evidence['suitePath'])
        if judge.get('labelKind') != 'qualityPreference' or fresh['modelSha256'] != judge['modelSha256']:
            raise ValueError('Lesson admission requires the frozen quality judge recalibrated from this suite')
        promotion = fresh['calibration']['promotion']
        if promotion['quarantined']:
            raise ValueError('Automatic taste-lesson promotion quarantined: ' + '; '.join(promotion['reasons']))
        rubric_raw = Path(evidence['rubricPath']).read_bytes()
        if hashlib.sha256(rubric_raw).hexdigest() != evidence['rubricSha256']:
            raise ValueError('Frozen lesson rubric changed')
        hashes['rubricSha256'] = evidence['rubricSha256']
        task_raw = Path(evidence['taskPath']).read_bytes()
        task_hash = hashlib.sha256(task_raw).hexdigest()
        if task_hash != evidence['taskSha256']:
            raise ValueError('Source task changed')
        suite = json.loads(Path(evidence['suitePath']).read_bytes())
        case_ids = {row['pairId'] for row in suite['pairs']}
        scores, suite_scores = {}, {}
        for key in ('beforeCase', 'afterCase', 'beforeSuite', 'afterSuite'):
            row = evidence[key]
            raw = Path(row['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError(key + ' artifact hash mismatch')
            artifact = json.loads(raw)
            score = row['score']
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError(key + ' finite score required')
            if artifact.get('score') != score or any(artifact.get(k) != v for k, v in hashes.items()):
                raise ValueError(key + ' frozen score binding mismatch')
            if artifact.get('taskSha256') != task_hash:
                raise ValueError(key + ' source task identity mismatch')
            execution = artifact.get('execution', {})
            if execution.get('model') != 'gpt-6-luna' or execution.get('exitCode') != 0 or execution.get('timedOut'):
                raise ValueError(key + ' successful Luna rerun receipt required')
            for binding in execution.get('files', []):
                if hashlib.sha256(Path(binding['path']).read_bytes()).hexdigest() != binding['sha256']:
                    raise ValueError(key + ' execution receipt changed')
            if not execution.get('files'):
                raise ValueError(key + ' hashed execution receipts required')
            if key.endswith('Case'):
                case_hash = artifact.get('caseSha256', '')
                if not re.fullmatch('[a-f0-9]{64}', case_hash):
                    raise ValueError(key + ' case hash missing')
                source = Path(artifact['casePath']).read_bytes()
                if hashlib.sha256(source).hexdigest() != case_hash:
                    raise ValueError(key + ' case bytes changed')
            else:
                per_case = artifact.get('caseScores', {})
                if set(per_case) != case_ids or any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)
                                                   for value in per_case.values()):
                    raise ValueError(key + ' complete finite frozen case scores required')
                suite_scores[key] = per_case
            scores[key] = score
        if scores['afterCase'] <= scores['beforeCase']:
            reasons.append('Source case did not improve')
        if scores['afterSuite'] < scores['beforeSuite']:
            reasons.append('Frozen suite regressed')
        if any(suite_scores['afterSuite'][key] < value for key,value in suite_scores['beforeSuite'].items()):
            reasons.append('A frozen suite case regressed')
        if evidence.get('noise', 0) != 0:
            reasons.append('Noise allowance must be zero')
    except (KeyError, TypeError, ValueError, OSError) as error:
        reasons.append(str(error))
    return {'accepted': not reasons, 'state': 'verified' if not reasons else 'quarantined',
            'reasons': reasons, 'noise': 0, 'evidenceSha256': digest(evidence)}
