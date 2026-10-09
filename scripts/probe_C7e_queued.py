"""Capture actual concurrent queued reconciliation outcomes without changing owners."""
import argparse
import json
from pathlib import Path
import sys
import threading
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=8)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    if args.runs not in range(1, 65):
        parser.error('Bounded 1-64 runs required')
    args.output.resolve().relative_to(REPO / 'scripts/evidence')
    root = REPO / '.agent_control/proofs/c7e-queued' / uuid.uuid4().hex
    root.mkdir(parents=True)
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.fluxio_harness import FluxioHarness
    from grant_agent.edge_fixture_c7d_control import _delegated_queue
    from grant_agent.proof_contracts import source_digest
    sources = ('src/grant_agent/runtime_supervisor.py', 'src/grant_agent/durability.py', 'src/grant_agent/harness_jobs.py',
               'src/grant_agent/fluxio_harness.py', 'src/grant_agent/edge_fixture_c7d_control.py', 'scripts/probe_C7e_queued.py')
    bindings = {n:source_digest(REPO / n) for n in sources}
    original = FluxioHarness._reconcile_delegated_sessions
    observations, runs = [], []
    lock = threading.Lock()
    def observed(*values, **kwargs):
        result = original(*values, **kwargs)
        sessions, status, trigger = result
        steps = values[1][-1].steps
        row = {'status':status, 'trigger':trigger, 'sessions':[{k:s.get(k) for k in ('status','detail','acknowledged','exit_code','heartbeat_status','cluster_job_id')} for s in sessions],
               'steps':[{'status':s.status,'attempts':s.attempts} for s in steps], 'risks':values[4]}
        with lock:
            observations.append(row)
        return result
    FluxioHarness._reconcile_delegated_sessions = staticmethod(observed)
    try:
        for index in range(args.runs):
            area = root / str(index)
            area.mkdir()
            try:
                _delegated_queue(area, 'concurrency', 'a-cli.scheduler.queued')
                runs.append({'status':'passed'})
            except Exception as error:
                runs.append({'status':'failed','type':type(error).__name__,'error':str(error)})
    finally:
        FluxioHarness._reconcile_delegated_sessions = staticmethod(original)
    stable = bindings == {n:source_digest(REPO / n) for n in sources}
    report = {'schema':'neyvia.c7e-queued-probe.v1', 'ok':stable and all(r['status']=='passed' for r in runs), 'sourceStable':stable, 'explicitPort':args.port, 'runs':runs, 'observations':observations,
              'sourceBindings':bindings, 'boundary':'Actual production reconciliation; wrapper records outcomes and does not substitute results'}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok':report['ok'], 'runs':len(runs), 'failedRuns':[r for r in runs if r['status']=='failed'], 'unexpected':[r for r in observations if r['status']!='running' or r['trigger'] or r['risks'] or any(s['status']!='in_progress' or s['attempts']!=3 for s in r['steps'])]}))
    return int(not report['ok'])


if __name__ == '__main__':
    raise SystemExit(main())
