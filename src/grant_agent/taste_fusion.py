"""Sol concept/draft/final crops, Luna reading/repairs, one measured arm budget."""
from pathlib import Path
import json
from .taste_model import invoke, object_schema
from .taste_gate import save, digest


def read_brief(task, brief, manual, folder, budget):
    from .taste_context import compact_manual
    schema = object_schema({'notes': {'type': 'string'}, 'research': {'type': 'array', 'items': object_schema({
        'name': {'type': 'string'}, 'used': {'type': 'boolean'}, 'source': {'type': 'string'},
        'sourceKind': {'type': 'string'}, 'why': {'type': 'string'}})}})
    prompt = ('Read the brief and executable rules. Return a concise implementation briefing, not HTML. '
              'For a landing page research is empty. For rare UI search primary HCI sources once: '
              'choose 6 uncommon mechanisms that can really work with pointer, keyboard and touch, plus 6 alternatives. '
              'Return exact paper titles, authors, venue, year, defining mechanism and verified URLs in why. '
              'Keep the subject distinct from fungi. This is the only search in the fusion arm.\n' +
              compact_manual(manual, rare=task == 'T2') + '\nTASK:\n' + brief)
    response, usage = invoke(prompt, folder / 'reading', schema, model='gpt-6-luna', search=task == 'T2',
                             effort='low', bounded=True, budget=budget)
    return response


def rollback_if_worse(host, current, row, folder):
    rounds = host.taste.rounds[str(current.resolve())]
    accepted_path = folder / 'accepted.json'
    accepted = json.loads(accepted_path.read_text()) if accepted_path.exists() else None
    score = row['critique']['quality']
    common_before = {c['check']: c for c in rounds[accepted['round'] - 1]['pageChecks']['checks']} if accepted else {}
    worsened = any(not c['passed'] and common_before.get(c['check'], {}).get('passed') for c in row['pageChecks']['checks'])
    rejected = bool(accepted and score < accepted['quality'])
    if rejected:
        previous = rounds[accepted['round'] - 1]
        snapshot = Path(previous['folder']) / 'artifact.html'
        before = digest(current)
        current.write_bytes(snapshot.read_bytes())
        host.invalidate_done()
        save(folder / ('rollback-' + str(row['round']) + '.json'), {'rejectedSha256': before,
             'restoredSha256': digest(current), 'quality': score, 'acceptedQuality': accepted['quality'],
             'reason': 'Lower score; paid evidence retained', 'newlyFailingChecks': worsened})
        # Keep rejected evidence, but resume repair from the accepted observation.
        host.taste.repairs.pop(str(current.resolve()), None)
        rounds.pop()
        save(host.taste.out() / 'rounds.json', host.taste.rounds)
        return previous
    save(accepted_path, {'round': row['round'], 'quality': score, 'blocks': row['pageChecks']['blocks'], 'sha256': row['sha256']})
    return row


def final_pass(host, current, folder, brief):
    from .taste_context import image_packet
    rounds = host.taste.rounds[str(current.resolve())]
    accepted = json.loads((folder / 'accepted.json').read_text())
    row = rounds[accepted['round'] - 1]
    verdict = folder / 'sol-final/verdict.json'
    if verdict.exists():
        prior = json.loads(verdict.read_bytes())
        if prior['artifactSha256'] == digest(current):
            return prior
    images, manifest = image_packet(row['interaction'], 'Final', folder / 'sol-final/packet',
                                  max_images=2, max_actions=0, overview_only=True)
    schema = object_schema({'quality': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                            'verdict': {'type': 'string', 'enum': ['ready', 'repair']},
                            'reason': {'type': 'string'}, 'repair': {'type': 'string'}})
    budget = host.taste.model_budget
    budget.protected_usd = 0
    response, usage = invoke('Final taste pass on these two rendered crops. State one concrete remaining fix if needed. '
        'Do not invent missing whole-page evidence. <=150 words.\nTASK:\n' + brief + '\nCROPS:\n' + json.dumps(manifest),
        folder / 'sol-final', schema, images=images, model='gpt-6.1-sol', effort='low', bounded=True,
        budget=budget, reservation_tokens=19000, reservation_usd=.04)
    save(folder / 'sol-final/verdict.json', {**response, 'artifactSha256': digest(current), 'usage': usage})
    return response
