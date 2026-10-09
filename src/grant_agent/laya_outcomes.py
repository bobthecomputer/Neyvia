"""Durable app outcome queue: posting is outside the user action's critical path."""
from pathlib import Path
import json
import urllib.request
from .durability import atomic_write_json
from .laya_client.contracts import digest


def enqueue(root, question, state, correct, evidence, decision_id=None):
    value = {'question': question, 'state': state, 'correct': correct, 'evidence': evidence}
    name = digest(value) + '.json'
    folder = Path(root) / '.neyvia/laya/outcomes'
    posted = folder / 'posted' / name
    pending = folder / 'pending' / name
    if posted.exists():
        return {'serviceOutcome': json.loads(posted.read_text())['serviceOutcome']}
    if not pending.exists():
        atomic_write_json(pending, {**value, 'decisionId': decision_id})
    return {'serviceOutcomePending': str(pending)}


def flush(root):
    from .laya_hooks import SET, SCOPES
    from .laya_service import endpoint
    folder = Path(root) / '.neyvia/laya/outcomes'

    def post(route, payload):
        request = urllib.request.Request(endpoint() + route, json.dumps(payload).encode(),
                                         {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response)

    # Bound each pass so a cold/unavailable service cannot starve vote ingestion.
    for path in list((folder / 'pending').glob('*.json'))[:5]:
        value = None
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            outcome = None
            if value.get('serviceError') and value.get('decisionId'):
                # A timed-out POST may already have committed. Recover that receipt
                # before retrying so copies do not consume the service memory quota.
                with urllib.request.urlopen(endpoint() + '/v1/memory', timeout=3) as response:
                    memory = json.load(response)
                match = next((row for row in memory.get('rows', []) if row.get('decision_id') == value['decisionId']
                              and row.get('correct') == value['correct'] and row.get('evidence') == value['evidence']), None)
                if match:
                    outcome = {'outcome_id': match['outcome_id'], 'generation': memory['generation'], 'durable': True}
            if not value.get('decisionId'):
                decision = post('/v1/decide', {'set': SET, 'questions': [value['question']],
                    'state': value['state'], 'scope': SCOPES[value['question']], 'client': 'neyvia-outcome-binding'})
                value['decisionId'] = decision['decision_id']
                atomic_write_json(path, value)
            if outcome is None:
                outcome = post('/v1/outcome', {'decision_id': value['decisionId'], 'question': value['question'],
                    'correct': value['correct'], 'kind': 'verified_effect', 'evidence': value['evidence']})
            value['serviceOutcome'] = outcome
            value.pop('serviceError', None)
            atomic_write_json(path, value)
            destination = folder / 'posted' / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.replace(destination)  # Preserve the complete receipt after posting.
        except Exception as exc:
            if isinstance(value, dict):
                value['serviceError'] = type(exc).__name__
                atomic_write_json(path, value)
