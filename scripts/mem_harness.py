"""Bounded local CL transport when an attached MCP is not exposed by the client.

Uses the production gateway, permissions, executable manuals and effect checks.
No alternate handlers or synthetic successful results.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=REPO / '.agent_control/mem/harness')
    parser.add_argument('--project', type=Path, default=REPO)
    parser.add_argument('--layer')
    parser.add_argument('--lines')
    parser.add_argument('--lines-file', type=Path)
    parser.add_argument('--exercise', action='store_true', help='Grant the owned pinned CL contract drivers local execution')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--task', default='')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    gateway = NeyviaToolGateway(args.project, action_root=args.root, action_scope='mem-harness',
        allow_mutations=True, allowed_mutation_tools={'workspace.write', 'workspace.patch',
        'neyvia.memory.remember', 'neyvia.memory.correct', 'neyvia.memory.forget'} | ({'terminal.exec'} if args.exercise else set()),
        permission_mode='full-access' if args.exercise else 'workspace',
        managed_capabilities=False)
    gateway.cl_task_text = args.task
    gateway.task_goal_root = args.root
    # This local runner owns only its disposable synthetic fixture identity.
    # Production MCP without a launcher-bound context continues to refuse.
    from grant_agent.cue_memory import MemoryContext
    gateway.memory_context = MemoryContext(args.root, 'mem-contract-owner', args.project,
        'manual-contract', 'user_action', True, True)
    lines = args.lines_file.read_text(encoding='utf-8') if args.lines_file else args.lines
    if lines:
        result = gateway.call_native('neyvia.cl', {'lines': lines})
    else:
        result = gateway.call_native('neyvia.cl.describe', {'layer': args.layer} if args.layer else {'primer': True})
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: result.get(key) for key in ('ok', 'status')} if args.quiet else result, ensure_ascii=False))
    if result.get('ok') is False:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
