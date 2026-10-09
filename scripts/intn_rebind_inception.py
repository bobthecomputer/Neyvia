"""Rebind unchanged C8 contract closures; refuse semantic changes for review."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual
from grant_agent.neyvia_inception import inventory, validate_bindings
from grant_agent.neyvia_manuals import get_manual, records


def digest(value):
    # CL may retain numeric page-map keys; JSON artifacts necessarily stringify
    # them. Compare the actual JSON contract, then sort its string keys.
    value = json.loads(json.dumps(value, ensure_ascii=False))
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def blob(ref, path):
    return subprocess.check_output(['git', 'show', ref + ':' + path], cwd=ROOT)


def closure(manual, identity):
    parts = identity.split('/')
    chapter = manual['chapters'][parts[1]]
    if len(parts) == 4 and parts[2] == '@check':
        return {'check': chapter['checks'][parts[3]]}
    procedure = chapter['procedures'][parts[2]]
    return {'procedure': procedure,
            'actions': {step['action']: chapter['actions'][step['action']]
                        for step in procedure['steps'] if 'action' in step},
            'checks': {step['check']: chapter['checks'][step['check']]
                       for step in procedure['steps'] if 'check' in step},
            'judges': {step['judge']: chapter['judge'][step['judge']]
                       for step in procedure['steps'] if 'judge' in step}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='8051fb4b9')
    parser.add_argument('--apply-unchanged', action='store_true')
    parser.add_argument('--reviews', type=Path, help='Exact before/after closures with explicit integrator review reasons')
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    path = ROOT / 'config/inception_journeys.json'
    bindings = json.loads(path.read_text(encoding='utf-8'))
    catalog = inventory()
    current = {row['id']: row for row in catalog['rows']}
    old_records = {row['id']: row for row in json.loads(blob(args.base, 'config/neyvia_manuals.json'))['manuals']}
    old, changes, refused = {}, [], []
    reviews = json.loads(args.reviews.read_text(encoding='utf-8')) if args.reviews else {}
    for identity, binding in bindings.items():
        row = current.get(identity)
        if row is None:
            refused.append({'id': identity, 'reason': 'Coverage row removed'})
            continue
        if binding['sourceHash'] == row['sourceHash']:
            continue
        name = row['manual']
        try:
            if name not in old:
                record = old_records[name]
                raw = blob(args.base, record.get('clSource', record['path']))
                manual = cl_to_manual(raw.decode('utf-8')) if record.get('clSource') else json.loads(raw)
                old[name] = (raw, manual)
            raw, manual = old[name]
            # Git may store LF while the authored run hashed a CRLF checkout.
            candidates = {hashlib.sha256(value).hexdigest() for value in
                          (raw, raw.replace(b'\r\n', b'\n'), raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))}
            if binding['sourceHash'] not in candidates:
                raise ValueError('Original binding does not match this source revision')
            _, _, latest = get_manual(name)
            before, after = (json.loads(json.dumps(closure(source, identity), ensure_ascii=False))
                             for source in (manual, latest))
            if before != after:
                review = reviews.get(identity, {})
                if (review.get('beforeClosureSha256') != digest(before)
                        or review.get('afterClosureSha256') != digest(after)
                        or not review.get('reason')):
                    refused.append({'id': identity, 'reason': 'Contract closure changed', 'before': before, 'after': after,
                                    'observedBeforeSha256': digest(before), 'observedAfterSha256': digest(after), 'review': review})
                    continue
            changes.append({'id': identity, 'beforeHash': binding['sourceHash'],
                            'afterHash': row['sourceHash'], 'contractClosureUnchanged': before == after,
                            **({'review': reviews[identity]} if before != after else {})})
            binding['sourceHash'] = row['sourceHash']
        except (KeyError, ValueError, subprocess.CalledProcessError) as exc:
            refused.append({'id': identity, 'reason': str(exc)})
    if args.apply_unchanged:
        path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    receipt = {'base': args.base, 'applied': args.apply_unchanged, 'unchanged': changes,
               'requiresReview': refused, 'validation': validate_bindings(catalog, bindings)}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'unchanged': len(changes), 'requiresReview': len(refused),
                      'invalid': len(receipt['validation']['errors']), 'unbound': len(receipt['validation']['unbound'])}))
    return 0 if not refused and receipt['validation']['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
