"""Adversarial BrowserService authorization checks; no rendered proof claim."""
import argparse
import json
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from grant_agent.edge_fixture_c7d_local import _isolate
    root = REPO / '.agent_control/proofs/c7e-authorization' / uuid.uuid4().hex
    _isolate(root, args.port)
    from grant_agent.neyvia_browser import BrowserService, BrowserError
    from grant_agent.proof_contracts import source_digest
    paths = ['src/grant_agent/neyvia_browser.py', 'scripts/prove_C7e_authorization.py']
    before = {p: source_digest(REPO / p) for p in paths}
    service = BrowserService(root)
    token = service.request('runtime.connect', {}, owner=True)['token']
    tab = service.request('tab.open', {'url': f'http://127.0.0.1:{args.port}/validator'}, owner=True)['tabId']
    def runtime(op, **values):
        return service.runtime({'token': token, 'op': op, **values})
    def project(revision):
        runtime('report', event={'type': 'projection', 'tabId': tab, 'projection': {'revision': revision, 'readyState': 'complete', 'elements': [{'id': '1', 'name': 'validator', 'role': 'button', 'actions': ['click']}], 'text': 'supplied validator input', 'url': f'http://127.0.0.1:{args.port}/validator'}})
    def queued():
        project('old')
        service.request('tab.grant', {'tabId': tab, 'enabled': True}, owner=True)
        identity = service.request('action', {'tabId': tab, 'revision': 'old', 'element': '1', 'action': 'click'}, owner=True)['actionId']
        runtime('poll')
        return identity
    def failed(identity):
        runtime('report', event={'type': 'action', 'tabId': tab, 'actionId': identity, 'ok': False, 'error': 'native denial'})
        try:
            service.request('wait', {'actionId': identity, 'timeoutMs': 100}, owner=True)
        except BrowserError as error:
            assert error.code == 'action_failed'
            return error.no_effect_refusal
        raise AssertionError('Failed operation returned success')
    cases = []
    identity = queued()
    project('new')
    assert runtime('authorize', actionId=identity)['authorized'] is False
    refusal = failed(identity)
    assert refusal['code'] == 'stale_projection' and refusal['effectApplied'] is False
    cases.append({'case': 'stale-before-first-authorization', 'refusal': refusal})
    identity = queued()
    service.request('tab.grant', {'tabId': tab, 'enabled': False}, owner=True)
    assert runtime('authorize', actionId=identity)['authorized'] is False
    refusal = failed(identity)
    assert refusal['code'] == 'tab_not_granted' and refusal['effectApplied'] is False
    cases.append({'case': 'revocation-is-not-stale-recovery', 'refusal': refusal})
    identity = queued()
    assert runtime('authorize', actionId=identity)['authorized'] is True
    project('new')
    assert runtime('authorize', actionId=identity)['authorized'] is False
    refusal = failed(identity)
    assert refusal['effectApplied'] is None
    cases.append({'case': 'prior-authorization-preserves-uncertainty', 'refusal': refusal})
    identity = queued()
    service.actions[identity].update(status='failed', error={'code': 'runtime_timeout'})
    try:
        service.request('wait', {'actionId': identity, 'timeoutMs': 100}, owner=True)
    except BrowserError as error:
        assert error.no_effect_refusal is None
    else:
        raise AssertionError('Timeout fabricated completion')
    cases.append({'case': 'timeout-never-claims-no-effect'})
    stable = before == {p: source_digest(REPO / p) for p in paths}
    assert stable
    report = {'schema': 'neyvia.c7e-authorization.v1', 'ok': True, 'sourceStable': stable, 'explicitPort': args.port,
              'sourceBindings': before, 'cases': cases, 'root': str(root),
              'boundary': 'Actual production authorization/wait validators on supplied protocol inputs. No native effect, rendered UI, provider or device proof is claimed.'}
    args.output.resolve().relative_to(REPO / 'scripts/evidence')
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': True, 'cases': len(cases)}))


if __name__ == '__main__':
    main()
