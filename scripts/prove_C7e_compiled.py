"""Exercise a learned C7 admission procedure through actual Neyvia stdio MCP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manual', default='edge-contracts')
    parser.add_argument('--chapter', default='campaign')
    parser.add_argument('--procedure', default='verify-admission')
    parser.add_argument('--family')
    parser.add_argument('--local-small-state', action='store_true', help='Keep small gateway journals on C; campaign output stays at the explicit D run root')
    parser.add_argument('--replay-from', type=Path, help='Reuse an existing learned script and its owned root; rerun the actual effects and checks')
    parser.add_argument('--resume-root', type=Path, help='Continue admission in an owned workspace; the real compiler still requires two verified runs')
    args = parser.parse_args()
    from grant_agent.proof_ports import c7_port_block, c7_run_root
    try:
        c7_port_block(args.port)
    except ValueError as error:
        parser.error(str(error))
    target = args.output.resolve()
    if not target.is_relative_to(REPO / 'scripts/evidence'):
        target.relative_to(Path(r'D:\NeyviaRuns').resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    prior = None
    if args.replay_from:
        prior_path = args.replay_from.resolve()
        prior_path.relative_to(REPO / 'scripts/evidence')
        prior = json.loads(prior_path.read_bytes())
        if (prior['manual'], prior['procedure'], prior['family'], prior['explicitPort']) != (args.manual, args.procedure, args.family, args.port):
            raise ValueError('Learned replay inputs differ')
    if prior and args.resume_root:
        parser.error('Select learned replay or admission workspace, not both')
    root = (Path(prior['root']).resolve() if prior else args.resume_root.resolve()
            if args.resume_root else (c7_run_root() / 'compiled' if os.environ.get('NEYVIA_C7_RUN_ROOT') and not args.local_small_state
                                     else REPO / '.agent_control/proofs/c7e-compiled') / uuid.uuid4().hex)
    if not root.is_relative_to(REPO / '.agent_control/proofs/c7e-compiled'):
        root.relative_to(c7_run_root() / 'compiled')
    if args.resume_root and not (root / '.neyvia/manual-runs.jsonl').is_file():
        raise ValueError('Admission workspace has no actual run journal')
    from grant_agent.edge_fixture_c7d_local import _isolate
    _isolate(root, args.port)
    if args.family:
        workspace = REPO / '.agent_control/C7e/compiled-families' / (args.family + '.workspace.json')
        workspace.parent.mkdir(parents=True, exist_ok=True)
        workspace.write_text(json.dumps({'family': args.family, 'port': args.port, 'root': str(root)}) + '\n', encoding='utf8')
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    if not prior and not args.resume_root:
        prepare_broker_fixture(root)
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    from grant_agent.neyvia_manuals import unwrap
    answers = queue.Queue()
    transcript = []
    with (root / 'stdio-errors.log').open('wb') as errors:
        child = subprocess.Popen([sys.executable, '-m', 'grant_agent.neyvia_mcp_stdio', '--root', str(root), '--read-only', '--session-id', 'c7e-compiled'],
                                 cwd=REPO, env={**os.environ, 'PYTHONPATH': str(REPO / 'src')}, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=errors, text=True, encoding='utf8', **hidden_windows_subprocess_kwargs())
        def read():
            for line in child.stdout:
                answers.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        def rpc(tool, arguments):
            identity = len(transcript) + 1
            child.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': identity, 'method': 'tools/call', 'params': {'name': tool, 'arguments': arguments}}) + '\n')
            child.stdin.flush()
            answer = answers.get(timeout=10830 if args.family else 600)
            with target.with_suffix('.rpc.jsonl').open('a', encoding='utf8') as trace:
                trace.write(json.dumps({'tool': tool, 'arguments': arguments, 'answer': answer}) + '\n')
            if answer.get('id') != identity or answer.get('error'):
                raise ValueError(answer)
            result = unwrap(answer['result']['structuredContent'])
            if result.get('ok') is False:
                raise ValueError(result)
            transcript.append({'tool': tool, 'arguments': arguments, 'result': result})
            return result
        try:
            rpc('neyvia.manual.load', {'id': args.manual, 'chapter': args.chapter, 'maxChars': 8000})
            inputs = {'port': args.port}
            procedure = {'id': args.manual, 'chapter': args.chapter, 'procedure': args.procedure, 'inputs': inputs}
            fresh_runs = 0
            for _ in range(0 if prior or args.resume_root else 2):
                result = rpc('neyvia.manual.run', procedure)
                if result['status'] != 'completed' or not all(r['passed'] for r in result['checks']):
                    raise ValueError('Unverified training trace')
                fresh_runs += 1
            if prior:
                compiled = {'scriptId': prior['compiledScriptId']}
            else:
                for attempt in range(3):
                    try:
                        compiled = rpc('neyvia.manual.compile', {**procedure, 'minRuns': 2})
                        break
                    except (RuntimeError, ValueError) as error:
                        if not args.resume_root or 'Compilation needs 2 verified successful runs' not in str(error) or attempt == 2:
                            raise
                    result = rpc('neyvia.manual.run', procedure)
                    if result['status'] != 'completed' or not all(r['passed'] for r in result['checks']):
                        raise ValueError('Unverified resumed training trace')
                    fresh_runs += 1
            replay = rpc('neyvia.manual.script.run', {'scriptId': compiled['scriptId'], 'inputs': inputs})
            if replay['status'] != 'completed' or not all(r['passed'] for r in replay['checks']):
                raise ValueError('Compiled replay failed its original verifiers')
            final = rpc('neyvia.verify.edges.status', {'family': args.family} if args.family else {})
            if not final['sourceCurrent'] or not final['receiptIntact']:
                raise ValueError('Compiled replay lost source binding')
            if args.family and not final.get('allApplicableCasesPassed'):
                raise ValueError('Compiled family replay contains missing, blocked or failed cases')
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=15)
    report = {'schema': 'neyvia.c7e-compiled.v1', 'ok': True, 'explicitPort': args.port, 'root': str(root),
              'campaignRoot': str(c7_run_root()), 'localSmallState': args.local_small_state,
              'transport': 'actual hidden Neyvia stdio MCP process', 'compiledScriptId': compiled['scriptId'],
              'verifiedUncompiledRuns': 2, 'compiledReplayChecks': replay['checks'], 'finalStatus': final,
              'freshUncompiledRuns': fresh_runs,
              'resumedAdmissionWorkspace': str(args.resume_root.resolve()) if args.resume_root else None,
              'trainingTraceOrigin': ({'path': prior_path.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(prior_path.read_bytes()).hexdigest()} if prior else None),
              'manual': args.manual, 'procedure': args.procedure, 'family': args.family,
              'sourceBindings': {'scripts/prove_C7e_compiled.py': hashlib.sha256(Path(__file__).read_text(encoding='utf8').encode()).hexdigest()},
              'boundary': ('Actual generated cases in the selected family; real rendering is not implied by model cases.' if args.family
                           else 'Generated admission cases only; semantic and rendered fixtures remain the separate full native campaign.')}
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': True, 'compiledScriptId': compiled['scriptId'], 'checks': len(replay['checks'])}))


if __name__ == '__main__':
    main()
