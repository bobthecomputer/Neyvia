"""Evidence script: run one gate target from a candidate overlay inside a measurement tree.

The plan-25 evolving engine (grant_agent.evolve_engine) calls this in a fresh process per
measurement, exactly as the gate itself starts. Candidate files replace target modules
through an import overlay whose ``__file__`` is the real tree path, so the code under
measurement sees the same repository, caches and Git history as the original.

Tasks
  plan     gate.py run() with every subprocess step stubbed: impact selection, bindings,
           job setup and receipt, i.e. the gate's own overhead before and after its steps.
  compile  scripts/cl_compile_manuals.py --check (the gate's critical-path sub-step).
  worker   gate.py --worker <job.json> (the gate's own CL contract area runner).

Outputs are normalised (durations and the scratch root removed) and hashed; the engine
compares hashes, never the candidate's own claims.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time


def install_overlay(tree: Path, overlay: dict[str, str]) -> None:
    mapping = {}
    for rel, candidate in overlay.items():
        if rel.startswith('src/') and rel.endswith('.py'):
            module = rel[len('src/'):-3].replace('/', '.')
            package = module.endswith('.__init__')
            module = module.removesuffix('.__init__')
            mapping[module] = (Path(candidate), tree / rel, package)

    class Overlay(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, name, path=None, target=None):
            if name not in mapping:
                return None
            _, real, package = mapping[name]
            return importlib.util.spec_from_file_location(
                name, real, loader=self, submodule_search_locations=[str(real.parent)] if package else None)

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            candidate, real, _ = mapping[module.__name__]
            source = candidate.read_bytes()
            # Harness-only path redirect (same for baseline and candidates): newer gates hard-code
            # P22's own data folder for worker state; contract runs here must never write there.
            for pair in filter(None, os.environ.get('EVOLVE_REDIRECT', '').split(';')):
                old, new = pair.split('=>')
                source = source.replace(old.encode(), new.encode())
            exec(compile(source, str(real), 'exec'), module.__dict__)

    sys.meta_path.insert(0, Overlay())


def normalise(value, root: Path):
    variants = sorted({str(root), root.as_posix(), str(root).replace('\\', '\\\\')}, key=len, reverse=True)
    def walk(item):
        if isinstance(item, dict):
            return {key: walk(child) for key, child in item.items() if key not in {'durationMs', 'transcriptionMs'}}
        if isinstance(item, list):
            return [walk(child) for child in item]
        if isinstance(item, str):
            for variant in variants:
                item = item.replace(variant, '<ROOT>')
            return item
        return item
    return walk(value)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def task_plan(tree: Path, args) -> dict:
    from grant_agent import contract_gate as gate

    def stubbed(command, root, timeout, env=None):
        return {'ok': True, 'exitCode': 0, 'timedOut': False, 'durationMs': 0, 'logs': str(root)}

    gate.process = stubbed
    # Measurement roots live on the SSD (see evolve_gate.GATE_ROOTS); the check itself is unchanged.
    gate.output_root = lambda path, small=False: Path(path).resolve()
    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    started = time.perf_counter()
    import inspect
    options = dict(changed=args.paths, root=root, workers=1, timeout=240, build=args.build, committed_only=True, ports=(49087, 49088))
    if 'coverage_map' in inspect.signature(gate.run).parameters:
        # Never read or write P22's live execution cache: a private map inside the measured state.
        options['coverage_map'] = tree / '.agent_control/p22/execution-cache.json'
    report = gate.run(args.since, **options)
    elapsed = time.perf_counter() - started
    output = normalise(report, root)
    shutil.rmtree(root, ignore_errors=True)
    return {'output': output, 'innerSeconds': elapsed}


def task_compile(tree: Path, args) -> dict:
    receipt = Path(args.root) / 'compile-receipt.json'
    shutil.rmtree(receipt.parent, ignore_errors=True)
    script = tree / 'scripts/cl_compile_manuals.py'
    source = Path(args.script_overlay).read_bytes() if args.script_overlay else script.read_bytes()
    sys.argv = [str(script), '--check', '--receipt', str(receipt)]
    namespace = {'__name__': '__main__', '__file__': str(script)}
    buffer = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buffer):
        exec(compile(source, str(script), 'exec'), namespace)
    elapsed = time.perf_counter() - started
    output = {'stdout': buffer.getvalue(), 'receipt': json.loads(receipt.read_text(encoding='utf-8'))}
    shutil.rmtree(receipt.parent, ignore_errors=True)
    return {'output': output, 'innerSeconds': elapsed}


def task_worker(tree: Path, args) -> dict:
    from grant_agent import contract_gate as gate
    spec_source = Path(args.job)
    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    spec = root / 'job.json'
    spec.write_bytes(spec_source.read_bytes())
    buffer = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buffer):
        code = gate.worker(spec)
    elapsed = time.perf_counter() - started
    outcomes = json.loads((root / 'outcomes.json').read_text(encoding='utf-8'))
    witnessed = sorted({identity for case in outcomes.get('cases', []) if case.get('ok') is True for identity in case.get('contracts', [])})
    return {'output': {'exitCode': code, 'ok': outcomes.get('ok'), 'witnessed': witnessed,
                       'missingWitnesses': outcomes.get('missingWitnesses', [])}, 'innerSeconds': elapsed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, help='JSON {repo-relative path: candidate file}')
    parser.add_argument('--task', choices=['plan', 'compile', 'worker'], required=True)
    parser.add_argument('--since')
    parser.add_argument('--paths', nargs='+')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--job', help='worker job JSON')
    parser.add_argument('--root', required=True, help='scratch directory under D:/NeyviaRuns')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profile', type=Path, help='write cProfile stats of the task here')
    args = parser.parse_args()
    tree = args.tree.resolve()
    overlay = json.loads(args.overlay.read_text(encoding='utf-8')) if args.overlay else {}
    args.script_overlay = overlay.pop('scripts/cl_compile_manuals.py', None)
    sys.path.insert(0, str(tree / 'src'))
    install_overlay(tree, overlay)
    os.chdir(tree)
    status = 'ok'
    task = {'task_plan': task_plan, 'task_compile': task_compile, 'task_worker': task_worker}['task_' + args.task]
    profiler = None
    if args.profile:
        import cProfile
        profiler = cProfile.Profile()
        profiler.enable()
    try:
        result = task(tree, args)
    except BaseException as error:  # the engine records every failure as a judged outcome
        message = str(error).replace(str(tree), '<TREE>').replace(tree.as_posix(), '<TREE>')
        result = {'output': None, 'error': f'{type(error).__name__}: {message}'[:2000]}
        status = 'error'
    if profiler:
        profiler.disable()
        profiler.dump_stats(str(args.profile))
    result.update(status=status, outputSha256=digest({'output': result.get('output'), 'error': result.get('error')}),
                  cpuSeconds=time.process_time())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, sort_keys=True, ensure_ascii=False), encoding='utf-8')
    return 0 if status == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
