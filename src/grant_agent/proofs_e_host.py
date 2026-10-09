"""Production invariants for owned OS probes and portable host observations."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


def require(condition, identity, detail):
    if not condition:
        from .proof_contracts import ContractViolation
        raise ContractViolation(f"{identity}: {detail}")


def check_writer_home(home, rollout):
    expected = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    if rollout:
        expected = next((p.parent for p in Path(str(rollout)).parents
                         if p.name in {"sessions", "archived_sessions"}), expected)
    require(home == expected, "proofs-e-host.writer", "writer home does not follow its rollout")


def writer_result(value, evidence, error=None):
    expected = {"legacy": None, "invalid-id": None, "missing": False,
                "locked": True, "released": False}.get(evidence)
    if evidence == "os-error":
        expected = True if error in {32, 33} else None
    require(value is expected, "proofs-e-host.writer", "OS ownership evidence contradicts the writer result")
    return value


def check_limits(rows, payload, previous, root):
    from .connected_sessions.plan_limits import _percent, _iso
    allowed = {"app", "window", "label", "usedPercent", "status", "resetsAt", "at", "source"}
    require(all(set(r) <= allowed and r.get("app") == "claude-code" for r in rows),
            "proofs-e-host.limits", "status-line input leaked into public limit rows")
    observed = {r["window"]: r for r in rows}
    limits = payload.get("rate_limits", {}) if isinstance(payload, dict) else {}
    for kind in ("five_hour", "seven_day"):
        value = limits.get(kind) if isinstance(limits, dict) else None
        percent = _percent(value.get("used_percentage"), fraction=False) if isinstance(value, dict) else None
        if percent is not None:
            row = observed.get(kind, {})
            require(row.get("usedPercent") == percent and row.get("resetsAt") == _iso(value.get("resets_at"))
                    and row.get("source") == "claude-statusline" and row.get("at"),
                    "proofs-e-host.limits", "accepted window is missing or changed")
        elif kind in previous:
            require(observed.get(kind) == previous[kind], "proofs-e-host.limits", "missing data erased last-known usage")
    stored = Path(root) / ".neyvia/plan-limits.json"
    if stored.is_file():
        require(json.loads(stored.read_text(encoding="utf-8")) == observed,
                "proofs-e-host.limits", "limit receipt differs from its durable windows")


def check_import_closure(repo, inputs, output):
    require(output == sorted(set(output)) and set(inputs) <= set(output) and "src/grant_agent/__init__.py" in output,
            "proofs-e-host.pack-closure", "portable closure is not unique, sorted or complete")
    for name in output:
        require("\\" not in name, "proofs-e-host.pack-closure", "archive path is platform-specific")
        if name.startswith("src/grant_agent/") and name.endswith(".py"):
            path = Path(repo) / name
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ImportFrom) and node.level and node.module:
                    relative = Path(name).parent.joinpath(node.module.replace(".", "/")).as_posix() + ".py"
                    require(not (Path(repo) / relative).is_file() or relative in output,
                            "proofs-e-host.pack-closure", "local imported module omitted")


def check_safe_receipt(value):
    allowed = {"ok", "status", "actionId", "duplicateSuppressed", "url", "finalUrl", "pageUrl", "origin",
               "hash", "sha256", "semanticHash", "revision", "observation", "actionReceiptPath", "operationStatus",
               "operationReceiptPath", "recoveryRef", "receipt_id", "receipt_path", "duration_ms",
               "toolResult", "failure", "filesChanged", "verification"}
    require(isinstance(value, dict) and set(value) <= allowed, "proofs-e-host.action-sanitization", "raw callback fields escaped receipt projection")
    import re
    def safe(item):
        if isinstance(item, dict):
            return all(not re.search(r"password|secret|credential|authorization|cookie|api.?key|access.?token|refresh.?token", str(k), re.I)
                       and safe(v) for k, v in item.items())
        return all(safe(v) for v in item) if isinstance(item, list) else True
    require(all(safe(value[k]) for k in {"toolResult", "failure", "filesChanged", "verification"} & value.keys()),
            "proofs-e-host.action-sanitization", "nested credential-bearing key escaped receipt projection")
    return value


def check_action_completion(path, record, result, duplicate):
    saved = json.loads(path.read_text(encoding="utf-8"))
    body = json.loads(path.with_suffix(".result").read_text(encoding="utf-8"))
    from .action_receipts import _digest
    require(saved == record and saved["resultHash"] == _digest(body) and saved["actionId"] == result["actionId"]
            and result["duplicateSuppressed"] is duplicate,
            "proofs-e-host.action-once", "action outcome is not bound to its durable request/result")


def check_startup_readiness(report, result):
    require(result.get('state') != 'passed' or (report.get('contractsOk') is True and report.get('complete') is True),
            'proofs.background-readiness', 'Passing partial contracts escaped as complete startup readiness')


def self_check(scratch):
    from .proof_contracts import REPO, ContractViolation
    scratch = Path(scratch); scratch.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((REPO / "config/proofs/proofs-e-host.json").read_text(encoding="utf-8"))
    started = time.perf_counter(); procedures = []; failures = []; observed = set()
    def negative(call):
        try: call()
        except ContractViolation: return
        raise RuntimeError("Contradictory host evidence escaped its production contract")
    def procedure(identity, ids, call):
        try:
            call(); procedures.append({"id": identity, "status": "passed"}); observed.update(ids)
        except Exception as exc:
            row = {"id": identity, "status": "failed", "error": str(exc)}; procedures.append(row); failures.append(row)

    def startup_readiness():
        check_startup_readiness({'contractsOk':True, 'complete':True}, {'state':'passed'})
        check_startup_readiness({'contractsOk':True, 'complete':False}, {'state':'failed'})
        negative(lambda: check_startup_readiness({'contractsOk':True, 'complete':False}, {'state':'passed'}))
        negative(lambda: check_startup_readiness({'contractsOk':False, 'complete':True}, {'state':'passed'}))
    procedure('startup-completeness', [], startup_readiness)

    def schema_literal_order():
        import re
        from .cl.manuals import cl_to_manual
        from .cl.schema import SchemaCompileError
        source = (REPO / 'manuals/cl/proofs.cl').read_text(encoding='utf-8')
        original = cl_to_manual(source)
        matches = re.finditer(r'json:("(?:[^"\\]|\\.)*")', source)
        match, schema = next((m, json.loads(json.loads(m.group(1)))) for m in matches
                             if 'default' in json.loads(json.loads(m.group(1))))
        def replace(value):
            return source[:match.start()] + 'json:' + json.dumps(json.dumps(value,separators=(',',':'))) + source[match.end():]
        reordered = dict(reversed(list(schema.items())))
        require(cl_to_manual(replace(reordered)) == original, 'host.schema-key-order',
                'Reordered schema keys changed the compiled manual')
        altered = dict(reordered, default=not schema['default'])
        try:
            cl_to_manual(replace(altered))
        except SchemaCompileError:
            pass
        else:
            raise ValueError('A changed schema default bypassed visible-record agreement')
    procedure('schema-key-order-and-default-refusal', [], schema_literal_order)

    def quoted_process_authority():
        from .proof_credential_guard import check_process
        from .subprocess_utils import split_process_command, hidden_windows_subprocess_kwargs
        arguments = [sys.executable, '-c', 'print("A quoted Windows argument")']
        encoded = subprocess.list2cmdline(arguments) if os.name == 'nt' else __import__('shlex').join(arguments)
        require(split_process_command(encoded) == arguments, 'proofs.process-argv', 'Quoted process argv changed during decoding')
        check_process(encoded)
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=20, **hidden_windows_subprocess_kwargs())
        require(result.returncode == 0 and result.stdout.strip() == 'A quoted Windows argument',
                'proofs.process-argv', 'The guarded hidden child did not receive its exact quoted program')
        forbidden = [str(REPO / 'config/proofs-a/forbidden-launch/codex.exe'), 'say "quoted"']
        encoded = subprocess.list2cmdline(forbidden) if os.name == 'nt' else __import__('shlex').join(forbidden)
        try: check_process(encoded)
        except PermissionError: pass
        else: raise RuntimeError('Quoted unscoped provider argv escaped authority')
    procedure('quoted-process-authority', [], quoted_process_authority)

    def scoped_denial():
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        scope = scratch / 'guard-workspace'; scope.mkdir()
        refused = scratch / 'refused-output.txt'
        refused_log = scratch / 'refused-log.jsonl'
        program = ('import pathlib,int3_pytest_guard; int3_pytest_guard.install();\n'
                   'try: pathlib.Path(' + repr(str(refused)) + ').write_text("refused")\n'
                   'except PermissionError: print("REFUSED")\n'
                   'else: raise RuntimeError("escaped fence")')
        env = {**os.environ, 'PYTHONPATH':os.pathsep.join((str(REPO / 'scripts'), os.environ.get('PYTHONPATH',''))),
               'INT3_WORKSPACE_ROOT':str(scope), 'INT3_GUARD_LOG':str(refused_log)}
        result = subprocess.run([sys.executable,'-B','-c',program],env=env,capture_output=True,text=True,
                                timeout=20, **hidden_windows_subprocess_kwargs())
        require(result.returncode == 0 and result.stdout.strip() == 'REFUSED' and not refused.exists() and not refused_log.exists(),
                'proofs.guard-diagnostic', 'Refusal logging deadlocked or escaped its write fence')
    procedure('scoped-denial-diagnostic', [], scoped_denial)

    def fixture_authority():
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        scope = scratch / 'fresh-fixture-guard'; scope.mkdir()
        program = '''import json,pathlib,int3_pytest_guard
int3_pytest_guard.install()
scope=pathlib.Path(__import__('os').environ['INT3_WORKSPACE_ROOT'])
fixture=scope/'.agent_control/int3/pytest-temp/owned/.codex/auth.json'
fixture.parent.mkdir(parents=True)
fixture.write_text('{"synthetic":true}')
assert json.loads(fixture.read_text())=={'synthetic':True}
refused=[]
for target in (scope/'auth.json',fixture.parent/'NAS_ACCESS_RUNBOOK.md'):
    try: target.write_text('must not be created')
    except PermissionError: refused.append(target.name)
    else: raise RuntimeError('Fixture authority escaped its exact tree or protected name')
    assert not target.exists()
print(json.dumps({'fixtureReadBack':True,'refused':refused}))
'''
        env = {**os.environ, 'PYTHONPATH':os.pathsep.join((str(REPO/'scripts'),os.environ.get('PYTHONPATH',''))),
               'INT3_WORKSPACE_ROOT':str(scope),'INT3_GUARD_LOG':str(scope/'guard.jsonl')}
        result = subprocess.run([sys.executable,'-B','-c',program],env=env,capture_output=True,text=True,timeout=20,
                                **hidden_windows_subprocess_kwargs())
        facts = json.loads(result.stdout) if result.returncode == 0 else {}
        require(facts == {'fixtureReadBack':True,'refused':['auth.json','NAS_ACCESS_RUNBOOK.md']},
                'proofs.fixture-authority','Fresh synthetic fixture round trip or saved-file refusal failed: '+result.stderr[-400:])
    procedure('fresh-fixture-authority', [], fixture_authority)

    def writer():
        home = scratch / "writer-home"; home.mkdir()
        program = '''import os,sys,json,subprocess
from pathlib import Path
from grant_agent.connected_sessions.codex_writer import active_writer
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
h=Path(sys.argv[1]); legacy=active_writer('owned',None); d=h/'thread-writer-locks'; d.mkdir(); missing=active_writer('owned',None)
p=d/'owned.lock'; p.write_bytes(b'0')
holder=subprocess.Popen([sys.executable,'-u','-c',sys.argv[2],str(p)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,**hidden_windows_subprocess_kwargs())
try:
 if holder.stdout.readline().strip()!='owned': raise RuntimeError('owned writer failed')
 os.utime(p,(1,1)); locked=active_writer('owned',None); invalid=active_writer('../owned',None)
 os.environ['CODEX_HOME']=str(h/'unrelated'); redirected=active_writer('owned',h/'sessions'/'day'/'rollout.jsonl')
 holder.stdin.write('release\\n'); holder.stdin.flush(); holder.wait(timeout=10)
 released=active_writer('owned',h/'sessions'/'rollout.jsonl')
 print(json.dumps([legacy,missing,locked,invalid,redirected,released]))
finally:
 if holder.poll() is None: holder.terminate(); holder.wait(timeout=10)
'''
        holder_program = """import os,sys
