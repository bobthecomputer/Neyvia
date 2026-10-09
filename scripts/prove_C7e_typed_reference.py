"""Generated C7 contract cases for fixed-port manual reference admission."""
import argparse
import itertools
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    from grant_agent.manual_contracts import template
    from jsonschema import ValidationError
    from grant_agent.proof_contracts import source_digest
    paths = ['src/grant_agent/manual_contracts.py', 'scripts/prove_C7e_typed_reference.py']
    bindings = {name: source_digest(REPO / name) for name in paths}
    target = {'type': 'integer', 'minimum': 48741, 'maximum': 48749}
    cases = []
    values = [48741, 48742, 48744, 48745, 48749, 48740, 48750, '48741', None, True]
    for reference, value in itertools.product(('input', 'result'), values):
        source = {'type': 'integer', 'const': value}
        inputs = {'type': 'object', 'properties': {'port': source}, 'required': ['port']}
        arguments = {'$input': 'port'} if reference == 'input' else {'$result': 'saved.port'}
        expected = type(value) is int and value in range(48741, 48750)
        try:
            template(arguments, target, inputs, {'saved': {'type': 'object', 'properties': {'port': source}}})
            admitted = True
        except (ValueError, TypeError, ValidationError):
            admitted = False
        if admitted != expected:
            raise AssertionError((reference, value, expected, admitted))
        cases.append({'id': f'c7e.typed-reference.{reference}.{len(cases)}', 'status': 'passed',
                      'admitted': admitted, 'expected': expected})
    if bindings != {name: source_digest(REPO / name) for name in paths}:
        raise ValueError('Typed reference sources changed')
    target_path = args.output.resolve()
    target_path.relative_to(REPO / 'scripts/evidence')
    report = {'schema': 'neyvia.c7e-typed-reference.v1', 'ok': True, 'explicitPort': args.port,
              'cases': cases, 'sourceBindings': bindings, 'sourceStable': True,
              'boundary': 'Actual production typed-reference validator; supplied values only, no socket calls or rendered claim.'}
    target_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': True, 'cases': len(cases)}))


if __name__ == '__main__':
    main()
