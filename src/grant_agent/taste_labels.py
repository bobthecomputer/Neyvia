"""Blind-vote labels with identity and quality kept apart (plan 20 C9/C13, ASTRA2 review section 2).

A blind round can ask two different questions:
  identityGuess      which side Paul thinks Claude made           -> recognizability ("can he still spot Claude?")
  qualityPreference  which side is better, or a tie               -> taste ("which would he keep?")
Rounds 1-3 (r4, r5, r6 pages) asked only "Which one is Claude?". Those votes are identity guesses. They are
never converted into quality labels: a missing quality answer stays "unknown", and an identity guess does not
imply the guessed side was better (in r4 Paul called Luna "Claude" five times, often because Luna's output looked
more finished; in r5 he spotted Claude because it looked more finished; the same click meant different things).

Automatic taste-lesson promotion stays quarantined until the suite holds enough genuine quality labels:
  MIN_DECISIVE_QUALITY_LABELS decisive (C or L, not tie, not unknown) labels from at least MIN_QUALITY_RUNS
  separate blind rounds, and a frozen judge whose leave-one-out agreement on them is strictly above the
  majority-class baseline, abstentions counted as misses.
30 labels is the smallest suite where a judge at 75% true agreement clears a 60% majority baseline by more than
one binomial standard error (sqrt(.25/30) = 0.09); below that, agreement is noise (the v1 judge scored 5/18 on
identity labels, below its 12/18 majority baseline).
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

SCHEMA_V1 = 'neyvia.preference-pairs.v1'
SCHEMA_V2 = 'neyvia.preference-pairs.v2'
ARMS = ('C', 'L')
IDENTITY = {'C', 'L', 'unknown'}
QUALITY = {'C', 'L', 'tie', 'unknown'}
MIN_DECISIVE_QUALITY_LABELS = 30
MIN_QUALITY_RUNS = 3
V1_SOURCE = 'spot-the-claude page: the only question was "Which one is Claude?"; no quality question was asked'


def _other(side):
    return {'A': 'B', 'B': 'A'}[side]


def migrate_v1(data):
    """v1 stored the identity click as paulPickedArm and called it a preference. Keep the click as identityGuess."""
    if data.get('schema') != SCHEMA_V1:
        raise ValueError('Not a v1 preference file')
    pairs = []
    for pair in data['pairs']:
        if pair['paulPickedArm'] not in ARMS:
            raise ValueError('Invalid v1 identity click: ' + pair['pairId'])
        row = {key: deepcopy(value) for key, value in pair.items() if key not in {'paulPick', 'paulPickedArm', 'correct'}}
        row.update(identityGuess=pair['paulPickedArm'], identityCorrect=pair['paulPickedArm'] == 'C',
                   qualityPreference='unknown', reason=None, labelSource=V1_SOURCE)
        pairs.append(row)
    summary = {run: {'identityVotes': row['votes'], 'identityCorrect': row['correct'], 'qualityLabels': 0}
               for run, row in data.get('summary', {}).items()}
    return {'schema': SCHEMA_V2,
            'meaning': ('Blind A/B pairs, Claude (C) against GPT-6 Luna + Neyvia (L). identityGuess is the arm Paul '
                        'thought was Claude; identityCorrect says whether that guess was right. qualityPreference is '
                        'the arm Paul judged better (C, L or tie) and is "unknown" when the page did not ask. An identity '
                        'guess is never a quality label.'),
            'identityReasons': deepcopy(data.get('paulReasons', {})),
            'summary': summary, 'sources': deepcopy(data.get('sources', {})), 'pairs': pairs}


def load(path_or_data):
    """Read a pairs file (v1 is migrated in memory) and validate every label."""
    data = json.loads(Path(path_or_data).read_bytes()) if isinstance(path_or_data, (str, Path)) else path_or_data
    if data.get('schema') == SCHEMA_V1:
        data = migrate_v1(data)
    if data.get('schema') != SCHEMA_V2:
        raise ValueError('Unsupported preference schema')
    seen = set()
    for pair in data['pairs']:
        if pair['pairId'] in seen:
            raise ValueError('Duplicate pair ' + pair['pairId'])
        seen.add(pair['pairId'])
        if pair.get('identityGuess') not in IDENTITY or pair.get('qualityPreference') not in QUALITY:
            raise ValueError('Invalid label on ' + pair['pairId'])
        if 'paulPickedArm' in pair or 'paulPick' in pair:
            raise ValueError('v2 pair carries the conflated v1 field: ' + pair['pairId'])
    return data


def ingest_vote(doc, claude_side):
    """One stored vote document from a blind page -> labels, given the sealed answer (which side was Claude).

    v1 page documents {pairId, pick, correct, reason} answered only the identity question.
    v2 page documents {pairId, identity, quality, reason} answer both; 'unsure' stays unknown.
    """
    if claude_side not in {'A', 'B'}:
        raise ValueError('Answer key must name side A or B')
    arm = {claude_side: 'C', _other(claude_side): 'L'}
    reason = (doc.get('reason') or '').strip() or None
    if doc.get('schema') == 'neyvia.blind-vote.v2':
        identity = doc.get('identity')
        quality = doc.get('quality')
        if identity not in {'A', 'B', 'unsure'} or quality not in {'A', 'B', 'tie', 'unsure'}:
            raise ValueError('Invalid v2 vote document')
        identity_guess = arm.get(identity, 'unknown')
        quality_preference = 'tie' if quality == 'tie' else arm.get(quality, 'unknown')
        source = 'blind page v2: quality and identity asked separately'
    else:
        if doc.get('pick') not in {'A', 'B'}:
            raise ValueError('Invalid v1 vote document')
        identity_guess, quality_preference, source = arm[doc['pick']], 'unknown', V1_SOURCE
    return {'pairId': doc['pairId'], 'identityGuess': identity_guess,
            'identityCorrect': None if identity_guess == 'unknown' else identity_guess == 'C',
            'qualityPreference': quality_preference, 'reason': reason, 'labelSource': source,
            'votedAt': doc.get('at')}


def counts(data):
    data = load(data)
    pairs = data['pairs']
    decisive = [p for p in pairs if p['qualityPreference'] in ARMS]
    return {'pairs': len(pairs),
            'identityKnown': sum(p['identityGuess'] != 'unknown' for p in pairs),
            'identityCorrect': sum(bool(p.get('identityCorrect')) for p in pairs),
            'qualityDecisive': len(decisive),
            'qualityTies': sum(p['qualityPreference'] == 'tie' for p in pairs),
            'qualityUnknown': sum(p['qualityPreference'] == 'unknown' for p in pairs),
            'qualityRuns': len({p['run'] for p in decisive})}


def rows(data, target):
    """(pair, label) for a judge. quality: decisive quality labels only; identity: known identity guesses."""
    data = load(data)
    if target == 'quality':
        return [(p, p['qualityPreference']) for p in data['pairs'] if p['qualityPreference'] in ARMS]
    if target == 'identity':
        return [(p, p['identityGuess']) for p in data['pairs'] if p['identityGuess'] in ARMS]
    raise ValueError('Judge target is quality or identity')


def promotion_status(data, calibration=None):
    """Whether automatic taste-lesson promotion may leave quarantine. calibration is a quality judge's LOO block."""
    tally = counts(data)
    reasons = []
    if tally['qualityDecisive'] < MIN_DECISIVE_QUALITY_LABELS:
        reasons.append(f"{tally['qualityDecisive']}/{MIN_DECISIVE_QUALITY_LABELS} decisive genuine quality labels "
                       f"({tally['identityKnown']} identity guesses do not count)")
    if tally['qualityRuns'] < MIN_QUALITY_RUNS:
        reasons.append(f"quality labels from {tally['qualityRuns']}/{MIN_QUALITY_RUNS} blind rounds")
    if calibration is None or calibration.get('labelKind') != 'qualityPreference':
        reasons.append('no frozen judge calibrated on quality labels')
    elif not calibration.get('total') or calibration['agreement'] is None or \
            calibration['agreement'] <= calibration['majorityBaseline']:
        reasons.append('frozen judge leave-one-out agreement {} is not above the majority baseline {}'.format(
            calibration.get('agreement'), calibration.get('majorityBaseline')))
    return {'quarantined': bool(reasons), 'reasons': reasons, 'counts': tally,
            'thresholds': {'minDecisiveQualityLabels': MIN_DECISIVE_QUALITY_LABELS, 'minQualityRuns': MIN_QUALITY_RUNS,
                           'agreement': 'strictly above the majority-class baseline, abstentions counted as misses'}}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Migrate a v1 pairs file to v2, or report label counts and promotion status')
    parser.add_argument('pairs', type=Path)
    parser.add_argument('--migrate', action='store_true', help='rewrite the file as v2 (identity kept, quality unknown)')
    args = parser.parse_args(argv)
    data = load(args.pairs)
    if args.migrate:
        args.pairs.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(promotion_status(data), indent=1))


if __name__ == '__main__':
    main()
