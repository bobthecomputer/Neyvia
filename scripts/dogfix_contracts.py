"""Executable DOGFIX manual procedures; confined fixtures, no provider substitution."""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def bug1(root):
    from grant_agent.connected_sessions import folders
    target = root / "existing folder"
    target.mkdir(parents=True, exist_ok=True)
    assert folders.candidates(query=str(target))["direct"]["path"] == str(target)
    assert folders.candidates(query=str(target / "missing"))["direct"] is None
    file = root / "file.txt"
    file.write_text("not a folder")
    assert folders.candidates(query=str(file))["direct"] is None


def bug2(root):
    from grant_agent.connected_sessions import folders
    projects = root / "projects"
    projects.mkdir(exist_ok=True)
    before = {row["path"] for row in folders.candidates()["local"]}
    import uuid
    created = projects / ("new-" + uuid.uuid4().hex)
    created.mkdir()
    assert str(created) not in before
    assert str(created) in {row["path"] for row in folders.candidates()["local"]}


def bug3(root):
    import subprocess
    subprocess.run(["node", "scripts/dogfix_browser.mjs", "3"], cwd=REPO, check=True)


def bug4(root):
    import time
    import uuid
    from grant_agent.connected_sessions.broker import ConnectedBroker
    from grant_agent.connected_sessions.codex import CodexAdapter
    from grant_agent.connected_sessions.runs import ACTIVE_STATES
    adapter = CodexAdapter(state_root=root)
    broker = ConnectedBroker(root / "steering", adapters={"codex": adapter}, autostart=False)
    run = None
    try:
        run = broker.new(app="codex", cwd=str(root), message=(
            "This is a bounded UI verification. Do not edit any files or launch agents. "
            "Run one PowerShell command Start-Sleep -Seconds 12, then reply ORIGINAL-DOGFIX."),
            request_id="dogfix-" + uuid.uuid4().hex, options={"permission_mode": "full-access"})
        assert run["canSteer"], run
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            own = adapter._runs.get(run["runId"])
            if own and own.turn_ready.is_set():
                break
            time.sleep(.1)
        steered = broker.steer(run["runId"], "Change the final reply to STEERED-DOGFIX. No more tools or file edits.")
        assert steered["canSteer"]
        while time.monotonic() < deadline and broker.get_run(run["runId"])["state"] in ACTIVE_STATES:
            time.sleep(.2)
        final = broker.get_run(run["runId"])
        assert final["state"] == "completed", final
        page = broker.read(run["sessionId"])
        assert any("STEERED-DOGFIX" in str(item.get("data", {}).get("text", "")) for item in page["items"] if item["kind"] == "assistant"), page
        (root / "steered-session.json").write_text(json.dumps({"id": run["sessionId"], "runId": run["runId"], "cwd": str(root)}))
    finally:
        if run and broker.get_run(run["runId"])["state"] in ACTIVE_STATES:
            broker.stop(run["runId"])
        broker.close()
        adapter.close()
    import subprocess
    subprocess.run(["node", "scripts/dogfix_browser.mjs", "4"], cwd=REPO, check=True)


def bug5(root):
    import subprocess
    source = """import assert from 'node:assert/strict';
import {stripAnsi,toolDetails} from './web/src/neyvia/next/nxTransparencyModel.js';
const raw='\\x1b[33m50\\x1b[39m\\n\\x1b]8;;https://example.com\\x07link\\x1b]8;;\\x07';
assert.equal(stripAnsi(raw),'50\\nlink');
assert.equal(stripAnsi('\\u009b32mgreen\\u009b0m'),'green');
assert.equal(stripAnsi('line\\t50%\\n✓'),'line\\t50%\\n✓');
assert.equal(toolDetails({output:raw})[0].text,raw);
"""
    subprocess.run(["node", "--input-type=module", "-e", source], cwd=REPO, check=True)


