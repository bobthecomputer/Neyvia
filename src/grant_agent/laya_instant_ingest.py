"""Provenance-preserving local vote/experience ingestion, outside the query path."""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
from .laya_instant import store

_WORKERS = {}
_LOCK = threading.Lock()
_SEEN = {}


def experience(root, domain, input, signal, source, user='', value=None, elapsedSeconds=0):
    corrective = {'kept', 'reverted', 'contract-pass', 'contract-fail', 'verifier-pass', 'verifier-fail'}
    personal = {'edit-distance', 'accept-time', 'reask', 'different-route'}
    if signal not in corrective | personal:
        raise ValueError('Unknown experience signal')
    if signal == 'reverted' and not 0 <= elapsedSeconds <= 120:
        return {'learned': False, 'reason': 'outside-undo-window'}
    label = signal in {'kept', 'contract-pass', 'verifier-pass'} if signal in corrective else str(value if value is not None else signal)
    return store(str(root)).learn(domain, input, label, source, user=user,
        layer='corrective' if signal in corrective else 'personal', weight=.35,
        evidence={'signal': signal, 'value': value, 'elapsedSeconds': elapsedSeconds, 'implicit': True})


def rows(value):
    """Identity guesses are retained in their own domain, never quality labels."""
    if isinstance(value, dict) and {'domain', 'input', 'label'} <= value.keys():
        row = {k: v for k, v in value.items() if k in {'domain', 'input', 'label', 'user', 'layer', 'weight', 'evidence'}}
        if isinstance(row['label'], dict):
            label = row['label']
            if 'vote' in label and ('tie' in label or 'abstain' in label):
                # A comparative quality vote belongs to this pair, not to a
                # general claim that a model/author is better in every context.
                vote = label.get('vote')
                abstain, tie = bool(label.get('abstain')), bool(label.get('tie'))
                if (abstain and tie) or (not abstain and not tie and vote not in {'A', 'B'}):
                    raise ValueError('Invalid comparative personal vote')
                if vote in {'A', 'B'}:
                    # The direct vote file puts arm identities in input; C13i's
                    # screenshot export puts them beside the vote in label.
                    arm = row['input'].get(vote, label.get(vote))
                    if arm is None or label.get('winner') != arm:
                        raise ValueError('Vote and declared winner disagree')
                    if vote in row['input'] and vote in label and row['input'][vote] != label[vote]:
                        raise ValueError('Conflicting comparative arm identities')
                yield {**row, 'domain': 'personal-abstention' if abstain else 'personal',
                    'label': 'abstain' if abstain else 'tie' if tie else vote, 'layer': 'personal', 'user': 'paul',
                    'evidence': {'label': label, 'source': value.get('source'), 'at': value.get('at'),
                                 'pairScoped': True, 'motionObserved': False}}
                if value.get('feedback'):
                    yield {'domain': 'personal-guidance', 'input': {'feedback': value['feedback'], 'source': value.get('source')},
                        'label': value['feedback'], 'layer': 'personal', 'user': 'paul',
                        'evidence': {'at': value.get('at'), 'motionObserved': False, 'qualityBound': False}}
                return
            kind = label.get('kind') or ('aspect' if label.get('aspect') or row['input'].get('evidenceKind') == 'reason-only' else None)
            row['domain'] = 'author-identity' if kind == 'identity' else 'personal-guidance' if kind == 'aspect' else 'personal' if row['layer'] == 'personal' else 'retention'
            row['label'] = label['keep'] if label.get('keep') is not None else (label.get('value') or label.get('reason') or kind)
            if isinstance(row['label'], (dict, list)):
                row['label'] = json.dumps(row['label'], sort_keys=True)
            row['evidence'] = {'label': label, 'source': value.get('source'), 'episodeId': value.get('episodeId')}
            if kind == 'aspect':
                row['input'] = {**row['input'], 'aspect': label.get('aspect'), 'guidance': row['label']}
                row['evidence']['qualityBound'] = False
            if kind == 'workflow-retention':
                row['weight'] = min(.35, row.get('weight', 1))
            if row['layer'] == 'personal':
                row['user'] = 'paul'
        yield row
    elif isinstance(value, dict) and 'pairId' in value:
        quality = value.get('better')
        label = quality if quality is not None else value.get('pick')
        if label is not None:
            yield {'domain': 'personal' if quality is not None else 'author-identity',
                   'input': {'pairId': value['pairId'], 'run': value.get('run')}, 'label': label,
                   'user': 'paul', 'layer': 'personal', 'evidence': value}
    elif isinstance(value, dict):
        for round in value.get('rounds', []):
            for reason in round.get('reasons', []):
                yield {'domain': 'personal-guidance', 'input': reason, 'label': reason,
                       'user': 'paul', 'layer': 'personal', 'evidence': {'round': round.get('round'), 'qualityBound': False}}
        for vote in value.get('votes', []):
            if vote.get('qualityPreference'):
                yield {'domain': 'personal', 'input': {'pair': vote['pair'], 'round': value.get('round')},
                       'label': vote['qualityPreference'], 'user': 'paul', 'layer': 'personal', 'evidence': vote}
        for name, text in value.get('followup', {}).items():
            yield {'domain': 'personal-guidance', 'input': {'aspect': name, 'round': value.get('round')},
                   'label': text, 'user': 'paul', 'layer': 'personal', 'evidence': {'qualityBound': False}}
    elif isinstance(value, list):
        for row in value:
            yield from rows(row)


