"""Run the bounded small-model CL host against a selected disposable workspace."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from grant_agent.cl.efficient_runner import run

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--task-file', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--layers', nargs='+', default=['workspace'])
    parser.add_argument('--budget', type=int, default=8000)
    parser.add_argument('--max-turns', type=int, default=12)
    parser.add_argument('--goal', action='append', default=[])
    parser.add_argument('--full-history-control', action='store_true')
    parser.add_argument('--full-mechanism-control', action='store_true',
                        help='Disable procedures, diffs, compaction, batching and short stable prefix')
    args = parser.parse_args()
    result = run(args.task_file.read_text(encoding='utf-8'), args.root, args.receipts,
                 layers=args.layers, port=args.port, token_budget=args.budget,
                 max_turns=args.max_turns, efficient=not (args.full_history_control or args.full_mechanism_control),
                 ablate_all=args.full_mechanism_control, goals=args.goal)
    print(json.dumps({k:result[k] for k in ('passed','tokens','failure','elapsedSeconds')}))
    return 0 if result['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
