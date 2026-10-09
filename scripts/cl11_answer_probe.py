"""Real native image read plus explicit-answer transport and refusal journey."""
from pathlib import Path
import json
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.benchmark11_fixtures import Fixture11, DEV_TASKS
from grant_agent.cl.host import HostContext
from grant_agent.cl.provider11 import native

task = next(row for row in DEV_TASKS if row['id'] == 105)
fixture = Fixture11(task, REPO / '.agent_control/cl11/answer-proof' / uuid.uuid4().hex, port=48289)
try:
    provider = native('Read the development chart using Read. Submit its total as one JSON object. '
                      'Wrap that object in a JSON fence and add one short prose sentence. '
                      'Use only this fixture; do not inspect any other path. Fixture: ' +
                      json.dumps(fixture.native_manifest()), 'claude-alone', fixture.root / 'native',
                      fixture_root=fixture.root, image=fixture.visual_paths[0], timeout=120, claude_budget=.08)
    fixture.accept_native_answer(provider['answer'], image_evidence=provider['imageEvidence'])
    independent = fixture.check()
    host = HostContext(fixture.tools(), fixture.dispatch, contracts=fixture.contract,
                       procedures=fixture.procedures(), goals=task['goal'], root=fixture.root)
    done = host.execute('done("native image evidence and explicit answer")')
    checks = {'actual_native_image_read': provider['passed'] and bool(provider['imageEvidence']),
              'prose_fenced_object_accepted': independent['passed'] and done['ok']}
    refused = []
    for text in ('{"total":67}\n{"total":67}', '{"broken":invalid,"nested":{"total":67}}', 'The total is 67.'):
        fixture.answers.clear()
        fixture.accept_native_answer(text, image_evidence=provider['imageEvidence'])
        result = host.execute('done("ambiguous or missing explicit object")')
        refused.append({'answer': text, 'done': result, 'independent': fixture.check()})
    checks['ambiguous_malformed_and_prose_only_refused'] = all(not row['done']['ok'] and not row['independent']['passed'] for row in refused)
    path = REPO / 'scripts/evidence/CL11-answer-after.json'
    path.write_text(json.dumps({'allPassed': all(checks.values()), 'checks': checks, 'provider': provider,
                                'independent': independent, 'done': done, 'refused': refused}, indent=2),
                    encoding='utf-8', newline='\n')
    print(json.dumps({'allPassed': all(checks.values()), 'checks': checks, 'receipt': str(path)}))
    raise SystemExit(0 if all(checks.values()) else 1)
finally:
    fixture.close()