def bug6(root):
    from grant_agent.connected_sessions.codex import CodexAdapter
    session = json.loads((root / "steered-session.json").read_text())
    adapter = CodexAdapter(state_root=root)
    try:
        rows = adapter.list_sessions(limit=200)
        found = next(row for row in rows if row.id == session["id"])
        assert found.cwd == session["cwd"] and found.project == root.name, found
        assert not found.archived
    finally:
        adapter.close()
    import subprocess
    subprocess.run(["node", "scripts/dogfix_browser.mjs", "6"], cwd=REPO, check=True)


def bug7(root):
    import subprocess
    subprocess.run(["node", "--input-type=module", "-e", """
import assert from 'node:assert/strict';
import {insertItem,nextMessageSequence} from './web/src/neyvia/next/nxStore.js';
const history=[{id:'old',seq:8192,kind:'assistant'}];
const prompt={id:'pending',seq:nextMessageSequence(history),kind:'user',optimistic:true,data:{text:'follow-up'}};
let rows=insertItem(history,prompt);
rows=insertItem(rows,{id:'effect',seq:16388,kind:'tool'});
assert.deepEqual(rows.map(i=>i.id),['old','pending','effect']);
rows=insertItem(rows,{id:'native',seq:16384,kind:'user',data:{text:'follow-up'}});
assert.deepEqual(rows.map(i=>i.id),['old','native','effect']);
"""], cwd=REPO, check=True)
    subprocess.run(["node", "scripts/dogfix_browser.mjs", "7"], cwd=REPO, check=True)


def bug8(root):
    import subprocess
    subprocess.run(["node", "scripts/dogfix_browser.mjs", "8"], cwd=REPO, check=True)


def bug10(root):
    import subprocess
    import time
    import uuid
    from grant_agent.connected_sessions import folders, folder_jobs
    repo = root / ("repo-" + uuid.uuid4().hex[:8])
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "proof.txt").write_text("actual checkout bytes\n")
    subprocess.run(["git", "-C", str(repo), "add", "proof.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=DOGFIX", "-c", "user.email=dogfix@example.invalid", "commit", "-m", "Fixture"], check=True, capture_output=True)
    started = time.monotonic()
    job = folders.create_worktree(str(repo), "checkout", confirm=True, state_root=root)
    assert time.monotonic() - started < 3 and job["status"] in {"queued", "running"}, job
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = folder_jobs.status(root, job["jobId"])
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(.1)
    assert job["status"] == "completed", job
    assert (Path(job["path"]) / "proof.txt").read_text() == "actual checkout bytes\n"
    # A new process/root observer reads the same durable completion.
    raw = subprocess.check_output([sys.executable, "-c", "import sys,json;sys.path.insert(0,'src');from pathlib import Path;from grant_agent.connected_sessions.folder_jobs import status;print(json.dumps(status(Path(sys.argv[1]),sys.argv[2])))", str(root), job["jobId"]], cwd=REPO, text=True)
    assert json.loads(raw)["status"] == "completed"
    failed = folders.create_worktree(str(repo), "main", confirm=True, state_root=root)
    while time.monotonic() < deadline:
        failed = folder_jobs.status(root, failed["jobId"])
        if failed["status"] not in {"queued", "running"}:
            break
        time.sleep(.1)
    assert failed["status"] == "failed" and "already exists" in failed["error"], failed
    assert "Command [" not in failed["error"] and "timed out" not in failed["error"]
    slow_path = root / "slow-checkout.json"
    if slow_path.exists():
        slow = json.loads(slow_path.read_text())
        result = folder_jobs.status(root, slow["jobId"])
        assert result["status"] == "completed" and time.time() - slow["startedAt"] >= 125, result
        assert (Path(result["path"]) / "proof.txt").read_text() == "actual checkout bytes\n"
        slow.update(result=result, elapsedSeconds=time.time() - slow["startedAt"], passed=True)
        slow_path.write_text(json.dumps(slow, indent=2))


