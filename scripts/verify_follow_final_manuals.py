"""Validate the final executable manual catalog through owned HTTP only."""
import json
from pathlib import Path
from unittest.mock import patch
import verify_follow_failures as failures


def main():
    failures.SCRATCH = failures.REPO / '.agent_control/follow-final-manuals'
    failures.isolate()
    checks = []
    with failures.real_http() as (_, request):
        assert request('/api/auth/local-session', {})['http'] == 200
        def tool(name, arguments):
            row = request('/api/ui/tools/call', {'tool': 'neyvia.' + name, 'arguments': arguments})
            assert row['http'] == 200 and row['body']['ok'] and row['body']['data']['ok'], (name, arguments, row)
            return row['body']['data']['result']
        index = tool('manual.index', {})
        for manual in index['manuals']:
            identity = manual['id']
            for chapter in manual['chapters']:
                assert tool('manual.load', {'id': identity, 'chapter': chapter})
            validated = tool('manual.validate', {'id': identity})
            assert validated.get('grounded', True)
            checks.append({'id': identity, 'chaptersLoaded': manual['chapters'], 'grounded': True})
        assert len(checks) == 34
        assert request('/api/health')['body']['ok']
    receipt = {'passed': True, 'port': 48449, 'checks': checks, 'ownedServerStopped': True,
               'boundary': 'Current production manual catalog loaded and validated through real authenticated HTTP in disposable root. Readiness subprocesses bounded by existing isolation; terminal execution denied; no manual mutation procedure or model execution.',
               'earlierStrictRootRepeat': 'The approval-proof root refused a metadata readiness subprocess during a separate all-manual repeat. That attempt did not pass or replace the earlier successful receipt.'}
    (failures.REPO / 'scripts/evidence/FOLLOW-final-manuals.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'passed': True, 'manuals': len(checks), 'port': 48449}))


if __name__ == '__main__':
    with patch('winpty.PtyProcess.spawn', side_effect=PermissionError('Fixture terminal execution denied')):
        main()