f=open(sys.argv[1],'r+b')
if os.name=='nt':
 import msvcrt
 msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
else:
 import fcntl
 fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
print('owned',flush=True)
sys.stdin.readline()
f.close()
"""
        env = {**os.environ, "CODEX_HOME": str(home), "PYTHONPATH": str(REPO / "src")}
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        child = subprocess.run([sys.executable, "-c", program, str(home), holder_program], env=env, capture_output=True, text=True, timeout=30,
                               **hidden_windows_subprocess_kwargs())
        require(child.returncode == 0 and json.loads(child.stdout) == [None, False, True, None, True, False],
                "proofs-e-host.writer", "real cross-process old/released writer ownership is incorrect")
        negative(lambda: writer_result(False, "locked"))
    procedure("host.real-cross-process-writer", ["proofs-e-host.writer"], writer)

    def limits():
        from .connected_sessions.plan_limits import record_claude_statusline, claude_limits
        root = scratch / "limits"; root.mkdir()
        payload = {"rate_limits": {"five_hour": {"used_percentage": 37}, "seven_day": {"used_percentage": 62}}, "credential": "fixture-excluded-marker"}
        first = record_claude_statusline(payload, root)
        require({r["window"]: r["usedPercent"] for r in first} == {"five_hour": 37.0, "seven_day": 62.0}, "proofs-e-host.limits", "collector omitted reported windows")
        require(record_claude_statusline({}, root) == first, "proofs-e-host.limits", "empty observation erased timestamped readings")
        source = "import sys; from pathlib import Path; from grant_agent.connected_sessions.plan_limits import record_claude_statusline; record_claude_statusline({'rate_limits':{'five_hour':{'used_percentage':48}}},Path(sys.argv[1]))"
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        child = subprocess.run([sys.executable, "-c", source, str(root)], env={**os.environ, "PYTHONPATH": str(REPO / "src")}, capture_output=True, text=True, timeout=30,
                               **hidden_windows_subprocess_kwargs())
        require(child.returncode == 0 and next(r for r in claude_limits(root) if r["window"] == "five_hour")["usedPercent"] == 48,
                "proofs-e-host.limits", "live cache did not refresh a second process observation")
        negative(lambda: check_limits([{**first[0], "credential": "excluded"}], {}, {}, root))
    procedure("host.statusline-durable-refresh", ["proofs-e-host.limits"], limits)

    def pack():
        repo = scratch / "pack"; folder = repo / "src/grant_agent"; folder.mkdir(parents=True)
        for name, text in {"__init__.py": "", "parent.py": "from .child import value\n", "child.py": "from .leaf import value\n", "leaf.py": "value=9\n"}.items(): (folder / name).write_text(text, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("proofs_owned_pack", REPO / "scripts/package_onboarding_packs.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        result = module.import_closure(["src/grant_agent/parent.py", "src/grant_agent/child.py"], root=repo)
        require(result == ["src/grant_agent/__init__.py", "src/grant_agent/child.py", "src/grant_agent/leaf.py", "src/grant_agent/parent.py"],
                "proofs-e-host.pack-closure", "transitive portable module closure changed")
        negative(lambda: check_import_closure(repo, ["src/grant_agent/parent.py"], ["src/grant_agent/__init__.py", "src/grant_agent/parent.py"]))
    procedure("host.portable-transitive-pack", ["proofs-e-host.pack-closure"], pack)

    def actions():
        from .action_receipts import NativeActionStore
        root = scratch / "actions"; root.mkdir(); target = root / "outcome.txt"
        def mutate():
            target.write_text("actual authorized scratch effect", encoding="utf-8")
            return {"ok": True, "status": "success", "hash": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "observation": "scratch file written", "result": {"secret": "excluded-marker"}, "nested": ["excluded-marker"]}
        store = NativeActionStore(root, "owned-host-proof")
        first = store.execute("write-once", "scratch.write", {"path": "outcome.txt"}, mutate)
        prior = target.stat().st_mtime_ns
        second = NativeActionStore(root, "owned-host-proof").execute("write-once", "scratch.write", {"path": "outcome.txt"}, mutate)
        require(first["duplicateSuppressed"] is False and second["duplicateSuppressed"] is True and target.stat().st_mtime_ns == prior,
                "proofs-e-host.action-once", "recreated action store repeated the actual write")
        require("excluded-marker" not in json.dumps([first, second]) and all("excluded-marker" not in p.read_text(encoding="utf-8") for p in store.base.glob("*.result")),
                "proofs-e-host.action-sanitization", "callback data leaked into durable/replayed output")
        negative(lambda: check_safe_receipt({"ok": True, "raw": "not-metadata"}))
        negative(lambda: check_action_completion(store._path("write-once"), store.inspect("write-once"), {**second, "duplicateSuppressed": False}, True))
    procedure("host.durable-file-action-replay", ["proofs-e-host.action-once", "proofs-e-host.action-sanitization"], actions)
    return {"area": manifest["area"], "ok": not failures, "status": "failed" if failures else "passed", "contracts": [{"id": i, "status": "passed" if i in observed else "failed"} for i in [c["id"] for c in manifest["contracts"]]],
            "procedures": procedures, "failures": failures, "coverage": manifest["coverage"], "elapsedMs": round((time.perf_counter()-started)*1000,2),
            "boundary": "Owned OS lock holder, status-line processes, transitive local pack and durable scratch file action. No provider launches, credential files or external requests."}
