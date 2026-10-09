"""Evidence script: the final EVOLVE gate + CL-compile patches against the current release candidate.

  python scripts/evolve_final.py stale       # is the target stale in its generated files as committed (module map, manual cache)?
  python scripts/evolve_final.py patches     # regenerate both changes from the move library on the target commit
  python scripts/evolve_final.py verify      # every train/held-out/perturbation check: baseline vs patched outputs
  python scripts/evolve_final.py recheck     # re-run (both arms) any check that differed; every attempt is kept
  python scripts/evolve_final.py memo        # memo size and hit count in one real --check process
  python scripts/evolve_final.py time        # interleaved paired timings (5 pairs) + cold gate pairs
  python scripts/evolve_final.py contracts   # the gate's own contract areas (gate.py --worker), baseline vs patched trees
  python scripts/evolve_final.py report      # scripts/evidence/EVOLVE2-final.json
  python scripts/evolve_final.py all

The patches are produced by the same library transforms the engine evolved (statement-walk on
the gate's import scan; skip-repeated-validation, now with a bounded memo, on the compiler's
schema checks), applied to the target commit's own files, plus the module-map lines the
repository's generator writes for them. Measurement trees are private sparse clones of the target
commit in this worktree's ignored .agent_control/evolve; outputs go to D:/NeyviaRuns/EVOLVE2.
Contract trees redirect the hard-coded P22 data root to D:/NeyviaRuns/EVOLVE2/p22-sandbox in both
arms (harness only; P22's folder is never written) and the gate worker's own port block 49081-49089 (its only admitted block; checked free first).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'scripts'))

from grant_agent import evolve_engine as ev  # noqa: E402
from grant_agent import evolve_moves as moves_lib  # noqa: E402
from grant_agent.evolve_gate import GateTarget, TASKS, make_rename_tree, git  # noqa: E402
import evolve_run  # noqa: E402

TARGET_REF = 'track/int-final'
# The release candidate: 469da83aa (3 promotion-tool commits after 7342ab257, which earlier runs targeted;
# their receipts stay at D:/NeyviaRuns/EVOLVE2/*.json and in git history at 5471f3ae5).
TARGET = '469da83aa6032bdeb34ce17faa3a0c47699f7af0'
SOURCE_REPO = Path('C:/Users/user/Projects/Neyvia-next')
WORK = REPO / '.agent_control/evolve'
# Contract trees keep docs/ (+110 MB each) and stay on the internal SSD: D: is a USB disk where a checkout
# of the target ran at about 3 files/s (3499 files in 20 min, 21:09-21:29 on 7 Oct), so it is unusable for trees.
CONTRACT_WORK = WORK
RUN_ROOT = Path('D:/NeyviaRuns/EVOLVE2')
OUT = RUN_ROOT / f'rc-{TARGET[:9]}'
SANDBOX = RUN_ROOT / 'p22-sandbox'
EVIDENCE = REPO / 'scripts/evidence'
# The gate worker's proof_ports admits only the gate's own blocks (49081-49089, 48871-48889) for its
# asyncio wake-up sockets; EVOLVE's block 49141-49149 is refused. Runs here use 49081-49089 only after
# checking that nothing listens there and no gate.py process is running.
PORTS = '49081-49089'
PYTHON = os.environ.get('NEYVIA_SYSTEM_PYTHON') or sys.executable
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
PATCHES = {'gate': EVIDENCE / f'EVOLVE2-gate-{TARGET[:9]}.patch', 'compile': EVIDENCE / f'EVOLVE2-cl-compile-{TARGET[:9]}.patch',
           'combined': EVIDENCE / f'EVOLVE2-combined-{TARGET[:9]}.patch', 'repair': EVIDENCE / f'EVOLVE2-repair-{TARGET[:9]}.patch'}
# Sites the engine's verified finals changed (r5 gate-plan-latest; r6 cl-compile, three steps).
# (file, function, callee, argument source); the third check_schema site of validate_structure
# (rule["schema"]) was never part of the verified final and stays untouched.
GATE_SITES = [('src/grant_agent/contract_gate.py', 'dependencies', 'ast.walk', 'tree')]
COMPILE_SITES = [('src/grant_agent/cl/schema.py', 'add', 'validator_for(schema).check_schema', 'schema'),
                 ('src/grant_agent/manual_contracts.py', 'validate_structure', 'Draft202012Validator.check_schema', 'schema'),
                 ('src/grant_agent/manual_contracts.py', 'validate_structure', 'Draft202012Validator.check_schema', 'row[key]')]
CONTRACT_AREAS = ['fast-contracts', 'generator-outcomes', 'cl-completion', 'cl-effect-outcomes', 'coverage-ratchet', 'measured-coverage',
                  'path-policy-outcomes', 'manual-registry-journey', 'semantic-outcomes', 'release-outcomes']


def log(message):
    line = time.strftime('%H:%M:%S ') + message
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'final.log').open('a', encoding='utf-8') as handle:
        handle.write(line + '\n')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def run(command, cwd, **options):
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          creationflags=NO_WINDOW, **options)


# ---------------------------------------------------------------- trees

def clone(name, docs=False, root=None):
    """A private sparse clone of the target commit (proof/, scripts/evidence/ and, unless docs=True, docs/
    left out). Contract trees keep docs/: the SDK app generator copies docs/design/details-library.md, so
    without it p22.sdk-state fails in both arms with a missing-path error (a harness artefact)."""
    tree = (root or WORK) / name
    pattern = '/*\n!/proof/\n' + ('' if docs else '!/docs/\n') + '!/scripts/evidence/\n'
    if not (tree / '.git').exists():
        tree.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(['git', 'clone', '-q', '--shared', '--no-checkout', str(SOURCE_REPO), str(tree)], creationflags=NO_WINDOW)
        subprocess.check_call(['git', 'sparse-checkout', 'init', '--no-cone'], cwd=tree, creationflags=NO_WINDOW)
        (tree / '.git/info/sparse-checkout').write_text(pattern, encoding='utf-8')
        subprocess.check_call(['git', 'checkout', '-q', '--detach', TARGET], cwd=tree, creationflags=NO_WINDOW)
    else:
        if (tree / '.git/info/sparse-checkout').read_text(encoding='utf-8') != pattern:
            (tree / '.git/info/sparse-checkout').write_text(pattern, encoding='utf-8')
            reset(tree)
        if git(tree, 'rev-parse', 'HEAD') != TARGET:
            reset(tree)  # a private tree from an earlier target commit
    return tree


def measurement_tree():
    tree = clone('int-final-tree')
    if git(tree, 'rev-parse', 'HEAD') != TARGET or git(tree, 'status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('Measurement tree is not the clean target commit: ' + str(tree))
    return tree, make_rename_tree(tree, WORK / 'int-final-rename', commit=TARGET)


def reset(tree):
    subprocess.check_call(['git', 'checkout', '-q', '--detach', '--force', TARGET], cwd=tree, creationflags=NO_WINDOW)
    subprocess.check_call(['git', 'reset', '-q', '--hard', TARGET], cwd=tree, creationflags=NO_WINDOW)


def generate_module_map(tree):
    """The repository's own generator; its receipt (hard-coded under P22's folder) goes to the sandbox."""
    script = tree / 'scripts/generate_module_map.py'
    source = script.read_text(encoding='utf-8').replace(r'D:\NeyviaRuns\P22', str(SANDBOX / 'generator').replace('/', '\\'))
    source = source.replace('D:/NeyviaRuns/P22', (SANDBOX / 'generator').as_posix())
    code = ('import sys,runpy\nsys.argv=[%r]\nsys.path.insert(0,%r)\nns={"__name__":"__main__","__file__":%r}\n'
            'exec(compile(open(%r,encoding="utf-8").read(),%r,"exec"),ns)\n') % (str(script), str(tree / 'src'), str(script), str(OUT / 'generator-source.py'), str(script))
    (OUT / 'generator-source.py').write_text(source, encoding='utf-8')
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH', None)
    result = run([PYTHON, '-c', code], tree, env=env, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError('Module map generation failed: ' + result.stderr[-2000:])
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ''


def build_manual_cache(tree):
    """The repository's own builder of config/fixcl_manual_cache.json, whose manifest holds the raw
    SHA-256 of the CL compiler files (cl/schema.py and manual_contracts.py among them)."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH', None)
    result = run([PYTHON, 'scripts/build_fixcl_manual_cache.py'], tree, env=env, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError('Manual cache build failed: ' + result.stderr[-2000:])
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ''


def regenerate(tree):
    """Every generated file that binds the changed sources: manual cache first, then the module map."""
    return {'manualCache': build_manual_cache(tree), 'moduleMap': generate_module_map(tree)}


# ---------------------------------------------------------------- the changes

def apply_sites(files, sites, transform):
    files = dict(files)
    applied = []
    for rel, function, callee, argument in sites:
        before = files[rel]
        needle = (f'_evolve_once({callee!r}, {callee}, {argument})' if transform is moves_lib.skip_repeated_validation
                  else f' in _evolve_walk_statements({argument})')
        variants = [(text, detail) for text, detail in transform(before) if detail['function'] == function and detail['callee'] == callee
                    and text.count(needle) == before.count(needle) + 1]
        if not variants:
            raise RuntimeError(f'No {transform.__name__} site {rel}:{function} {callee} on the target commit')
        files[rel] = variants[0][0]
        applied.append(variants[0][1])
    return files, applied


HELPER_BLOCK = re.compile(r'# evolve-helper: skip-repeated-validation\n.*?\n    return result\n', re.S)


def patches(names=('repair', 'gate', 'compile', 'combined')):
    tree, _ = measurement_tree()
    gate_base = {rel: (tree / rel).read_text(encoding='utf-8') for rel in TASKS['gate-plan-latest']['targets']}
    compile_base = {rel: (tree / rel).read_text(encoding='utf-8') for rel in TASKS['cl-compile']['targets']}
    gate_final, gate_sites = apply_sites(gate_base, GATE_SITES, moves_lib.statement_walk)
    compile_final, compile_sites = apply_sites(compile_base, COMPILE_SITES, moves_lib.skip_repeated_validation)
    # Same change the engine verified before: r5's gate final exactly; r6's compile final up to the helper body.
    r5 = read_json(Path('D:/NeyviaRuns/EVOLVE/r5/gate-plan-latest-final.json'))
    r6 = read_json(Path('D:/NeyviaRuns/EVOLVE/r6/cl-compile-final.json'))
    changed_compile = sorted(rel for rel in compile_final if compile_final[rel] != compile_base[rel])
    same = {'gateEqualsR5': r5 is not None and all(r5.get(rel) == gate_final[rel] for rel in gate_final),
            'compileEqualsR6ExceptHelper': r6 is not None and all(HELPER_BLOCK.sub('', r6[rel]) == HELPER_BLOCK.sub('', compile_final[rel]) for rel in changed_compile),
            'compileHelperIsBounded': all('_EVOLVE_VALIDATED_MAX = 4096' in compile_final[rel] for rel in changed_compile)}
    write_json(OUT / 'finals.json', {'gate': gate_final, 'compile': compile_final, 'gateBase': gate_base, 'compileBase': compile_base})
    # Apply each change to a clean clone, let the repository's generator update the module map, keep the diff.
    apply_tree = clone('int-final-apply')
    previous = read_json(OUT / 'patches.json') or {}
    produced = dict(previous.get('patches', {}))
    # 'repair': no code change at all. Two generated files of the target are stale as committed: the
    # module map (7342ab257 edited scripts/nx_promote.py without regenerating it) and the CL manual
    # cache manifest (cl/tokens.py hash); the generators' diff on the untouched target is the repair.
    for name, files in (('repair', {}), ('gate', gate_final), ('compile', compile_final), ('combined', {**gate_final, **compile_final})):
        if name not in names:
            continue
        reset(apply_tree)
        for rel, text in files.items():
            if (apply_tree / rel).read_text(encoding='utf-8') != text:
                (apply_tree / rel).write_bytes(text.encode('utf-8'))
        generated = regenerate(apply_tree)
        # Raw bytes: config/fixcl_manual_cache.json is committed with CRLF (-text); text-mode capture
        # would drop the carriage returns and the patch would no longer apply.
        raw = subprocess.run(['git', 'diff', '--no-color', '--no-ext-diff', TARGET], cwd=apply_tree, capture_output=True,
                             creationflags=NO_WINDOW, check=True).stdout
        PATCHES[name].write_bytes(raw)
        diff = raw.decode('utf-8')
        changed = run(['git', 'diff', '--name-only', TARGET], apply_tree).stdout.split()
        produced[name] = {'patch': str(PATCHES[name]), 'files': changed, 'sha256': hashlib.sha256(raw).hexdigest(),
                          'lines': sum(1 for line in diff.splitlines() if line[:1] in '+-' and not line.startswith(('+++', '---'))),
                          'generator': generated}
        log(f'patch {name}: {changed}')
    reset(apply_tree)
    applies = {}
    for name, sequence in (('repair', ['repair']), ('gate', ['gate']), ('compile', ['compile']), ('combined', ['combined']),
                           ('gate-then-compile', ['gate', 'compile'])):
        index = OUT / f'apply-{name}.index'
        index.unlink(missing_ok=True)
        env = dict(os.environ, GIT_INDEX_FILE=str(index))
        subprocess.check_call(['git', 'read-tree', TARGET], cwd=apply_tree, env=env, creationflags=NO_WINDOW)
        ok, errors = True, []
        for part in sequence:
            result = run(['git', 'apply', '--cached', str(PATCHES[part])], apply_tree, env=env)
            ok = ok and result.returncode == 0
            if result.returncode:
                errors.append(result.stderr.strip()[-600:])
        applies[name] = {'ok': ok, 'errors': errors}
        index.unlink(missing_ok=True)
        log(f'git apply on {TARGET[:9]} {name}: {ok}')
    write_json(OUT / 'patches.json', {'target': TARGET, 'targetRef': TARGET_REF, 'sites': {'gate': gate_sites, 'compile': compile_sites},
                                      'sameAsEngineFinals': same, 'patches': produced, 'applies': applies})
    return read_json(OUT / 'patches.json')


def finals():
    data = read_json(OUT / 'finals.json')
    if data is None:
        patches()
        data = read_json(OUT / 'finals.json')
    return data


# ---------------------------------------------------------------- outputs, timings, memo

def compile_tree():
    """The compiler cannot be measured on the target as committed: its stale module map makes
    --check raise 'Module map drifted' in both arms. Its tree = target + the repair patch only."""
    tree = clone('int-final-compile')
    reset(tree)
    result = run(['git', 'apply', str(PATCHES['repair'])], tree)
    if result.returncode:
        raise RuntimeError('Repair patch does not apply: ' + result.stderr)
    return tree


def targets():
    tree, rename = measurement_tree()
    return (GateTarget('gate-plan-latest', tree, OUT / 'gate', rename_tree=rename),
            GateTarget('cl-compile', compile_tree(), OUT / 'compile'))


def same_outcome(a, b):
    """Byte-identical normalised output or raised error with the same status. Perturbations such as an
    edited manual, an edited source or an invalid schema are expected to raise (stale compiled artifact,
    module-map drift, SchemaCompileError); the patched arm must raise exactly the same way."""
    return (a.get('outputSha256') is not None and a.get('outputSha256') == b.get('outputSha256')
            and a.get('status') == b.get('status') and a.get('status') in {'ok', 'error'})


def verify(tasks=('gate', 'compile')):
    data = finals()
    gate, compiler = targets()
    out = read_json(OUT / 'verify.json') or {}
    for name, target, base, final in (('gate', gate, data['gateBase'], data['gate']), ('compile', compiler, data['compileBase'], data['compile'])):
        if name not in tasks:
            continue
        rows = {}
        for check in target.all_checks():
            a = target.check(base, check)
            b = target.check(final, check)
            rows[check] = {'baseline': a.get('outputSha256'), 'patched': b.get('outputSha256'), 'baselineStatus': a.get('status'),
                           'patchedStatus': b.get('status'), 'identical': same_outcome(a, b),
                           'baselineWall': round(a.get('wall', 0), 2), 'patchedWall': round(b.get('wall', 0), 2)}
            log(f'verify {name} {check}: {rows[check]["baselineStatus"]}/{rows[check]["patchedStatus"]} identical={rows[check]["identical"]}')
        out[name] = {'checks': rows, 'identical': all(r['identical'] for r in rows.values()), 'count': len(rows)}
        write_json(OUT / 'verify.json', out)
    return out


def recheck(attempts=2):
    """Re-run every check that differed, both arms, on a quieter machine. The gate's planning has a
    240 s wall deadline: under heavy load a cold run can exhaust it and report 'not run' steps, which
    is a timing outcome, not a patch outcome. Every attempt is kept in the receipt."""
    data = finals()
    gate, compiler = targets()
    checked = read_json(OUT / 'verify.json')
    for name, target, base, final in (('gate', gate, data['gateBase'], data['gate']), ('compile', compiler, data['compileBase'], data['compile'])):
        for check, row in checked[name]['checks'].items():
            if row['identical']:
                continue
            row.setdefault('earlierAttempts', [])
            for _ in range(attempts):
                row['earlierAttempts'].append({k: row[k] for k in ('baseline', 'patched', 'baselineStatus', 'patchedStatus', 'baselineWall', 'patchedWall')})
                a = target.check(base, check)
                b = target.check(final, check)
                row.update(baseline=a.get('outputSha256'), patched=b.get('outputSha256'), baselineStatus=a.get('status'), patchedStatus=b.get('status'),
                           baselineWall=round(a.get('wall', 0), 2), patchedWall=round(b.get('wall', 0), 2),
                           identical=same_outcome(a, b))
                log(f'recheck {name} {check}: identical={row["identical"]} ({row["baselineWall"]}s / {row["patchedWall"]}s)')
                if row['identical']:
                    break
        checked[name]['identical'] = all(r['identical'] for r in checked[name]['checks'].values())
    write_json(OUT / 'verify.json', checked)
    return checked


MEMO_PROBE = r'''
import contextlib, io, json, os, sys
from pathlib import Path
tree, overlay, receipt, runner = map(Path, sys.argv[1:5])
sys.path.insert(0, str(tree / 'src')); sys.path.insert(0, str(runner.parent))
from evolve_gate_runner import install_overlay
install_overlay(tree, json.loads(overlay.read_text(encoding='utf-8')))
os.chdir(tree)
from grant_agent.cl import schema
from grant_agent import manual_contracts
counts = {}
for module in (schema, manual_contracts):
    original = module._evolve_once
    def counted(label, call, *args, _original=original, _name=module.__name__):
        row = counts.setdefault(_name, {'calls': 0, 'validatorRuns': 0})
        row['calls'] += 1
        def run(*a):
            row['validatorRuns'] += 1
            return call(*a)
        return _original(label, run, *args)
    module._evolve_once = counted
script = tree / 'scripts/cl_compile_manuals.py'
sys.argv = [str(script), '--check', '--receipt', str(receipt)]
with contextlib.redirect_stdout(io.StringIO()) as out:
    exec(compile(script.read_bytes(), str(script), 'exec'), {'__name__': '__main__', '__file__': str(script)})
print(json.dumps({'counts': counts, 'entries': {m.__name__: len(m._EVOLVE_VALIDATED) for m in (schema, manual_contracts)},
                  'bound': {m.__name__: m._EVOLVE_VALIDATED_MAX for m in (schema, manual_contracts)}, 'stdout': out.getvalue()[-300:]}))
'''


def memo():
    data = finals()
    _, compiler = targets()
    overlay = compiler.materialise(data['compile'])
    mapping = {rel: path for rel, path in json.loads(overlay.read_text(encoding='utf-8')).items() if rel.startswith('src/')}
    probe_overlay = OUT / 'memo-overlay.json'
    write_json(probe_overlay, mapping)
    receipt = OUT / 'memo-receipt' / 'receipt.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH', None)
    result = run([PYTHON, '-c', MEMO_PROBE, str(compiler.tree), str(probe_overlay), str(receipt), str(REPO / 'scripts/evolve_gate_runner.py')],
                 compiler.tree, env=env, timeout=1800)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    row = json.loads(result.stdout.strip().splitlines()[-1])
    row['maxEntries'] = max(row['entries'].values())
    row['withinBound'] = all(row['entries'][m] <= row['bound'][m] for m in row['entries'])
    row['skipped'] = {m: c['calls'] - c['validatorRuns'] for m, c in row['counts'].items()}
    write_json(OUT / 'memo.json', row)
    log(f'memo: entries {row["entries"]} bound {row["bound"]} calls {row["counts"]}')
    return row


