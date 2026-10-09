"""Select authored proof outcomes through source sites and module dependencies.

Unknown changes and missing witnesses fail closed. Receipts distinguish the
contract gate from release admission while the independent LAYA step is absent.
"""
from __future__ import annotations

# evolve-helper: statement-walk
def _evolve_walk_statements(tree):
    """Statement nodes only: statements never occur inside expressions."""
    import ast as _ast
    pending = [tree]
    while pending:
        node = pending.pop()
        yield node
        for field in ('body', 'orelse', 'finalbody', 'handlers', 'cases'):
            children = getattr(node, field, None)
            if isinstance(children, list):
                pending.extend(child for child in reversed(children) if isinstance(child, _ast.AST))


import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
_SOURCE_PATHS = None
_PYTHON_SITES = None

# Known runner requirements are explicit, rather than quietly launching a
# different browser or claiming that an unavailable journey passed.
RUNNER_LIMITS = {
    'a-capabilities': {identity:'The factory journey requires a hard-coded Chrome launch'
                       for identity in ['a.factory-notes-ui','a.factory-guided-ui']},
}


def output_root(path, *, small=False):
    path = Path(path).resolve()
    allowed = [Path('D:/NeyviaRuns').resolve()]
    if small:
        allowed.append((REPO / '.agent_control/p22').resolve())
    if not any(path.is_relative_to(parent) for parent in allowed):
        raise ValueError('Builds and renders belong under D:/NeyviaRuns; only small startup state may use the owned p22 directory')
    return path


def assigned_ports(ports):
    ports = tuple(ports)
    blocks=(set(range(48871,48890)),set(range(49081,49090)))
    if len(ports) != 2 or len(set(ports)) != 2 or not any(set(ports)<=block for block in blocks):
        raise ValueError('Assign two different loopback ports within one owned gate block')
    return ports


def laya_admitted(result, allow_unavailable=False, *, advisory=False):
    return advisory is True or result.get('ok') is True or (allow_unavailable and result.get('status') == 'not available')


def wants(identities):
    """Shared case-group selection; full legacy runs remain explicit opt-in."""
    configured = os.environ.get('NEYVIA_GATE_CONTRACTS')
    if configured is None:
        return True
    identities = [identities] if isinstance(identities, str) else identities
    return bool(set(identities) & set(json.loads(configured)))


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True, encoding="utf-8",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0).strip()


def git_paths(*args):
    """Preserve path spelling, including spaces, Unicode and embedded newlines."""
    return [name for name in git(*args, '-z').split('\0') if name]


def python_sites(files):
    result={}
    for name in files:
        if name.startswith('src/grant_agent/') and name.endswith('.py'):
            module=name[len('src/grant_agent/'):].removesuffix('.py').replace('/','.')
            for alias in (module,'grant_agent.'+module):result.setdefault(alias,set()).add(name)
    return result


def sites(text, *, python_owners=None):
    found = set(re.findall(r"(?:src|web|scripts|config|manuals|sdk|tests|apps|packages|tools|templates|plugins|rust|connectors|src-tauri|desktop-ui)/[\w/.-]+\.(?:py|[cm]?jsx?|tsx?|css|html|json|cl|rs|toml|cs|cpp|gd|lua|cfg|patch)", text))
    found.update(re.findall(r'\b(?:vite\.config\.mjs|package\.json|pyproject\.toml)\b',text))
    # Older authored contracts use bare Python owners (foo.Bar.method),
    # while newer ones use grant_agent.foo.Bar.method. Both name real sites.
    python_owners=_PYTHON_SITES if python_owners is None else python_owners
    if python_owners is not None:
        for reference in re.findall(r'\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+',text):
            parts=reference.split('.')
            for end in range(len(parts),0,-1):
                name='.'.join(parts[:end])
                if name in python_owners:
                    found.update(python_owners[name]);break
    for name in re.findall(r"\bgrant_agent\.([\w.]+)", text):
        parts = name.rstrip(".").split(".")
        for end in range(len(parts), 0, -1):
            candidate = "src/grant_agent/" + "/".join(parts[:end]) + ".py"
            if (_SOURCE_PATHS is not None and candidate in _SOURCE_PATHS) or (_SOURCE_PATHS is None and (REPO / candidate).is_file()):
                found.add(candidate)
                break
    return found


