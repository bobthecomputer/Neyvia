"""Plan-25 evolving engine: populations, real judges, a move library that grows, an adversary.

One engine for code, vision, 3D, animation and models; a domain supplies a *target*
(files, cases, perturbations, a runner). This module owns the rest:

* **Spec** - a CL skill (``manuals/cl/evolve.cl``): ``-- @spec`` objective, must-hold
  constraints and budget per task; ``-- @predicate`` judge vocabulary; ``C`` acceptance.
* **Population** - three mutation sources: LAYA's move library (``evolve-moves.cl``,
  deterministic rewrites or a move instantiated by Luna), free Luna edits on hot
  functions, and a big-model idea call when progress plateaus (hard cap per run).
* **Pre-filter** - plan-21 episodes (domain ``scene:evolve-move``) predict which
  proposals deserve a run; exact replays of known losers die in milliseconds; a sample
  of killed proposals is run anyway to measure the pre-filter.
* **Judges, layered** - static compile; cheap checks judged by scene_core predicates;
  paired timing; the real test (held-out cases and perturbations); the target's CL
  contracts; one model look; Paul. A judge's weight is the share of its accepts that
  held up in every later layer (judge-the-judge).
* **Adversary** - exploit rewrites (fast and wrong) hunt for score-high/fail-real
  candidates; each exploit found becomes a predicate plus a promoted cheap check.
* **Archive** - MAP-Elites cells (family x footprint) and a Pareto set; elites cross over.
* **Capabilities evolve** - a winning change becomes a reusable move (CL procedure plus
  context) and an episode; moves that keep failing in one context (task, file) are retired
  there only and stay available elsewhere.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import pstats
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import uuid

from . import evolve_moves as moves_lib

REPO = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO / 'manuals/cl/evolve.cl'
MOVES_PATH = REPO / 'manuals/cl/evolve-moves.cl'
EPISODE_DOMAIN = 'scene:evolve-move'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
BUDGET_HOLD = Path('C:/Users/user/Projects/plans/logs/codex-budget.hold')
MODELS = {'luna': 'gpt-6-luna', 'sol': 'gpt-6.1-sol'}


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def sha(value):
    return hashlib.sha256((value if isinstance(value, str) else canonical(value)).encode('utf-8')).hexdigest()


def load_spec(path=SPEC_PATH):
    """``-- @spec`` and ``-- @predicate`` lines of the evolve CL skill."""
    specs, predicates = {}, []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith('-- @spec '):
            row = json.loads(line[len('-- @spec '):])
            specs[row['task']] = row
        elif line.startswith('-- @predicate '):
            predicates.append(json.loads(line[len('-- @predicate '):]))
    return specs, predicates


def footprint(base: dict, files: dict) -> int:
    changed = 0
    for rel, text in files.items():
        if base.get(rel) != text:
            changed += sum(1 for line in difflib.unified_diff(base.get(rel, '').splitlines(), text.splitlines(), lineterm='', n=0)
                           if line[:1] in '+-' and not line.startswith(('+++', '---')))
    return changed


def patch(base: dict, files: dict, prefix='') -> str:
    out = []
    for rel in sorted(files):
        if base.get(rel) != files[rel]:
            out.extend(difflib.unified_diff(base.get(rel, '').splitlines(keepends=True), files[rel].splitlines(keepends=True),
                                            fromfile='a/' + rel, tofile='b/' + rel))
    return ''.join(out)


# ==================================================================== model routes

class ModelBudgetError(RuntimeError):
    pass


class Models:
    """Luna and the big model through the existing Codex CLI route; every call logged."""

    def __init__(self, state: Path, caps: dict):
        self.state = Path(state)
        self.raw = self.state / 'model-calls'
        self.raw.mkdir(parents=True, exist_ok=True)
        self.sandbox = self.state / 'model-sandbox'
        self.sandbox.mkdir(parents=True, exist_ok=True)
        self.log = self.state / 'model-calls.jsonl'
        self.caps = dict(caps)
        self.used = Counter()
        if self.log.exists():
            for line in self.log.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                if row.get('run') == os.environ.get('NEYVIA_EVOLVE_RUN'):
                    self.used[row['tier']] += 1

    def remaining(self, tier):
        return self.caps.get(tier, 0) - self.used[tier]

    def ask(self, tier, prompt, schema, *, label, effort='low'):
        if self.remaining(tier) <= 0:
            raise ModelBudgetError(f'{tier} call cap reached ({self.caps.get(tier)})')
        if BUDGET_HOLD.exists():
            raise ModelBudgetError('Codex budget watchdog hold is active')
        executable = shutil.which('codex.cmd') or shutil.which('codex')
        if not executable:
            raise ModelBudgetError('Codex CLI unavailable; no substitute model is permitted')
        model = MODELS[tier]
        stem = self.raw / f'{label}-{uuid.uuid4().hex[:10]}'
        schema_path = stem.with_suffix('.schema.json')
        schema_path.write_text(json.dumps(schema), encoding='utf-8')
        stem.with_suffix('.prompt.txt').write_text(prompt, encoding='utf-8')
        command = [executable, 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check',
                   '--sandbox', 'read-only', '--json', '--cd', str(self.sandbox), '--model', model,
                   '-c', f'model_reasoning_effort="{effort}"', '-c', 'features.shell_tool=false',
                   '-c', 'features.multi_agent=false', '-c', 'web_search="disabled"', '--output-schema', str(schema_path), '-']
        self.used[tier] += 1
        started = time.time()
        row = {'at': now(), 'run': os.environ.get('NEYVIA_EVOLVE_RUN'), 'tier': tier, 'model': model, 'label': label,
               'effort': effort, 'promptChars': len(prompt)}
        try:
            result = subprocess.run(command, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=600, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            row.update(ok=False, error='timeout', seconds=round(time.time() - started, 2))
            self._log(row)
            return None, row
        stem.with_suffix('.stdout.jsonl').write_text(result.stdout, encoding='utf-8')
        events = []
        for line in result.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        messages = [e['item']['text'] for e in events if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
        usage = next((e.get('usage') for e in reversed(events) if e.get('type') == 'turn.completed'), None)
        row.update(seconds=round(time.time() - started, 2), usage=usage, exitCode=result.returncode, raw=str(stem.with_suffix('.stdout.jsonl')))
        answer = None
        if result.returncode == 0 and messages:
            try:
                answer = json.loads(messages[-1])
            except ValueError:
                row['error'] = 'invalid JSON'
        else:
            row['error'] = (result.stderr or '')[-400:]
        row['ok'] = answer is not None
        self._log(row)
        return answer, row

    def _log(self, row):
        with self.log.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row) + '\n')


EDIT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['idea', 'family', 'new_source', 'imports'],
               'properties': {'idea': {'type': 'string'}, 'family': {'type': 'string', 'enum': ['caching', 'io', 'algorithmic', 'parallel', 'startup', 'redundancy', 'other']},
                              'new_source': {'type': 'string'}, 'imports': {'type': 'array', 'items': {'type': 'string'}}}}
IDEA_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['idea', 'move', 'edits'],
               'properties': {'idea': {'type': 'string'},
                              'move': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'family', 'applies_when', 'match', 'cl'],
                                       'properties': {'id': {'type': 'string'}, 'family': {'type': 'string'}, 'applies_when': {'type': 'string'},
                                                      'match': {'type': 'string'}, 'cl': {'type': 'string'}}},
                              'edits': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                        'required': ['file', 'function', 'new_source', 'imports'],
                                        'properties': {'file': {'type': 'string'}, 'function': {'type': 'string'}, 'new_source': {'type': 'string'},
                                                       'imports': {'type': 'array', 'items': {'type': 'string'}}}}}}}
GENERALISE_SCHEMA = IDEA_SCHEMA['properties']['move']
REVIEW_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['verdict', 'risks'],
                 'properties': {'verdict': {'type': 'string', 'enum': ['preserves behaviour', 'may change behaviour']},
                                'risks': {'type': 'array', 'items': {'type': 'string'}}}}
ADVERSARY_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['claim', 'file', 'function', 'new_source', 'imports'],
                    'properties': {'claim': {'type': 'string'}, 'file': {'type': 'string'}, 'function': {'type': 'string'},
                                   'new_source': {'type': 'string'}, 'imports': {'type': 'array', 'items': {'type': 'string'}}}}


# ==================================================================== episodes (plan 21)

class Memory:
    """Move outcomes as instant episodes; the pre-filter reads them back."""

    LABELS = ['win', 'loss', 'invalid']

    def __init__(self, root: Path):
        from .laya_instant import store
        self.root = Path(root)
        self.store = store(str(self.root.resolve()))

    @staticmethod
    def features(move, family, task_kind, callee='', function='', file=''):
        return {'kind': task_kind, 'move': move, 'family': family, 'callee': callee, 'function': function,
                'file': Path(file).name if file else ''}

    def write(self, features, label, source, evidence):
        result = self.store.learn(EPISODE_DOMAIN, features, label, source, evidence=evidence)
        return result

    def predict(self, features):
        """Exact replay first, then the conformal store, then a plain neighbour vote (advisory)."""
        started = time.perf_counter()
        answer = self.store.query(EPISODE_DOMAIN, features, labels=self.LABELS)
        if not answer.get('escalate'):
            return {**answer, 'ms': (time.perf_counter() - started) * 1000}
        from .laya_instant import encode, latest_episodes
        rows = [r for r in latest_episodes(self.store.rows) if r['domain'] == EPISODE_DOMAIN]
        if not rows:
            return {'answer': None, 'escalate': True, 'probabilities': {}, 'reason': answer.get('reason'), 'ms': (time.perf_counter() - started) * 1000}
        import numpy as np
        vector, _ = encode(features, EPISODE_DOMAIN)
        probabilities, distance, count = self.store.scores(np.asarray(vector), rows, self.LABELS)
        decoded = {json.loads(k): v for k, v in probabilities.items()}
        return {'answer': None, 'escalate': True, 'probabilities': decoded, 'distance': distance, 'neighbours': count,
                'reason': answer.get('reason'), 'ms': (time.perf_counter() - started) * 1000}

    def rows(self):
        from .laya_instant import latest_episodes
        self.store.refresh()  # rows load lazily; a fresh process must not see an empty store
        return [r for r in latest_episodes(self.store.rows) if r['domain'] == EPISODE_DOMAIN]

    @staticmethod
    def context_of(row):
        """Where an episode was observed: the task (from its evidence or provenance) and the file.
        None = unknown/whole-task (late findings and ablation losses name no file)."""
        evidence = row.get('evidence') or {}
        task = evidence.get('task')
        if not task:
            prefix, _, rest = row['source'].partition(':')
            if prefix in {'evolve', 'evolve-late', 'evolve-ablation'}:
                task = rest.split(':')[0] or None
        return {'task': task or None, 'file': (row.get('input') or {}).get('file') or None}

    def stats(self):
        per = defaultdict(Counter)
        for row in self.rows():
            per[row['input']['move']][row['label']] += 1
        return per

    def context_stats(self, scope):
        """{move: {context tuple: Counter(label)}} with context = the values of ``scope`` keys."""
        per = defaultdict(lambda: defaultdict(Counter))
        for row in self.rows():
            context = self.context_of(row)
            per[row['input']['move']][tuple(context.get(key) for key in scope)][row['label']] += 1
        return per


def load_retire_rule(path=None):
    """``-- @retire`` line of the move library: which context keys scope a retirement and how
    many tries without a win retire a move there."""
    path = Path(path or MOVES_PATH)
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('-- @retire '):
            return json.loads(line[len('-- @retire '):])
    return {'scope': ['task', 'file'], 'tries': 3, 'maxWins': 0}


def _context_matches(key, context, scope):
    """An episode's context covers a proposal's context when every scope value agrees; an
    unknown file (whole-task finding) covers every file, an unknown task covers nothing."""
    for name, have, want in zip(scope, key, context):
        if have == want or (have is None and name != 'task'):
            continue
        return False
    return True


def retired_in(per_context, context, rule):
    """(retired?, label counts) for one move in one context under the retire rule."""
    total = Counter()
    for key, counts in per_context.items():
        if _context_matches(key, context, rule['scope']):
            total.update(counts)
    tries = sum(total.values())
    return (tries >= rule['tries'] and total['win'] <= rule.get('maxWins', 0)), dict(total)


def retirement_table(memory, rule, moves=None):
    """Every (move, context) the rule retires, and every move retired somewhere but available elsewhere."""
    stats = memory.context_stats(rule['scope'])
    retired, contexts = {}, defaultdict(set)
    for move, per in stats.items():
        for key in per:
            contexts[move].add(key)
    for move, per in stats.items():
        if moves is not None and move not in moves:
            continue
        for key in sorted(contexts[move], key=str):
            if any(value is None for value in key):
                continue
            gone, counts = retired_in(per, key, rule)
            if gone:
                retired.setdefault(move, {})['/'.join(map(str, key))] = counts
    elsewhere = sorted(move for move in retired if any(
        not any(v is None for v in key) and '/'.join(map(str, key)) not in retired[move] for key in contexts[move]))
    return retired, elsewhere


# ==================================================================== judge vocabulary as a scene_core domain

def register_domain():
    from . import scene_core
    if 'evolve' in scene_core._ADAPTERS:
        return
    scene_core.register('evolve', scene_core.Adapter(transcribe=lambda source: source, vocabulary=lambda: load_spec()[1]))


def transcribe_checks(candidate_id, checks: dict, reference: dict):
    """A candidate's checked outcomes as a Scene: one node per check (observations only)."""
    from . import scene_core
    register_domain()
    nodes = []
    for check, result in sorted(checks.items()):
        nodes.append({'id': check, 'kind': 'check', 'attributes': {'check': check, 'candidate': candidate_id},
                      'measurements': {'identical': result.get('outputSha256') == reference.get(check),
                                       'status': result.get('status', 'missing'),
                                       'nondeterministic': str(result.get('outputSha256') or '').startswith('nondeterministic:')},
                      'relations': {}, 'certainty': 'observed'})
    return scene_core.transcribe('evolve', {'surface': 'evolve:' + candidate_id, 'nodes': nodes})