def timing(tasks=('gate', 'compile')):
    data = finals()
    gate, compiler = targets()
    out = read_json(OUT / 'timing.json') or {}
    if 'gate' in tasks:
        log('timing gate (5 interleaved pairs: warm commit HEAD~5 + cold commit HEAD~3)')
        out['gate'] = evolve_run.direct_speedup(gate, data['gateBase'], data['gate'])
        out['gateCold'] = evolve_run.cold_speedup(gate, data['gateBase'], data['gate'])
        log(f"gate {out['gate']['speedup']}x (min {out['gate']['speedupMin']}x, cpu {out['gate']['cpuSpeedup']}x); cold {out['gateCold']['speedup']}x")
    if 'compile' in tasks:
        log('timing compile (5 interleaved pairs: --check)')
        out['compile'] = evolve_run.direct_speedup(compiler, data['compileBase'], data['compile'])
        log(f"compile {out['compile']['speedup']}x (min {out['compile']['speedupMin']}x, cpu {out['compile']['cpuSpeedup']}x)")
    write_json(OUT / 'timing.json', out)
    return out


# ---------------------------------------------------------------- the gate's own contracts

REDIRECTS = [('NeyviaRuns\\\\P22', 'NeyviaRuns\\\\EVOLVE2\\\\p22-sandbox'), ('NeyviaRuns\\P22', 'NeyviaRuns\\EVOLVE2\\p22-sandbox'),
             ('NeyviaRuns/P22', 'NeyviaRuns/EVOLVE2/p22-sandbox')]


