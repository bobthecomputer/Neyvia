"""Plan-25 target adapter: the P22 release gate (``scripts/gate.py``) as an evolvable task.

The gate is measured in a private sparse clone of a pinned ``track/p22`` commit; nothing
here edits ``track/p22`` or its worktree. Two tasks share one adapter:

* ``gate-plan``: ``contract_gate.run()`` with every subprocess step stubbed (impact
  selection, bindings, job setup, receipt). Outputs = the normalised gate receipt.
* ``cl-compile``: ``scripts/cl_compile_manuals.py --check``, the gate's critical-path
  step. Outputs = stdout, receipt and any raised error.

Each task has train cases (cheap judge), held-out cases and perturbations (the real test
that cannot be faked: edits to the measured tree, cold caches, repeats, renames).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / 'scripts/evolve_gate_runner.py'
PYTHON = os.environ.get('NEYVIA_SYSTEM_PYTHON') or sys.executable
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# Gate receipt roots live on the SSD during measurement (the real gate writes them to the USB
# disk D:, whose latency spikes would swamp the compute being compared).
GATE_ROOTS = REPO / '.agent_control/evolve/gate-roots'

# Perturbation edits: (path, kind, payload). Applied to the working tree, then restored
# byte-for-byte with the original modification time.
GATE_PERTURBATIONS = {
    'edit-import': [('src/grant_agent/compaction_policy.py', 'append', '\nimport grant_agent.contract_coverage  # evolve perturbation\n')],
    'new-proof': [('manuals/cl/proofs.cl', 'append', '-- @proof {"id":"evolve.perturbation","phase":"post","claim":"Perturbation","checkedAt":["grant_agent.contract_coverage.model"],"impact":["Evolve perturbation"]}\n')],
}
GATE_PERTURBATIONS['edit-import-latest'] = [('src/grant_agent/compaction_policy.py', 'append', '\nimport grant_agent.contract_web_reach  # evolve perturbation\n')]
GATE_PERTURBATIONS['new-proof-latest'] = [('manuals/cl/proofs.cl', 'append', '-- @proof {"id":"evolve.perturbation","phase":"post","claim":"Perturbation","checkedAt":["grant_agent.contract_web_reach"],"impact":["Evolve perturbation"]}\n')]
COMPILE_PERTURBATIONS = {
    'edit-cl': [('manuals/cl/hello-module.cl', 'replace', ('deterministic local action, not an AI model call.', 'deterministic local action.', 2))],
    'edit-source': [('src/grant_agent/evolver_laya.py', 'append', '\n# evolve perturbation\n')],
    'invalid-schema': [('manuals/cl/local-evolver.cl', 'replace', ('T t2 json:"{\\"type\\":\\"object\\"}"', 'T t2 json:"{\\"type\\":\\"objekt\\"}"', 1))],
}

TASKS = {
    'gate-plan': {
        'objective': ('Wall seconds of the gate process before and after its subprocess steps: a release diff with a warm '
                      'module cache plus a commit gate on a cold cache (first gate after checkout)'),
        'targets': ['src/grant_agent/contract_gate.py', 'src/grant_agent/contract_coverage.py', 'src/grant_agent/durability.py'],
        # Warm-only measurements were swamped by machine noise (+-50% wall for 2-10% effects); the cold
        # case is the gate's largest own cost and keeps the measured effect above the noise.
        'train': [{'id': 'release-HEAD~5', 'task': 'plan', 'since': 'HEAD~5', 'build': True},
                  {'id': 'cold-commit-HEAD~1', 'task': 'plan', 'since': 'HEAD~1', 'build': False, 'cold': True}],
        'heldout': [{'id': 'commit-HEAD~1', 'task': 'plan', 'since': 'HEAD~1', 'build': False},
                    {'id': 'release-HEAD~12', 'task': 'plan', 'since': 'HEAD~12', 'build': True},
                    # Added after r3: a warm cache hides every change to the parse path, so a cold
                    # release diff with web sources is the only check that exercises it (r3's final
                    # dropped '..' JS import edges and passed every warm check).
                    {'id': 'cold-release-HEAD~12', 'task': 'plan', 'since': 'HEAD~12', 'build': True, 'cold': True},
                    {'id': 'commit-HEAD~3', 'task': 'plan', 'since': 'HEAD~3', 'build': False},
                    {'id': 'focused-paths', 'task': 'plan', 'since': 'HEAD~1', 'build': False,
                     'paths': ['src/grant_agent/contract_gate.py', 'web/src/main.jsx', 'docs/README.md']}],
        'perturbations': [{'id': 'edit-import', 'base': 'commit-HEAD~1', 'edits': 'edit-import'},
                          {'id': 'new-proof', 'base': 'commit-HEAD~1', 'edits': 'new-proof'},
                          {'id': 'repeat', 'base': 'release-HEAD~5', 'repeat': True},
                          {'id': 'rename', 'base': 'rename-HEAD~1', 'tree': 'rename'}],
        # Default Git rename detection lists only the new path of a committed exact move, so the
        # rename case names both paths explicitly (as a focused --paths run does).
        'extraCases': {'rename-HEAD~1': {'id': 'rename-HEAD~1', 'task': 'plan', 'since': 'HEAD~1', 'build': False,
                                         'paths': ['src/grant_agent/evolver_laya.py', 'src/grant_agent/evolver_laya_moved.py']}},
        'cold': {'id': 'cold-commit-HEAD~1', 'task': 'plan', 'since': 'HEAD~1', 'build': False},
        'stateDir': '.agent_control/p22',
    },
    # The same gate task on the latest track/p22 commit (the second similar task): P22 rewrote
    # run() and added a coverage ratchet; refs and perturbation anchors follow that history.
    'gate-plan-latest': {
        'objective': ('Wall seconds of the gate process before and after its subprocess steps: a commit gate over five commits '
                      'with a warm module cache plus a commit gate on a cold cache (first gate after checkout)'),
        'targets': ['src/grant_agent/contract_gate.py', 'src/grant_agent/contract_coverage.py', 'src/grant_agent/durability.py',
                    'src/grant_agent/contract_measurements.py', 'src/grant_agent/contract_diff.py'],
        # Build mode of this gate reads and writes P22's live build cache under D:/NeyviaRuns/P22, so the
        # latest task measures the gate in commit (skip-build) mode only; the planning code is the same.
        'train': [{'id': 'commit-HEAD~5', 'task': 'plan', 'since': 'HEAD~5', 'build': False},
                  {'id': 'cold-commit-HEAD~3', 'task': 'plan', 'since': 'HEAD~3', 'build': False, 'cold': True}],
        'heldout': [{'id': 'commit-HEAD~3', 'task': 'plan', 'since': 'HEAD~3', 'build': False},
                    {'id': 'commit-HEAD~1', 'task': 'plan', 'since': 'HEAD~1', 'build': False},
                    {'id': 'commit-HEAD~12', 'task': 'plan', 'since': 'HEAD~12', 'build': False},
                    {'id': 'cold-commit-HEAD~25', 'task': 'plan', 'since': 'HEAD~25', 'build': False, 'cold': True},
                    {'id': 'focused-paths', 'task': 'plan', 'since': 'HEAD~1', 'build': False,
                     'paths': ['src/grant_agent/contract_gate.py', 'web/src/main.jsx', 'docs/README.md']}],
        'perturbations': [{'id': 'edit-import', 'base': 'commit-HEAD~3', 'edits': 'edit-import-latest'},
                          {'id': 'new-proof', 'base': 'commit-HEAD~3', 'edits': 'new-proof-latest'},
                          {'id': 'repeat', 'base': 'commit-HEAD~5', 'repeat': True},
                          {'id': 'rename', 'base': 'rename-HEAD~1', 'tree': 'rename'}],
        'extraCases': {'rename-HEAD~1': {'id': 'rename-HEAD~1', 'task': 'plan', 'since': 'HEAD~1', 'build': False,
                                         'paths': ['src/grant_agent/evolver_laya.py', 'src/grant_agent/evolver_laya_moved.py']}},
        'cold': {'id': 'cold-commit-HEAD~3', 'task': 'plan', 'since': 'HEAD~3', 'build': False},
        'stateDir': '.agent_control/p22',
    },
    'cl-compile': {
        'objective': 'Wall seconds of scripts/cl_compile_manuals.py --check',
        'targets': ['scripts/cl_compile_manuals.py', 'src/grant_agent/cl/manuals.py', 'src/grant_agent/cl/schema.py',
                    'src/grant_agent/cl/parser.py', 'src/grant_agent/module_map.py', 'src/grant_agent/manual_contracts.py'],
        'train': [{'id': 'check', 'task': 'compile'}],
        'heldout': [],
        'perturbations': [{'id': 'edit-cl', 'base': 'check', 'edits': 'edit-cl'},
                          {'id': 'edit-source', 'base': 'check', 'edits': 'edit-source'},
                          {'id': 'invalid-schema', 'base': 'check', 'edits': 'invalid-schema'},
                          {'id': 'repeat', 'base': 'check', 'repeat': True}],
        'extraCases': {},
        'cold': None,
        'stateDir': None,
    },
}


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def git(tree, *args):
    return subprocess.check_output(['git', *args], cwd=tree, text=True, encoding='utf-8', creationflags=NO_WINDOW).strip()


class GateTarget:
    """Runs cases for one task against candidate file sets in the measurement trees."""

    def __init__(self, task: str, tree: Path, scratch: Path, *, rename_tree: Path | None = None):
        self.name = task
        self.spec = TASKS[task]
        self.tree = Path(tree).resolve()
        self.rename_tree = Path(rename_tree).resolve() if rename_tree else None
        self.scratch = Path(scratch)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.commit = git(self.tree, 'rev-parse', 'HEAD')
        self.baseline = {rel: (self.tree / rel).read_text(encoding='utf-8') for rel in self.spec['targets']}
        self.states = {}
        self.runs = 0
        self.lock()

    # ---------------------------------------------------------------- candidate files and cache state
    def materialise(self, files: dict[str, str]) -> Path:
        digest = sha(json.dumps(files, sort_keys=True))[:16]
        folder = self.scratch / 'candidates' / digest
        overlay = folder / 'overlay.json'
        if not overlay.is_file():
            mapping = {}
            for rel, text in files.items():
                path = folder / 'files' / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8', newline='')
                mapping[rel] = str(path)
            overlay.write_text(json.dumps(mapping), encoding='utf-8')
        return overlay

    def _state_dir(self, tree):
        return tree / self.spec['stateDir'] if self.spec['stateDir'] else None

    def snapshot(self, tree):
        directory = self._state_dir(tree)
        if directory is None or not directory.is_dir():
            return {}
        return {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob('*') if path.is_file()}

    def restore(self, tree, snapshot):
        """Make the state directory hold exactly the snapshot (in place; retries brief file locks)."""
        directory = self._state_dir(tree)
        if directory is None:
            return
        for attempt in range(20):
            try:
                if directory.exists():
                    for path in sorted(directory.rglob('*'), reverse=True):
                        rel = path.relative_to(directory).as_posix()
                        if path.is_file() and rel not in snapshot:
                            path.unlink()
                        elif path.is_dir() and not any(path.iterdir()):
                            path.rmdir()
                for rel, data in snapshot.items():
                    path = directory / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if not path.is_file() or path.read_bytes() != data:
                        path.write_bytes(data)
                return
            except PermissionError:
                time.sleep(0.25)
        raise PermissionError(f'State directory stayed locked: {directory}')

    def lock(self):
        """One engine per measurement tree: concurrent edits would corrupt every comparison."""
        import psutil
        path = self.tree.parent / (self.tree.name + '.lock')
        if path.exists():
            try:
                pid = int(path.read_text())
            except ValueError:
                pid = 0
            if pid and pid != os.getpid() and psutil.pid_exists(pid):
                raise RuntimeError(f'Measurement tree in use by process {pid}')
        path.write_text(str(os.getpid()))

    # ---------------------------------------------------------------- one measured process
    def run(self, files, case, *, tree=None, profile=None, timeout=900):
        tree = tree or self.tree
        overlay = self.materialise(files)
        self.runs += 1
        out = self.scratch / 'runs' / f'{self.runs:06d}.json'
        root = GATE_ROOTS / f'{self.name}-{self.runs % 8}'
        command = [PYTHON, str(RUNNER), '--tree', str(tree), '--overlay', str(overlay), '--task', case['task'],
                   '--root', str(root), '--out', str(out)]
        if case.get('since'):
            command += ['--since', case['since']]
        if case.get('build'):
            command.append('--build')
        if case.get('paths'):
            command += ['--paths', *case['paths']]
        if profile:
            command += ['--profile', str(profile)]
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        env.pop('PYTHONPATH', None)
        started = time.perf_counter()
        try:
            completed = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True, encoding='utf-8',
                                       errors='replace', timeout=timeout, creationflags=NO_WINDOW)
            wall = time.perf_counter() - started
        except subprocess.TimeoutExpired:
            return {'status': 'timeout', 'outputSha256': None, 'wall': timeout, 'case': case['id']}
        try:
            result = json.loads(out.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            result = {'status': 'crash', 'outputSha256': None, 'stderr': completed.stderr[-2000:]}
        result['wall'] = wall
        result['case'] = case['id']
        return result

    # ---------------------------------------------------------------- warm state per file set
    def warm(self, files, *, tree=None):
        """Run once from the baseline warm state; keep the resulting state for this file set."""
        tree = tree or self.tree
        if self.spec['stateDir'] is None:
            return {}
        key = (sha(json.dumps(files, sort_keys=True)), str(tree))
        if key in self.states:
            return self.states[key]
        base_key = (sha(json.dumps(self.baseline, sort_keys=True)), str(tree))
        if base_key in self.states:
            self.restore(tree, self.states[base_key])
        self.run(files, self.spec['train'][0], tree=tree)
        self.states[key] = self.snapshot(tree)
        return self.states[key]

    def measure(self, files, case, *, tree=None, profile=None):
        tree = tree or self.tree
        state = {} if case.get('cold') else self.warm(files, tree=tree)
        self.restore(tree, state)
        return self.run(files, case, tree=tree, profile=profile)

    # ---------------------------------------------------------------- perturbations (the real test)
    def _edit(self, tree, edits):
        saved = []
        for rel, kind, payload in self._edits(edits):
            path = tree / rel
            info = path.stat()
            original = path.read_bytes()
            saved.append((path, original, info.st_atime_ns, info.st_mtime_ns))
            text = original.decode('utf-8')
            if kind == 'append':
                text = text + payload
            elif kind == 'replace':
                old, new, count = payload
                if old not in text:
                    raise ValueError(f'Perturbation anchor missing in {rel}')
                text = text.replace(old, new, count)
            path.write_bytes(text.encode('utf-8'))
        return saved

    @staticmethod
    def _edits(name):
        return GATE_PERTURBATIONS.get(name) or COMPILE_PERTURBATIONS.get(name) or []

    @staticmethod
    def _undo(saved):
        for path, original, atime, mtime in reversed(saved):
            path.write_bytes(original)
            os.utime(path, ns=(atime, mtime))

    def case(self, identity):
        for row in self.spec['train'] + self.spec['heldout']:
            if row['id'] == identity:
                return row
        return self.spec['extraCases'][identity]

    def check(self, files, check_id):
        """Run one named check for a file set; returns (output digest, run row)."""
        for row in self.spec['train'] + self.spec['heldout']:
            if row['id'] == check_id:
                result = self.measure(files, row)
                return result
        perturbation = next(p for p in self.spec['perturbations'] if p['id'] == check_id)
        base = self.case(perturbation['base'])
        if perturbation.get('tree') == 'rename':
            if self.rename_tree is None:
                return {'status': 'not available', 'outputSha256': None, 'case': check_id}
            return {**self.measure(files, base, tree=self.rename_tree), 'case': check_id}
        if perturbation.get('cold'):
            self.restore(self.tree, {})
            result = self.run(files, base)
            return {**result, 'case': check_id}
        if perturbation.get('repeat'):
            first = self.measure(files, base)
            second = self.run(files, base)  # same process state left by the first run
            same = first.get('outputSha256') == second.get('outputSha256')
            return {**first, 'outputSha256': first.get('outputSha256') if same else 'nondeterministic:' + str(second.get('outputSha256')),
                    'case': check_id}
        state = self.warm(files)
        saved = self._edit(self.tree, perturbation['edits'])
        try:
            self.restore(self.tree, state)
            result = self.run(files, base)
        finally:
            self._undo(saved)
        return {**result, 'case': check_id}

    def all_checks(self):
        return [row['id'] for row in self.spec['train'] + self.spec['heldout']] + [p['id'] for p in self.spec['perturbations']]

    def train_checks(self):
        return [row['id'] for row in self.spec['train']]


def make_rename_tree(source_tree: Path, target: Path, *, commit: str) -> Path:
    """A private clone whose HEAD adds one exact source rename on top of the pinned commit."""
    target = Path(target)
    if (target / '.git').is_dir() and git(target, 'rev-parse', 'HEAD~1') == commit:
        return target
    if target.exists():
        # A private clone of an earlier pinned commit; git writes its object files read-only on Windows.
        def writable(function, path, _error):
            os.chmod(path, 0o666)
            function(path)
        shutil.rmtree(target, onexc=writable)
    origin = git(source_tree, 'config', '--get', 'remote.origin.url')
    subprocess.check_call(['git', 'clone', '-q', '--shared', '--no-checkout', origin, str(target)], creationflags=NO_WINDOW)
    subprocess.check_call(['git', 'sparse-checkout', 'init', '--no-cone'], cwd=target, creationflags=NO_WINDOW)
    (target / '.git/info/sparse-checkout').write_text('/*\n!/proof/\n!/docs/\n!/scripts/evidence/\n', encoding='utf-8')
    subprocess.check_call(['git', 'checkout', '-q', '--detach', commit], cwd=target, creationflags=NO_WINDOW)
    subprocess.check_call(['git', 'mv', 'src/grant_agent/evolver_laya.py', 'src/grant_agent/evolver_laya_moved.py'], cwd=target, creationflags=NO_WINDOW)
    subprocess.check_call(['git', '-c', 'user.name=EVOLVE', '-c', 'user.email=evolve@localhost', 'commit', '-q', '-m',
                           'Evolve perturbation: exact source rename'], cwd=target, creationflags=NO_WINDOW)
    return target