def ingest(root, *, changed_only=False):
    origin = Path(os.environ.get('NEYVIA_INSTANT_VOTES', str(Path(__file__).resolve().parents[3] / 'nx-c13-taste/proof')))
    inbox = Path(os.environ.get('NEYVIA_INSTANT_LABELS', 'D:/NeyviaRuns/laya-labels'))
    paths = list((origin / 'votes-export').rglob('*.json')) + [origin / 'r10/paul-votes.json'] + list(inbox.glob('*.jsonl'))
    result = {'learned': 0, 'existing': 0, 'files': 0, 'errors': []}
    for path in paths:
        if not path.is_file():
            continue
        result['files'] += 1
        stamp = (path.stat().st_size, path.stat().st_mtime_ns)
        watch_key = (str(Path(root).resolve()), str(path.resolve()))
        if changed_only and _SEEN.get(watch_key) == stamp:
            continue
        local = store(str(root))
        local.refresh()
        if str(path.resolve()) in local.forgotten:
            continue
        try:
            error_count = len(result['errors'])
            raw = path.read_text(encoding='utf-8-sig')
            values = [json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix == '.jsonl' else [json.loads(raw)]
            file_counts = {'learned': 0, 'existing': 0}
            with local.import_batch():
                for value in values:
                    if isinstance(value, dict) and value.get('input', {}).get('evidenceKind') == 'reason-only':
                        # Retire a prior import that misclassified free-text
                        # C13 guidance as a categorical visual preference.
                        from .laya_instant import latest_episodes
                        for old in latest_episodes(local.rows):
                            if old.get('source') == str(path.resolve()) and old.get('domain') == 'personal' and old.get('input') == value['input'] and old.get('split') != 'holdout':
                                local.learn('personal', old['input'], old['label'], old['source'],
                                    user=old['user'], layer=old['layer'], split='holdout',
                                    evidence={'retiredReason': 'guidance-is-not-a-quality-vote'})
                    for index, row in enumerate(rows(value)):
                        # Stable provenance permits replacement and forgetting, independent of file mtime.
                        try:
                            response = local.learn(source=str(path.resolve()), split='train', **row)
                            file_counts['learned' if response['learned'] else 'existing'] += 1
                        except (OSError, ValueError, KeyError, TypeError) as exc:
                            result['errors'].append({'file': str(path), 'row': index, 'reason': str(exc)[:200]})
            for key, count in file_counts.items():
                result[key] += count
            if len(result['errors']) == error_count:
                _SEEN[watch_key] = stamp
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result['errors'].append({'file': str(path), 'reason': str(exc)[:200]})
    return result


def watch(root):
    key = str(Path(root).resolve())
    with _LOCK:
        if key in _WORKERS:
            return
        stop = threading.Event()
        def worker():
            while not stop.is_set():
                try:
                    harvest_browser_outcomes(key)
                    from .laya_outcomes import flush
                    flush(key)
                    ingested = ingest(key, changed_only=True)
                    if ingested['learned']:
                        from .laya_instant_consolidate import consolidate
                        consolidate(key)
                except Exception:
                    pass  # Explicit ingest reports errors; the UI never stalls on a partial label file.
                stop.wait(5)
        thread = threading.Thread(target=worker, name='laya-instant-labels', daemon=True)
        _WORKERS[key] = (thread, stop)
        thread.start()


def harvest_browser_outcomes(root):
    """Learn from durable task predicates, across HTTP, desktop and tool callers."""
    from .laya_hooks import learn_outcome, page_done_state
    from .browser_task import check_predicates
    from .durability import atomic_write_json
    folder = Path(root) / '.neyvia/laya/browser-outcomes'
    for path in (Path(root) / '.neyvia/browser/tasks').glob('*-task.json'):
        receipt = folder / path.name
        if receipt.exists():
            continue
        try:
            task = json.loads(path.read_text(encoding='utf-8'))
            checks = task.get('verification', {}).get('checks', [])
            predicates = task.get('checks') or [row['predicate'] for row in checks]
            observation = task.get('observation', {})
            # Only explicit predicates with fresh independently measured results
            # admit done/not-done. An exhausted budget is not a negative label.
            if not predicates or not observation.get('revision'):
                continue
            verified = check_predicates(observation, predicates)['verified']
            evidence = next((p['contains'] for p in predicates if p.get('path') == '/text' and
                             isinstance(p.get('contains'), str)), None)
            if not evidence:
                continue
            from .laya_client.browser_client import project_grounded_state
            current = project_grounded_state(observation, {'goal': task['goal']})['current']
            state = page_done_state(task['goal'], {'url': observation.get('url'), 'title': observation.get('title')},
                current, [], evidence)
            # Predicate-only completion has no synthetic action receipt.
            learned = learn_outcome(root, 'page_done', state, verified,
                {'receipt': str(path), 'verifier': 'browser-task-predicates', 'passed': True,
                 'goalVerified': verified, 'predicates': predicates})
            if learned.get('learned') or learned.get('reason') == 'already-ingested':
                atomic_write_json(receipt, learned)
        except (OSError, ValueError, KeyError, TypeError):
            continue