# ==================================================================== the engine

class Engine:
    def __init__(self, target, *, state: Path, runs: Path, models: Models, memory: Memory, spec: dict,
                 learned_moves: Path, log=print, seed_library=True):
        self.target = target
        self.state = Path(state)
        self.runs = Path(runs)
        self.runs.mkdir(parents=True, exist_ok=True)
        self.models = models
        self.memory = memory
        self.spec = spec
        self.log = log
        self.learned_path = Path(learned_moves)
        self.library = (moves_lib.load_moves(MOVES_PATH) if seed_library else []) + self._learned()
        self.retire_rule = load_retire_rule()
        self.base = dict(target.baseline)
        self.reference = {}
        self.incumbent = {'id': 'baseline', 'files': dict(self.base), 'speedup': 1.0, 'origin': {'source': 'baseline'}}
        self.evaluations = []
        self.curve = []
        self.archive = {}
        self.accepted = []
        self.exploits = []
        self.adversary_rounds = []
        self.ledger = defaultdict(Counter)
        self.started = time.time()
        self.seen = set()
        self.cheap_checks = list(target.train_checks())
        self.hot = []
        self.run_id = os.environ.get('NEYVIA_EVOLVE_RUN', uuid.uuid4().hex[:8])
        self.task_kind = spec.get('kind', 'python-speed')
        self.plateau = 0
        self.receipts = self.runs / 'receipts.jsonl'
        self.files_by_id = {}
        self.parent_of = {}

    # ---------------------------------------------------------------- library
    def _learned(self):
        if self.learned_path.exists():
            return json.loads(self.learned_path.read_text(encoding='utf-8'))
        return []

    def _save_learned(self, move):
        rows = self._learned()
        rows = [r for r in rows if r['id'] != move['id']] + [move]
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        self.learned_path.write_text(json.dumps(rows, indent=2), encoding='utf-8')
        self.library = [m for m in self.library if m['id'] != move['id']] + [move]

    def retired(self):
        """{move: {context: counts}} for every context where the retire rule retires a library move.
        Retirement is context-scoped (plan 27 EVOLVE2): a move that kept failing on one task's file
        stays available on other files and other tasks (r5: a globally retired parallel-map was a
        confirmed win on the newer gate)."""
        table, _ = retirement_table(self.memory, self.retire_rule, {m['id'] for m in self.library})
        return table

    def context(self, rel):
        values = {'task': self.target.name, 'file': Path(rel).name if rel else None, 'kind': self.task_kind}
        return tuple(values.get(key) for key in self.retire_rule['scope'])

    def is_retired(self, stats, move_id, rel):
        gone, _ = retired_in(stats.get(move_id, {}), self.context(rel), self.retire_rule)
        return gone

    # ---------------------------------------------------------------- receipts
    def receipt(self, row):
        row = {'at': now(), 'task': self.target.name, 'elapsed': round(time.time() - self.started, 1), **row}
        with self.receipts.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, default=str) + '\n')

    # ---------------------------------------------------------------- reference outputs
    def establish(self):
        for check in self.target.all_checks():
            result = self.target.check(self.base, check)
            self.reference[check] = result.get('outputSha256')
            self.log(f'  reference {check}: {result.get("status")} {str(result.get("outputSha256"))[:12]} {result.get("wall", 0):.1f}s')
        self.baseline_times = self.time_files(self.base, repeats=3)
        self.log(f'  baseline train wall {self.baseline_times["wall"]:.2f}s cpu {self.baseline_times["cpu"]:.2f}s')
        self.curve.append({'elapsed': 0, 'evaluations': 0, 'speedup': 1.0, 'wall': self.baseline_times['wall']})

    def time_files(self, files, repeats=3):
        walls, cpus = [], []
        for _ in range(repeats):
            total_wall = total_cpu = 0
            for check in self.target.train_checks():
                result = self.target.measure(files, self.target.case(check))
                total_wall += result['wall']
                total_cpu += result.get('cpuSeconds') or 0
            walls.append(total_wall)
            cpus.append(total_cpu)
        return {'wall': statistics.median(walls), 'cpu': statistics.median(cpus), 'walls': walls}

    # ---------------------------------------------------------------- profile
    def profile(self, files):
        """Hot functions of the target files in one profiled train run."""
        rows = []
        for check in self.target.train_checks():
            path = self.runs / f'profile-{sha(canonical(files))[:10]}-{check}.prof'
            self.target.measure(files, self.target.case(check), profile=path)
            if not path.exists():
                continue
            stats = pstats.Stats(str(path))

            def owner(filename):
                norm = filename.replace('\\', '/')
                return next((rel for rel in files if norm.endswith('/' + rel)), None)
            # Time a target function spends outside the targets (subprocesses, IO, libraries)
            # is attributable to it: score = self time + external callee time.
            external = Counter()
            for key, (cc, nc, tt, ct, callers) in stats.stats.items():
                if owner(key[0]) is None:
                    for caller, timing in callers.items():
                        if owner(caller[0]) is not None:
                            external[caller] += timing[3]
            for key, (cc, nc, tt, ct, callers) in stats.stats.items():
                rel = owner(key[0])
                if rel is not None:
                    qual = self._qualname(files[rel], key[1], key[2])
                    rows.append({'file': rel, 'function': qual, 'line': key[1], 'calls': nc, 'tottime': tt + external[key],
                                 'selfTime': tt, 'cumtime': ct, 'check': check})
        merged = {}
        for row in rows:
            key = (row['file'], row['function'])
            if key in merged:
                for field in ('calls', 'tottime', 'selfTime', 'cumtime'):
                    merged[key][field] += row[field]
            else:
                merged[key] = dict(row)
        self.hot = sorted(merged.values(), key=lambda r: -r['tottime'])
        return self.hot

    @staticmethod
    def _qualname(text, line, name):
        import ast
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return name
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name and child.lineno <= line <= child.end_lineno + 1:
                        return node.name + '.' + name
        return name

    # ---------------------------------------------------------------- proposals
    def library_proposals(self, parent):
        proposals = []
        stats = self.memory.context_stats(self.retire_rule['scope'])
        for move in self.library:
            transform = move.get('transform')
            if transform in moves_lib.TRANSFORMS:
                for rel, text in parent['files'].items():
                    if not rel.endswith('.py') or self.is_retired(stats, move['id'], rel):
                        continue
                    hot = [r for r in self.hot if r['file'] == rel]
                    try:
                        variants = moves_lib.TRANSFORMS[transform](text, hot)
                    except SyntaxError:
                        variants = []
                    for new_text, detail in variants:
                        files = {**parent['files'], rel: new_text}
                        proposals.append({'files': files, 'origin': {'source': 'library', 'hands': 'deterministic', 'move': move['id'],
                                                                      'family': move['family'], 'file': rel, **detail}})
            elif transform == 'luna':
                proposals.extend(self._luna_move_sites(parent, move, stats))
        return proposals

    def _luna_move_sites(self, parent, move, stats):
        """A learned move (CL text) is a candidate for hot functions that match its pattern; Luna applies it lazily."""
        sites = []
        pattern = move.get('match') or ''
        for row in self.hot[:12]:
            if self.is_retired(stats, move['id'], row['file']):
                continue
            source = moves_lib.function_source(parent['files'][row['file']], row['function'])
            if not source:
                continue
            try:
                hit = bool(re.search(pattern, source)) if pattern else False
            except re.error:
                hit = pattern in source
            if hit:
                sites.append({'files': None, 'lazy': 'luna-move', 'move': move, 'site': row,
                              'origin': {'source': 'library', 'hands': 'luna', 'move': move['id'], 'family': move['family'],
                                         'file': row['file'], 'function': row['function'], 'callee': move.get('callee', '')}})
                if len(sites) >= 2:
                    break
        return sites

    def realise(self, proposal, parent):
        """Turn a lazy proposal (needs a model) into concrete files; None if the model declines or fails."""
        if proposal.get('files') is not None:
            return proposal
        site = proposal['site']
        text = parent['files'][site['file']]
        source = moves_lib.function_source(text, site['function'])
        move = proposal['move']
        prompt = (f"Apply this known optimisation move to the Python function below.\nMove {move['id']} ({move['family']}): {move.get('applies_when','')}\n"
                  f"CL procedure: {move.get('cl','')}\n" + (f"Worked example (diff where it won before):\n{move.get('example','')[:3000]}\n" if move.get('example') else '') +
                  f"\nFile {site['file']}, function {site['function']} (profile: {site['calls']} calls, {site['tottime']:.3f}s self time):\n```python\n{source}\n```\n"
                  "Return the complete replacement function (same name and signature) that applies the move. Every output, return value, "
                  "exception and file written must stay byte-identical. If the move does not apply, return the function unchanged.")
        answer, call = self.models.ask('luna', prompt, EDIT_SCHEMA, label=f'move-{move["id"]}')
        proposal['origin']['modelCall'] = call
        if not answer:
            return None
        try:
            new = moves_lib.replace_function(text, site['function'], answer['new_source'])
            new = moves_lib.add_module_imports(new, answer['imports'])
        except (ValueError, SyntaxError):
            return None
        if new == text:
            return None
        proposal['files'] = {**parent['files'], site['file']: new}
        proposal['origin']['idea'] = answer['idea']
        return proposal

    def luna_edits(self, parent, count=2):
        proposals = []
        for row in [r for r in self.hot if moves_lib.function_source(parent['files'][r['file']], r['function'])][:count]:
            if self.models.remaining('luna') <= 0:
                break
            text = parent['files'][row['file']]
            source = moves_lib.function_source(text, row['function'])
            if len(source) > 12000:
                continue
            profile = '\n'.join(f"{r['file']}:{r['function']} calls={r['calls']} self={r['tottime']:.3f}s cum={r['cumtime']:.3f}s" for r in self.hot[:10])
            prompt = (f"You optimise Python for wall-clock speed with byte-identical observable behaviour.\nTask: {self.target.spec['objective']}.\n"
                      f"Profile of the current version (hot functions in the target files):\n{profile}\n\n"
                      f"File {row['file']}, function {row['function']}:\n```python\n{source}\n```\n"
                      "Propose ONE concrete change to this function that makes the task faster. Every output, return value, exception, "
                      "ordering and file written must stay identical for every input; caches must stay correct when files change. "
                      "Return the complete replacement function (same name and signature).")
            answer, call = self.models.ask('luna', prompt, EDIT_SCHEMA, label='edit')
            if not answer:
                continue
            try:
                new = moves_lib.replace_function(text, row['function'], answer['new_source'])
                new = moves_lib.add_module_imports(new, answer['imports'])
            except (ValueError, SyntaxError):
                continue
            proposals.append({'files': {**parent['files'], row['file']: new},
                              'origin': {'source': 'luna', 'hands': 'luna', 'move': 'luna:' + sha(answer['idea'])[:8], 'family': answer['family'],
                                         'idea': answer['idea'], 'file': row['file'], 'function': row['function'], 'modelCall': call}})
        return proposals

    def big_idea(self, parent):
        if self.models.remaining('sol') <= 0:
            return []
        tried = Counter((e['origin'].get('move'), e['verdict']) for e in self.evaluations)
        history = '\n'.join(f'{move}: {verdict} x{n}' for (move, verdict), n in tried.most_common(30))
        sources = []
        for row in self.hot[:6]:
            source = moves_lib.function_source(parent['files'][row['file']], row['function'])
            if source and sum(len(s) for s in sources) + len(source) < 40000:
                sources.append(f"# {row['file']} :: {row['function']} (calls={row['calls']}, self={row['tottime']:.3f}s, cum={row['cumtime']:.3f}s)\n{source}")
        prompt = (f"Progress on this optimisation task has plateaued. Task: {self.target.spec['objective']}. Current speed-up over the original: "
                  f"{parent['speedup']:.3f}x. Hard constraints: every output, exception, ordering and file written stays identical for every input, "
                  f"including after source edits, renames and cold caches; the gate's contracts must pass.\nAlready tried (move: verdict x count):\n{history}\n\n"
                  "Hot functions of the current version:\n" + '\n\n'.join(sources) +
                  "\n\nPropose ONE genuinely new idea (not in the tried list) with concrete edits (complete replacement functions), and describe it "
                  "as a reusable move: id (kebab-case), family, applies_when (one sentence), match (a Python regex that finds functions where it "
                  "applies), cl (a one-line CL procedure).")
        answer, call = self.models.ask('sol', prompt, IDEA_SCHEMA, label='idea', effort='medium')
        if not answer or not answer.get('edits'):
            return []
        files = dict(parent['files'])
        for edit in answer['edits']:
            if edit['file'] not in files:
                return []
            try:
                files[edit['file']] = moves_lib.add_module_imports(
                    moves_lib.replace_function(files[edit['file']], edit['function'], edit['new_source']), edit['imports'])
            except (ValueError, SyntaxError):
                return []
        move = answer['move']
        return [{'files': files, 'origin': {'source': 'big-model', 'hands': 'sol', 'move': 'idea:' + move['id'], 'family': move['family'],
                                            'idea': answer['idea'], 'proposedMove': move, 'file': answer['edits'][0]['file'],
                                            'function': answer['edits'][0]['function'], 'modelCall': call}}]

    def crossovers(self, parent):
        """Merge elites from other archive cells into the incumbent (3-way, per file)."""
        out = []
        for cell, elite in sorted(self.archive.items(), key=lambda kv: -kv[1]['speedup']):
            if elite['id'] == parent['id'] or elite['id'] in parent.get('ancestry', []):
                continue
            merged = dict(parent['files'])
            ok = True
            for rel in merged:
                if elite['files'][rel] == self.base[rel] or elite['files'][rel] == merged[rel]:
                    continue
                result = merge3(self.base[rel], merged[rel], elite['files'][rel])
                if result is None:
                    ok = False
                    break
                merged[rel] = result
            if ok and merged != parent['files']:
                out.append({'files': merged, 'origin': {'source': 'crossover', 'hands': 'merge', 'move': 'crossover:' + elite['origin'].get('move', ''),
                                                       'family': elite['origin'].get('family', 'other'), 'elite': elite['id']}})
            if len(out) >= 2:
                break
        return out

    # ---------------------------------------------------------------- pre-filter
    def features(self, proposal):
        o = proposal['origin']
        return self.memory.features(o.get('move', ''), o.get('family', ''), self.task_kind, o.get('callee', ''),
                                    o.get('function', ''), o.get('file', ''))

    def prefilter(self, proposals):
        """Rank by predicted win; kill admitted/exact-replay losers; audit every fourth kill."""
        ranked, killed = [], []
        for proposal in proposals:
            prediction = self.memory.predict(self.features(proposal))
            proposal['prediction'] = {k: v for k, v in prediction.items() if k in {'answer', 'escalate', 'probabilities', 'confidenceKind', 'ms', 'reason'}}
            answer = prediction.get('answer')
            if answer in {'loss', 'invalid'} and not prediction.get('escalate'):
                killed.append(proposal)
            else:
                proposal['score'] = (prediction.get('probabilities') or {}).get('win', 1 / 3) if answer is None else (1.0 if answer == 'win' else 0.0)
                ranked.append(proposal)
        ranked.sort(key=lambda p: (-p['score'], p['origin'].get('source') != 'library'))
        audit = []
        for index, proposal in enumerate(killed):
            self.ledger['prefilter']['killed'] += 1
            if self.ledger['prefilter']['killed'] % 4 == 1:
                proposal['audit'] = True
                audit.append(proposal)
        return ranked, killed, audit

    # ---------------------------------------------------------------- judging one candidate
    def evaluate(self, proposal, parent, *, adversarial=False):
        started = time.perf_counter()
        files = proposal['files']
        key = sha(canonical(files))
        cid = key[:12]
        row = {'id': cid, 'parent': parent['id'], 'origin': {k: v for k, v in proposal['origin'].items() if k != 'modelCall'},
               'modelCall': proposal['origin'].get('modelCall'), 'prediction': proposal.get('prediction'), 'audit': proposal.get('audit', False),
               'adversarial': adversarial, 'footprint': footprint(self.base, files), 'layers': {}}
        if key in self.seen:
            row.update(verdict='duplicate')
            return row
        self.seen.add(key)
        # L0 static
        for rel, text in files.items():
            if rel.endswith('.py'):
                try:
                    compile(text, rel, 'exec')
                except SyntaxError as error:
                    row['layers']['static'] = {'ok': False, 'error': str(error)}
                    row.update(verdict='invalid')
                    return self._finish(row, proposal, started)
        row['layers']['static'] = {'ok': True}
        # L1 cheap checks judged by the scene_core vocabulary
        checks = {check: self.target.check(files, check) for check in self.cheap_checks}
        scene = transcribe_checks(cid, checks, self.reference)
        from . import scene_core
        verdict = scene_core.judge(scene, rules=self.vocabulary(), record=False)
        errors = [f for f in verdict['findings'] if f['severity'] == 'error']
        row['layers']['cheap'] = {'ok': not errors, 'checks': list(checks), 'findings': [f['predicate'] + ':' + f['node'] for f in errors],
                                  'sceneSha256': scene['sha256'], 'judgeMs': round(verdict['ms'], 2)}
        if errors:
            row.update(verdict='invalid')
            return self._finish(row, proposal, started)
        # L2 paired timing against the parent
        timing = self.paired(parent['files'], files, family=proposal['origin'].get('family', ''))
        row['layers']['timing'] = timing
        if not timing['faster'] and not adversarial:
            row.update(verdict='loss')
            return self._finish(row, proposal, started)
        row['speedup'] = parent['speedup'] * timing['ratio']
        # L3 the real test (held-out + perturbations): cannot be faked
        real = {check: self.target.check(files, check) for check in self.target.all_checks() if check not in checks}
        real_scene = transcribe_checks(cid, {**checks, **real}, self.reference)
        real_verdict = scene_core.judge(real_scene, rules=self.vocabulary(), record=False)
        real_errors = [f for f in real_verdict['findings'] if f['severity'] == 'error']
        failing = sorted({f['node'] for f in real_errors})
        row['layers']['real'] = {'ok': not real_errors, 'failing': failing, 'checks': sorted(real)}
        if real_errors:
            row.update(verdict='exploit' if adversarial else 'fails-real')
            self.harden(row, failing)
            return self._finish(row, proposal, started)
        row.update(verdict='adversary-held' if adversarial else ('win' if timing['faster'] else 'loss'))
        return self._finish(row, proposal, started)

    def paired(self, a, b, pairs=3, family=''):
        """Interleaved A/B on the train cases. Faster = minimum-wall ratio >= 1.05, median pair ratio
        >= 1, and the process CPU agrees (except for parallel moves, which may spend more CPU); a
        candidate clearly slower early stops. r3 showed +-7% wall noise and cosmetic edits passing a
        wall-only 1.03 threshold twice, so CPU agreement is required."""
        ratios, wa, wb, cpu_a, cpu_b = [], [], [], [], []
        for index in range(pairs):
            order = [('a', a), ('b', b)] if index % 2 == 0 else [('b', b), ('a', a)]
            sums = {}
            for label, files in order:
                wall = cpu = 0
                for check in self.target.train_checks():
                    result = self.target.measure(files, self.target.case(check))
                    wall += result['wall']
                    cpu += result.get('cpuSeconds') or 0
                sums[label] = (wall, cpu)
            wa.append(sums['a'][0]); wb.append(sums['b'][0]); cpu_a.append(sums['a'][1]); cpu_b.append(sums['b'][1])
            ratios.append(sums['a'][0] / max(sums['b'][0], 1e-9))
            if index == 0 and ratios[0] < 0.85:
                break  # clearly slower on the first pair
            if index == 1 and max(ratios) < 1.0:
                break
        # Interference from other processes only ever slows a run, so the minimum of each arm
        # is the robust estimate; the median pair ratio must agree in direction.
        ratio = min(wa) / max(min(wb), 1e-9)
        median_ratio = statistics.median(ratios)
        cpu_ratio = min(cpu_a) / max(min(cpu_b), 1e-9)
        cpu_agrees = cpu_ratio >= 1.0 or family == 'parallel'
        faster = ratio >= 1.05 and median_ratio >= 1.0 and cpu_agrees and len(ratios) >= pairs
        return {'ratio': round(ratio, 4), 'medianPairRatio': round(median_ratio, 4), 'pairs': [round(r, 4) for r in ratios], 'parentWall': wa, 'candidateWall': wb,
                'parentCpu': cpu_a, 'candidateCpu': cpu_b, 'cpuRatio': round(cpu_ratio, 4), 'cpuAgrees': cpu_agrees, 'faster': faster}

    def vocabulary(self):
        return load_spec()[1] + [e['predicate'] for e in self.exploits]

    def harden(self, row, failing):
        """Every score-high/fail-real candidate becomes a predicate and a promoted cheap check."""
        for check in failing:
            identity = f'exploit-{check}'
            if any(e['predicate']['id'] == identity for e in self.exploits) or check in self.cheap_checks:
                continue
            predicate = {'id': identity, 'severity': 'error', 'evidence': ['measurements.identical', 'measurements.status'],
                         'condition': {'all': [{'field': 'attributes.check', 'op': 'eq', 'value': check},
                                               {'any': [{'field': 'measurements.identical', 'op': 'eq', 'value': False},
                                                        {'field': 'measurements.nondeterministic', 'op': 'eq', 'value': True}]}]},
                         'fix': {'action': 'evolve.reject', 'arguments': {}},
                         'means': f"Found by {row['origin'].get('source')} candidate {row['id']} ({row['origin'].get('move')}): {row['origin'].get('claim', row['origin'].get('idea', ''))}"[:300]}
            self.exploits.append({'predicate': predicate, 'check': check, 'candidate': row['id'], 'origin': row['origin'],
                                  'task': self.target.name, 'at': now()})
            self.cheap_checks.append(check)
            self.log(f'    judge hardened: {identity} (cheap checks now {self.cheap_checks})')

    def _finish(self, row, proposal, started):
        row['seconds'] = round(time.perf_counter() - started, 2)
        self.evaluations.append(row)
        label = {'win': 'win', 'loss': 'loss', 'invalid': 'invalid', 'fails-real': 'invalid'}.get(row['verdict'])
        if label and not row['adversarial']:
            row['features'] = self.features(proposal)
            row['episode'] = self.memory.write(row['features'], label, f"evolve:{self.target.name}:{row['id']}",
                                               {'speedup': row.get('speedup'), 'verdict': row['verdict'], 'task': self.target.name})
        self.receipt({'kind': 'evaluation', **row})
        speed = row.get('speedup')
        self.log(f"    {row['id']} {row['origin'].get('source'):10s} {str(row['origin'].get('move'))[:44]:44s} -> {row['verdict']:12s}"
                 f" {'' if speed is None else f'{speed:.3f}x'} ({row['seconds']}s)")
        return row

    # ---------------------------------------------------------------- archive and Pareto
    def place(self, row, files):
        bucket = 'small' if row['footprint'] <= 5 else 'medium' if row['footprint'] <= 30 else 'large'
        cell = f"{row['origin'].get('family', 'other')}/{bucket}"
        entry = {'id': row['id'], 'files': files, 'speedup': row['speedup'], 'origin': row['origin'], 'footprint': row['footprint'],
                 'cell': cell, 'ancestry': row.get('ancestry', [])}
        if cell not in self.archive or self.archive[cell]['speedup'] < entry['speedup']:
            self.archive[cell] = entry
        self.accepted.append(entry)
        self.files_by_id[row['id']] = files
        self.parent_of[row['id']] = (row['parent'], row['origin'].get('move'))

    def lineage(self):
        """[(step id, move, parent files, child files)] from the baseline to the incumbent."""
        chain, node = [], self.incumbent['id']
        while node != 'baseline':
            parent, move = self.parent_of[node]
            chain.append((node, move, self.base if parent == 'baseline' else self.files_by_id[parent], self.files_by_id[node]))
            node = parent
        return chain[::-1]

    def pareto(self):
        points = [e for e in self.accepted]
        front = []
        for p in points:
            dominated = any(q['speedup'] >= p['speedup'] and q['footprint'] <= p['footprint'] and
                            (q['speedup'] > p['speedup'] or q['footprint'] < p['footprint']) for q in points)
            if not dominated:
                front.append({'id': p['id'], 'speedup': round(p['speedup'], 4), 'footprint': p['footprint'], 'cell': p['cell'],
                              'move': p['origin'].get('move')})
        return sorted(front, key=lambda r: -r['speedup'])

    # ---------------------------------------------------------------- moves learned from wins
    def learn_move(self, row, files):
        origin = row['origin']
        if origin.get('source') == 'library':
            return None
        diff = patch(self.incumbent_before_files, files)
        move = origin.get('proposedMove')
        if not move and self.models.remaining('luna') > 0:
            prompt = (f"This change won (speed-up {row['speedup']:.3f}x, outputs identical, real test passed). Generalise it into a reusable "
                      f"optimisation move for other Python code: id (kebab-case), family, applies_when (one sentence), match (a Python regex "
                      f"that finds functions where it applies), cl (one-line CL procedure).\nIdea: {origin.get('idea')}\nDiff:\n{diff[:6000]}")
            move, _ = self.models.ask('luna', prompt, GENERALISE_SCHEMA, label='generalise')
        if not move:
            return None
        learned = {'id': 'learned:' + re.sub(r'[^a-z0-9-]+', '-', move['id'].lower()).strip('-'), 'family': move['family'],
                   'applies_when': move['applies_when'], 'match': move['match'], 'cl': move['cl'], 'transform': 'luna',
                   'origin': origin.get('source'), 'example': diff[:4000], 'evidence': {'task': self.target.name, 'candidate': row['id'],
                   'speedup': row['speedup']}, 'learnedAt': now()}
        self._save_learned(learned)
        self.memory.write(self.memory.features(learned['id'], learned['family'], self.task_kind, '', origin.get('function', ''), origin.get('file', '')),
                          'win', f"evolve-move:{learned['id']}", {'learnedFrom': row['id'], 'task': self.target.name})
        self.log(f"    new move learned: {learned['id']} ({learned['family']}): {learned['applies_when'][:100]}")
        return learned

    # ---------------------------------------------------------------- adversary
    def adversary_round(self, generation, constants=None):
        parent = self.incumbent
        population = []
        for name, transform in moves_lib.EXPLOITS.items():
            for rel, text in parent['files'].items():
                if not rel.endswith('.py'):
                    continue
                variants = transform(text) if name != 'disk-memo' else (
                    transform(text, 'select') if 'def select(' in text else transform(text, 'check') if 'def check(' in text else [])
                for new, detail in variants:
                    population.append({'files': {**parent['files'], rel: new},
                                       'origin': {'source': 'adversary', 'hands': 'deterministic', 'move': 'exploit:' + name, 'family': 'exploit',
                                                  'file': rel, **detail}})
        if constants:
            for rel, text in parent['files'].items():
                for new, detail in moves_lib.exploit_skip_module_check(text, constants.get('moduleCheck')):
                    population.append({'files': {**parent['files'], rel: new},
                                       'origin': {'source': 'adversary', 'hands': 'deterministic', 'move': 'exploit:frozen-module-check',
                                                  'family': 'exploit', 'file': rel, **detail}})
        if generation >= 1 and self.models.remaining('luna') > 0:
            population.extend(self.luna_adversary(parent))
        found, tried = [], 0
        for proposal in population:
            row = self.evaluate_adversary(proposal, parent)
            tried += 1
            if row['verdict'] == 'exploit':
                found.append(row['id'])
        record = {'generation': generation, 'tried': tried, 'found': len(found), 'rate': round(len(found) / tried, 3) if tried else None,
                  'exploits': found, 'cheapChecks': list(self.cheap_checks)}
        self.adversary_rounds.append(record)
        self.receipt({'kind': 'adversary-round', **record})
        self.log(f'  adversary round {generation}: {len(found)}/{tried} exploits found')
        return record

    def evaluate_adversary(self, proposal, parent):
        """An exploit 'scores high' if it passes the cheap judge and is not slower; then the real test decides."""
        files = proposal['files']
        cid = sha(canonical(files))[:12]
        started = time.perf_counter()
        row = {'id': cid, 'parent': parent['id'], 'origin': {k: v for k, v in proposal['origin'].items() if k != 'modelCall'},
               'modelCall': proposal['origin'].get('modelCall'), 'adversarial': True, 'footprint': footprint(self.base, files), 'layers': {}}
        for rel, text in files.items():
            try:
                compile(text, rel, 'exec')
            except SyntaxError as error:
                row.update(verdict='invalid')
                return self._finish(row, proposal, started)
        checks = {check: self.target.check(files, check) for check in self.cheap_checks}
        from . import scene_core
        verdict = scene_core.judge(transcribe_checks(cid, checks, self.reference), rules=self.vocabulary(), record=False)
        errors = [f for f in verdict['findings'] if f['severity'] == 'error']
        row['layers']['cheap'] = {'ok': not errors, 'checks': list(checks), 'findings': [f['predicate'] + ':' + f['node'] for f in errors]}
        self.ledger['cheap']['adversary-tried'] += 1
        if errors:
            row.update(verdict='caught-cheap')
            return self._finish(row, proposal, started)
        real = {check: self.target.check(files, check) for check in self.target.all_checks() if check not in checks}
        real_verdict = scene_core.judge(transcribe_checks(cid, {**checks, **real}, self.reference), rules=self.vocabulary(), record=False)
        failing = sorted({f['node'] for f in real_verdict['findings'] if f['severity'] == 'error'})
        row['layers']['real'] = {'ok': not failing, 'failing': failing}
        if failing:
            self.ledger['cheap']['adversary-passed-but-wrong'] += 1
            row.update(verdict='exploit')
            self.harden(row, failing)
        else:
            row.update(verdict='adversary-held')
        return self._finish(row, proposal, started)

    def luna_adversary(self, parent):
        rows = [r for r in self.hot if moves_lib.function_source(parent['files'][r['file']], r['function'])][:4]
        listing = '\n'.join(f"{r['file']}:{r['function']}" for r in rows)
        sources = '\n\n'.join(f"# {r['file']} :: {r['function']}\n{moves_lib.function_source(parent['files'][r['file']], r['function'])[:5000]}" for r in rows)
        prompt = (f"You are the adversary of an optimisation judge. The judge accepts a faster variant when these checks give byte-identical "
                  f"outputs: {', '.join(self.cheap_checks)} (check names describe the case). Write ONE variant of one function below that is "
                  f"faster and would pass exactly those checks, but is wrong in some other realistic circumstance (stale caches, other refs, "
                  f"edited files, renames, cold state, nondeterminism). State the circumstance in 'claim'.\nFunctions:\n{listing}\n\n{sources}")
        answer, call = self.models.ask('luna', prompt, ADVERSARY_SCHEMA, label='adversary')
        if not answer or answer.get('file') not in parent['files']:
            return []
        try:
            new = moves_lib.add_module_imports(moves_lib.replace_function(parent['files'][answer['file']], answer['function'], answer['new_source']), answer['imports'])
        except (ValueError, SyntaxError):
            return []
        return [{'files': {**parent['files'], answer['file']: new},
                 'origin': {'source': 'adversary', 'hands': 'luna', 'move': 'exploit:luna-' + sha(answer['claim'])[:6], 'family': 'exploit',
                            'claim': answer['claim'], 'file': answer['file'], 'function': answer['function'], 'modelCall': call}}]

    # ---------------------------------------------------------------- the loop
    def run(self, *, generations=5, per_generation=8, luna_per_generation=2, max_seconds=4 * 3600, adversary_constants=None,
            stop_after=None, adversary=True):
        self.log(f'[{self.target.name}] establishing reference outputs and baseline')
        self.establish()
        self.search_started = time.time()
        if adversary:
            self.adversary_round(0, adversary_constants)
        first_win_at = None
        for generation in range(1, generations + 1):
            if time.time() - self.started > max_seconds:
                break
            parent = self.incumbent
            self.profile(parent['files'])
            self.log(f'[{self.target.name}] generation {generation}: incumbent {parent["id"]} {parent["speedup"]:.3f}x; hot: '
                     + ', '.join(f"{r['function']} {r['tottime']:.2f}s" for r in self.hot[:4]))
            proposals = self.library_proposals(parent) + self.crossovers(parent)
            if self.plateau >= 1:
                proposals += self.big_idea(parent)
            ranked, killed, audit = self.prefilter(proposals)
            budget = per_generation
            chosen = ranked[:budget] + audit
            self.log(f'  proposals {len(proposals)} (library {sum(p["origin"]["source"]=="library" for p in proposals)}); '
                     f'pre-filter killed {len(killed)} in {sum(p["prediction"]["ms"] for p in killed):.1f} ms; running {len(chosen)}')
            for proposal in killed:
                if not proposal.get('audit'):
                    self.receipt({'kind': 'prefilter-kill', 'origin': {k: v for k, v in proposal['origin'].items() if k != 'modelCall'},
                                  'prediction': proposal['prediction']})
            winners = []
            self.incumbent_before_files = parent['files']
            for proposal in chosen:
                proposal = self.realise(proposal, parent)
                if proposal is None:
                    continue
                row = self.evaluate(proposal, parent)
                self._judge_ledger(row, proposal)
                if row['verdict'] == 'win':
                    winners.append((row, proposal['files']))
                    row['ancestry'] = parent.get('ancestry', []) + [parent['id']]
                    self.place(row, proposal['files'])
                    if first_win_at is None:
                        first_win_at = len([e for e in self.evaluations if not e['adversarial']])
                self._curve()
            if len([w for w in winners]) < 1:
                for proposal in self.luna_edits(parent, luna_per_generation):
                    row = self.evaluate(proposal, parent)
                    self._judge_ledger(row, proposal)
                    if row['verdict'] == 'win':
                        winners.append((row, proposal['files']))
                        row['ancestry'] = parent.get('ancestry', []) + [parent['id']]
                        self.place(row, proposal['files'])
                        if first_win_at is None:
                            first_win_at = len([e for e in self.evaluations if not e['adversarial']])
                    self._curve()
            winners = self.confirm(parent, winners)
            if winners:
                best_row, best_files = max(winners, key=lambda w: w[0]['speedup'])
                for row, files in winners:
                    self.learn_move(row, files)
                self.incumbent = {'id': best_row['id'], 'files': best_files, 'speedup': best_row['speedup'], 'origin': best_row['origin'],
                                  'ancestry': best_row.get('ancestry', [])}
                self.plateau = 0
            else:
                self.plateau += 1
            self._curve()
            if adversary:
                self.adversary_round(generation, adversary_constants)
            if stop_after == 'first-win' and first_win_at is not None:
                break
            if self.plateau >= 3 or (self.plateau >= 2 and self.models.remaining('sol') <= 0):
                self.log(f'[{self.target.name}] plateau: stopping')
                break
        return self.summary(first_win_at)

    def confirm(self, parent, winners):
        """Judge the timing judge: re-time each winner against the parent later; only winners that
        hold up stay winners (a fresh episode with the same provenance supersedes the old label)."""
        held = []
        for row, files in sorted(winners, key=lambda w: -w[0]['speedup'])[:4]:
            again = self.paired(parent['files'], files, pairs=3, family=row['origin'].get('family', ''))
            ok = again['ratio'] >= 1.02 and again['medianPairRatio'] >= 1.0 and again['cpuAgrees']
            row['confirmation'] = {'ratio': again['ratio'], 'medianPairRatio': again['medianPairRatio'], 'held': ok}
            self.ledger['timing']['confirm-checked'] += 1
            self.ledger['timing']['confirm-held'] += int(ok)
            if ok:
                # The confirmed speed-up is the mean of both independent measurements.
                row['speedup'] = parent['speedup'] * (row['layers']['timing']['ratio'] + again['ratio']) / 2
                held.append((row, files))
            else:
                row['verdict'] = 'unconfirmed'
                self.accepted = [a for a in self.accepted if a['id'] != row['id']]
                self.archive = {cell: e for cell, e in self.archive.items() if e['id'] != row['id']}
                if row.get('features'):
                    self.memory.write(row['features'], 'loss', f"evolve:{self.target.name}:{row['id']}",
                                      {'verdict': 'unconfirmed', 'task': self.target.name})
            self.receipt({'kind': 'confirmation', 'id': row['id'], 'move': row['origin'].get('move'), **row['confirmation']})
            self.log(f"    confirm {row['id']} {str(row['origin'].get('move'))[:40]}: {again['ratio']:.3f}x -> {'held' if ok else 'not confirmed'}")
        return held

    def _judge_ledger(self, row, proposal):
        layers = row.get('layers', {})
        if proposal.get('audit'):
            self.ledger['prefilter']['audited'] += 1
            if row['verdict'] == 'win':
                self.ledger['prefilter']['audited-would-win'] += 1
        if layers.get('cheap', {}).get('ok'):
            self.ledger['cheap']['accepts'] += 1
            if 'real' in layers:
                self.ledger['cheap']['accepts-checked'] += 1
                self.ledger['cheap']['accepts-held'] += int(layers['real']['ok'])
        if layers.get('timing', {}).get('faster'):
            self.ledger['timing']['accepts'] += 1
            self.ledger['timing']['accepts-held'] += int(layers.get('real', {}).get('ok', False))

    def _curve(self):
        best = max([self.incumbent['speedup']] + [e['speedup'] for e in self.accepted])
        point = {'elapsed': round(time.time() - self.started, 1),
                 'searchSeconds': round(time.time() - getattr(self, 'search_started', self.started), 1),
                 'searchEvalSeconds': round(sum(e['seconds'] for e in self.evaluations if not e['adversarial']), 1),
                 'evaluations': len([e for e in self.evaluations if not e['adversarial']]),
                 'modelCalls': sum(1 for e in self.evaluations if e.get('modelCall')), 'speedup': round(best, 4)}
        if not self.curve or self.curve[-1]['speedup'] != point['speedup'] or self.curve[-1]['evaluations'] != point['evaluations']:
            self.curve.append(point)

    def judge_weights(self):
        weights = {}
        for layer, counts in self.ledger.items():
            if layer == 'prefilter':
                audited = counts['audited']
                weights[layer] = {'killed': counts['killed'], 'audited': audited, 'auditedWouldWin': counts['audited-would-win'],
                                  'weight': round((audited - counts['audited-would-win']) / (audited + 1), 3) if audited else None}
            elif layer == 'timing':
                checked, held = counts['confirm-checked'], counts['confirm-held']
                weights[layer] = {**dict(counts), 'weight': round(held / (checked + 1), 3) if checked else None,
                                  'meaning': 'share of timing accepts that held up when re-timed later'}
            else:
                checked = counts.get('accepts-checked', counts.get('accepts', 0))
                held = counts['accepts-held']
                weights[layer] = {**dict(counts), 'weight': round(held / (checked + 1), 3) if checked else None,
                                  'meaning': 'share of cheap-judge accepts that passed the real test'}
        return weights

    def summary(self, first_win_at):
        library_wins = [a for a in self.accepted if a['origin'].get('source') == 'library']
        model_wins = [a for a in self.accepted if a['origin'].get('source') in {'luna', 'big-model'}]
        regular = [e for e in self.evaluations if not e['adversarial']]
        final = self.incumbent
        target_speed = 1 + 0.9 * (final['speedup'] - 1)
        reach90 = next((p for p in self.curve if p['speedup'] >= target_speed), None) if final['speedup'] > 1 else None
        return {'task': self.target.name, 'baselineWall': self.baseline_times['wall'], 'finalSpeedupChained': round(final['speedup'], 4),
                'final': {'id': final['id'], 'origin': final['origin'], 'ancestry': final.get('ancestry', [])},
                'evaluations': len(regular), 'firstWinAt': first_win_at,
                'reach90': reach90, 'secondsTotal': round(time.time() - self.started, 1),
                'wins': {'library': len(library_wins), 'model': len(model_wins),
                         'crossover': len([a for a in self.accepted if a['origin'].get('source') == 'crossover'])},
                'libraryShare': round(len(library_wins) / max(len(library_wins) + len(model_wins), 1), 3),
                'verdicts': dict(Counter(e['verdict'] for e in regular)),
                'prefilterKilled': self.ledger['prefilter']['killed'],
                'modelCalls': dict(self.models.used),
                'curve': self.curve, 'archive': {cell: {'id': e['id'], 'speedup': round(e['speedup'], 4), 'move': e['origin'].get('move'),
                                                       'footprint': e['footprint']} for cell, e in self.archive.items()},
                'pareto': self.pareto(), 'adversary': self.adversary_rounds,
                'exploitPredicates': [e['predicate'] for e in self.exploits], 'cheapChecks': self.cheap_checks,
                'judgeWeights': self.judge_weights(), 'retired': self.retired()}