def start_slow_checkout(root):
    """A scoped 125-second CLI-start delay; the production worker then runs real Git."""
    import subprocess
    import time
    import uuid
    from grant_agent.durability import atomic_write_json
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    repo = next(p for p in root.glob("repo-*") if (p / ".git").is_dir())
    job_id = uuid.uuid4().hex
    branch = "slow-" + job_id[:8]
    path = root / ".agent_control/folder-jobs" / (job_id + ".json")
    atomic_write_json(path, {"jobId": job_id, "status": "queued", "path": str(repo.parent / (repo.name + "-" + branch)),
        "branch": branch, "repo": str(repo), "createdAt": time.time(), "pid": None, "error": None})
    code = """import sys,time,subprocess
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from grant_agent.connected_sessions.folder_jobs import run_job
original=subprocess.Popen
def delayed(*args,**kwargs):
    if 'worktree' in args[0]: time.sleep(125)
    return original(*args,**kwargs)
subprocess.Popen=delayed
run_job(Path(sys.argv[2]))
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(REPO / "src"), str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs())
    (root / "slow-checkout.json").write_text(json.dumps({"jobId": job_id, "pid": process.pid, "startedAt": time.time()}))
    print(json.dumps({"slowCheckoutStarted": True, "jobId": job_id, "pid": process.pid}))


def bug9(root):
    import subprocess
    from grant_agent.connected_sessions.folder_jobs import checkout_progress
    assert checkout_progress("Updating files: 12% (12/100)\rUpdating files: 54% (54/100)", "running") == (54, "Checking out files")
    assert checkout_progress("Updating files: 100% (100/100)", "running") == (100, "Finishing checkout")
    assert checkout_progress("", "running") == (None, "Checking out files")
    repo = REPO / "dogfix-ui-repo"
    if not (repo / ".git").exists():
        repo.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
        for n in range(5000):
            (repo / f"file-{n:05d}.txt").write_text("Actual worktree checkout fixture\n" * 20)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=DOGFIX", "-c", "user.email=dogfix@example.invalid", "commit", "-m", "Progress fixture"], check=True, capture_output=True)
    (root / "progress-fixture.json").write_text(json.dumps({"path": str(repo), "name": repo.name}))
    subprocess.run(["node", "scripts/dogfix_browser.mjs", "9"], cwd=REPO, check=True)


def diagnose_order(root):
    from grant_agent.connected_sessions.codex import CodexAdapter
    saved = json.loads((root / "steered-session.json").read_text())
    adapter = CodexAdapter(state_root=root)
    try:
        raw = adapter._rpc("thread/turns/list", {"threadId": saved["id"].split(":", 3)[3], "limit": 4, "sortDirection": "desc", "itemsView": "full"})
        diagnostic = [{"id": t["id"], "startedAt": t.get("startedAt"), "items": [{"id": i.get("id"), "type": i.get("type"), "startedAt": i.get("startedAt"), "text": str(i.get("text") or i.get("content") or "")[:160]} for i in t.get("items", [])]} for t in raw.get("data", [])]
        (REPO / "scripts/evidence/DOGFIX-order-diagnostic.json").write_text(json.dumps(diagnostic, indent=2))
        print(json.dumps(diagnostic))
    finally:
        adapter.close()


def run(bug):
    root = REPO / ".agent_control" / "dogfix" / "contracts"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["NEYVIA_PROJECTS_DIR"] = str(root / "projects")
    os.environ["GIT_CEILING_DIRECTORIES"] = str(root)
    globals()[f"bug{bug}"](root)
    path = REPO / "scripts/evidence" / f"DOGFIX-{bug}.json"
    path.write_text(json.dumps({"bug": bug, "passed": True}, indent=2) + "\n", encoding="utf-8")
    return {"bug": bug, "passed": True, "receipt": str(path)}


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]))))