def inventory():
    contracts, manifests = {}, {}
    for path in sorted((REPO / "manuals/cl").glob("*.cl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("-- @proof "):
                row = json.loads(line[len("-- @proof "):])
                if row["id"] in contracts:
                    raise ValueError("Duplicate authored proof: " + row["id"])
                contracts[row["id"]] = {**row, "source": path.relative_to(REPO).as_posix()}
    for path in sorted((REPO / "config/proofs").glob("*.json")):
        if path.name == "test-inventory.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("area"):
            manifests[data["area"]] = {**data, '_source': path.relative_to(REPO).as_posix()}
            for row in data.get("contracts", []):
                if row["id"] in contracts:
                    contracts[row["id"]].setdefault("areas", []).append(data["area"])
    return contracts, manifests


def dependencies():
    """Import edges are the local module map, including optional plan-21 maps."""
    global _SOURCE_PATHS, _PYTHON_SITES
    files = [name for name in git_paths("ls-files", "--cached", "--others", "--exclude-standard", "src", "web/src", "scripts")
             if not name.startswith("scripts/evidence/") and "/vendor/" not in name]
    known = set(files)
    _SOURCE_PATHS = known
    _PYTHON_SITES=python_sites(files)
    cache_path = REPO / ".agent_control/p22/module-imports.json"
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    saved = {}
    edges = {}
    for name in files:
        path = REPO / name
        if not path.is_file() or path.suffix not in {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs"}:
            continue
        info = path.stat()
        stamp = [info.st_mtime_ns, info.st_size]
        if cached.get(name, {}).get("stamp") == stamp:
            saved[name] = cached[name]
            edges[name] = set(cached[name]["refs"])
            continue
        source = path.read_text(encoding="utf-8-sig")
        refs = set()
        if path.suffix == ".py":
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in _evolve_walk_statements(tree):
                if isinstance(node, ast.Import):
                    refs.update(site for alias in node.names for site in sites(alias.name))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level and name.startswith("src/grant_agent/"):
                        base = name.removesuffix(".py").split("/")[:-node.level]
                        module = ".".join(base[1:] + module.split(".")) if module else ".".join(base[1:])
                    refs.update(sites(module))
                    refs.update(site for alias in node.names for site in sites(module + "." + alias.name))
        else:
            for ref in re.findall(r"(?:from\s*|import\s*\(|import\s*)['\"]([^'\"]+)['\"]", source):
                if ref.startswith("."):
                    stem = (path.parent / ref).resolve()
                    for candidate in [stem, *[Path(str(stem) + suffix) for suffix in (".js", ".jsx", ".ts", ".tsx", ".css")]]:
                        if candidate.is_relative_to(REPO) and candidate.relative_to(REPO).as_posix() in known:
                            refs.add(candidate.relative_to(REPO).as_posix())
        edges[name] = refs
        saved[name] = {"stamp": stamp, "refs": sorted(refs)}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    from .durability import atomic_write_json
    atomic_write_json(cache_path, saved)
    # An explicit map may add non-import dependencies; never replaces real edges.
    map_path = REPO / "config/contract_module_map.json"
    if map_path.is_file():
        for owner, refs in json.loads(map_path.read_text(encoding="utf-8")).items():
            edges.setdefault(owner, set()).update(refs)
    return edges


def exact_renames(since):
    """Preserve current ownership for Git-confirmed unchanged code moves."""
    rows=git('diff','--name-status','--find-renames=100%','--diff-filter=R',since,'HEAD','--',
             'src','web/src','scripts','apps','tools','connectors','plugins','desktop-ui',
             ':(exclude)scripts/evidence').splitlines()
    return {old:new for status,old,new in (row.split('\t') for row in rows) if status=='R100'}


def select(changed, *, renames=None):
    from .contract_coverage import model, uncovered_by_module
    changed_set = set(changed)
    edges = dependencies()
    contracts, manifests = inventory()
    ownership=model(REPO,changed,contracts,sites,renames=renames)
    for owner,refs in ownership['dependencies'].items():edges.setdefault(owner,set()).update(refs)
    consumers = {}
    for owner, refs in edges.items():
        for ref in refs:
            consumers.setdefault(ref, set()).add(owner)
    origins = {}
    origins_by_module = {}
    direct_origins = {}
    for name,target in ownership['origins'].items():
        direct_origins.setdefault(target,set()).add(name)
        visited, pending = set(), [target]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            pending.extend(consumers.get(current, ()))
        origins[name] = visited
        for module in visited:
            origins_by_module.setdefault(module, set()).add(name)
    affected = set().union(*origins.values()) if origins else set()
    selected, coverage = {}, {path: [] for path in ownership['origins']}
    module_files={}
    for file,module in ownership['owners'].items():
        for identity in ownership['outcomes'][module]:module_files.setdefault(identity,set()).add(file)
    for identity, row in contracts.items():
        bound = set().union(*(sites(text) for text in row.get("checkedAt", []) + row.get("impact", []))) | {row["source"]}
        bound.add('manuals/' + Path(row['source']).stem + '.manual.json')
        bound.update(module_files.get(identity,()))
        for area in row.get("areas", []):
            bound.add(manifests[area]['_source'])
            # Editing a runner impacts its witnesses. Its imports must not
            # make an unrelated source edit select every case in that runner.
            manifest=manifests[area]
            runner_sites=sites(manifest.get('runner','')) | sites(manifest.get('module',''))
            bound.update(runner_sites & changed_set)
        covered_origins = set().union(*(origins_by_module.get(module, set()) for module in bound))
        proof_input_changed = any(manifests[area]['_source'] in changed_set for area in row.get('areas', []))
        if covered_origins or proof_input_changed:
            selected[identity] = row
            # The reverse index preserves each independent changed origin,
            # without scanning an entire release diff for every contract.
            # Imports expand impact selection, but an unrelated consumer's
            # smoke check cannot satisfy the changed owner's outcome obligation.
            direct_coverage=set().union(*(direct_origins.get(file,set()) for file in bound))
            for name in direct_coverage:
                coverage[name].append(identity)
    metadata = [name for name,row in ownership['classes'].items() if row['kind']=='no behaviour']
    metadata_set = set(metadata)
    uncovered = [name for name, ids in coverage.items() if not ids and name not in metadata_set]
    jobs = {}
    unbound = []
    for identity, row in selected.items():
        if not row.get("areas"):
            unbound.append(identity)
        for area in row.get("areas", []):
            jobs.setdefault(area, []).append(identity)
    return {"contracts": selected, "jobs": jobs, "uncovered": uncovered,
            "unboundContracts": unbound, "coverage": coverage, "metadataOnly": metadata,
            "pathPolicyCounts":ownership['counts'],
            "renamedPaths":{name:row['ownerPath'] for name,row in ownership['classes'].items() if 'ownerPath' in row},
            "uncoveredByModule":uncovered_by_module(uncovered,ownership['classes'],ownership['owners']),
            "uncoveredByCategory":dict(Counter(ownership['classes'][name]['kind'] for name in uncovered)),
            "generatedPaths":{name:row['generator'] for name,row in ownership['classes'].items() if row['kind']=='generated'},
            "affectedModules": sorted(affected), "manifests": manifests}


def process(command, root, timeout, env=None):
    from .contract_resources import capture_resource_bounded
    started = time.perf_counter()
    try:
        process_env = dict(env or os.environ, NEYVIA_PROOF_AREA_TIMEOUT=str(timeout))
        captured = capture_resource_bounded(command, cwd=REPO, env=process_env, input_text=None, timeout=timeout,
                                            logs_root=root, acquire_slot='--worker' not in command)
    except OSError as error:
        return {'ok':False,'error':str(error),'durationMs':round((time.perf_counter()-started)*1000),'logs':str(root)}
    root.mkdir(parents=True, exist_ok=True)
    (root / "stdout.log").write_text(captured["stdout"], encoding="utf-8")
    (root / "stderr.log").write_text(captured["stderr"], encoding="utf-8")
    return {"ok": captured["returncode"] == 0 and not captured["timedOut"] and not captured.get('memoryExceeded'),
            "exitCode": captured["returncode"], "timedOut": captured["timedOut"],
            "memoryExceeded": captured.get('memoryExceeded', False),
            "peakPrivateBytes": captured.get('peakPrivateBytes'),
            "durationMs": round((time.perf_counter() - started) * 1000), "logs": str(root)}


def passing_areas(results):
    return {row['step'] for row in results if row.get('ok') is True}


def bind_tokenizer_cache(root):
    """Bind installed public tokenizer bytes before isolating runtime homes."""
    import tempfile
    name=hashlib.sha1(b'https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken').hexdigest()
    source=Path(os.environ.get('TIKTOKEN_CACHE_DIR') or Path(tempfile.gettempdir())/'data-gym-cache')/name
    if not source.is_file():return None
    data=source.read_bytes()
    if hashlib.sha256(data).hexdigest() != '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d':
        raise ValueError('Installed tokenizer resource differs from its pinned public bytes')
    target=root/'resources/tiktoken'
    target.mkdir(parents=True,exist_ok=True)
    (target/name).write_bytes(data)
    return target


def baseline_bindings(document):
    """Independently bind the debt payload to its committed Git ancestry."""
    from .contract_ratchet import BASELINE_PATH, payload_sha256
    committed=json.loads(git('show','HEAD:'+BASELINE_PATH))
    if committed != document:
        raise ValueError('The release baseline has uncommitted changes')
    def bind(row, policy_ref=None):
        candidate=row['sourceBinding']['commit']
        if subprocess.run(['git','merge-base','--is-ancestor',candidate,'HEAD'],cwd=REPO,
                          capture_output=True).returncode:
            raise ValueError('Baseline candidate is not an ancestor of this checkout')
        policy_bytes=subprocess.check_output(['git','show',policy_ref+':config/contract_path_policy.json'],cwd=REPO) if policy_ref else (REPO/'config/contract_path_policy.json').read_bytes()
        blob=subprocess.check_output(['git','show',(policy_ref or 'HEAD')+':'+BASELINE_PATH],cwd=REPO)
        return {'path':BASELINE_PATH,'sha256':payload_sha256(row),'commit':candidate,
                'policySha256':hashlib.sha256(policy_bytes.replace(b'\r\n',b'\n')).hexdigest(),
                'tracked':True,'committed':True,'measuredCommitAncestor':True,
                'containingCommit':policy_ref or git('rev-parse','HEAD'),
                'blobSha256':hashlib.sha256(blob).hexdigest()}
    previous=None
    previous_binding=None
    for revision in git('log','--format=%H','HEAD','--',BASELINE_PATH).splitlines():
        old=json.loads(git('show',revision+':'+BASELINE_PATH))
        if old != committed:
            previous=old
            previous_binding=bind(old,revision)
            break
    return bind(committed),previous,previous_binding


def run(since, *, changed=None, root=None, workers=1, timeout=55, build=True, laya_command=None,
        ports=(49087, 49088), allow_unavailable_laya=False, committed_only=False,
        coverage_map=None, measure_all=False, measurement_indices=(), release=False,
        bootstrap_baseline=False, laya_advisory=False):
    from .contract_diff import changed_lines, trace_scope
    from .contract_coverage import classify, uncovered_by_module, uncovered_by_surface
    from .contract_measurements import read_cache, write_cache, fresh, impacted, admission, measured_record, import_index
    started = time.perf_counter()
    if not 1 <= workers <= 2: raise ValueError('At most two heavy runs may execute concurrently')
    deadline = started + timeout
    commit = git("rev-parse", "HEAD")
    base = git("rev-parse", "--verify", since + "^{commit}")
    ports = assigned_ports(ports)
    focused = changed is not None
    if changed is None:
        changed = git_paths("diff", "--name-only", "--no-renames", base, "HEAD") if committed_only else (
            git_paths("diff", "--name-only", "--no-renames", base) + git_paths("ls-files", "--others", "--exclude-standard"))
    changed = sorted(set(changed))
    policy=json.loads((REPO/'config/contract_path_policy.json').read_text(encoding='utf-8'))
    classes={name:classify(name,policy) for name in changed}
    obligations=[name for name,row in classes.items() if row['kind'] in {'behaviour','unknown'}]
    details=changed_lines(REPO,base,committed_only=committed_only,paths=obligations)
    deleted=sorted(name for name in git('diff','--name-only','--diff-filter=D','--no-renames','-z',base,
                                      *(['HEAD'] if committed_only else [])).split('\0') if name in classes)
    active_changed=[name for name in changed if name not in deleted]
    excluded_working_changes = git('status', '--porcelain').splitlines() if committed_only else []
    root = output_root(root or Path('D:/NeyviaRuns/P22/gates') / uuid.uuid4().hex, small=not build)
    root.mkdir(parents=True, exist_ok=True)
    scope_path = root / 'trace-scope.json'
    scope_path.write_text(json.dumps({'schema':'neyvia.python-trace-scope.v1','source':'git:'+base,
                                    'files':trace_scope(REPO, base, details=details)},
                                   separators=(',', ':')), encoding='utf-8')
    plan = select(active_changed)
    historical_contracts = sorted(plan['contracts'])
    baseline_document = None
    if release or bootstrap_baseline:
        if focused or not build or measure_all:
            raise ValueError('A release ratchet requires an unfocused built candidate')
        from .contract_ratchet import BASELINE_PATH
        if release:
            baseline_document = json.loads((REPO/BASELINE_PATH).read_text(encoding='utf-8'))
            if baseline_document['coverageSince'] != base:
                raise ValueError('Release coverage reference differs from the committed baseline')
            outcome_base = baseline_document['sourceBinding']['commit']
        else:
            if (REPO/BASELINE_PATH).exists():
                raise ValueError('A coverage baseline already exists; bootstrap cannot replace published debt')
            outcome_base = commit
        # Historic obligations remain in the debt receipt. The ratchet makes
        # newly edited outcomes mandatory without rerunning four days of legacy
        # declarations on every release. Old stale receipts receive no credit.
        outcome_changes = git_paths('diff','--name-only','--no-renames',outcome_base,
                                    *(['HEAD'] if committed_only else []))
        if not committed_only:
            outcome_changes += git_paths('ls-files','--others','--exclude-standard')
        current_plan = select([name for name in sorted(set(outcome_changes))
                               if (REPO/name).exists()])
        plan.update(contracts=current_plan['contracts'], jobs=current_plan['jobs'],
                    unboundContracts=current_plan['unboundContracts'],
                    outcomeImpactSince=outcome_base,
                    historicalImpactedContracts=historical_contracts)
    contracts,manifests=inventory()
    coverage_map=output_root(coverage_map or 'D:/NeyviaRuns/P22/execution-cache.json',small=True)
    cached=read_cache(coverage_map)['records']
    import_errors=[]
    for index in measurement_indices:
        try:cached.extend(import_index(REPO,index,contracts,manifests))
        except (OSError,ValueError,KeyError,TypeError) as error:
            import_errors.append({'index':str(index),'reason':str(error)})
    impact_changes=outcome_changes if release or bootstrap_baseline else active_changed
    for identity in impacted(cached,impact_changes,contracts) | (set(contracts) if measure_all else set()):
        row=contracts[identity]
        plan['contracts'][identity]=row
        if not row.get('areas'):plan['unboundContracts'].append(identity)
        for area in row.get('areas',[]):plan['jobs'].setdefault(area,[]).append(identity)
    plan['jobs']={area:sorted(set(ids)) for area,ids in plan['jobs'].items()}
    # Generator validation is itself a measured outcome and supplies the
    # actual execution edge for checked generated artifacts.
    if plan['generatedPaths'] and 'generator-outcomes' in manifests:
        identities=[row['id'] for row in manifests['generator-outcomes']['contracts']]
        plan['jobs']['generator-outcomes']=identities
        plan['contracts'].update({identity:contracts[identity] for identity in identities})
    snapshot={}
    valid=[row for row in cached if fresh(row,REPO,contracts,snapshot=snapshot)]
    reusable={identity for row in valid for identity in row['contracts']}
    if release or bootstrap_baseline:
        required = {'p22.pdf-render','p22.panels','p22.chips','p22.visible-copy',
                    'p22.coverage-ratchet.monotonic','p22.static-web-reach',
                    'p22.build-cache.source-and-artifacts','p22.production-build',
                    'p22.path-policy-outcomes','p22.laya-advisory'}
        if 'scripts/package_onboarding_packs.py' in plan['generatedPaths'].values():
            required.add('p22.pack-generator.local-components')
        # All registered declarations need a runner even if their old coverage
        # obligation is debt. Newly impacted stale witnesses must be remeasured.
        from .proof_verifier import ADAPTERS, RUNNERS
        plan['unboundContracts'] = sorted(identity for identity,row in contracts.items()
            if not row.get('areas') or any(area not in ADAPTERS and area not in RUNNERS
                                          and area not in {'fast-ui','build'} for area in row.get('areas',[])))
        plan['staleUncreditedContracts']=sorted({identity for row in cached
            for identity in row.get('contracts',[]) if identity in contracts and identity not in reusable})
        for identity in sorted(required):
            row=contracts[identity]
            plan['contracts'][identity]=row
            for area in row.get('areas',[]):
                plan['jobs'].setdefault(area,[]).append(identity)
        plan['jobs']={area:sorted(set(ids)) for area,ids in plan['jobs'].items()}
        # The release always obtains a fresh mounted observation of today's bugs.
        reusable.difference_update(plan['jobs'].get('fast-ui',[]))
    # Keep only freshness verdicts. Parsed receipts otherwise survive across
    # every worker and are duplicated by final admission's fresh snapshot.
    snapshot.clear()
    # Static release archives have no executable claim. Uncovered paths already
    # fail admission. Bind the covered source and actual witness inputs rather
    # than reading tens of thousands of archived screenshots before checking it.
    bound_paths = (set(active_changed) - set(plan['metadataOnly'])) | {row['source'] for row in plan['contracts'].values()}
    bound_paths.difference_update(name for name,row in classes.items() if row['kind']=='configuration')
    bound_paths.difference_update(plan['generatedPaths'])
    bound_paths.update(plan['generatedPaths'].values())
    bound_paths.update(plan['renamedPaths'].values())
    bound_paths.update(['config/contract_path_policy.json','config/neyvia.modules.json','config/contract_module_outcomes.json'])
    bound_paths.update(path for row in plan['contracts'].values() for site in row.get('checkedAt',[]) for path in sites(site))
    if build:
        bound_paths.update(name for name in _SOURCE_PATHS if name.startswith('web/'))
        bound_paths.update(['vite.config.mjs','package.json','package-lock.json'])
    def bindings():
        from .contract_measurements import _path_hashes
        from .proof_credential_guard import check_access
        for name in bound_paths:
            if (REPO/name).is_file():check_access(REPO/name)
        return {name:_path_hashes(REPO/name)[1] if (REPO/name).is_file() else None for name in sorted(bound_paths)}
    before = bindings()
    cached_build=None
    build_directory=root/'build'
    build_inputs=None
    build_cache_path=Path('D:/NeyviaRuns/P22/build-cache.json')
    if build:
        from .contract_build_cache import load, source_paths
        cached_build=load(REPO,build_cache_path)
        if cached_build:
            build_directory=cached_build['build']
        else:
            build_inputs=source_paths(REPO)
    tasks = []
    blocked_steps = []
    for area, identities in sorted(plan["jobs"].items()):
        if area in {'fast-ui','build'}:
            continue  # The actual mounted journey depends on this build.
        limits=RUNNER_LIMITS.get(area,{})
        unavailable={identity:limits.get(identity,limits.get('*')) for identity in identities
                     if identity in limits or '*' in limits}
        if unavailable:
            blocked_steps.append({'step':area,'ok':False,'status':'not available',
                                  'requestedContracts':sorted(unavailable),'unavailableContracts':unavailable})
            identities=sorted(set(identities)-set(unavailable))
            if not identities:continue
        if set(identities)<=reusable:
            blocked_steps.append({'step':area,'ok':True,'status':'cached passing execution',
                                  'requestedContracts':identities})
            continue
        job_root = root / area
        job_root.mkdir()
        spec = job_root / "job.json"
        state_root=Path('D:/NeyviaRuns/P22/state/gate')/root.name/area
        spec.write_text(json.dumps({"area": area, "contracts": identities,'measure':True,
                                    'stateRoot':str(state_root), 'traceScope':str(scope_path)}), encoding="utf-8")
        tasks.append((area, [sys.executable, str(REPO / "scripts/gate.py"), "--worker", str(spec)], job_root))
    tasks.append(("cl-compile", [sys.executable, str(REPO / "scripts/cl_compile_manuals.py"), "--check"], root / "compile"))
    if build and cached_build is None:
        config = root / "vite.config.mjs"
        config.write_text("import config from " + json.dumps((REPO / "vite.config.mjs").as_posix()) + ";\nexport default env => ({...config(env),build:{...config(env).build,sourcemap:true},cacheDir:" + json.dumps(str(root / "vite-cache")) + "});\n", encoding="utf-8")
        tasks.append(("build", ["node", str(REPO / "node_modules/vite/bin/vite.js"), "build", "--config", str(config), "--configLoader", "runner", "--outDir", str(root / "build")], root / "build-log"))
    port_block='49081-49089' if ports[0]>=49081 else '48871-48889'
    env = dict(os.environ, PYTHONIOENCODING="utf-8", NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
               NEYVIA_BROWSER_PROOF_PORTS=port_block, NEYVIA_GATE_ASSIGNED_PORTS=port_block,
               NEYVIA_GATE_WORKER_PORTS=json.dumps(ports),
               NEYVIA_P22_TRACE_SCOPE=str(scope_path), NEYVIA_P22_TRACE_SINCE=base,
               TEMP=str(root/'temp'), TMP=str(root/'temp'), PYTHONDONTWRITEBYTECODE='1')
    tokenizer_cache=bind_tokenizer_cache(root)
    if tokenizer_cache is not None:env['TIKTOKEN_CACHE_DIR']=str(tokenizer_cache)
    if build:
        env['NEYVIA_PROOF_BUILD_ROOT']=str(build_directory)
    (root/'temp').mkdir(exist_ok=True)
    # A measured parent can need the second heavy slot for a real Python child.
    # Queue worker launches before either parent reserves a slot; two parents
    # must not occupy both permits and then wait for each other's children.
    worker_admission = threading.Lock()
    def bounded(command, folder):
        if '--worker' in command:
            job=json.loads(Path(command[command.index('--worker')+1]).read_text(encoding='utf-8'))
            if manifests.get(job['area'],{}).get('requiresBuild') and build:
                if build_future is not None and not build_future.result()['ok']:
                    return {'ok':False,'status':'not available','reason':'Required production build failed'}
        if '--worker' in command:
            queued=time.perf_counter()
            with worker_admission:
                remaining=deadline-time.perf_counter()
                if remaining<=0:return {'ok':False,'status':'not run','reason':'Gate wall deadline exhausted'}
                wait_ms=round((time.perf_counter()-queued)*1000)
                return {**process(command,folder,remaining,env),'workerQueueMs':wait_ms}
        remaining=deadline-time.perf_counter()
        if remaining<=0:return {'ok':False,'status':'not run','reason':'Gate wall deadline exhausted'}
        return process(command,folder,remaining,env)
    def mounted(build_future):
        if set(plan['jobs']['fast-ui'])<=reusable:
            return {'step':'fast-ui','ok':True,'status':'cached passing execution',
                    'requestedContracts':plan['jobs']['fast-ui']}
        if cached_build or (build_future is not None and build_future.result()['ok']):
            names = {'p22.pdf-render':'pdf', 'p22.panels':'panels', 'p22.chips':'chips', 'p22.visible-copy':'copy', 'image.library.missing-file':'image-missing'}
            folder = root/'render'
            command = [sys.executable, str(REPO/'scripts/p22_render.py'), '--build', str(build_directory), '--root', str(folder),
                       '--ports', *map(str, ports), '--only', *sorted({names[identity] for identity in plan['jobs']['fast-ui']})]
            result = {'step':'fast-ui', **bounded(command, root/'render-log')}
            try:
                rendered=json.loads((folder/'receipt.json').read_text(encoding='utf-8'))
                witnessed={row['contract'] for row in rendered['checks'] if row.get('ok') is True}
                missing=sorted(set(plan['jobs']['fast-ui'])-witnessed)
                from .contract_measurements import outcome_passes
                result.update(ok=result['ok'] and outcome_passes(rendered) and not missing,
                                   missingWitnesses=missing,receipt=str(folder/'receipt.json'))
            except (OSError,ValueError,KeyError,TypeError):
                result.update(ok=False,reason='Fresh render receipt missing or invalid')
        else:
            result = {'step':'fast-ui','ok':False,'status':'not available','reason':'Fresh mounted outcomes require a successful build'}
        return result
    # Build and compile are submitted first, but the pool drains every submitted
    # task before starting the mounted journey below. This deliberately keeps
    # render from waiting for its two heavy slots while traced workers are live.
    tasks.sort(key=lambda item: item[0] not in {'build', 'cl-compile'})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        build_future = None
        futures=[]
        for name,command,folder in tasks:
            future=pool.submit(bounded,command,folder)
            futures.append((name,future))
            if name=='build':build_future=future
        results = [{"step": name, **future.result()} for name, future in futures]
    # A rendered journey needs both slots for its engine and backend. Starting
    # it beside a trace with its own child can deadlock all four participants.
    if 'fast-ui' in plan['jobs']:
        results.append(mounted(build_future))
    results.extend(blocked_steps)
    if cached_build:
        results.append({'step':'build','ok':True,'exitCode':0,'status':'cached source-bound Vite build',
                        'durationMs':0,'receipt':cached_build['receipt'],'build':str(build_directory)})
    new_records=[]
    for result in results:
        area=result['step']
        if area in {'build','cl-compile'} or result.get('status')=='cached passing execution':continue
        if result.get('ok') is not True:continue
        if area=='fast-ui':
            rendered=json.loads((root/'render/receipt.json').read_text(encoding='utf-8'))
            execution=rendered.get('executionCoverage',{})
            passing={row['contract'] for row in rendered['checks'] if row.get('ok') is True}
            group=execution.get('browser',{}).get('measurementGroup',{}).get('id')
            for kind,trace in [('backend',execution.get('backend',{})),
                               ('browser',execution.get('browser',{}).get('sourceMapped',{}))]:
                if trace.get('ok') is not True:continue
                ids=trace.get('contracts',[])
                if not ids or not set(ids)<=passing or not set(plan['jobs'][area])<=set(ids):continue
                if not group or trace.get('measurementGroupId')!=group:continue
                try:
                    execution_path=root/'render'/(kind+'-execution.json')
                    execution_path.write_text(json.dumps(trace,indent=2)+'\n',encoding='utf-8')
                    record=measured_record(REPO,area,ids,trace,contracts,receipt=execution_path,
                                           manifest=manifests.get(area))
                    from .contract_measurements import digest
                    # Render outcomes depend on the complete built candidate,
                    # even when native CDP cannot expose its script execution.
                    record['sourceBindings'].update({name:digest(REPO/name) for name in _SOURCE_PATHS
                                                    if name.startswith('web/') and (REPO/name).is_file()})
                    new_records.append(record)
                except (OSError,ValueError,KeyError,TypeError) as error:
                    result.setdefault('measurementErrors',[]).append(str(error))
            continue
        try:
            execution_path=root/area/'execution.json'
            trace=json.loads(execution_path.read_text(encoding='utf-8'))
            new_records.append(measured_record(REPO,area,trace['contracts'],trace,contracts,
                                               receipt=execution_path,manifest=manifests.get(area)))
        except (OSError,ValueError,KeyError,TypeError) as error:
            result.update(ok=False,coverageError=str(error))
    records=valid+new_records
    measured=admission(REPO,details,records,contracts)
    # Generated views inherit only actual execution of their declared generator.
    generator_details={name:{'status':'changed','lines':[],'lineData':False}
                       for name in plan['generatedPaths'].values()}
    generators=admission(REPO,generator_details,records,contracts)
    passing = {identity for row in results if row.get('ok') is True
               for identity in plan['jobs'].get(row['step'],[])}
    generator_contracts = {'scripts/generate_module_map.py':'p22.module-registry',
                          'scripts/cl_compile_manuals.py':'p22.manual-compiler',
                          'scripts/build_fixcl_manual_cache.py':'p22.manual-cache',
                          'vite.config.mjs':'p22.production-build',
                          'scripts/package_onboarding_packs.py':'p22.pack-generator.local-components'}
    generated_coverage={name:[generator_contracts[generator]]
        for name,generator in plan['generatedPaths'].items()
        if generator_contracts.get(generator) in passing}
    generated_coverage.update({name:generators['coverage'][generator]
        for name,generator in plan['generatedPaths'].items() if generator in generators['coverage']})
    generated_uncovered=sorted(set(plan['generatedPaths'])-set(generated_coverage))
    static_coverage={}
    if (release or bootstrap_baseline) and 'fast-ui' in passing_areas(results):
        from .contract_web_reach import analyze
        entries={'p22.pdf-render':['web/src/neyvia/next/NxPdfApp.jsx'],
                 'p22.panels':['web/src/neyvia/next/NxPlacement.jsx'],
                 'p22.chips':['web/src/neyvia/next/NxComposer.jsx','web/src/neyvia/next/nxShell.css'],
                 'p22.visible-copy':['web/src/neyvia/next/NxComposer.jsx','web/src/neyvia/next/NxSidebar.jsx'],
                 'image.library.missing-file':['web/src/neyvia/ImagePlayground.jsx']}
        journeys={identity:{'status':'PASS','entries':entries[identity],
                           'sourceBindings':{name:before[name] for name in entries[identity]}}
                  for identity in plan['jobs'].get('fast-ui',[]) if identity in passing and identity in entries}
        try:
            reached=analyze(REPO,journeys,aliases={'~':'web/src'})
        except (OSError,ValueError) as error:
            reached={'ok':False,'files':{},'error':str(error)}
            results.append({'step':'static-web-reach','ok':False,'status':'production graph refused',
                            'reason':str(error)})
        (root/'static-web-reach.json').write_text(json.dumps(reached,indent=2)+'\n',encoding='utf-8')
        static_coverage={name:row['journeyIDs'] for name,row in reached['files'].items()
                         if name in classes and classes[name]['kind'] in {'behaviour','unknown'}}
        plan['staticJourneyCoverage']={'classification':'statically reached by passing journey',
                                      'coverage':static_coverage,'receipt':str(root/'static-web-reach.json')}
    plan['coverage']=measured['coverage'] | generated_coverage
    plan['generatedCoverage']=generated_coverage
    # Static reachability affects debt admission only in its explicitly weaker
    # class. It never enters the measured execution map or executed count.
    plan['uncovered']=sorted((set(measured['uncovered'])-set(static_coverage)) | set(generated_uncovered))
    registry=json.loads((REPO/'config/neyvia.modules.json').read_text(encoding='utf-8'))
    owners={name:row['id'] for row in registry['modules'] for name in row['files']}
    plan['uncoveredByModule']=uncovered_by_module(plan['uncovered'],classes,owners)
    plan['uncoveredBySurface']=uncovered_by_surface(plan['uncovered'],classes,owners,registry)
    plan['uncoveredByCategory']=dict(Counter(classes[name]['kind'] for name in plan['uncovered']))
    plan.update(deletedPaths=deleted,configurationPaths=sorted(name for name,row in classes.items() if row['kind']=='configuration'),
                pathPolicyCounts=dict(Counter(classes[name]['kind'] for name in active_changed)) | {'deleted':len(deleted)},
                executionCoverage={'map':str(coverage_map),'newRecords':len(new_records),'reusedRecords':len(valid),
                                   'importErrors':import_errors,
                                   'unexecutedChangedLines':measured['unexecutedChangedLines'],
                                   'noExecutableChanges':measured['noExecutableChanges']})
    for result in results:
        if result['step']=='build':
            result['requestedContracts']=plan['jobs'].get('build',[])
            result['witnessedContracts']=plan['jobs'].get('build',[]) if result.get('ok') else []
    if 'build' in plan['jobs'] and not build:
        results.append({'step':'build','ok':False,'status':'not run','reason':'Selected generator outcome requires a build',
                        'requestedContracts':plan['jobs']['build']})
    surfaces = sorted({name for name in (outcome_changes if release or bootstrap_baseline else changed)
                       if name.startswith("web/") and (REPO/name).is_file()})
    laya = {"status": "not available", "ok": False, "surfaces": surfaces}
    if not surfaces:
        laya = {"status": "not applicable", "ok": True, "surfaces": []}
    else:
        installed_laya = REPO/'scripts/laya_glance_gate.py'
        if laya_command is None and installed_laya.is_file():
            laya_command = [sys.executable, str(installed_laya), '--budget', str(max(1,deadline-time.perf_counter()))]
    if surfaces and laya_command:
        request = root / "laya-request.json"
        request.write_text(json.dumps({"commit": commit, "sourceBindings":before,"changedSurfaces": surfaces, "renderReceipt":str(root/'render/receipt.json'),
                                       "build":str(build_directory),"assignedPorts":list(ports),
                                       "observerPorts":[48875,48876] if min(ports)<49000 else [49085,49086],
                                       "variants": ["dark-desktop", "light-desktop", "dark-phone", "light-phone"]}), encoding="utf-8")
        laya = {"status": "completed", **bounded([*laya_command, str(request)], root / "laya")}
        try:
            verdict = json.loads((root/'laya/stdout.log').read_text(encoding='utf-8'))
            expected = {(surface,variant) for surface in surfaces for variant in ['dark-desktop','light-desktop','dark-phone','light-phone']}
            admitted = {(row['surface'],row['variant']) for row in verdict['observations'] if row.get('verdict')=='looks fine' and row.get('admitted') is True and row.get('screenshotSha256') and row.get('reason')}
            laya['ok'] = laya['ok'] and verdict.get('commit') == commit and admitted == expected
            laya['verdict'] = verdict
        except (OSError,ValueError,KeyError,TypeError):
            laya.update(ok=False,status='invalid response')
    after=bindings()
    changed_sources=sorted(name for name in set(before)|set(after) if before.get(name)!=after.get(name))
    commit_stable=commit == git('rev-parse','HEAD')
    stable = before == after and commit_stable
    if stable:write_cache(coverage_map,records)
    ratchet=None
    coverage_ok=not plan['uncovered']
    if bootstrap_baseline:
        from .contract_ratchet import BASELINE_PATH, SCHEMA, payload_sha256
        pending={'schema':SCHEMA,'coverageSince':base,'paths':plan['uncovered']}
        from .contract_measurements import digest
        pending['sourceBinding']={'path':BASELINE_PATH,'sha256':payload_sha256(pending),
                                  'commit':commit,'policySha256':digest(REPO/'config/contract_path_policy.json')}
        (root/'baseline-proposal.json').write_text(json.dumps(pending,indent=2)+'\n',encoding='utf-8')
        ratchet={'status':'bootstrap proposal','ok':False,'baselineProposal':str(root/'baseline-proposal.json')}
    elif release:
        from .contract_ratchet import evaluate
        binding,previous,previous_binding=baseline_bindings(baseline_document)
        ratchet=evaluate(baseline_document,plan['uncovered'],source_binding=binding,
                         previous_baseline=previous,previous_source_binding=previous_binding,
                         bootstrap_authorized=previous is None,
                         failed_contracts=[identity for row in results if row.get('ok') is not True
                                           for identity in plan['jobs'].get(row['step'],[row['step']])],
                         missing_runners=plan['unboundContracts'],
                         execution_counts={'coveredFiles':len(measured['coverage'])},
                         static_web_counts={'coveredFiles':len(static_coverage)})
        coverage_ok=ratchet['ok']
    contracts_ok = stable and coverage_ok and not plan["unboundContracts"] and all(row["ok"] for row in results)
    glance_ok = laya_admitted(laya, allow_unavailable_laya, advisory=laya_advisory)
    report = {"schema": "neyvia.fast-contract-gate.v1", "commit": commit, "since": base,
              "scope":"focused" if focused else "committed-diff" if committed_only else "diff",
              "changedFiles": changed, **{key: value for key, value in plan.items() if key not in {"contracts", "manifests"}},
              "excludedWorkingChanges": excluded_working_changes,
              "selectedContracts": sorted(plan["contracts"]), "steps": results, "laya": laya,
              "contractsOk": contracts_ok, "releaseGate": contracts_ok and glance_ok and build and not focused and not bootstrap_baseline,
              'ratchet':ratchet, 'releaseMode':release,
              'baselineProposalReady':bool(bootstrap_baseline and stable and not plan['unboundContracts']
                                          and all(row['ok'] for row in results) and glance_ok),
              "layaPolicy": {"allowUnavailable": allow_unavailable_laya, "pending": laya['status'] == 'not available',
                             "advisory": laya_advisory is True,
                             "boundary": "Findings are retained as advisory and do not block this release" if laya_advisory is True
                             else "An unavailable hook may be explicitly pending; a failed or uncertain hook is never admitted"},
              "assignedPorts": list(ports),
              "sourceStable": stable, "sourceBindings": before,
              "sourceChangedPaths": changed_sources, "commitStable": commit_stable,
              "ok": contracts_ok and glance_ok, "buildIncluded": build,
              'buildDirectory':str(build_directory),
              "durationMs": round((time.perf_counter() - started) * 1000)}
    (root / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if build and cached_build is None and stable:
        build_step=next((row for row in results if row['step']=='build' and row.get('ok')),None)
        if build_step:
            from .contract_build_cache import save
            save(REPO,build_cache_path,build_directory,build_inputs,build_step,root/'receipt.json')
    return report


def worker(spec):
    from .subprocess_utils import install_hidden_subprocess_default
    install_hidden_subprocess_default()
    job = json.loads(spec.read_text(encoding="utf-8"))
    root = Path(job.get('stateRoot', spec.parent / "state")).resolve()
    if not root.is_relative_to(Path('D:/NeyviaRuns/P22').resolve()):
        raise ValueError('Worker stateRoot must stay under D:/NeyviaRuns/P22')
    root.mkdir(parents=True, exist_ok=True)
    # Bind installed code resources before isolating user/runtime homes.
    # Their exact bytes are public tooling data, never account state.
    import tempfile
    import shutil
    original_home=Path.home()
    os.environ.setdefault('NEYVIA_GATE_RESOURCE_HOME',str(original_home))
    import site
    os.environ.setdefault('PYTHONUSERBASE',site.getuserbase())
    token_cache=bind_tokenizer_cache(root)
    rustc=Path(os.environ.get('RUSTUP_HOME') or original_home/'.rustup')/'toolchains/stable-x86_64-pc-windows-msvc/bin/rustc.exe'
    if rustc.is_file():os.environ['NEYVIA_GATE_RUSTC']=str(rustc)
    os.environ["NEYVIA_GATE_CONTRACTS"] = json.dumps(job["contracts"])
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "TEMP", "TMP"):
        target = root / "home" / key.lower()
        target.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(target)
    tempfile.tempdir=str(root/'home/temp')
    for key in list(os.environ):
        if any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH_FILE")):
            os.environ.pop(key)
    if token_cache is not None:os.environ['TIKTOKEN_CACHE_DIR']=str(token_cache)
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT"):
        os.environ.pop(key, None)
    from .proof_ports import configure_ports, configure_asyncio
    declared=os.environ.get('NEYVIA_GATE_ASSIGNED_PORTS','49081-49089')
    first,last=map(int,declared.split('-'))
    admitted=list(range(first,last+1))
    manifest=inventory()[1].get(job['area'], {})
    if 'portRoles' in manifest:
        admitted=list(assigned_ports(job.get('ports') or json.loads(os.environ.get('NEYVIA_GATE_WORKER_PORTS', '[49087,49088]'))))
        configure_ports(admitted, roles=manifest['portRoles'], phases=manifest.get('portPhases'))
        os.environ['NEYVIA_BROWSER_PROOF_PORTS']=','.join(map(str,admitted))
    else:
        configure_ports(admitted[:6])
    if manifest.get('portRoles') or 'portRoles' not in manifest:
        configure_asyncio(admitted[:6],pairs=manifest.get('asyncioLoops',1))
    os.environ['NEYVIA_SYSTEM_PYTHON']=sys.executable
    os.environ['NEYVIA_LAYA_AUTOSTART']='0'
    from .proof_credential_guard import install
    install(root)
    # The guard admits this exact synthetic proof subtree, not its parent or
    # any real account store. Every adapter fixture must live beneath it.
    proof_root=root/'.agent_control/proofs'
    proof_root.mkdir(parents=True,exist_ok=True)
    def audit(event, args):
        if event == 'subprocess.Popen':
            executable=str(args[0]).lower()
            if Path(executable).name in {'chrome.exe','chromium.exe','chrome','chromium','msedge.exe'}:
                raise PermissionError('P22 journeys require the admitted headless Obscura engine')
        if event in {"socket.bind", "socket.connect"}:
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"} or address[1] not in admitted:
                raise PermissionError("P22 proof may only use assigned loopback ports the explicitly assigned block")
    sys.addaudithook(audit)
    from .proof_verifier import _run_area
    # Historical adapters declare six distinct fixture roles. They share the
    # assigned block only while executing; pure adapters retain parallelism.
    from .proof_verifier import ADAPTERS, RUNNERS
    if job['area'] not in RUNNERS and job['area'] not in ADAPTERS:
        report={'ok':False,'contracts':[],'cases':[], 'error':'No registered runner for area: '+job['area'], 'missingWitnesses':job['contracts']}
        (spec.parent/'outcomes.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'area':job['area'],'ok':False,'error':report['error']}))
        return 1
    owner = REPO/RUNNERS[job['area']] if job['area'] in RUNNERS else REPO/'src'/Path(*ADAPTERS[job['area']].split('.')).with_suffix('.py')
    network = bool(re.search(r'\b(?:proof_port|proofPort)\(',owner.read_text(encoding='utf-8')))
    if manifest:
        if 'networkContracts' in manifest:network=bool(set(job['contracts']) & set(manifest['networkContracts']))
    trace = None
    if job.get('measure'):
        from .contract_execution import start, start_children
        scope_path = output_root(job.get('traceScope') or os.environ.get('NEYVIA_P22_TRACE_SCOPE'))
        trace_start = start_children if manifest.get('traceMode') == 'children' else start
        trace = trace_start(REPO, spec.parent/'trace', job['contracts'], scope=scope_path)
    try:
        if network:
            from .harness_jobs import _exclusive_job_lock
            with _exclusive_job_lock(REPO/'.agent_control/p22'/('ports-'+ '-'.join(map(str,admitted))),timeout_seconds=240):
                report=_run_area(job['area'],proof_root)
        else:
            report=_run_area(job['area'],proof_root)
    except Exception as error:
        # Preserve a failed observation and its trace rather than losing both
        # receipts when an adapter raises. Such execution never earns coverage.
        report={'ok':False,'contracts':[],'cases':[],
                'error':f'{type(error).__name__}: {error}'}
    finally:
        execution = trace.stop() if trace is not None else None
    from .contract_measurements import outcome_passes
    if not outcome_passes(report):
        report.update(ok=False)
    witnessed = {identity for case in report.get('cases',[]) if case.get('ok') is True
                 for identity in case.get('contracts',[case.get('id')]) if identity}
    witnessed.update(row if isinstance(row,str) else row.get('id') for row in report.get('contracts',[])
                     if isinstance(row,str) or row.get('status') == 'passed')
    witnessed.update(row.get('id') for row in report.get('outcomes',[])
                     if isinstance(row,dict) and row.get('status') == 'PASS')
    missing = sorted(set(job['contracts']) - witnessed)
    if missing:
        report.update(ok=False, missingWitnesses=missing)
    if execution is not None:
        execution['ok'] = execution.get('ok') is True and report.get('ok') is True and not missing
        execution['contracts'] = sorted(set(job['contracts']) & witnessed) if execution['ok'] else []
        (spec.parent/'execution.json').write_text(json.dumps(execution,indent=2)+'\n',encoding='utf-8')
    (spec.parent / "outcomes.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"area": job["area"], "ok": report.get("ok"), "requestedContracts": job["contracts"]}))
    return int(not report.get("ok"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--paths", nargs="+", help="Explicit impact paths for a focused CL procedure")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--workers", type=int, default=1,
                        help='Default reserves the second heavy slot for an owned worker child')
    parser.add_argument("--timeout", type=float, default=240, help="Total wall deadline in seconds; use 55 for a commit check, release diffs default to 240")
    parser.add_argument("--skip-build", action="store_true", help="Startup/focused contract checks only; never release admission")
    parser.add_argument("--laya-command", nargs="+", help="Pluggable LAYA process, given a JSON request file as its last argument")
    parser.add_argument('--ports', nargs=2, type=int, default=[49087, 49088], help='Two owned ports in the explicitly assigned gate block')
    parser.add_argument('--allow-unavailable-laya', action='store_true', help='Explicit release policy: report an unavailable glance as pending; failed or uncertain responses still fail')
    parser.add_argument('--laya-advisory', action='store_true', help='Explicit release policy: retain all glance findings as advisory without blocking release')
    parser.add_argument('--committed-only', action='store_true', help='Check the committed candidate diff; preserve unrelated local working state')
    parser.add_argument('--coverage-map',type=Path,help='Source-bound passing execution cache; defaults to the owned P22 evidence root')
    parser.add_argument('--measure-all',action='store_true',help='Bootstrap execution measurement of all authored outcomes once; never runs pytest')
    parser.add_argument('--import-measurements',nargs='+',type=Path,default=[],help='Admit source-bound PASS receipts from bounded measurement batches')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--release',action='store_true',help='Admit only non-growing debt against the committed coverage baseline')
    mode.add_argument('--bootstrap-baseline',action='store_true',help='Write a debt proposal after real outcomes; proposal cannot admit a release')
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    if args.release and not args.since:
        from .contract_ratchet import BASELINE_PATH
        args.since=json.loads((REPO/BASELINE_PATH).read_text(encoding='utf-8'))['coverageSince']
    if not args.since or args.workers < 1 or args.timeout <= 0:
        parser.error("--since, positive workers and a positive deadline are required")
    report = run(args.since, changed=args.paths, root=args.root, workers=args.workers, timeout=args.timeout, build=not args.skip_build,
                 laya_command=args.laya_command, ports=args.ports, allow_unavailable_laya=args.allow_unavailable_laya,
                 committed_only=args.committed_only,coverage_map=args.coverage_map,measure_all=args.measure_all,
                 measurement_indices=args.import_measurements,release=args.release,
                 bootstrap_baseline=args.bootstrap_baseline, laya_advisory=args.laya_advisory)
    print(json.dumps(report, indent=2))
    return int(not report["ok"])