def ablate(target, base: dict, lineage: list, *, log=print, pairs=5):
    """A stronger, later judge over the final candidate: remove each accepted step in turn and keep
    it only if removing it measurably slows the final (wall-minimum >= 1.03 with CPU agreement, or
    CPU >= 1.03). ``lineage`` = [(step id, label, parent files, child files)] from baseline to final."""
    final = dict(lineage[-1][3]) if lineage else dict(base)
    report = []
    for step, label, parent, child in lineage:
        without = revert_step(final, parent, child)
        if without is None or without == final:
            report.append({'step': step, 'label': label, 'kept': True, 'reason': 'cannot be separated'})
            continue
        try:
            for rel, text in without.items():
                compile(text, rel, 'exec')
        except SyntaxError:
            report.append({'step': step, 'label': label, 'kept': True, 'reason': 'removal does not compile'})
            continue
        # A removal that changes or breaks the output is not separable; a crash is never 'faster'.
        same = all(target.measure(without, target.case(check)).get('outputSha256') ==
                   target.measure(final, target.case(check)).get('outputSha256') for check in target.train_checks())
        if not same:
            report.append({'step': step, 'label': label, 'kept': True, 'reason': 'removal changes the output'})
            log(f'  ablation {label}: removal changes the output -> kept')
            continue
        a, b, ca, cb = [], [], [], []
        for index in range(pairs):
            order = [('a', without), ('b', final)] if index % 2 == 0 else [('b', final), ('a', without)]
            for name, files in order:
                wall = cpu = 0
                for check in target.train_checks():
                    result = target.measure(files, target.case(check))
                    wall += result['wall']
                    cpu += result.get('cpuSeconds') or 0
                (a if name == 'a' else b).append(wall)
                (ca if name == 'a' else cb).append(cpu)
        wall_ratio = min(a) / max(min(b), 1e-9)
        cpu_ratio = min(ca) / max(min(cb), 1e-9)
        kept = (wall_ratio >= 1.03 and cpu_ratio >= 0.99) or cpu_ratio >= 1.03
        row = {'step': step, 'label': label, 'kept': kept, 'wallRatioWithoutOverWith': round(wall_ratio, 4),
               'cpuRatioWithoutOverWith': round(cpu_ratio, 4), 'withoutWall': a, 'withWall': b, 'withoutCpu': ca, 'withCpu': cb}
        report.append(row)
        log(f"  ablation {label}: removing it -> wall x{wall_ratio:.3f}, cpu x{cpu_ratio:.3f} -> {'kept' if kept else 'pruned'}")
        if not kept:
            final = without
    return final, report


def revert_step(final: dict, parent: dict, child: dict):
    """``final`` without the change one accepted step made (3-way, per file); None if inseparable."""
    without = {}
    for rel in final:
        if parent.get(rel) == child.get(rel):
            without[rel] = final[rel]
            continue
        merged = merge3(child[rel], final[rel], parent[rel])
        if merged is None:
            return None
        without[rel] = merged
    return without


def merge3(base: str, ours: str, theirs: str):
    with tempfile.TemporaryDirectory() as folder:
        paths = []
        for name, text in (('ours', ours), ('base', base), ('theirs', theirs)):
            path = Path(folder) / name
            path.write_text(text, encoding='utf-8', newline='')
            paths.append(str(path))
        result = subprocess.run(['git', 'merge-file', '-p', *paths], capture_output=True, text=True, encoding='utf-8', creationflags=NO_WINDOW)
        if result.returncode != 0:
            return None
        return result.stdout