def contract_tree(arm):
    """Clean clone (+ the combined patch for the patched arm); then the harness-only data-root redirect
    and a module-map regeneration, identical in both arms."""
    tree = clone(f'int-final-{arm}', docs=True, root=CONTRACT_WORK)
    reset(tree)
    subprocess.check_call(['git', 'clean', '-q', '-fdx', '-e', '.agent_control'], cwd=tree, creationflags=NO_WINDOW)
    # Baseline = target + the repair of its stale generated files; patched = target + combined patch
    # (which carries the same repair), so the comparison isolates EVOLVE's change.
    result = run(['git', 'apply', str(PATCHES['combined' if arm == 'patched' else 'repair'])], tree)
    if result.returncode:
        raise RuntimeError(f'{arm} patch does not apply: ' + result.stderr)
    redirected = []
    for folder in ('src', 'scripts'):
        for path in (tree / folder).rglob('*'):
            if path.suffix not in {'.py', '.mjs', '.js', '.json'} or not path.is_file():
                continue
            data = path.read_bytes()
            new = data
            for old, replacement in REDIRECTS:
                new = new.replace(old.encode(), replacement.encode())
            if new != data:
                path.write_bytes(new)
                redirected.append(path.relative_to(tree).as_posix())
    regenerated = regenerate(tree)
    compile_check = run([PYTHON, 'scripts/cl_compile_manuals.py', '--check'], tree,
                        env={k: v for k, v in dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1').items() if k != 'PYTHONPATH'},
                        timeout=1800)
    cache_check = run([PYTHON, 'scripts/build_fixcl_manual_cache.py', '--check'], tree,
                      env={k: v for k, v in dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1').items() if k != 'PYTHONPATH'},
                      timeout=1800)
    return tree, {'redirectedFiles': len(redirected), 'regenerated': regenerated, 'manualCacheCheckOk': cache_check.returncode == 0,
                  'compileCheck': compile_check.stdout.strip().splitlines()[-1:] or compile_check.stderr[-400:],
                  'compileOk': compile_check.returncode == 0}


def gate_selection(tree, arm='patched'):
    """The gate's own impact selection for the patch's changed files (subprocess steps stubbed). Run in
    both arms: besides the selection itself, a gate run creates the .agent_control/p22 state that
    some contracts expect (a worker in a tree that never ran the gate fails on a missing job guard)."""
    out = OUT / 'contracts' / f'selection-{arm}.json'
    changed = sorted({rel for rel in read_json(OUT / 'patches.json')['patches']['combined']['files'] if rel.endswith('.py')})
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH', None)
    run([PYTHON, str(REPO / 'scripts/evolve_gate_runner.py'), '--tree', str(tree), '--task', 'plan', '--since', 'HEAD~1', '--paths', *changed,
         '--root', str(WORK / 'gate-roots/selection'), '--out', str(out)], tree, env=env, timeout=1800)
    report = read_json(out)
    return changed, (report.get('output') or {}).get('jobs', {}), len((report.get('output') or {}).get('selectedContracts', []))


def worker(tree, arm, area, contracts):
    job_root = OUT / 'contracts' / arm / area
    shutil.rmtree(job_root, ignore_errors=True)
    job_root.mkdir(parents=True)
    spec = job_root / 'job.json'
    state = SANDBOX / 'state' / arm / area
    shutil.rmtree(state, ignore_errors=True)
    spec.write_text(json.dumps({'area': area, 'contracts': contracts, 'stateRoot': str(state)}), encoding='utf-8')
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', NEYVIA_GATE_ASSIGNED_PORTS=PORTS,
               NEYVIA_BROWSER_PROOF_PORTS=PORTS, NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_COORDINATOR_AUTOSTART='0',
               TEMP=str(job_root / 'temp'), TMP=str(job_root / 'temp'))
    # As gate.run() does: the installed public tokenizer bytes are bound before TEMP is isolated
    # (the worker copies and hash-checks them); otherwise tokenizer-using contracts try the network.
    import tempfile
    tokenizer = Path(os.environ.get('TIKTOKEN_CACHE_DIR') or Path(tempfile.gettempdir()) / 'data-gym-cache')
    if tokenizer.is_dir():
        env['TIKTOKEN_CACHE_DIR'] = str(tokenizer)
    (job_root / 'temp').mkdir()
    env.pop('PYTHONPATH', None)
    started = time.time()
    try:
        result = run([PYTHON, 'scripts/gate.py', '--worker', str(spec)], tree, env=env, timeout=2400)
        code, tail = result.returncode, result.stderr[-1500:]
    except subprocess.TimeoutExpired:
        code, tail = 'timeout', ''
    outcomes = read_json(job_root / 'outcomes.json') or {}
    witnessed = sorted({identity for case in outcomes.get('cases', []) if case.get('ok') is True for identity in case.get('contracts', [])})
    return {'exitCode': code, 'ok': outcomes.get('ok'), 'witnessed': witnessed, 'missing': sorted(set(contracts) - set(witnessed)),
            'seconds': round(time.time() - started, 1), 'stderrTail': tail if code else ''}


def ports_free():
    first, last = map(int, PORTS.split('-'))
    import socket
    busy = []
    for port in range(first, last + 1):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                busy.append(port)
    gates = run(['powershell', '-NoProfile', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'gate.py' } | Measure-Object | Select-Object -ExpandProperty Count"],
                REPO).stdout.strip()
    return busy, gates


def wait_for_ports(limit=5400):
    """Another session's gate workers use the same block: never overlap them; wait (bounded)."""
    started = time.time()
    while True:
        busy, gates = ports_free()
        if not busy and gates in {'', '0'}:
            return round(time.time() - started)
        if time.time() - started > limit:
            raise SystemExit(f'Gate port block {PORTS} busy {busy} or gate.py running ({gates}) for {limit} s; contracts not run')
        log(f'waiting: gate block busy {busy}, gate.py processes {gates}')
        time.sleep(60)


def contracts(areas=None, reuse=False, patched_first=False):
    if not PATCHES['combined'].exists():
        patches()
    trees = {}
    previous = read_json(OUT / 'contracts.json') or {}
    for arm in ('baseline', 'patched'):
        if reuse and previous.get('trees', {}).get(arm, {}).get('compileOk'):
            trees[arm] = (CONTRACT_WORK / f'int-final-{arm}', previous['trees'][arm])
        else:
            trees[arm] = contract_tree(arm)
        log(f'contract tree {arm}: {trees[arm][1]}')
    wait_for_ports()
    _, baseline_jobs, baseline_selected = gate_selection(trees['baseline'][0], 'baseline')
    changed, jobs, selected = gate_selection(trees['patched'][0], 'patched')
    log(f'gate selection for {changed}: {selected} contracts in {len(jobs)} areas (baseline tree: {baseline_selected}, same jobs {baseline_jobs == jobs})')
    results = {'ports': PORTS, 'changedFiles': changed, 'gateSelected': selected, 'sameSelectionBothTrees': baseline_jobs == jobs, 'gateAreas': len(jobs), 'trees': {a: t[1] for a, t in trees.items()},
               'areas': dict(previous.get('areas', {})) if areas else {}}
    for area in areas or CONTRACT_AREAS:
        identities = jobs.get(area)
        if not identities:
            continue
        row = {'requested': identities, 'order': ['patched', 'baseline'] if patched_first else ['baseline', 'patched']}
        earlier = results['areas'].get(area)
        if earlier:  # a re-run of one area keeps every earlier attempt
            row['earlierAttempts'] = earlier.pop('earlierAttempts', []) + [earlier]
        for arm in row['order']:
            row.setdefault('waitedSeconds', {})[arm] = wait_for_ports()
            row[arm] = worker(trees[arm][0], arm, area, identities)
        row['sameWitnesses'] = row['baseline']['witnessed'] == row['patched']['witnessed']
        row['allWitnessedPatched'] = not row['patched']['missing']
        results['areas'][area] = row
        log(f"contracts {area}: baseline {len(row['baseline']['witnessed'])}/{len(identities)} patched {len(row['patched']['witnessed'])}/{len(identities)} "
            f"same={row['sameWitnesses']} ({row['baseline']['seconds']}s/{row['patched']['seconds']}s)")
        write_json(OUT / 'contracts.json', results)
    requested = sum(len(r['requested']) for r in results['areas'].values())
    results['summary'] = {'areas': len(results['areas']), 'requested': requested,
                          'witnessedBaseline': sum(len(r['baseline']['witnessed']) for r in results['areas'].values()),
                          'witnessedPatched': sum(len(r['patched']['witnessed']) for r in results['areas'].values()),
                          'sameEverywhere': all(r['sameWitnesses'] for r in results['areas'].values()),
                          'patchedMissing': sorted(c for r in results['areas'].values() for c in r['patched']['missing']),
                          'baselineMissing': sorted(c for r in results['areas'].values() for c in r['baseline']['missing'])}
    write_json(OUT / 'contracts.json', results)
    return results


# ---------------------------------------------------------------- the target as committed

def stale():
    """Are the target's generated files stale as committed? A clean clone of the target runs the module-map
    check, the gate's cl-compile step and the manual-cache check; then the repository's own generators run
    and the resulting diff (the repair) is recorded line by line."""
    tree = clone('int-final-stale')
    reset(tree)
    subprocess.check_call(['git', 'clean', '-q', '-fdx', '-e', '.agent_control'], cwd=tree, creationflags=NO_WINDOW)
    env = {k: v for k, v in dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1').items() if k != 'PYTHONPATH'}
    checks = {}
    for name, command in (('moduleMap', [PYTHON, '-c', 'import sys; sys.path.insert(0, "src"); from grant_agent import module_map; module_map.check()']),
                          ('clCompileCheck', [PYTHON, 'scripts/cl_compile_manuals.py', '--check']),
                          ('manualCacheCheck', [PYTHON, 'scripts/build_fixcl_manual_cache.py', '--check'])):
        result = run(command, tree, env=env, timeout=1800)
        tail = (result.stderr.strip() or result.stdout.strip()).splitlines()[-1:] or ['']
        checks[name] = {'exitCode': result.returncode, 'ok': result.returncode == 0, 'last': tail[0][-300:]}
        log(f'target as committed {name}: exit {result.returncode} {tail[0][-160:]}')
    regenerate(tree)
    diff = subprocess.run(['git', 'diff', '--no-color', '-U0', TARGET], cwd=tree, capture_output=True, creationflags=NO_WINDOW, check=True).stdout.decode('utf-8')
    lines = [line.strip() for line in diff.splitlines() if line[:1] in '+-' and not line.startswith(('+++', '---'))]
    blob = {rel: hashlib.sha256(subprocess.run(['git', 'cat-file', '-p', f'{TARGET}:{rel}'], cwd=tree, capture_output=True,
                                               creationflags=NO_WINDOW, check=True).stdout).hexdigest()
            for rel in ('src/grant_agent/cl/tokens.py', 'scripts/nx_promote.py')}
    last_map = git(tree, 'log', '-1', '--format=%h %s', TARGET, '--', 'config/neyvia.modules.json')
    last_promote = git(tree, 'log', '-1', '--format=%h %s', TARGET, '--', 'scripts/nx_promote.py')
    row = {'target': TARGET, 'checks': checks, 'stale': not all(c['ok'] for c in checks.values()), 'repairLines': lines,
           'committedBlobSha256': blob, 'lastModuleMapCommit': last_map, 'lastNxPromoteCommit': last_promote,
           'note': ('Hashes are of the committed blobs (no line-ending conversion involved). The repair patch is the generators\' '
                    'diff on the untouched target; the gate, compile and combined patches each contain it, and compile '
                    'measurements and the contract baseline use target + repair.')}
    reset(tree)
    write_json(OUT / 'stale.json', row)
    return row


# ---------------------------------------------------------------- report

def report():
    made = read_json(OUT / 'patches.json')
    checked = read_json(OUT / 'verify.json')
    timed = read_json(OUT / 'timing.json')
    memo_row = read_json(OUT / 'memo.json')
    contract_rows = read_json(OUT / 'contracts.json')
    final = {'schema': 'neyvia.evolve.final.v1', 'targetRef': TARGET_REF, 'target': TARGET, 'patches': made['patches'], 'applies': made['applies'],
             'sameAsEngineFinals': made['sameAsEngineFinals'], 'sites': made['sites'],
             'appliesToTarget': all(v['ok'] for k, v in made['applies'].items() if k in {'gate', 'compile', 'combined'}),
             'verify': {name: {'identical': all(same_outcome({'outputSha256': r['baseline'], 'status': r['baselineStatus']},
                                                             {'outputSha256': r['patched'], 'status': r['patchedStatus']}) for r in row['checks'].values()),
                               'count': row['count'],
                               'checks': {c: {k: v for k, v in r.items() if k in {'identical', 'baselineStatus', 'patchedStatus'}} for c, r in row['checks'].items()}}
                        for name, row in (checked or {}).items()},
             'outputsIdentical': bool(checked) and all(same_outcome({'outputSha256': r['baseline'], 'status': r['baselineStatus']},
                                                                    {'outputSha256': r['patched'], 'status': r['patchedStatus']})
                                                       for row in checked.values() for r in row['checks'].values()),
             'timing': timed, 'memo': memo_row,
             'gateSpeedup': (timed or {}).get('gate', {}).get('speedup', 0), 'compileSpeedup': (timed or {}).get('compile', {}).get('speedup', 0),
             'memoEntries': (memo_row or {}).get('maxEntries'), 'memoBound': min((memo_row or {}).get('bound', {0: 0}).values()),
             'contracts': contract_rows and {**contract_rows['summary'], 'gateSelected': contract_rows['gateSelected'], 'gateAreas': contract_rows['gateAreas'],
                                             'perArea': {a: {'requested': len(r['requested']), 'baseline': len(r['baseline']['witnessed']),
                                                             'patched': len(r['patched']['witnessed']), 'same': r['sameWitnesses'],
                                                             'patchedMissing': r['patched']['missing']} for a, r in contract_rows['areas'].items()},
                                             'trees': contract_rows['trees']},
             'contractsSame': bool(contract_rows) and contract_rows['summary']['sameEverywhere'],
             'targetGeneratedFilesStale': read_json(OUT / 'stale.json'),
             'stacking': 'gate and compile patches are alternatives (each carries module-map lines and the repair); apply "combined" for both',
             'harness': ['Outputs and timings: the engine runner overlays candidate modules on a clean sparse clone of the target (subprocess steps of the gate stubbed for planning, exactly as the engine measured).',
                         'Contracts: gate.py --worker on a git-applied combined patch vs target + repair patch; both arms redirect the hard-coded D:/NeyviaRuns/P22 root to D:/NeyviaRuns/EVOLVE2/p22-sandbox and regenerate the manual cache and module map; ports ' + PORTS + ' (the gate worker admits only its own blocks), waited free first.']}
    write_json(EVIDENCE / 'EVOLVE2-final.json', final)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step', choices=['stale', 'patches', 'verify', 'recheck', 'memo', 'time', 'contracts', 'report', 'all'])
    parser.add_argument('--areas', nargs='+')
    parser.add_argument('--reuse', action='store_true', help='reuse contract trees whose compile check passed')
    parser.add_argument('--patched-first', action='store_true', help='run the patched arm first (order-effect check for wall-clock-bounded contracts)')
    parser.add_argument('--patches', nargs='+', default=['repair', 'gate', 'compile', 'combined'])
    parser.add_argument('--tasks', nargs='+', default=['gate', 'compile'])
    args = parser.parse_args()
    steps = ['stale', 'patches', 'verify', 'recheck', 'memo', 'time', 'contracts', 'report'] if args.step == 'all' else [args.step]
    for step in steps:
        log(f'== {step}')
        result = {'stale': stale, 'patches': lambda: patches(args.patches), 'verify': lambda: verify(args.tasks), 'recheck': recheck, 'memo': memo, 'time': lambda: timing(args.tasks),
                  'contracts': lambda: contracts(args.areas, args.reuse, args.patched_first), 'report': report}[step]()
        print(json.dumps(result, default=str)[:1500])


if __name__ == '__main__':
    main()
