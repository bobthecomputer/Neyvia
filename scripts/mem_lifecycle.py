"""Run authored memory CL procedures against disposable, real gateway stores."""
from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cue_memory import MemoryContext, CueMemoryStore
from grant_agent.neyvia_gateway import NeyviaToolGateway


def gateway(context):
    host = NeyviaToolGateway(context.project_path, action_root=context.root, action_scope='memory-contract',
        allow_mutations=True, allowed_mutation_tools={'neyvia.memory.remember', 'neyvia.memory.correct', 'neyvia.memory.forget'}, managed_capabilities=False)
    host.memory_context = context
    host.cl_task_text = 'launch signal'
    host.task_goal_root = context.root
    return host


def main():
    root = REPO / '.agent_control/mem/contracts' / uuid.uuid4().hex
    project = root / 'project-a'
    project.mkdir(parents=True)
    context = MemoryContext(root, 'contract-owner', project, 'user-turn-a', 'user_turn', True, True)
    host = gateway(context)
    rows = []
    def run(label, lines, current=host, expected=True):
        result = current.call_native('neyvia.cl', {'lines': lines})
        rows.append({'label': label, 'expectedOk': expected, 'observedOk': result.get('ok'), 'result': result})
        if result.get('ok') is not expected:
            path = REPO / 'scripts/evidence/MEM-lifecycle.json'
            path.write_text(json.dumps({'ok': False, 'root': str(root), 'procedures': rows}, indent=2), encoding='utf-8')
            raise RuntimeError(label + ' diverged; actual receipt saved')
    # Every successful gate is an authored procedure or explicit observer G.
    run('teach', 'G: "mint-seven" in memory.recall(situation={"intent":"launch signal"})["section"]\n'
        'run memory.remember(key="launch signal", content="mint-seven", cues={"intent":["launch signal"]}, exportPolicy="provider", requestId="teach-a")')
    record = CueMemoryStore(context).snapshot()['memories'][0]
    identity = json.dumps(record['id'])
    run('new-context-recall', 'run memory.recall-known(query="launch signal", expectedContent="mint-seven")', gateway(context))
    run('other-project', 'run memory.recall-empty(query="launch signal")', gateway(replace(context, project_path=root/'project-b')))
    run('other-user', 'run memory.recall-empty(query="launch signal")', gateway(replace(context, owner='second-user')))
    run('unrelated-cue', 'run memory.recall-empty(query="garden irrigation")')
    run('correct', 'G: "coral-eight" in memory.recall(situation={"intent":"launch signal"})["section"]\n'
        f'run memory.correct(id={identity}, expectedRevision=1, key="launch signal", content="coral-eight", cues={{"intent":["launch signal"]}}, exportPolicy="provider", requestId="correct-a")')
    run('current-revision', f'run memory.inspect-current(id={identity}, expectedContent="coral-eight")')
    run('stale-correction-refused', 'G: "coral-eight" in memory.recall(situation={"intent":"launch signal"})["section"]\n'
        f'run memory.correct(id={identity}, expectedRevision=1, key="launch signal", content="stale-write", requestId="stale-a")', expected=False)
    # Use a fresh interpreter after the deliberately refused procedure.
    host = gateway(context)
    run('forget', 'G: memory.recall(situation={"intent":"launch signal"})["tokens"] == 0\n'
        f'run memory.forget(id={identity}, expectedRevision=2, requestId="forget-a")', host)
    run('reopened-deleted-cue', 'run memory.recall-empty(query="launch signal")', gateway(context))
    run('local-only-write', 'G: "birch-nine" in memory.recall(situation={"intent":"private signal"})["section"]\n'
        'run memory.remember(key="private signal", content="birch-nine", cues={"intent":["private signal"]}, requestId="local-a")', gateway(context))
    run('local-only-provider-filter', 'run memory.recall-empty(query="private signal")', gateway(replace(context, channel='provider')))
    run('local-only-provider-inspect-refused', 'memory.inspect(id=' + json.dumps(CueMemoryStore(context).snapshot()['memories'][0]['id']) + ')', gateway(replace(context, channel='provider')), False)
    receipt = {'ok': True, 'boundary': 'Production gateway and authored CL; disposable synthetic scopes, not provider chat or rendered UI.',
               'root': str(root), 'procedures': rows}
    (REPO/'scripts/evidence/MEM-lifecycle.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'procedureCount': len(rows), 'root': str(root)}))


if __name__ == '__main__':
    main()
