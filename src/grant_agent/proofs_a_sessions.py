"""Connected-session host contracts and confined scratch observer procedures.

The verifier invokes the procedure in a child interpreter. Availability and CLI
transport fixtures never replace Git, the workspace implementation or broker.
No real provider, account, project catalogue or service is contacted.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import functools
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def require(condition, identity, message):
    if not condition:
        from .proof_contracts import ContractViolation
        raise ContractViolation(f"{identity}: {message}")


def check_remote(raw, result):
    # URL syntax, rather than the production regex, is the independent oracle.
    from urllib.parse import urlsplit
    value = str(raw).strip()
    if "://" not in value and ":" in value and not re.match(r"^[A-Za-z]:[\\/]", value):
        host, _, suffix = value.partition(":")
        value = "ssh://" + host + "/" + suffix
    parsed = urlsplit(value)
    parts = parsed.path.strip("/").split("/")
    eligible = parsed.hostname in {"github.com", "www.github.com"} and len(parts) == 2
    if eligible:
        owner, name = parts
        name = name.removesuffix(".git")
        eligible = bool(owner and name and all(re.fullmatch(r"[\w.-]+", p) for p in (owner, name)))
    expected = {"owner": owner, "name": name, "url": f"https://github.com/{owner}/{name}"} if eligible else None
    require(result == expected, "sessions.workspace.remote", "remote identity or credential stripping differs")


def check_rollup(raw, result):
    rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    outcomes = [str(row.get("conclusion") or row.get("state") or "").upper() for row in rows]
    failure = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
    pending = {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}
    expected = None if not isinstance(raw, list) or not raw else "failing" if any(v in failure for v in outcomes) else "pending" if (
        any(v in pending for v in outcomes) or any(row.get("status") and str(row["status"]).upper() != "COMPLETED" for row in rows)
    ) else "passing"
    require(result == expected, "sessions.workspace.checks", "failure must outrank pending, which outranks passing")


def check_state(state, *, parsed=None, counts=None, root=None, untracked=None):
    from .connected_sessions import workspace as w
    require(isinstance(state, dict) and isinstance(state.get("exists"), bool), "sessions.workspace.state", "missing existence receipt")
    require(len(state["changes"]) <= w.MAX_CHANGES and isinstance(state["changesTruncated"], bool), "sessions.workspace.state", "change observer is unbounded")
    repo = state.get("repo")
    if repo:
        url = repo.get("remoteUrl")
        require(not url or not re.match(r"^\w+://[^/]*@", url), "sessions.workspace.remote", "userinfo leaked into a receipt")
        require(os.path.isabs(repo["root"]), "sessions.workspace.state", "repository root must be absolute")
        require(state["upstream"] is not None or state["ahead"] is None and state["behind"] is None, "sessions.workspace.state", "invented divergence without an upstream")
        for tree in state["worktrees"]:
            require(tree["current"] is (w._norm(tree["path"]) == w._norm(repo["root"])), "sessions.workspace.state", "worktree current flag differs from repository root")
    else:
        require(state["changes"] == [] and state["worktrees"] == [], "sessions.workspace.state", "nonrepository has repository changes")
    if parsed is not None:
        entries, branch = parsed["entries"], parsed["branch"]
        require(state["branch"] == (None if branch["head"] in {None, "(detached)"} else branch["head"])
                and state["detached"] is (branch["head"] == "(detached)")
                and state["upstream"] == branch["upstream"], "sessions.workspace.state", "branch projection differs from Git")
        require(state["changesTruncated"] is (len(entries) > w.MAX_CHANGES)
                and [row["path"] for row in state["changes"]] == [entry["path"].replace("\\", "/") for entry in entries[:w.MAX_CHANGES]],
                "sessions.workspace.state", "change order, count, or truncation differs from Git")
        labels = {"U": "conflicted", "R": "renamed", "C": "copied", "D": "deleted", "A": "added", "T": "typechange", "M": "modified"}
        for entry, row in zip(entries, state["changes"]):
            xy = entry["xy"]
            status = "untracked" if xy == "??" else next((label for key, label in labels.items() if key in xy), "modified")
            require(row["status"] == status and row["staged"] is (xy[0] not in {".", "?"}) and row.get("oldPath") == entry.get("oldPath"), "sessions.workspace.state", "change metadata differs from Git")
            expected = (untracked or {}).get(entry["path"], (None, None)) if xy == "??" else (counts or {}).get(entry["path"], (None, None))
            require((row["additions"], row["deletions"]) == expected, "sessions.workspace.state", "line counts differ from the observed data")


def check_diff(result):
    from .connected_sessions import workspace as w
    require(isinstance(result["patch"], str) and len(result["patch"].encode("utf-8")) <= w.MAX_PATCH_BYTES * 3 + 64,
            "sessions.workspace.diff", "patch exceeds bounded decoded bytes")
    require(not result["truncated"] or result["patch"].endswith("[diff truncated]\n"), "sessions.workspace.diff", "truncation must be visible")
    require(not Path(result["path"]).is_absolute() and ".." not in Path(result["path"]).parts, "sessions.workspace.diff", "diff path leaves the repository")


def check_action(raw, result):
    from .connected_sessions import workspace as w
    expected = "\n".join(part for part in (raw["out"].strip(), raw["err"].strip()) if part)
    if raw["timedOut"]:
        expected += ("\n" if expected else "") + "The command did not finish in time and was stopped."
    if len(expected) > w.MAX_OUTPUT_CHARS:
        expected = expected[:w.MAX_OUTPUT_CHARS] + "\n... [output truncated]"
    require(result == {"ok": raw["code"] == 0, "output": expected}, "sessions.workspace.action", "command outcome must retain real code, output, timeout and cap")


def check_cli_invocation(args, env):
    require(not any(value in {"--show-token", "--with-token"} for value in args), "sessions.workspace.cli", "account credential extraction is outside workspace actions")
    require(env.get("GIT_TERMINAL_PROMPT") == "0" and env.get("GH_PROMPT_DISABLED") == "1"
            and env.get("GCM_INTERACTIVE") == "never", "sessions.workspace.cli", "workspace command may prompt on an invisible desktop")
    if args[1:2] == ["commit"]:
        require(len(args) == 5 and args[2:4] == ["-a", "-m"], "sessions.workspace.action", "commit must update tracked files only and pass its message as one literal argument")
    if args[1:3] == ["pr", "create"]:
        require(len(args) == 7 and args[3] == "--title" and args[5] == "--body", "sessions.workspace.github", "PR title/body must be explicit single arguments")


def check_github_result(raw, pull, error):
    from .connected_sessions import workspace as w
    if raw["code"] == 0:
        try:
            data = json.loads(raw["out"])
            expected = {"number": data.get("number"), "title": data.get("title"), "url": data.get("url"),
                        "state": str(data.get("state") or "").lower() or None, "checks": w._checks_summary(data.get("statusCheckRollup"))}
        except (ValueError, AttributeError):
            require(pull is None and error == "The GitHub CLI returned an unreadable pull request.", "sessions.workspace.github", "malformed CLI result was accepted")
        else:
            require(pull == expected and error is None, "sessions.workspace.github", "PR identity/state/check projection differs from CLI")
    elif raw["timedOut"]:
        require(pull is None and error == "The GitHub CLI did not answer in time.", "sessions.workspace.github", "CLI timeout was hidden")
    elif "no pull requests found" in raw["err"].lower():
        require(pull is None and error is None, "sessions.workspace.github", "absent PR reported as failure")
    else:
        require(pull is None and isinstance(error, str) and bool(error), "sessions.workspace.github", "CLI failure was reported as success")


def _workspace_observers(root, repo, run):
    """Remaining repository observers and finite GitHub CLI wire procedures."""
    if os.environ.get("NEYVIA_PROOF_CREDENTIAL_GUARD") == "1":
        from .proof_credential_guard import install
        install(root)
    from .connected_sessions import workspace as w, folders as f
    from . import github_client as github
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    launched = []
    original_popen = subprocess.Popen
    saved_github = dict(github._SHARED)
    class ObservedProcess(original_popen):
        def __init__(self, *args, **kwargs):
            launched.append(kwargs)
            super().__init__(*args, **kwargs)
    subprocess.Popen = ObservedProcess
    try:
        w.invalidate()
        clean = root / "clean"
        run(root, "clone", "-q", "--no-hardlinks", str(repo), str(clean))
        run(clean, "remote", "remove", "origin")
        w.invalidate()
        state = w.workspace_state(str(clean))
        require(state["exists"] and state["cwd"] == str(clean) and state["repo"] == {"root": str(clean), "name": "clean", "remoteUrl": None, "github": None}
                and (state["branch"], state["detached"], state["upstream"]) == ("main", False, None)
                and state["ahead"] is None and state["behind"] is None and state["changes"] == [] and state["changesTruncated"] is False
                and state["worktrees"] == [{"path": str(clean), "branch": "main", "current": True}]
                and state["pullRequest"] is None and state["gh"] == {"installed": False, "authenticated": False, "reason": "The GitHub CLI (gh) is not installed on this PC."},
                "sessions.workspace.state", "clean repository observer differs")
        empty = root / "initial"
        empty.mkdir()
        run(empty, "init", "-q", "-b", "trunk")
        (empty / "first.txt").write_text("hello\n", encoding="utf-8")
        (empty / "loose.txt").write_text("a\nb\n", encoding="utf-8")
        run(empty, "add", "first.txt")
        state = w.workspace_state(str(empty))
        changes = {row["path"]: row for row in state["changes"]}
        require(state["branch"] == "trunk" and changes["first.txt"]["status"] == "added" and changes["first.txt"]["additions"] == 1
                and changes["loose.txt"]["status"] == "untracked" and changes["loose.txt"]["additions"] == 2,
                "sessions.workspace.state", "initial repository changes differ")
        run(clean, "checkout", "-q", "--detach")
        w.invalidate()
        require(w.workspace_state(str(clean))["branch"] is None and w.workspace_state(str(clean))["detached"] is True,
                "sessions.workspace.state", "detached head was invented as a branch")
        try:
            w.git_action(str(clean), "push", confirm=True)
        except w.WorkspaceError as error:
            require(error.code == "detached_head", "sessions.workspace.confirm", "detached push refusal differs")
        else:
            require(False, "sessions.workspace.confirm", "detached branch attempted push")
        run(clean, "checkout", "-q", "main")
        try:
            w.git_action(str(clean), "push", confirm=True)
        except w.WorkspaceError as error:
            require(error.code == "no_remote", "sessions.workspace.confirm", "missing remote push refusal differs")
        else:
            require(False, "sessions.workspace.confirm", "remote-free branch attempted push")
        tracked = root / "tracked-commit"
        run(root, "clone", "-q", "--no-hardlinks", str(clean), str(tracked))
        run(tracked, "remote", "remove", "origin")
        for key, value in (("user.name", "Proofs"), ("user.email", "proofs@example.invalid"), ("commit.gpgsign", "false")):
            run(tracked, "config", key, value)
        (tracked / "a.txt").write_text("changed\n", encoding="utf-8")
        # The initial procedure deleted b, so choose another observed tracked
        # file to prove the two-file commit and untracked exclusion boundary.
        run(tracked, "rm", "-q", "sub/deeper.txt")
        (tracked / "untracked.txt").write_text("stay out\n", encoding="utf-8")
        w.workspace_state(str(tracked))
        committed = w.git_action(str(tracked), "commit", message="Change a, drop deep", confirm=True)
        require(committed["ok"] and "Change a, drop deep" in committed["output"] and "2 files changed" in committed["output"]
                and run(tracked, "log", "-1", "--format=%s").strip() == "Change a, drop deep"
                and run(tracked, "status", "--porcelain").strip() == "?? untracked.txt"
                and w.workspace_state(str(tracked))["changes"][0]["path"] == "untracked.txt", "sessions.workspace.action", "tracked commit/output/cache exclusion differs")
        nothing = w.git_action(str(tracked), "commit", message="again", confirm=True)
        require(nothing["ok"] is False and "nothing" in nothing["output"].lower(), "sessions.workspace.action", "empty commit reported success")
        for bad in ("", "   ", "x" * 5001, None):
            try:
                w.git_action(str(tracked), "commit", message=bad, confirm=True)
            except w.WorkspaceError as error:
                require(error.code == "message_required", "sessions.workspace.confirm", "invalid message refusal differs")
            else:
                require(False, "sessions.workspace.confirm", "invalid commit message accepted")
        for number in range(w.MAX_CHANGES + 9):
            (empty / f"file-{number:03}.txt").write_text("x\n", encoding="utf-8")
        w.invalidate()
        state = w.workspace_state(str(empty))
        require(len(state["changes"]) == w.MAX_CHANGES and state["changesTruncated"] is True, "sessions.workspace.state", "real default change cap did not truncate")
        (clean / "big.txt").write_text("".join(f"line {number} {'x' * 60}\n" for number in range(20_000)), encoding="utf-8")
        patch = w.file_diff(str(clean), "big.txt")
        require(patch["truncated"] and len(patch["patch"].encode()) <= w.MAX_PATCH_BYTES + 64
                and patch["patch"].endswith("[diff truncated]\n") and patch["patch"].startswith("diff --git a/big.txt b/big.txt"),
                "sessions.workspace.diff", "actual oversized patch did not expose bounded truncation")
        require(w.workspace_state(str(clean / "sub"))["repo"]["root"] == str(clean), "sessions.workspace.state", "subfolder observer lost repository root")
        plain = root / "Projects" / "notes"
        for cwd, code, status in ((str(plain), "not_a_repo", 400), (str(root / "gone"), "no_workspace", 404)):
            try:
                w.file_diff(cwd, "a.txt")
            except w.WorkspaceError as error:
                require((error.code, error.status) == (code, status), "sessions.workspace.diff", "missing workspace refusal differs")
            else:
                require(False, "sessions.workspace.diff", "nonrepository diff accepted")
        for cwd, action, code in ((str(clean), "force_push", "unknown_action"), (str(root / "gone"), "commit", "no_workspace"), (str(plain), "commit", "not_a_repo")):
            try:
                w.git_action(cwd, action, message="x", confirm=True)
            except w.WorkspaceError as error:
                require(error.code == code, "sessions.workspace.confirm", "action refusal differs")
            else:
                require(False, "sessions.workspace.confirm", "invalid workspace action accepted")
        # Divergence is observed through real Git histories/ref updates. No push
        # is needed or attempted, even between these disposable local stores.
        bare = root / "local-remote.git"
        run(root, "clone", "-q", "--bare", str(clean), str(bare))
        run(clean, "remote", "add", "origin", str(bare))
        run(clean, "fetch", "-q", "origin")
        run(clean, "config", "branch.main.remote", "origin")
        run(clean, "config", "branch.main.merge", "refs/heads/main")
        w.invalidate()
        state = w.workspace_state(str(clean))
        require((state["upstream"], state["ahead"], state["behind"]) == ("origin/main", 0, 0) and state["repo"]["remoteUrl"] == str(bare)
                and state["repo"]["github"] is None, "sessions.workspace.state", "initial local upstream differs")
        other = root / "other-local"
        run(root, "clone", "-q", str(bare), str(other))
        for target in (clean, other):
            for key, value in (("user.name", "Proofs"), ("user.email", "proofs@example.invalid"), ("commit.gpgsign", "false")):
                run(target, "config", key, value)
        for number in range(2):
            (clean / f"local-{number}.txt").write_text("local\n", encoding="utf-8")
            run(clean, "add", f"local-{number}.txt")
            run(clean, "commit", "-q", "-m", f"local-{number}")
        (other / "remote.txt").write_text("remote\n", encoding="utf-8")
        run(other, "add", "remote.txt")
        run(other, "commit", "-q", "-m", "remote-history")
        if os.name == "nt":
            # Upload-pack intentionally strips client Git configuration from
            # its environment. Configure only this newly created lab server.
            run(other, "config", "--local", "core.longpaths", "true")
        run(clean, "fetch", "-q", os.path.relpath(other, clean), "main:refs/remotes/origin/main")
        w.invalidate()
        require((w.workspace_state(str(clean))["ahead"], w.workspace_state(str(clean))["behind"]) == (2, 1), "sessions.workspace.state", "divergent local histories were not observed")
        # CLI fixture is a process boundary only: production auth/PR parsers,
        # caches, argument construction and command outcomes remain in use.
        fixture = root / "gh-transport.py"
        settings = root / "gh-transport.json"
        log = root / "gh-transport.log"
        fixture.write_text("import json,sys\nfrom pathlib import Path\n"
                           f"settings=Path({str(settings)!r}); log=Path({str(log)!r})\n"
                           "args=sys.argv[1:]\nwith log.open('a',encoding='utf-8') as stream: stream.write(json.dumps(args)+'\\n')\n"
                           "data=json.loads(settings.read_text())\n"
                           "if args[:2]==['auth','status']: sys.exit(0 if data['authenticated'] else 1)\n"
                           "if args[:2]==['pr','view']:\n"
                           " if data['view'] is None: sys.stderr.write('no pull requests found'); sys.exit(1)\n"
                           " print(json.dumps(data['view'])); sys.exit(0)\n"
                           "if args[:2]==['pr','create']:\n"
                           " if not data['create']: sys.exit(1)\n"
                           " print(data['create']); sys.exit(0)\n"
                           "sys.exit(2)\n", encoding="utf-8")
        wrapper = root / "gh.cmd"
        # This external stdlib-only wire fixture executes no repository code.
        # Keep inherited sitecustomize/PYTHONPATH out: otherwise the already
        # traced scratch child asks for a third heavy slot merely to read JSON.
        # Its real process remains inside the ancestor's memory governor.
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" -I "{fixture}" %*\r\n', encoding="utf-8")
        git = w._which("git")
        w._which = lambda name: git if name == "git" else str(wrapper) if name == "gh" else None
        run(clean, "remote", "set-url", "origin", "https://github.com/octo/demo.git")
        view = {"number": 7, "title": "Scratch transport PR", "url": "https://github.com/octo/demo/pull/7", "state": "OPEN", "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}, {"state": "PENDING"}]}
        api_calls = []
        def configure(authenticated=True, view=view, create="https://github.com/octo/demo/pull/7", api_mode="fallback"):
            settings.write_text(json.dumps({"authenticated": authenticated, "view": view, "create": create}), encoding="utf-8")
            api_calls.clear()
            def transport(method, url, headers, data, timeout):
                require(method == "GET" and url.startswith("https://api.github.com/repos/octo/demo/")
                        and "Authorization" not in headers and data is None,
                        "sessions.workspace.github", "scratch API transport escaped its declared anonymous read")
                api_calls.append(url)
                if api_mode == "fallback":
                    return 503, {}, b'{"message":"controlled offline API failure"}'
                if api_mode == "limited":
                    return 403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 3600)}, b'{"message":"rate limit exceeded"}'
                if "/pulls?" in url:
                    payload = [] if view is None else [{"number": view["number"], "title": view["title"], "html_url": view["url"],
                                                       "state": view["state"].lower(), "head": {"sha": "scratch-head"}}]
                else:
                    require(url.endswith("/commits/scratch-head/check-runs?per_page=100"),
                            "sessions.workspace.github", "API checks read the wrong head")
                    payload = {"check_runs": [{"status": "completed", "conclusion": "success"}, {"status": "queued"}]}
                return 200, {}, json.dumps(payload).encode()
            github._SHARED["watch"] = github.PullRequestWatch(github.GitHubClient(anonymous=True, transport=transport))
            w.invalidate()
            w._GH_CACHE.clear()
            log.write_text("", encoding="utf-8")
        def calls():
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        configure()
        state = w.workspace_state(str(clean))
        require(state["gh"] == {"installed": True, "authenticated": True, "reason": None}
                and state["pullRequest"] == {"number": 7, "title": "Scratch transport PR", "url": "https://github.com/octo/demo/pull/7", "state": "open", "checks": "pending"}
                and ["auth", "status"] in calls() and ["pr", "view", "--json", "number,title,url,state,statusCheckRollup"] in calls(), "sessions.workspace.github", f"CLI observer argument/response projection differs: gh={state['gh']!r}, pr={state['pullRequest']!r}, calls={calls()!r}")
        require(len(api_calls) == 1, "sessions.workspace.github", "CLI fallback bypassed the primary API failure")
        configure(api_mode="primary")
        primary = w.workspace_state(str(clean))
        require(primary["pullRequest"] == state["pullRequest"] and len(api_calls) == 2
                and api_calls[0].endswith("/pulls?head=octo:main&state=all&per_page=1")
                and not any(call[:2] == ["pr", "view"] for call in calls()),
                "sessions.workspace.github", "primary API projection differs or used the CLI unnecessarily")
        configure(api_mode="primary", view=None)
        require(w.workspace_state(str(clean))["pullRequest"] is None and len(api_calls) == 1
                and not any(call[:2] == ["pr", "view"] for call in calls()),
                "sessions.workspace.github", "absent API PR unnecessarily fell back to CLI")
        configure(api_mode="limited")
        limited = w.workspace_state(str(clean))
        require(limited["pullRequest"] is None and limited.get("pullRequestError", "").startswith("GitHub is limiting")
                and not any(call[:2] == ["pr", "view"] for call in calls()),
                "sessions.workspace.github", "rate-limited API bypassed the shared gate through CLI")
        configure(view=None)
        state = w.workspace_state(str(clean))
        require(state["pullRequest"] is None and "pullRequestError" not in state, "sessions.workspace.github", "absent PR was reported as failure")
        configure(authenticated=False)
        state = w.workspace_state(str(clean))
        require(state["gh"]["installed"] and state["gh"]["authenticated"] is False and "gh auth login" in state["gh"]["reason"]
                and state["pullRequest"] is None and not any(call[:2] == ["pr", "view"] for call in calls()), "sessions.workspace.github", "signed-out CLI was asked for private PR data")
        configure()
        run(clean, "remote", "remove", "origin")
        require(w.workspace_state(str(clean))["pullRequest"] is None and not any(call[:2] == ["pr", "view"] for call in calls()), "sessions.workspace.github", "non-GitHub repo was asked for a PR")
        configure()
        outcome = w.git_action(str(clean), "create_pr", title="Scratch title", body="Scratch body", confirm=True)
        require(outcome == {"ok": True, "output": "https://github.com/octo/demo/pull/7", "url": "https://github.com/octo/demo/pull/7"}
                and ["pr", "create", "--title", "Scratch title", "--body", "Scratch body"] in calls(), "sessions.workspace.github", "PR transport did not receive explicit title/body")
        for title in (" ", "x" * 501):
            try:
                w.git_action(str(clean), "create_pr", title=title, confirm=True)
            except w.WorkspaceError as error:
                require(error.code == "title_required", "sessions.workspace.github", "invalid title refusal differs")
            else:
                require(False, "sessions.workspace.github", "invalid title accepted")
        configure(create=None)
        failed = w.git_action(str(clean), "create_pr", title="Scratch", confirm=True)
        require(failed["ok"] is False and "url" not in failed, "sessions.workspace.github", "failed CLI created a PR success claim")
        configure(authenticated=False)
        try:
            w.git_action(str(clean), "create_pr", title="Scratch", confirm=True)
        except w.WorkspaceError as error:
            require((error.code, error.status) == ("gh_not_signed_in", 503), "sessions.workspace.github", "signed-out creation refusal differs")
        else:
            require(False, "sessions.workspace.github", "signed-out CLI created a PR")
        w._which = lambda name: git if name == "git" else None
        try:
            w.git_action(str(clean), "create_pr", title="Scratch", confirm=True)
        except w.WorkspaceError as error:
            require(error.code == "gh_missing", "sessions.workspace.github", "missing CLI creation refusal differs")
        else:
            require(False, "sessions.workspace.github", "missing CLI created a PR")
        if os.name == "nt":
            no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            require(len(launched) >= 8 and all(value.get("creationflags", 0) & no_window and value["startupinfo"].wShowWindow == 0 for value in launched),
                    "sessions.workspace.cli", "real child launched a visible window")
        # Exercise catalogue identities from all original supported remotes.
        for name, url in (("lib", "git@github.com:octo/lib.git"), ("internal", "https://gitlab.example.com/team/internal.git")):
            path = root / "Projects" / name
            path.mkdir()
            run(path, "init", "-q", "-b", "main")
            run(path, "remote", "add", "origin", url)
        f._CACHE.clear()
        projects = {row["name"]: row for row in f.local_projects()}
        require(projects["lib"]["github"] == "octo/lib" and projects["internal"]["github"] is None, "sessions.folders.catalogue", "SSH/non-GitHub catalogue identity differs")
    finally:
        subprocess.Popen = original_popen
        github._SHARED.clear()
        github._SHARED.update(saved_github)
    ids = ["sessions.workspace.github", "sessions.workspace.cli"]
    return ids, [{"contract": identity, "ok": True, "boundary": "finite anonymous HTTP and CLI transport; no GitHub account/network"} for identity in ids], []


def checked_result(check):
    import inspect
    def decorate(function):
        signature = inspect.signature(function)
        @functools.wraps(function)
        def call(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            result = function(*args, **kwargs)
            check(tuple(bound.arguments.values()), bound.arguments, result)
            return result
        return call
    return decorate


def check_folder_info(path, result):
    from configparser import ConfigParser
    marker = Path(path) / ".git"
    if not marker.exists():
        require(result is None, "sessions.folders.catalogue", "plain folder reported as repository")
        return
    if marker.is_file():
        text = marker.read_text(encoding="utf-8", errors="replace").strip()
        if not text.startswith("gitdir:"):
            require(result is None, "sessions.folders.catalogue", "invalid Git marker reported as repository")
            return
        directory = Path(text[7:].strip())
    else:
        directory = marker
    if not directory.is_absolute():
        directory = (Path(path) / directory).resolve()
    try:
        head = (directory / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        head = ""
    branch = head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else None
    common = directory
    if (directory / "commondir").is_file():
        common = (directory / (directory / "commondir").read_text(encoding="utf-8").strip()).resolve()
    config = ConfigParser(interpolation=None, strict=False)
    try:
        config.read(common / "config", encoding="utf-8")
        remote = config.get('remote "origin"', "url", fallback="")
    except (OSError, __import__("configparser").Error):
        # Git configurations with malformed unrelated lines remain readable by
        # this deliberately narrow catalogue, as in the production reader.
        remote, section = "", ""
        try:
            lines = (common / "config").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if line.startswith("["):
                section = line
            elif section == '[remote "origin"]' and line.startswith("url") and "=" in line:
                remote = line.partition("=")[2].strip()
    # Match the feature's catalogue rule: host suffix + valid owner/repository.
    match = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", remote, re.I)
    expected = {"branch": branch, "github": f"{match[1]}/{match[2]}" if match else None}
    require(result == expected, "sessions.folders.catalogue", "Git files and catalogue differ")


def check_catalogue(selected, infos, result):
    expected = [{"path": str(child), "name": child.name, "isGit": info is not None,
                 "branch": (info or {}).get("branch"), "github": (info or {}).get("github"),
                 "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(updated))}
                for (updated, child), info in zip(selected, infos)]
    require(result == expected, "sessions.folders.catalogue", "catalogue membership, timestamp or Git projection differs")


def check_candidates(recent, local, query, result, projects_root):
    needle = query.strip().casefold()
    def matches(row, keys):
        return not needle or any(needle in str(row.get(key) or "").lower() for key in keys)
    require(result == {"recent": [row for row in recent or [] if matches(row, ("path", "name"))][:8],
                       "local": [row for row in local if matches(row, ("name", "github"))][:30], "projectsRoot": str(projects_root),
                       "direct": result.get("direct")},
            "sessions.folders.filter", "folder query, limits or root projection differs")
    path = Path(query.strip()).expanduser()
    direct = result.get("direct")
    eligible = bool(query.strip()) and path.is_absolute() and path.is_dir()
    require(bool(direct) == eligible and (not eligible or direct["path"] == str(path)),
            "sessions.folders.direct", "existing absolute directory was not offered exactly")


def check_event_buffer(buffer, cursor, result):
    """Called with the event condition held: no concurrent-writer snapshot race."""
    events, head, resync = result
    expected_head = buffer._next - 1
    oldest = buffer._ring[0][0] if buffer._ring else expected_head + 1
    expected_resync = cursor is not None and not oldest - 1 <= cursor <= expected_head
    if cursor is None or expected_resync:
        expected = []
    else:
        from itertools import islice
        length = expected_head - cursor
        expected = [event for stamp, event, _ in islice(reversed(buffer._ring), length)][::-1]
    require((events, head, resync) == (expected, expected_head, expected_resync), "sessions.events.cursor", "cursor projection or resync differs from ring")


def check_event_publish(buffer, event, cursor, previous_bytes, removed_bytes):
    size = len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    require(event["cursor"] == cursor and buffer._next == cursor + 1 and event["hostDeviceId"] == buffer.host_device_id,
            "sessions.events.stamp", "cursor or host stamp differs")
    require(len(buffer._ring) <= buffer.max_events and buffer._bytes == previous_bytes + size - removed_bytes
            and 0 <= buffer._bytes <= buffer.max_bytes and size <= buffer.max_event_bytes,
            "sessions.events.bounds", "event/ring count or byte budget differs")


def check_run_record(result):
    if result is None:
        return
    from .connected_sessions.runs import ACTIVE_STATES, TERMINAL_STATES
    state = result["state"]
    require(state in ACTIVE_STATES | TERMINAL_STATES, "sessions.run.lifecycle", "unknown run state")
    require(state in ACTIVE_STATES or result.get("canStop") is False and result.get("canSteer") is False,
            "sessions.run.lifecycle", "terminal run exposes live controls")
    require(state in {"waiting_input", "waiting_approval"} or result.get("pendingRequest") is None,
            "sessions.run.lifecycle", "request remains pending outside waiting state")


def check_tidy_item(session_id, original, result, output_cap):
    from urllib.parse import quote
    identity = "sessions.broker.read"
    source = original.get("data")
    if not isinstance(source, dict):
        require(result == original, identity, "item without data was mutated")
        return
    data = result["data"]
    output = source.get("output")
    if isinstance(output, str):
        require(data.get("output") == output[:output_cap], identity, "page output prefix differs from full source")
        if len(output) > output_cap:
            require(data.get("outputTruncated") is True, identity, "bounded output lost truncation flag")
    for raw, attachment in zip(source.get("attachments") or [], data.get("attachments") or []):
        if not isinstance(raw, dict):
            require(attachment == raw, identity, "invalid attachment entry was rewritten")
            continue
        url = str(raw.get("url") or "")
        expected = url if url.startswith(("/api/connected/media", "/api/connected-chat-media")) else (f"/api/connected/media?session={quote(session_id, safe='')}&media={quote(str(raw['id']), safe='')}" if raw.get("id") else None)
        label = raw.get("label")
        expected_label = Path(label.replace("\\", "/")).name if isinstance(label, str) and ("/" in label or "\\" in label) else label
        require(attachment.get("url") == expected and attachment.get("label") == expected_label, identity, "attachment exposed host URL/label or lost served identity")


def check_broker_page(session_id, result, run):
    require(result.get("run") == run and ((result.get("session") or {}).get("id") == session_id), "sessions.broker.read", "read receipt lost session or current run")
    check_run_record(run)


def check_broker_list(broker, observed, sources, result, *, query, category, archived, harness, limit, offset):
    from .connected_sessions.registry import APP_LABELS
    identity = "sessions.broker.catalogue"
    rows = [row for row in observed if (archived or not row.archived) and (harness or row.origin != "neyvia-harness") and (not category or row.category == category)]
    needle = " ".join(str(query or "").casefold().split())
    if needle:
        rows = [row for row in rows if needle in " ".join(str(value or "") for value in (row.title, row.project, row.cwd, row.git_branch, APP_LABELS.get(row.app))).casefold()]
    from .connected_sessions.broker import _sort_key
    rows.sort(key=lambda row: (_sort_key(row.updated_at), row.id), reverse=True)
    budget, start = max(1, min(int(limit or 100), 500)), max(0, int(offset or 0))
    page = rows[start:start + budget]
    require([row["id"] for row in result["sessions"]] == [row.id for row in page] and result["total"] == len(rows)
            and result["nextOffset"] == (start + budget if start + budget < len(rows) else None)
            and result["sources"] == sources and result["host"] == {"deviceId": broker.host["deviceId"], "deviceName": broker.host["deviceName"]}, identity, "catalogue filter, order, pagination, sources or host differ")
    for raw, row in zip(page, result["sessions"]):
        require(all(row.get(key) == value for key, value in raw.public().items()) and isinstance(row.get("unread"), bool), identity, "session projection lost observed metadata or unread flag")


def check_control_projection(raw, result, operation):
    from .connected_sessions.registry import jsonable
    expected = {"goal": jsonable(raw) if raw else None, "supported": True} if operation == "goal" else jsonable(raw)
    require(result == expected, "sessions.broker.controls", "adapter control projection differs")


def check_adapter_refusal(arguments, result):
    exc = arguments["exc"]
    if hasattr(exc, "public") and hasattr(exc, "status"):
        require(result is exc, "sessions.broker.refusals", "existing coded refusal identity changed")
        return
    code = getattr(exc, "code", None)
    from .connected_sessions.registry import _STATUS_BY_CODE, describe, jsonable
    if isinstance(code, str) and code:
        expected_status = _STATUS_BY_CODE.get(code) or (404 if "not_found" in code else 400 if any(word in code for word in ("invalid", "required", "empty", "missing")) else arguments["fallback_status"])
        owner = getattr(exc, "owner", None)
        extra = {"owner": owner} if isinstance(owner, str) and owner else {"owner": str(owner["owner"]), "ownerDetail": jsonable(owner)} if isinstance(owner, dict) and owner.get("owner") else {}
        require((result.code, result.status, result.message, result.extra) == (code, expected_status, describe(exc), extra), "sessions.broker.refusals", "coded adapter refusal lost status, message or owner")
    else:
        require((result.code, result.status, result.message) == (arguments["fallback_code"], arguments["fallback_status"], (arguments["fallback_message"] + " " if arguments["fallback_message"] else "") + describe(exc)), "sessions.broker.refusals", "uncoded adapter failure lost fallback")


def check_registry_adapter(arguments, result):
    adapter, reason = result
    require((adapter is None and isinstance(reason, str) and bool(reason)) or (adapter is not None and reason is None), "sessions.broker.registry", "adapter state is ambiguous")
    if adapter is not None:
        from .connected_sessions.registry import _REQUIRED_METHODS
        require(all(callable(getattr(adapter, method, None)) for method in _REQUIRED_METHODS) and getattr(adapter, "app", arguments["app"]) == arguments["app"], "sessions.broker.registry", "incomplete or wrong-app adapter accepted")


def check_watchdog_selection(broker, observed, now, selected):
    expected = [live for live, state, stopping, last in observed if state in ("queued", "running") and not stopping and now - last >= broker.idle_watchdog_seconds]
    require(selected == expected, "sessions.run.watchdog", "watchdog selected a waiting or recent run")


def check_recovered_runs(records):
    from .connected_sessions.runs import INTERRUPTED_BY_RESTART
    require(all(row.get("state") == "interrupted" and row.get("pendingRequest") is None and row.get("error") == INTERRUPTED_BY_RESTART and row.get("updatedAt") for row in records), "sessions.run.recovery", "dead owner recovery retained active state")


def check_full_output(item_id, raw, result):
    from .connected_sessions.broker import FULL_TOOL_OUTPUT_CHARS
    text = str(raw)
    require(result == {"itemId": item_id, "output": text[:FULL_TOOL_OUTPUT_CHARS], "truncated": len(text) > FULL_TOOL_OUTPUT_CHARS}, "sessions.broker.read", "full output cap/identity differs")


def check_unread(row, updated_at, latest_seq, result):
    from .connected_sessions.seen import _epoch
    expected = False
    if row is not None:
        expected = latest_seq is not None and isinstance(row.get("seq"), int) and latest_seq > row["seq"]
        seen_at, current = _epoch(row.get("updatedAt")), _epoch(updated_at)
        expected = expected or (seen_at is not None and current is not None and current > seen_at + 0.001)
    require(result is bool(expected), "sessions.broker.unread", "unread marker ignored observed sequence/activity baseline")


def check_media_result(result):
    require(isinstance(result, tuple) and len(result) == 3 and isinstance(result[0], bytes)
            and all(isinstance(value, str) for value in result[1:]), "sessions.broker.media", "media hook returned invalid byte/MIME/name receipt")


def check_turn_options(raw, result):
    raw = raw if isinstance(raw, dict) else {}
    identity = "sessions.broker.options"
    def text(*keys):
        return next((raw[key].strip()[:200] for key in keys if isinstance(raw.get(key), str) and raw[key].strip()), None)
    require((result.model, result.effort, result.permission_mode, result.transport, result.fork_from) ==
            (text("model"), text("effort"), text("permissionMode", "permission_mode"), text("transport"), text("forkFrom", "fork_from"))
            and result.transport in (None, "print", "terminal"), identity, "turn option projection or transport authority differs")


def check_broker_request(arguments, result):
    check_run_record(result)
    require(result["runId"] == str(arguments["request_id"]).strip(), "sessions.run.request", "returned run belongs to a different request")
    if "session_id" in arguments:
        require(result["sessionId"] == arguments["session_id"], "sessions.run.request", "returned run belongs to a different session")


def check_state_transition(run, state, error, pending, flags):
    from .connected_sessions.runs import TERMINAL_STATES
    expected_pending = pending if state in {"waiting_approval", "waiting_input"} else None
    require(run.data["state"] == state and run.data.get("pendingRequest") == expected_pending
            and run.data.get("error") == (error if state in TERMINAL_STATES or error else None)
            and run.terminal is (state in TERMINAL_STATES), "sessions.run.lifecycle", "state/request/error transition differs from provider event")
    for name in ("canStop", "canSteer"):
        if flags and name in flags:
            require(run.data[name] is bool(flags[name]), "sessions.run.lifecycle", "live control flag differs from provider event")


def check_seq(ordinal, index, sub, result):
    from .connected_sessions.codex_items import SEQ_SLOTS, SEQ_MAX_INDEX
    expected = max(0, ordinal) * SEQ_SLOTS + min(max(index, 0), SEQ_MAX_INDEX) * 4 + sub
    require(result == expected, "sessions.codex.sequence", "turn ordinal/slot mapping differs")


def check_uuid_clock(value, result):
    match = re.fullmatch(r"([0-9a-f]{8})-([0-9a-f]{4})-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", str(value or "").lower())
    clock = int(match.group(1) + match.group(2), 16) if match else None
    expected = clock if clock is not None and 1_600_000_000_000 < clock < 4_100_000_000_000 else None
    require(result == expected, "sessions.codex.sequence", "UUIDv7 clock fabricated an older turn timestamp")


def check_clip(text, limit, result):
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        expected = text
    else:
        kept = raw[:limit].decode("utf-8", errors="ignore")
        expected = kept + f"\n[... {len(text) - len(kept)} more characters omitted]"
    require(result == expected, "sessions.codex.text", "UTF-8 prefix or omitted-character receipt differs")


def check_codex_item(arguments, result):
    raw = arguments["item"]
    identity = "sessions.codex.text"
    require(isinstance(result, list) and all(entry.id and isinstance(entry.seq, int) for entry in result), identity, "invalid mapped item identity")
    if not raw.get("id"):
        require(result == [], identity, "anonymous thread item became visible")
    if raw.get("type") in ("agentMessage", "userMessage") and result:
        source = str(raw.get("text") or "") if raw.get("type") == "agentMessage" else None
        if source is not None:
            from .connected_sessions.codex_items import TEXT_LIMIT
            check_clip(source, TEXT_LIMIT, result[0].data["text"])
            if len(source) > len(result[0].data["text"]):
                require(result[0].data.get("truncated") is True, identity, "truncated assistant item missing marker")
        require(len(json.dumps(result[0].public(), ensure_ascii=False).encode("utf-8")) < 64_000, identity, "message exceeds event envelope budget")


def check_codex_turns(turns, ordinals, result):
    identity = "sessions.codex.sequence"
    # Identity slots must belong to their originating turn, including generated
    # reasoning and interrupted/failed markers. Do not re-run the mapper.
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        slot = max(0, ordinals.get(str(turn.get("id")), 0)) * 8192
        raw_ids = {str(item.get("id")) for item in turn.get("items") or [] if isinstance(item, dict)}
        markers = {f"reasoning-unreported:{turn.get('id')}", f"turn-error:{turn.get('id')}", f"turn-interrupted:{turn.get('id')}"}
        for entry in result:
            if entry.id in raw_ids | markers or any(entry.id == key + ":diff" for key in raw_ids):
                require(slot <= entry.seq < slot + 8192, identity, "mapped item escaped originating turn slot")
        if turn.get("status") == "completed" and not any(isinstance(item, dict) and item.get("type") == "reasoning" for item in turn.get("items") or []):
            generated = [entry for entry in result if entry.id == f"reasoning-unreported:{turn.get('id')}"]
            require(len(generated) == 1 and generated[0].data.get("exposure") == "not_reported", identity, "absent reasoning became invented text")


def check_codex_diff(changes, cwd, limit, result):
    identity = "sessions.codex.diff"
    require(result["patch"] is None or len(result["patch"]) <= limit, identity, "file patch exceeds bound")
    candidates = [change for change in changes if isinstance(change, dict)] if isinstance(changes, list) else []
    require(len(result["files"]) <= len(candidates), identity, "file receipt invented changes")
    for raw, entry in zip(candidates, result["files"]):
        body = str(raw.get("diff") or "")
        kind = (raw.get("kind") or {}).get("type") or "update"
        if kind in ("add", "delete"):
            lines = body.count("\n") + int(bool(body) and not body.endswith("\n"))
            expected = (lines, 0) if kind == "add" else (0, lines)
        else:
            hunk = "@@" not in body
            added = removed = 0
            for line in body.split("\n"):
                if line.startswith("@@"):
                    hunk = True
                elif hunk:
                    added += int(line.startswith("+") and not line.startswith("+++ "))
                    removed += int(line.startswith("-") and not line.startswith("--- "))
            expected = (added, removed)
        require((entry["additions"], entry["deletions"]) == expected and entry["kind"] == kind, identity, "file counts or kind differ from full source patch")
        path = str(raw.get("path") or "")
        base = str(cwd or "").replace("\\", "/").rstrip("/")
        normalized = path.replace("\\", "/")
        expected_path = normalized[len(base) + 1:] if base and normalized.lower().startswith(base.lower() + "/") else path
        require(entry["path"] == expected_path, identity, "file path is not relative to observed workspace")


def check_permission(arguments, result, operation):
    identity = "sessions.codex.permissions"
    modes = {
        "ask": ("on-request", "read-only", {"type": "readOnly", "networkAccess": False}),
        "auto": ("on-request", "workspace-write", {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False, "excludeTmpdirEnvVar": False, "excludeSlashTmp": False}),
        "full": ("never", "danger-full-access", {"type": "dangerFullAccess"}),
    }
    if operation == "match":
        expected = next((key for key, value in modes.items() if value[:2] == (arguments["approval_policy"], arguments["sandbox_mode"])), None)
    elif operation == "catalogue":
        require([row["id"] for row in result] == list(modes) and [row["label"] for row in result] == ["Ask for approval", "Auto in workspace", "Full access"], identity, "permission catalogue changed advertised policy")
        return
    else:
        mode = modes.get(str(arguments["mode_id"] or ""))
        expected = {} if mode is None else {"approvalPolicy": mode[0], "sandboxPolicy": mode[2]} if operation == "turn" else {"approvalPolicy": mode[0], "sandbox": mode[1]}
    require(result == expected, identity, "permission mode changed sandbox authority")


def check_request_wire(arguments, result):
    identity = "sessions.codex.requests"
    method, params, response = arguments["method"], arguments["params"], arguments["response"]
    decision = str(response.get("decision") or "deny")
    answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
    if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        expected = {"decision": {"approve": "accept", "cancel": "cancel"}.get(decision, "decline")}
    elif method == "item/permissions/requestApproval":
        permissions = params.get("permissions")
        expected = {"permissions": {key: value for key, value in permissions.items() if value is not None} if decision == "approve" and isinstance(permissions, dict) else {}, "scope": "turn"}
    elif method == "item/tool/requestUserInput":
        expected = {"answers": {str(question["id"]): {"answers": [str(answers[question["id"]])[:20_000]] if decision == "approve" and str(answers.get(question["id"], "")) else []} for question in params.get("questions") or [] if isinstance(question, dict) and question.get("id")}}
    elif method == "mcpServer/elicitation/request":
        action = "accept" if decision == "approve" else "cancel" if decision == "cancel" else "decline"
        content = None
        if decision == "approve" and str(params.get("mode") or "") != "url":
            properties = (params.get("requestedSchema") or {}).get("properties") or {}
            properties = dict(list(properties.items())[:20])
            content = {}
            for key, value in answers.items():
                text = str(value)
                kind = (properties.get(str(key)) or {}).get("type")
                if kind == "boolean":
                    text = text.strip().lower() in ("true", "yes", "1", "on")
                elif kind in ("number", "integer"):
                    try:
                        number = float(text)
                        text = int(number) if kind == "integer" or number.is_integer() else number
                    except ValueError:
                        pass
                content[str(key)] = text
        expected = {"action": action, "content": content, "_meta": None}
    else:
        expected = {}
    require(result == expected, identity, "request reply changed wire shape or granted broader authority")


def check_public_request(arguments, result):
    identity = "sessions.codex.requests"
    require(result["requestId"] == arguments["request_id"] and result["method"] == arguments["method"], identity, "pending request lost identity")
    if result["kind"] == "approval":
        require(set(result["choices"]) <= {"approve", "deny", "cancel"} and result["decision"] is None, identity, "pending approval exposes persistent authority")
    else:
        require(result["kind"] == "question" and result["answers"] == {}, identity, "pending question invented an answer")
        require(len(json.dumps(result)) < 64_000, "sessions.codex.text", "pending question exceeds event envelope budget")


def check_media_token(ref, result):
    import hashlib
    require(result == hashlib.sha256(ref.encode()).hexdigest(), "sessions.codex.media", "media identity differs from reference SHA-256")


def check_origin(path, result):
    normal = str(path or "").replace("/", "\\").lower().rstrip("\\") + "\\"
    harness = normal != "\\" and any(marker in normal for marker in ("\\.agent_control\\", "\\proof\\", "evidence", "harness", ".sandbox-scratch", "\\temp\\", "\\tmp\\", "\\appdata\\local\\temp\\"))
    require(result == ("neyvia-harness" if harness else "user"), "sessions.codex.origin", "origin projection lost automation/temp boundary")


def check_tail_read(max_bytes, raw, rows, clipped):
    require(len(raw) <= max_bytes, "sessions.codex.rollout", "rollout read escaped bounded tail")
    lines = raw.split(b"\n")[1:] if clipped else raw.split(b"\n")
    expected = []
    for line in lines:
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict):
            expected.append(value)
    require(rows == expected, "sessions.codex.rollout", "bounded tail parser omitted or invented complete dictionary rows")


def check_rollout_activity(result, age, *, marker=None, payload=None, timestamp=None):
    from .connected_sessions.codex_items import ROLLOUT_ACTIVE_SECONDS, ROLLOUT_STALE_SECONDS, iso_from_seconds
    open_turn = age is not None and age <= ROLLOUT_STALE_SECONDS and (marker in {"task_started", "turn_started"} if marker is not None else age <= ROLLOUT_ACTIVE_SECONDS)
    expected = {"inProgress": open_turn, "ageSeconds": age, "turnId": (payload or {}).get("turn_id") if open_turn and marker else None,
                "since": (iso_from_seconds((payload or {}).get("started_at")) or timestamp) if open_turn and marker else None}
    require(result == expected, "sessions.codex.rollout", "activity ignored fresh start, terminal marker or stale deadline")


def check_native_category(runtime, result):
    from .connected_sessions.neyvia_options import NATIVE_RUNTIME, normalize_runtime, is_native
    expected = ("native", None) if not runtime else ("native", NATIVE_RUNTIME) if is_native(runtime) else ("hybrid", None if runtime == "mixed-routes" else normalize_runtime(runtime))
    require(result == expected, "sessions.neyvia.category", "native/hybrid runtime projection differs")


def check_native_runtime(row, result):
    from .connected_sessions.neyvia_options import normalize_runtime
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    route = next((entry for entry in (metadata.get("routeSelection"), metadata.get("route")) if isinstance(entry, dict)), {})
    expected = None
    for source in (row, metadata, route):
        for key in ("runtimeId", "runtime_id", "runtime", "harnessId", "harness_id"):
            if isinstance(source.get(key), str) and source[key]:
                expected = normalize_runtime(source[key])
                break
        if expected is not None:
            break
    if expected is None:
        snapshot = metadata.get("routeSnapshot")
        rows = snapshot if isinstance(snapshot, list) else snapshot.values() if isinstance(snapshot, dict) else []
        ids = set()
        for route in rows:
            if isinstance(route, dict):
                value = next((route[key] for key in ("runtimeId", "runtime_id", "runtime", "harnessId", "harness_id") if route.get(key)), None)
                if value:
                    ids.add(normalize_runtime(value))
        expected = next(iter(ids)) if len(ids) == 1 else "mixed-routes" if ids else ""
    require(result == expected, "sessions.neyvia.category", "conversation runtime ignored priority or mixed routes")


def check_native_summary(adapter, row, context, node_runtime, result):
    identity = "sessions.neyvia.summary"
    from .connected_sessions.neyvia import conversation_runtime, classify, ORCHESTRATION_REASON
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    workspace = context.workspaces.get(str(row.get("workspaceId") or ""), {})
    cwd = next((str(value) for value in (metadata.get("workspacePath"), metadata.get("executionRoot"), workspace.get("root_path")) if isinstance(value, str) and value.strip()), None)
    require((result.app, result.id, result.cwd, result.project, result.title, result.archived) ==
            ("neyvia", adapter._sid(row["conversationId"]), cwd, row.get("projectId") or workspace.get("name") or (Path(cwd).name if cwd else None) or None,
             str(row.get("title") or "Conversation"), bool(row.get("archivedAt"))), identity, "conversation identity/workspace/archive projection differs")
    category, runtime = classify(conversation_runtime(row) or node_runtime)
    require((result.category, result.runtime) == (category, runtime) and result.updated_at == (row.get("lastMeaningfulActivityAt") or row.get("updatedAt"))
            and result.created_at == row.get("createdAt"), identity, "conversation category or timestamps differ")
    require((result.status, result.live_owner) == adapter._status(row, context), identity, "summary lost active/waiting/error attribution")
    if row["kind"] != "chat":
        require(not result.capabilities.continue_session and result.capabilities.reason == ORCHESTRATION_REASON, identity, "orchestration became continuable")
    else:
        require(result.capabilities.continue_session and result.capabilities.stop and result.capabilities.new_session
                and result.capabilities.model_choice and result.capabilities.permission_choice and result.capabilities.goal == (category == "native"), identity, "chat controls or native goal capability differ")


def check_native_page(result, *, after, before, budget, earliest, trimmed):
    identity = "sessions.neyvia.page"
    seqs = [entry.seq for entry in result.items]
    require(seqs == sorted(seqs) and len(seqs) == len(set(seqs)), identity, "page sequence order collides")
    require(all((after is None or seq > after) and (before is None or seq < int(before)) for seq in seqs), identity, "page escaped cursor window")
    require(result.cursor == str(max(seqs + ([after] if after is not None else []), default=0)) and result.has_earlier == (trimmed or earliest > 0), identity, "page cursor or earlier flag differs from delivered items")


def check_native_tool_category(name, result):
    name = str(name or "").lower()
    rules = [(r"^mcp|[._]mcp[._]", "mcp"), (r"terminal|shell|command|powershell|bash|(^|[._])exec($|[._])", "command"),
             (r"write|edit|patch|apply|delete|rename|move", "edit"), (r"web|browser|situation|fetch|url|preview", "web"),
             (r"search|find|grep|glob|list|describe|retrieve|memory", "search"), (r"read|open|inspect|view|screenshot", "read"),
             (r"agent|delegate|spawn|goal|ask_user|question", "agent")]
    expected = next((category for pattern, category in rules if re.search(pattern, name)), "other")
    require(result == expected, "sessions.neyvia.tools", "tool category ignored ordered classification rules")


def check_native_tool(arguments, result):
    identity = "sessions.neyvia.tools"
    call = arguments["call"]
    data = result.data
    check_native_tool_category(call["tool"], data["category"])
    status = call["status"].lower()
    state = "error" if call.get("error") or status in {"failed", "error"} else "ok" if status in {"completed", "ok", "success", "succeeded", "done"} else "error" if arguments["finished"] else "running"
    try:
        parsed = json.loads(call["output"])
    except (ValueError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    text = (call["error"] or call["output"]) if state == "error" else call["output"]
    bodies = [parsed] + [parsed[key] for key in ("toolResult", "result") if isinstance(parsed.get(key), dict)]
    if state != "error":
        for body in bodies[1:]:
            if data["category"] == "command" and isinstance(body.get("stdout"), str):
                text = body["stdout"] + ("\n" + body["stderr"] if isinstance(body.get("stderr"), str) and body["stderr"] else "")
                break
            if data["category"] == "read" and isinstance(body.get("content"), str):
                text = body["content"]
                break
    def number(keys):
        return next((int(body[key]) for body in bodies for key in keys if isinstance(body.get(key), (int, float)) and not isinstance(body[key], bool)), None)
    require(result.id == arguments["item_id"] and result.seq == arguments["seq"] and data["name"] == call["tool"]
            and data["status"] == state and data["output"] == (text or "")[:8192]
            and data.get("exitCode") == number(("exit_code", "exitCode", "exitcode"))
            and data.get("durationMs") == (number(("duration_ms", "durationMs")) or arguments["duration_ms"]), identity, "tool result lost status, readable output, timing or identity")
    if len(text or "") > 8192:
        require(data.get("outputTruncated") is True, identity, "tool output lost truncation marker")
    if arguments["finished"] and state == "error" and status not in {"failed", "error"} and not call.get("error"):
        require(data.get("note") == "No result was recorded for this call.", identity, "finished unresolved tool still looks live")


def check_native_turn(arguments, result):
    identity = "sessions.neyvia.items"
    turn, ordinal = arguments["turn"], arguments["ordinal"]
    items, route = result
    seqs = [item.seq for item in items]
    require(1 <= len(items) <= 100 and seqs == sorted(set(seqs)) and seqs[-1] == (ordinal + 1) * 100 + 99
            and all((ordinal + 1) * 100 <= seq < (ordinal + 2) * 100 for seq in seqs), identity, "turn slots collide or lose text slot")
    content = str(turn.get("content") or "")
    require(items[-1].data.get("text") == content, identity, "stored turn main text changed")
    if turn.get("role") == "user":
        require(len(items) == 1 and items[0].kind == "user", identity, "user turn invented activity")
    else:
        metadata = turn.get("metadata") if isinstance(turn.get("metadata"), dict) else {}
        outcome = metadata.get("runtimeResult") if isinstance(metadata.get("runtimeResult"), dict) else {}
        status = str(outcome.get("status") or "").lower()
        source = str(turn.get("source") or "")
        level = "error" if status in ("failed", "error", "timeout") or source.endswith("error") else "info" if status == "cancelled" else "warning" if status in ("stop_unconfirmed", "interrupted") or source == "chat-interrupted" else None
        require(items[-1].kind == ("notice" if level else "assistant") and (not level or items[-1].data.get("level") == level), identity, "failed/stopped turn became a normal answer")
    require(all(len(item.data.get("summary") or "") <= 8192 and item.data.get("hidden") is False for item in items if item.kind == "reasoning"), identity, "reasoning item is unbounded or claims hidden content")


def check_native_segments(receipt, result):
    identity = "sessions.neyvia.items"
    require(all(row.get("kind") in {"tool", "reasoning_summary", "thinking_text"} for row in result), identity, "activity invented an unsupported segment kind")
    rows = receipt.get("activitySegments") if isinstance(receipt, dict) else None
    if isinstance(rows, list):
        public = "\n".join(str(row.get("text") or "") for row in rows if isinstance(row, dict) and (row.get("kind") in {"reasoning_summary", "summary"} or row.get("source") == "provider.reasoning_content"))
        reasoning = "\n".join(str(row.get("text") or "") for row in result if row.get("kind") != "tool")
        for row in rows:
            if isinstance(row, dict) and row.get("kind") in {"thinking_text", "runtime_thinking", "runtime_thinking_delta"} and row.get("source") != "provider.reasoning_content":
                text = str(row.get("text") or "")
                if text and text not in public:
                    require(text not in reasoning, identity, "unlabelled/private reasoning became public activity")


def check_native_attachments(images, result):
    import base64
    expected = []
    extensions = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
    for number, image in enumerate(images, 1):
        mime = str(image.get("mime") or "application/octet-stream")
        expected.append({"name": str(image.get("name") or f"image-{number}{extensions.get(mime, '.bin')}"), "mime": mime,
                         "size": len(base64.b64decode(str(image.get("data") or ""), validate=True)), "dataBase64": image["data"]})
    require(result == expected, "sessions.neyvia.payload", "native attachment altered bytes, MIME, name or size")


def check_native_payload(arguments, result):
    identity = "sessions.neyvia.payload"
    route = arguments["route"]
    require(result["message"] == arguments["message"] and result["attachments"] == arguments["attachments"]
            and result["permissionMode"] == arguments["mode"] and result["workspaceToolsAllowed"] == (arguments["mode"] != "read-only")
            and result["runtime"] == route[0] and result["route"] == {"runtimeId": route[0], "provider": route[1], "model": route[2], "effort": route[3], "role": "executor"}
            and result["conversationId"] == result["sessionId"] == arguments["conversation_id"]
            and (result["userTurnId"], result["assistantTurnId"]) == arguments["ids"] and result["requestStartedAt"] == arguments["started"], identity, "native payload changed route/permission/turn authority")


def check_opencode_capabilities(ready, result):
    from .connected_sessions.opencode import REASON
    from .connected_sessions.model import Capabilities
    expected = Capabilities(continue_session=ready, new_session=ready, stop=ready, approvals=ready, images=ready, model_choice=ready, permission_choice=ready, billing="OpenCode configured provider", reason=None if ready else REASON)
    require(result == expected, "sessions.opencode.inventory", "observed CLI readiness not projected into capabilities")


def check_opencode_page(observed, result, cursor, before, limit, newest):
    if cursor not in (None, ""):
        try: after = int(cursor)
        except ValueError: after = 0
        selected = [item for item in observed if item.seq > after]
        earlier = False
    else:
        selected = [item for item in observed if before is None or item.seq < before]
        earlier = len(selected) > limit
        selected = selected[-limit:]
    require(result.items == selected and result.has_earlier is earlier and result.cursor == str(newest), "sessions.opencode.inventory", "OpenCode exclusive paging or context cursor differs")


def check_connected_allowlist():
    from .connected_sessions.api import CONNECTED_COMMANDS
    from .desktop_bridge import ALLOWED_DESKTOP_COMMANDS
    require(CONNECTED_COMMANDS <= ALLOWED_DESKTOP_COMMANDS, "sessions.api.allowlist", "connected command missing desktop eligibility")


def check_http_response(status, body, *, result=None, error=None):
    if status == 200:
        require(body == {"ok": True, "data": result}, "sessions.api.response", "success envelope changed dispatch result")
    elif error is not None:
        require(status == error.status and body == error.public(), "sessions.api.response", "refusal lost status, code or owner details")
    elif status == 500:
        require(body.get("ok") is False and body.get("code") == "internal_error" and body.get("error") == body.get("message")
                and len(body["error"]) <= 300 and "Traceback (most recent call last)" not in body["error"], "sessions.api.response", "unexpected failure leaked a traceback or lost code")


def check_sse(event, frame):
    lines = frame.splitlines()
    require(lines[0] == f"id: {event['cursor']}" and json.loads(lines[1].removeprefix("data: ")) == event
            and frame.endswith("\n\n"), "sessions.api.sse", "SSE id/data/framing differs from broker event")


def check_poll(body, wait, result, observed):
    from .connected_sessions.api import MAX_POLL_SECONDS
    events, head, resync = observed
    require(wait == min(MAX_POLL_SECONDS, max(0.0, float(body.get("waitSeconds") or 0)))
            and result == {"events": events, "cursor": head, **({"resync": True} if resync else {})}, "sessions.api.poll", "poll wait bound or event receipt differs")


def check_subscription(broker, token, active):
    from .connected_sessions.broker import MAX_SUBSCRIBERS
    require((token in broker._subscribers) is active and len(broker._subscribers) <= MAX_SUBSCRIBERS,
            "sessions.events.subscription", "subscriber ownership or limit differs")


def check_forward_request(state_root, command, inner, body, base):
    from urllib.parse import urlsplit
    parsed = urlsplit(base)
    require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and 0 < parsed.port < 65536
            and body == {"command": command, "payload": {**inner, "_expectedStateRoot": str(state_root)}}, "sessions.api.forward", "desktop forwarding lost loopback or state-root fence")


def check_forward_result(result):
    if isinstance(result, dict) and result.get("ok") is False:
        require(isinstance(result.get("code"), str) and bool(result["code"]) and isinstance(result.get("message"), str)
                and result.get("error") == result["message"], "sessions.api.forward", "desktop refusal lost code or message envelope")


def _http_procedure(root):
    """Real TCP/HTTP/SSE over a finite in-memory authentication/adapter boundary.

    The product's session-cookie issuer is outside this contract. No password,
    token file, existing backend service or provider account is accessed.
    """
    import http.client
    import threading
    import socket
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit
    from .connected_sessions import api, broker as bm
    os.environ["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    # The real host imports its response helpers before it starts serving.
    from . import web_backend  # noqa: F401
    from .connected_sessions.model import SessionSummary, Capabilities
    from .external_chat_inventory import _host
    host = _host()["deviceId"]
    session = bm.make_session_id("claude-code", host, "http-scratch")
    image = b"\x89PNG\r\n\x1a\nproof-fixture"
    class Boundary:
        mode = "normal"
        stored_goal = None
        media_override = None
        started = threading.Event()
        release = threading.Event()
        def available(self):
            return True, None
        def list_sessions(self, **kwargs):
            return [SessionSummary(id=session, app="claude-code", title="Scratch", cwd=str(root), capabilities=Capabilities(continue_session=True, stop=True))]
        def live_status(self):
            return {}
        def auth(self, *, force=False):
            return {"state": "signed-out", "boundary": "finite account status"}
        def options(self, session_id=None): return {"models": [{"id": "m1"}]}
        def goal(self, session_id, action, text):
            if action == "set": self.stored_goal = {"text": text, "state": "set"}
            if action == "clear": self.stored_goal = None
            return self.stored_goal
        def can_start_new(self): return True, None
        def start_turn(self, session_id, message, options, *, cwd, run_id, emit):
            session_id = session_id or bm.make_session_id("claude-code", host, "http-created-" + run_id)
            emit({"type": "session.created", "sessionId": session_id})
            emit({"type": "item.added", "item": {"id": "http-user", "seq": 1, "kind": "user", "data": {"text": message}}})
            emit({"type": "item.added", "item": {"id": "http-assistant", "seq": 2, "kind": "assistant", "data": {"text": ""}}})
            emit({"type": "item.delta", "itemId": "http-assistant", "textDelta": "Hello"})
            self.started.set()
            if self.mode == "hold": require(self.release.wait(8), "sessions.api.response", "HTTP transport hold timed out")
            return session_id
        def read(self, session_id, *, cursor=None, before_seq=None, limit=200):
            from .connected_sessions.model import Item, ItemsPage, ContextUsage
            if session_id != session:
                raise FileNotFoundError(session_id)
            return ItemsPage(self.list_sessions()[0], [Item("http-read", 1, "assistant", data={"text": "finite receipt", "attachments": [{"id": "png", "kind": "image", "label": "C:/private/scratch.png", "url": "C:/private/scratch.png"}]})], ContextUsage(), cursor="1", has_earlier=False)
        def media(self, session_id, media_id):
            if self.media_override is False: return None
            if isinstance(self.media_override, tuple): return self.media_override
            if media_id == "png":
                return image, "image/png", "scratch.png"
            if media_id == "text":
                return b"scratch", "application/x-proof-fixture", "scratch file.txt"
            raise FileNotFoundError(media_id)
    class Backend:
        username = "proof-owner"
        def __init__(self):
            self.root = root / "http"
            self.root.mkdir()
        def authenticated_session(self, handler):
            value = handler.headers.get("X-Proof-Session")
            if not value and "proof-session=proof-owner" in handler.headers.get("Cookie", ""):
                value = "proof-owner"
            return {"username": value} if value in {"proof-owner", "proof-guest"} else None
        def is_authenticated(self, handler):
            return self.authenticated_session(handler) is not None
        def dispatch(self, command, payload):
            if command == "finite_error":
                raise RuntimeError("finite transport failure")
            if command not in api.CONNECTED_COMMANDS and command != "approval_modes_command":
                raise bm.ConnectedError("unknown_command", "Unknown connected command.", 404)
            return web_backend.FluxioWebBackend.dispatch(self, command, payload)
    backend = Backend()
    boundary = Boundary()
    broker = bm.ConnectedBroker(backend.root, adapters={"claude-code": boundary}, autostart=False, list_ttl=0, start_cursor=0)
    key = os.path.normcase(str(backend.root))
    bm._BROKERS[key] = broker
    stream_threads, stream_lock = set(), threading.Lock()
    def stream_count():
        with stream_lock:
            return len(stream_threads)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args):
            pass
        def do_GET(self):
            parsed = urlsplit(self.path)
            is_stream = parsed.path == "/api/connected/events"
            identity = threading.get_ident()
            if is_stream:
                with stream_lock:
                    stream_threads.add(identity)
            try:
                api.serve_connected_get(backend, self, parsed)
            finally:
                if is_stream:
                    with stream_lock:
                        stream_threads.discard(identity)
        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.path == "/api/auth/local-session":
                # A finite cookie issuer is solely the forwarder's transport
                # boundary; no product account/session authority is claimed.
                raw = json.dumps({"ok": True}).encode()
                self.send_response(200)
                web_backend._apply_security_headers(self)
                self.send_header("Set-Cookie", "proof-session=proof-owner; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if self.path == "/api/auth/logout":
                web_backend._json_response(self, 200, {"ok": True})
                return
            if not backend.is_authenticated(self):
                web_backend._json_response(self, 401, {"ok": False, "loginRequired": True})
                return
            api.respond_connected_command(self, backend, value["command"], value.get("payload", {}))
    # The task explicitly authorizes this one port; never use an ephemeral port.
    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48469)), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, name="proofs-a-http", daemon=True)
    worker.start()
    def request(method, path, *, user=None, value=None, extra=None):
        # New-session admission may wait the broker's documented naming budget.
        # Keep other wire requests at five seconds, including poll wake checks.
        timeout = bm.NEW_SESSION_WAIT_SECONDS + 5 if isinstance(value, dict) and value.get('command') == 'connected_session_new_command' else 5
        connection = http.client.HTTPConnection("127.0.0.1", proof_port(48469), timeout=timeout)
        headers = dict(extra or {})
        if user:
            headers["X-Proof-Session"] = user
        raw = json.dumps(value).encode() if value is not None else None
        if raw is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, raw, headers)
        response = connection.getresponse()
        body = response.read()
        returned = (response.status, dict(response.getheaders()), body)
        connection.close()
        return returned
    def command(name, payload=None, *, user="proof-owner", extra=None):
        status, headers, raw = request("POST", "/api/backend", user=user, value={"command": name, "payload": payload or {}}, extra=extra)
        return status, json.loads(raw)
    streams = []
    try:
        for path in ("/api/connected/events", "/api/connected/events?cursor=1", "/api/connected/media?session=x&media=y", "/api/connected/unknown"):
            status, _, raw = request("GET", path)
            require(status == 401 and json.loads(raw)["loginRequired"] is True, "sessions.api.authority", "anonymous read crossed auth boundary")
        status, body = command("connected_sessions_list_command", user=None)
        require(status == 401 and body["loginRequired"] is True and request("GET", "/api/connected/events", extra={"Cookie": "grand_agent_session=not-a-real-token"})[0] == 401, "sessions.api.authority", "anonymous/forged token crossed command boundary")
        require(command("approval_modes_command")[1]["data"] is not None, "sessions.api.response", "existing native approval command stopped beside connected commands")
        require(request("GET", "/api/connected/unknown", user="proof-owner")[0] == 404 and not broker._subscribers, "sessions.api.authority", "unknown/rejected streams acquired a subscription")
        for name, payload in (("connected_session_send_command", {"id": session, "message": "hello", "requestId": "scratch-guest-0001"}), ("connected_session_new_command", {"app": "claude-code", "cwd": str(root), "message": "hello", "requestId": "scratch-guest-0002"}), ("connected_session_git_action_command", {"id": session, "action": "commit", "message": "x", "confirm": True}), ("connected_folder_clone_command", {"repo": "octo/app", "confirm": True}), ("connected_app_sign_in_command", {"app": "claude-code"}), ("connected_app_sign_in_code_command", {"app": "claude-code", "code": "finite-code"})):
            status, body = command(name, payload, user="proof-guest")
            require((status, body["code"]) == (403, "owner_required"), "sessions.api.authority", "guest mutation crossed owner boundary")
        require(command("connected_app_auth_command", {"app": "claude-code"}, user="proof-guest") == (200, {"ok": True, "data": {"state": "signed-out", "boundary": "finite account status"}}), "sessions.api.authority", "guest auth-status read was treated as sign-in mutation")
        status, body = command("connected_sessions_list_command", user="proof-guest")
        require(status == 200 and body["data"]["sessions"][0]["id"] == session, "sessions.api.authority", "guest lost permitted reads")
        status, body = command("connected_sessions_list_command", extra={"X-Neyvia-Controller": "desktop"})
        require(status == 200 and body["data"]["sessions"][0]["title"] == "Scratch", "sessions.api.response", "desktop header diverted connected command")
        status, body = command("finite_error")
        require(status == 500 and body["code"] == "internal_error" and "Traceback" not in json.dumps(body), "sessions.api.response", "unexpected failure was not a coded envelope")
        status, body = command("connected_session_stop_command", {"runId": "missing"})
        require(status == 404 and body["code"] == "run_not_found" and body["error"] == body["message"], "sessions.api.response", "coded refusal changed status or message")
        status, body = command("connected_sessions_list_command", {"_expectedStateRoot": str(root)})
        require(status == 409 and body["code"] == "wrong_state_root", "sessions.api.state_root", "wrong root was accepted")
        require(command("connected_sessions_list_command", {"_expectedStateRoot": str(backend.root)})[0] == 200,
                "sessions.api.state_root", "matching root was refused")
        require(command("connected_session_bogus_command")[1]["code"] == "unknown_command", "sessions.api.response", "unknown command was accepted")
        require(api.handle_connected_command(backend, "connected_sessions_list_command", None)["total"] == 1, "sessions.api.response", "None body did not use defaults")
        boundary.mode = "hold"
        bad_requests = [("connected_session_send_command", {"id": session, "message": " ", "requestId": "scratch-http-bad-01"}, 400, "invalid_message"),
                        ("connected_session_send_command", {"id": "junk", "message": "x", "requestId": "scratch-http-bad-02"}, 400, "invalid_session"),
                        ("connected_session_send_command", {"id": bm.make_session_id("claude-code", host, "gone"), "message": "x", "requestId": "scratch-http-bad-03"}, 404, "session_not_found")]
        for name, value, expected_status, code in bad_requests:
            status, body = command(name, value)
            require((status, body["code"]) == (expected_status, code) and body["ok"] is False and body["error"] == body["message"], "sessions.api.response", "HTTP send refusal differs")
        started_run = command("connected_session_send_command", {"id": session, "message": "one", "requestId": "scratch-http-busy-01"})[1]["data"]
        require(boundary.started.wait(3), "sessions.api.response", "HTTP busy turn did not start")
        status, body = command("connected_session_send_command", {"id": session, "message": "two", "requestId": "scratch-http-busy-02"})
        require((status, body["code"], body["runId"]) == (409, "session_busy", "scratch-http-busy-01"), "sessions.api.response", "HTTP busy owner identity differs")
        for name, value, expected_status, code in [("connected_session_send_command", {"id": session, "message": "different", "requestId": "scratch-http-busy-01"}, 409, "request_id_conflict"),
                    ("connected_session_stop_command", {"runId": "missing"}, 404, "run_not_found"),
                    ("connected_session_answer_command", {"runId": "scratch-http-busy-01", "requestId": "x", "response": {"decision": "approve"}}, 409, "request_not_pending"),
                    ("connected_session_read_command", {"id": bm.make_session_id("claude-code", host, "gone")}, 404, "session_not_found"),
                    ("connected_provider_options_command", {"app": "nope"}, 400, "invalid_app"),
                    ("connected_sessions_list_command", {"limit": "many"}, 400, "invalid_request")]:
            status, body = command(name, value)
            require((status, body["code"]) == (expected_status, code) and body["ok"] is False and body["error"] == body["message"], "sessions.api.response", "HTTP control refusal differs")
        boundary.release.set()
        deadline = time.monotonic() + 3
        while broker.get_run(started_run["runId"])["state"] != "completed" and time.monotonic() < deadline: time.sleep(.005)
        boundary.mode = "normal"
        require(set(started_run) == {"runId","sessionId","app","state","startedAt","updatedAt","pendingRequest","error","canStop","canSteer","usage","model","effort","permissionMode","promptCharacters","impact","feedback","memoryRecall","memoryWrite","memoryCandidate"}, "sessions.api.response", "current run envelope fields differ")
        require(all(started_run[key] is None or isinstance(started_run[key], dict)
                    for key in ('memoryRecall','memoryWrite','memoryCandidate')),
                'sessions.api.response', 'Memory projection fields have an invalid shape')
        if started_run['memoryRecall'] is not None:
            require(set(started_run['memoryRecall']) == {'selected','generation','route','reason','tokens','generationTokens','latencyMs'},
                    'sessions.api.response', 'Memory recall exposed a body or lost bounded accounting')
        run = command("connected_session_send_command", {"id": session,"message":"hello","requestId":"scratch-http-surface-01","options":{"effort":"low"}})[1]["data"]
        deadline = time.monotonic()+3
        while broker.get_run(run["runId"])["state"] != "completed" and time.monotonic()<deadline:time.sleep(.005)
        page = command("connected_session_read_command", {"id":session,"limit":50})[1]["data"]
        require(page["session"]["id"]==session and page["run"]["runId"]==run["runId"] and "items" in page, "sessions.api.response", "HTTP page lost current run")
        created = command("connected_session_new_command", {"app":"claude-code","cwd":str(root),"message":"start","requestId":"scratch-http-surface-02"})[1]["data"]
        require(created["sessionId"].startswith("external:claude-code:") and command("connected_session_stop_command", {"runId":run["runId"]})[1]["data"]["state"]=="completed", "sessions.api.response", "HTTP new/terminal stop differs")
        require(command("connected_session_goal_command", {"id":session,"action":"set","text":"Ship"})[1]["data"]["goal"]["text"]=="Ship" and command("connected_session_goal_command", {"id":session,"action":"get"})[1]["data"]["goal"]=={"text":"Ship","state":"set"} and command("connected_provider_options_command", {"app":"claude-code"})[1]["data"]["models"][0]["id"]=="m1" and command("connected_session_mark_seen_command", {"id":session,"seq":3})[1]["data"]=={"ok":True}, "sessions.api.response", "HTTP goal/options/seen differs")
        workspace = command("connected_session_workspace_command", {"id":session})[1]["data"]
        require(workspace["exists"] is True and workspace["cwd"]==str(root) and "gh" in workspace, "sessions.api.response", "HTTP selected workspace differs")
        for name,payload,expected_status,code in [("connected_session_file_diff_command",{"id":session,"path":"a.txt"},400,"not_a_repo"),("connected_session_git_action_command",{"id":session,"action":"commit","message":"m"},400,"confirmation_required"),("connected_session_compact_command",{"id":session},409,"not_supported")]:
            status,body=command(name,payload)
            require((status,body["code"])==(expected_status,code), "sessions.api.response", "HTTP workspace/compact refusal differs")
        auth = boundary.auth
        boundary.auth = None
        require(command("connected_app_auth_command", {"app":"claude-code"})[0]==400 and command("connected_app_auth_command", {"app":"claude-code"})[1]["code"]=="unsupported", "sessions.api.response", "missing app auth hook advertised support")
        boundary.auth=auth
        from .desktop_bridge import dispatch_desktop_command
        os.environ["NEYVIA_CONNECTED_SERVICE_PORT"] = proof_text("48469")
        desktop = dispatch_desktop_command(backend.root, "connected_sessions_list_command", {"query": "scratch"})
        require([row["title"] for row in desktop["sessions"]] == ["Scratch"], "sessions.api.forward", "desktop did not read persistent service broker")
        desktop_run = dispatch_desktop_command(backend.root, "connected_session_send_command", {"id": session, "message": "from desktop", "requestId": "scratch-desktop-0001"})
        deadline = time.monotonic() + 3
        while broker.get_run(desktop_run["runId"])["state"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.02)
        require(desktop_run["runId"] == "scratch-desktop-0001" and command("connected_session_read_command", {"id": session})[1]["data"]["run"]["runId"] == desktop_run["runId"], "sessions.api.forward", "desktop/browser broker ownership diverged")
        polled = dispatch_desktop_command(backend.root, "connected_events_poll_command", {"cursor": 0, "waitSeconds": 1})
        require(any(event["type"] == "run.state" and event["runId"] == desktop_run["runId"] for event in polled["events"])
                and polled["cursor"] == broker.head(), "sessions.api.forward", "desktop event stream lost service run")
        missing = bm.make_session_id("claude-code", host, "missing")
        for value in ({"id": missing}, {"payload": {"id": missing}}):
            refused = dispatch_desktop_command(backend.root, "connected_session_read_command", value)
            require(refused["ok"] is False and refused["code"] == "session_not_found" and bool(refused["message"]), "sessions.api.forward", "nested desktop refusal lost code")
        wrong_root = root / "wrong-state"
        wrong_root.mkdir()
        require(dispatch_desktop_command(wrong_root, "connected_sessions_list_command", {})["code"] == "wrong_state_root", "sessions.api.forward", "desktop crossed state-root authority")
        env = dict(os.environ, NEYVIA_CONNECTED_SERVICE_PORT=proof_text("48469"))
        payload = json.dumps({"command": "connected_sessions_list_command", "payload": {}})
        process = subprocess.run([sys.executable, "-m", "grant_agent.desktop_bridge", "--root", str(backend.root)], input=payload, text=True, capture_output=True, env=env, timeout=60,
                                 **__import__("grant_agent.subprocess_utils", fromlist=["hidden_windows_subprocess_kwargs"]).hidden_windows_subprocess_kwargs())
        require(process.returncode == 0 and bool(process.stdout.strip()), "sessions.api.forward",
                f"real bridge process failed ({process.returncode}): {process.stderr[-2000:]}")
        envelope = json.loads(process.stdout)
        require(process.returncode == 0 and envelope["ok"] is True and envelope["data"]["total"] == 1, "sessions.api.forward", "real bridge process lost Tauri envelope")
        poll_head = broker.head()
        timer = threading.Timer(0.3, lambda: broker._publish({"type": "notice", "text": "poll"}))
        timer.start()
        started = time.monotonic()
        status, body = command("connected_events_poll_command", {"cursor": poll_head, "waitSeconds": 10})
        timer.join()
        require(status == 200 and [event["type"] for event in body["data"]["events"]] == ["notice"]
                and body["data"]["cursor"] == poll_head + 1 and "resync" not in body["data"]
                and 0.2 < time.monotonic() - started < 5 and not broker._subscribers, "sessions.api.poll", "actual HTTP poll did not wake and release subscription")
        started = time.monotonic()
        status, body = command("connected_events_poll_command", {"cursor": poll_head + 1, "waitSeconds": 0.4})
        require(status == 200 and body["data"] == {"events": [], "cursor": poll_head + 1}
                and 0.3 < time.monotonic() - started < 3, "sessions.api.poll", "quiet HTTP poll differs")
        saved_cap = api.MAX_POLL_SECONDS
        api.MAX_POLL_SECONDS = 0.3
        try:
            started = time.monotonic()
            require(command("connected_events_poll_command", {"cursor": broker.head(), "waitSeconds": 100})[0] == 200
                    and time.monotonic() - started < 3, "sessions.api.poll", "finite poll cap was ignored")
            require(command("connected_events_poll_command", {"waitSeconds": "soon"})[0] == 400
                    and command("connected_events_poll_command", {"waitSeconds": "soon"})[1]["code"] == "invalid_request", "sessions.api.poll", "invalid poll duration was accepted")
        finally:
            api.MAX_POLL_SECONDS = saved_cap
        from urllib.parse import quote
        base = "/api/connected/media?session=" + quote(session, safe="") + "&media="
        status, headers, data = request("GET", base + "png", user="proof-owner")
        require(status == 200 and data == image and headers["Content-Type"] == "image/png"
                and headers["X-Content-Type-Options"] == "nosniff" and headers["Cache-Control"] == "private, no-store", "sessions.api.media", "image MIME/body/security receipt differs")
        status, headers, data = request("GET", base + "text", user="proof-owner")
        require(status == 200 and data == b"scratch" and headers["Content-Type"] == "application/octet-stream"
                and "attachment;" in headers["Content-Disposition"] and "scratch%20file.txt" in headers["Content-Disposition"], "sessions.api.media", "unknown MIME was not a bounded download")
        import base64
        from .desktop_bridge import ALLOWED_DESKTOP_COMMANDS
        page = command("connected_session_read_command", {"id": session})[1]["data"]
        url = page["items"][0]["data"]["attachments"][0]["url"]
        require(url == base + "png" and "private" not in json.dumps(page["items"]), "sessions.api.media", "read attachment path was not converted to authenticated URL")
        status, headers, data = request("GET", url, user="proof-owner")
        require(status == 200 and data == image and "Content-Disposition" not in headers and request("GET", url)[0] == 401, "sessions.api.media", "image route auth/disposition differs")
        found = command("connected_session_media_command", {"id": session, "mediaRef": "png"})[1]["data"]
        require(base64.b64decode(found["data"]) == image and found["mime"] == "image/png" and "connected_session_media_command" in ALLOWED_DESKTOP_COMMANDS, "sessions.api.media", "desktop media command bytes/allowlist differs")
        actual = dispatch_desktop_command(backend.root, "connected_session_media_command", {"id": session, "mediaRef": "png"})
        require(base64.b64decode(actual["data"]) == image and actual["mime"] == "image/png", "sessions.api.forward", "desktop image did not pass through real loopback")
        boundary.media_override = (b"<html>", "text/html", "page.html")
        status, headers, _ = request("GET", url, user="proof-owner")
        require(status == 200 and headers["Content-Disposition"].startswith("attachment"), "sessions.api.media", "HTML media served inline")
        boundary.media_override = (b"MZ", "application/x-msdownload", "x.exe")
        require(request("GET", url, user="proof-owner")[1]["Content-Type"] == "application/octet-stream", "sessions.api.media", "executable MIME passed through")
        boundary.media_override = False
        status, _, data = request("GET", url, user="proof-owner")
        require(status == 404 and json.loads(data)["code"] == "media_not_found" and command("connected_session_media_command", {"id": session, "mediaRef": "png"})[0] == 404 and request("GET", "/api/connected/media?session=junk&media=x", user="proof-owner")[0] == 400, "sessions.api.media", "missing/invalid media did not refuse")
        boundary.media_override = None
        require(api.CONNECTED_COMMANDS <= ALLOWED_DESKTOP_COMMANDS, "sessions.api.allowlist", "connected/desktop command parity differs")
        cursor = broker.head()
        broker._publish({"type": "notice", "text": "old"})
        connection = http.client.HTTPConnection("127.0.0.1", proof_port(48469), timeout=4)
        streams.append(connection)
        connection.request("GET", "/api/connected/events?cursor=0", headers={"X-Proof-Session": "proof-owner", "Last-Event-ID": str(cursor)})
        response = connection.getresponse()
        require(response.status == 200 and response.getheader("Content-Type").startswith("text/event-stream") and response.getheader("X-Accel-Buffering") == "no", "sessions.api.sse", "SSE headers differ")
        def frame():
            value = {}
            while True:
                line = response.fp.readline().decode("utf-8").strip()
                if not line and value:
                    return value
                if line.startswith("id:"):
                    value["id"] = int(line[3:])
                elif line.startswith("data:"):
                    value["data"] = json.loads(line[5:])
                elif line.startswith(":"):
                    value["comment"] = line[1:].strip()
                elif line.startswith("retry:"):
                    value["retry"] = int(line[6:])
        require(frame() == {"comment": "connected", "retry": 3000}, "sessions.api.sse", "SSE opening frame differs")
        actual = frame()
        require(actual["id"] == cursor + 1 and actual["data"]["text"] == "old", "sessions.api.sse", "Last-Event-ID cursor did not resume")
        broker._publish({"type": "notice", "text": "live"})
        actual = frame()
        require(actual["id"] == cursor + 2 and actual["data"]["text"] == "live", "sessions.api.sse", "live event was not streamed")
        saved_limit = bm.MAX_SUBSCRIBERS
        bm.MAX_SUBSCRIBERS = 1
        try:
            status, _, raw = request("GET", "/api/connected/events", user="proof-owner")
            require(status == 429 and json.loads(raw)["code"] == "too_many_streams", "sessions.events.subscription", "excess HTTP subscriber was not refused")
        finally:
            bm.MAX_SUBSCRIBERS = saved_limit
        response.close()
        connection.close()
        deadline = time.monotonic() + 3
        while broker._subscribers and time.monotonic() < deadline:
            time.sleep(0.02)
        require(not broker._subscribers, "sessions.api.sse", "dropped stream leaked a subscription")
        def open_events(path, extra=None):
            connection = http.client.HTTPConnection("127.0.0.1", proof_port(48469), timeout=4)
            streams.append(connection)
            connection.request("GET", path, headers={"X-Proof-Session": "proof-owner", **(extra or {})})
            response = connection.getresponse()
            require(response.status == 200, "sessions.api.sse", "stream could not reconnect")
            return connection, response
        replay_head = broker.head()
        for number in range(4):
            broker._publish({"type": "notice", "number": number})
        connection, response = open_events(f"/api/connected/events?cursor={replay_head + 2}")
        frame()
        require([frame()["id"], frame()["id"]] == [replay_head + 3, replay_head + 4], "sessions.api.sse", "query cursor replay differs")
        response.close()
        connection.close()
        connection, response = open_events(f"/api/connected/events?cursor={replay_head + 1}", {"Last-Event-ID": str(replay_head + 4)})
        frame()
        broker._publish({"type": "notice", "number": "new"})
        require(frame()["id"] == replay_head + 5, "sessions.api.sse", "header did not override stale query cursor")
        response.close()
        connection.close()
        saved_events = broker.events.max_events
        broker.events.max_events = 3
        for number in range(10):
            broker._publish({"type": "notice", "number": number})
        stale_head = broker.head()
        require(command("connected_events_poll_command", {"cursor": 0, "waitSeconds": 5})[1]["data"] == {"events": [], "cursor": stale_head, "resync": True}
                and command("connected_events_poll_command")[1]["data"]["cursor"] == stale_head, "sessions.api.poll", "stale/no-cursor poll differs")
        connection, response = open_events("/api/connected/events?cursor=1")
        frame()
        resync = frame()
        require(resync == {"id": stale_head, "data": {"type": "resync", "cursor": stale_head}}, "sessions.api.sse", "stale stream did not resync to head")
        broker._publish({"type": "notice", "number": "after"})
        require(frame()["data"]["number"] == "after", "sessions.api.sse", "resynced stream replayed old history")
        response.close()
        connection.close()
        connection, response = open_events("/api/connected/events?cursor=999999")
        frame()
        require(frame()["data"]["type"] == "resync", "sessions.api.sse", "ahead cursor did not resync")
        response.close()
        connection.close()
        broker.events.max_events = saved_events
        deadline = time.monotonic() + 3
        while broker._subscribers and time.monotonic() < deadline:
            time.sleep(0.02)
        saved_limit = bm.MAX_SUBSCRIBERS
        bm.MAX_SUBSCRIBERS = 2
        try:
            with broker.subscription(), broker.subscription():
                try:
                    with broker.subscription():
                        pass
                except bm.ConnectedError as error:
                    require((error.code, error.status) == ("too_many_streams", 429), "sessions.events.subscription", "third nested subscriber refusal differs")
                else:
                    require(False, "sessions.events.subscription", "subscriber budget crossed")
            with broker.subscription():
                pass
        finally:
            bm.MAX_SUBSCRIBERS = saved_limit
        deadline = time.monotonic() + 3
        while (broker._subscribers or stream_count()) and time.monotonic() < deadline: time.sleep(.02)
        require(not broker._subscribers and stream_count() == 0, "sessions.events.subscription", "earlier owned streams did not close")
        dropped = []
        for _ in range(4):
            connection, response = open_events("/api/connected/events")
            require(frame() == {"comment": "connected", "retry": 3000}, "sessions.api.sse", "dropped stream opening differs")
            dropped.append((connection, response))
        require(len(broker._subscribers) == 4 and stream_count() == 4, "sessions.events.subscription", "four stream thread ownership differs")
        for connection, response in dropped: response.close(); connection.close()
        deadline = time.monotonic() + 8
        while (broker._subscribers or stream_count()) and time.monotonic() < deadline: time.sleep(.02)
        require(not broker._subscribers and stream_count() == 0, "sessions.events.subscription", "dropped stream thread/subscriber leaked")
        connection, response = open_events("/api/connected/events")
        frame()
        response.fp.close()
        response.fp = None
        response.close()
        if connection.sock: connection.sock.close()
        connection.close()
        deadline = time.monotonic() + 8
        while broker._subscribers and time.monotonic() < deadline: time.sleep(.02)
        require(not broker._subscribers, "sessions.events.subscription", "vanished client retained subscriber")
        for _ in range(3): broker._publish({"type": "notice"})
        connection, response = open_events("/api/connected/events")
        require(response.getheader("Cache-Control").startswith("no-cache") and frame() == {"comment": "connected", "retry": 3000}, "sessions.api.sse", "new stream cache/start differs")
        require(len(broker._subscribers) == 1, "sessions.events.subscription", "live stream not owned")
        require(command("connected_session_send_command", {"id": session, "message": "hi", "requestId": "scratch-http-stream-01"})[0] == 200, "sessions.api.sse", "HTTP turn could not start")
        frames = []
        while len(frames) < 30:
            value = frame()
            frames.append(value)
            if value.get("data", {}).get("state") == "completed":
                break
        events = [value["data"] for value in frames if "data" in value]
        require([value["id"] for value in frames if "id" in value] == [event["cursor"] for event in events]
                and [event["cursor"] for event in events] == sorted(event["cursor"] for event in events)
                and [event["state"] for event in events if event["type"] == "run.state"] == ["queued", "running", "completed"]
                and "Hello" in [event.get("textDelta") for event in events] and all(event["hostDeviceId"] for event in events), "sessions.api.sse", "real HTTP turn SSE ordering/identity differs")
        saved_heartbeat = api.HEARTBEAT_SECONDS
        api.HEARTBEAT_SECONDS = 0.2
        try:
            while True:
                value = frame()
                if value.get("comment") == "heartbeat":
                    require(value == {"comment": "heartbeat"}, "sessions.api.sse", "heartbeat frame differs")
                    break
        finally:
            api.HEARTBEAT_SECONDS = saved_heartbeat
        response.close()
        connection.close()
        connection, response = open_events("/api/connected/events")
        frame()
        broker.close()
        require(response.fp.readline() == b"", "sessions.api.sse", "broker close did not end stream")
        response.close()
        connection.close()
        deadline = time.monotonic() + 3
        while broker._subscribers and time.monotonic() < deadline:
            time.sleep(0.02)
        require(not broker._subscribers, "sessions.events.subscription", "stream close did not release subscriber")
    finally:
        broker.close()
        for stream in streams:
            stream.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        bm._BROKERS.pop(key, None)
    offline = dispatch_desktop_command(backend.root, "connected_sessions_list_command", {})
    require(offline["ok"] is False and offline["code"] == "pc_service_offline" and "not running" in offline["message"] and offline["error"] == offline["message"], "sessions.api.forward", "closed owned service did not return offline receipt")
    process = subprocess.run([sys.executable, "-m", "grant_agent.desktop_bridge", "--root", str(backend.root)], input=payload, text=True, capture_output=True, env=env, timeout=60,
                             **__import__("grant_agent.subprocess_utils", fromlist=["hidden_windows_subprocess_kwargs"]).hidden_windows_subprocess_kwargs())
    envelope = json.loads(process.stdout)
    require(envelope["ok"] is True and envelope["data"]["code"] == "pc_service_offline" and envelope["data"]["ok"] is False, "sessions.api.forward", "offline bridge failure moved outside Tauri data envelope")
    identities = ["sessions.api.authority", "sessions.api.response", "sessions.api.state_root", "sessions.api.media", "sessions.api.sse", "sessions.api.poll", "sessions.events.subscription", "sessions.api.forward", "sessions.api.allowlist"]
    return identities, [{"contract": identity, "ok": True} for identity in identities], [{"contract": "sessions.api.authority", "rejected": True}, {"contract": "sessions.api.state_root", "rejected": True}]


def _native_observer_procedure(root):
    from types import SimpleNamespace
    from .neyvia_conversations import NeyviaConversationStore
    from .connected_sessions.neyvia import NeyviaAdapter, conversation_runtime, classify
    from . import agent_questions
    store_root = root / "native-observer"
    store_root.mkdir()
    store = NeyviaConversationStore(store_root)
    backend = SimpleNamespace(root=store_root, neyvia_mcp=SimpleNamespace(conversations=store))
    adapter = NeyviaAdapter(backend)
    def timestamp(number):
        return f"2026-09-29T10:00:{number:02d}.000000Z"
    def seed(cid, *, runtime="neyvia-agent", exchanges=1, number=1, workspace="", metadata=None):
        # Avoid last-connection WAL checkpoints for every fixture turn.
        # Production calls retain independent FULL commits; close before reads.
        with store._connection():
            store.create_conversation(conversation_id=cid, title=cid.capitalize() + " conversation", workspace_id=workspace, now=timestamp(number), metadata=metadata or {})
            for ordinal in range(exchanges):
                turn_metadata = {"runtime": runtime} if runtime else {}
                store.append_turn(cid, role="user", content="question " + str(ordinal), turn_id=f"{cid}-u{ordinal}", now=timestamp(number + ordinal * 2), metadata=turn_metadata)
                result = {"runtime": runtime, "status": "completed"} if runtime else {"status": "completed"}
                store.append_turn(cid, role="assistant", content="answer " + str(ordinal), turn_id=f"{cid}-a{ordinal}", now=timestamp(number + ordinal * 2 + 1), metadata={"runtimeResult": result})
    vectors = [({"runtimeId": value}, expected) for value, expected in (("neyvia-agent", ("native", "neyvia-agent")), ("Neyvia", ("native", "neyvia-agent")), ("own", ("native", "neyvia-agent")), ("codex", ("hybrid", "codex")), ("claude_code", ("hybrid", "claude-code")), ("fluxio-hybrid", ("hybrid", "fluxio-hybrid")))]
    vectors += [({"metadata": {"route": {"runtimeId": "hermes"}}}, ("hybrid", "hermes")),
                ({"metadata": {"runtime": "neyvia-agent"}}, ("native", "neyvia-agent")),
                ({"metadata": {"routeSnapshot": {"planner": {"runtimeId": "codex"}, "worker": {"runtimeId": "codex"}}}}, ("hybrid", "codex")),
                ({"metadata": {"routeSnapshot": {"planner": {"runtimeId": "codex"}, "worker": {"runtimeId": "hermes"}}}}, ("hybrid", None)),
                ({"runtimeId": "", "metadata": {}}, ("native", None)), ({}, ("native", None))]
    for row, expected in vectors:
        require(classify(conversation_runtime(row=row)) == expected, "sessions.neyvia.category", "runtime category vector differs")
    seed("native")
    seed("hybrid", runtime="codex", number=5)
    seed("unlabeled", runtime=None, number=9)
    store.create_conversation(conversation_id="titled-empty", title="Written but nothing sent", now=timestamp(20))
    store.create_conversation(conversation_id="hidden-shell", now=timestamp(21))
    rows = {row.id: row for row in adapter.list_sessions()}
    sid = adapter._sid
    require(sid("hidden-shell") not in rows and rows[sid("native")].title == "Native conversation"
            and rows[sid("native")].created_at == timestamp(1)
            and (rows[sid("native")].category, rows[sid("native")].runtime) == ("native", "neyvia-agent")
            and (rows[sid("hybrid")].category, rows[sid("hybrid")].runtime) == ("hybrid", "codex")
            and (rows[sid("unlabeled")].category, rows[sid("unlabeled")].runtime) == ("native", None)
            and rows[sid("titled-empty")].category == "native", "sessions.neyvia.summary", "empty/unlabeled/classified chat listing differs")
    control = store_root / ".agent_control"
    control.mkdir(exist_ok=True)
    (control / "workspaces.json").write_text(json.dumps([{"workspace_id": "workspace-a", "name": "Registered project", "root_path": str(store_root / "registered")}]), encoding="utf-8")
    seed("registered", workspace="workspace-a", number=23)
    seed("own-folder", metadata={"workspacePath": str(store_root / "elsewhere" / "app")}, number=26)
    seed("nowhere", number=29)
    rows = {row.id: row for row in adapter.list_sessions()}
    require((rows[sid("registered")].project, rows[sid("registered")].cwd) == ("Registered project", str(store_root / "registered"))
            and (rows[sid("own-folder")].project, rows[sid("own-folder")].cwd) == ("app", str(store_root / "elsewhere" / "app"))
            and (rows[sid("nowhere")].project, rows[sid("nowhere")].cwd) == (None, None), "sessions.neyvia.summary", "workspace registry or metadata precedence lost")
    for ordinal, name in enumerate(("idle", "settled", "asks", "approval", "failed", "old")):
        seed(name, number=ordinal * 6 + 1)
    store.settle_conversation("settled", settlement_reason="done")
    agent_questions.request_question(store_root, "asks", "Choose database", ["sqlite", "postgres"])
    with store._connection() as connection:
        connection.execute("UPDATE conversations SET metadata_json = ? WHERE conversation_id = ?", (json.dumps({"hasBlockingApproval": True}), "approval"))
        connection.execute("UPDATE conversations SET status = 'failed' WHERE conversation_id = ?", ("failed",))
        connection.execute("UPDATE conversations SET archived_at = ? WHERE conversation_id = ?", (timestamp(50), "old"))
        connection.commit()
    store.create_conversation(conversation_id="plan", kind="orchestration", title="Two workers", now=timestamp(40), metadata={"executionRoot": str(store_root)})
    store.create_concurrency_plan("plan", tasks=[{"id": "n1", "objective": "one", "runtime": "codex"}, {"id": "n2", "objective": "two", "runtime": "codex"}])
    rows = {row.id: row for row in adapter.list_sessions(include_archived=True)}
    require([rows[sid(name)].status for name in ("idle", "settled", "asks", "approval", "failed")] == ["idle", "idle", "waiting_input", "waiting_approval", "failed"]
            and rows[sid("old")].archived and not rows[sid("idle")].archived
            and sid("old") not in {row.id for row in adapter.list_sessions()}
            and (rows[sid("plan")].category, rows[sid("plan")].runtime) == ("hybrid", "codex")
            and not rows[sid("plan")].capabilities.continue_session and "orchestration" in rows[sid("plan")].capabilities.reason.lower()
            and rows[sid("plan")].cwd == str(store_root), "sessions.neyvia.summary", "attention/archive/orchestration view differs")
    seed("history", exchanges=12, number=0)
    newest = adapter.read(sid("history"), limit=6)
    require([item.id for item in newest.items] == [f"history-{kind}{number}" for number in (9, 10, 11) for kind in "ua"] and newest.has_earlier, "sessions.neyvia.page", "tail page window changed")
    older = adapter.read(sid("history"), before_seq=newest.items[0].seq, limit=6)
    require([item.id for item in older.items] == [f"history-{kind}{number}" for number in (6, 7, 8) for kind in "ua"]
            and older.items[-1].seq < newest.items[0].seq, "sessions.neyvia.page", "older page overlaps newest")
    seen = []
    before = None
    while True:
        page = adapter.read(sid("history"), before_seq=before, limit=7)
        seen = [item.id for item in page.items] + seen
        before = page.items[0].seq
        if not page.has_earlier:
            break
    require(seen == [f"history-{kind}{number}" for number in range(12) for kind in "ua"], "sessions.neyvia.page", "backward paging duplicates or loses history")
    store.append_turn("history", role="user", content="one more", turn_id="history-new", now=timestamp(58))
    fresh = adapter.read(sid("history"), cursor=newest.cursor)
    require([item.id for item in fresh.items] == ["history-new"] and int(fresh.cursor) > int(newest.cursor)
            and adapter.read(sid("history"), cursor=fresh.cursor).items == [], "sessions.neyvia.page", "incremental page duplicates old history")
    from .connected_sessions.neyvia_items import tool_item, tool_category, ordinal_of
    categories = [("terminal.exec", "command"), ("neyvia_workspace_read", "read"), ("workspace.read", "read"), ("workspace.write", "edit"),
                  ("workspace.search", "search"), ("web.search", "web"), ("workspace.browser", "web"), ("neyvia_situation", "web"),
                  ("preview.screenshot", "web"), ("neyvia_goal", "agent"), ("neyvia_ask_user", "agent"), ("neyvia_tools_search", "search"),
                  ("neyvia_tools_describe", "search"), ("semantic.memory.find", "search"), ("codex.plugins.list", "search"), ("codex.assets.inspect", "read"),
                  ("mcp.github.create_issue", "mcp"), ("runtime.environment", "other"), ("neyvia_access_context", "other"), ("neyvia_native_call", "other")]
    for name, category in categories:
        require(tool_category(name=name) == category, "sessions.neyvia.tools", "named tool category differs")
    command = tool_item({"tool": "terminal.exec", "status": "completed", "input": json.dumps({"command": "dir"}), "error": "", "output": json.dumps({"ok": True, "status": "completed", "duration_ms": 1759, "toolResult": {"exitCode": 2, "stdout": "listing", "stderr": "a warning"}})}, "x", 1, None, finished=True)
    reading = tool_item({"tool": "workspace.read", "status": "completed", "input": json.dumps({"path": "a.c"}), "error": "", "output": json.dumps({"ok": True, "result": {"path": "a.c", "content": "int main() {}"}})}, "y", 2, None, finished=True)
    require((command.data["output"], command.data["exitCode"], command.data["durationMs"]) == ("listing\na warning", 2, 1759)
            and (reading.data["output"], reading.data["files"]) == ("int main() {}", ["a.c"]), "sessions.neyvia.tools", "readable nested tool result differs")
    receipt = {"reasoningSummary": "Legacy summary.", "toolTimeline": [
        {"at": timestamp(2), "kind": "runtime.progress", "summary": "Compacting saved conversation automatically", "status": "recorded"},
        {"at": timestamp(2), "kind": "runtime.progress", "summary": "Conversation compacted; continuing", "status": "recorded"},
        {"at": timestamp(2), "kind": "runtime.progress", "summary": "Continuing active goal: finish", "status": "recorded"}],
        "activitySegments": [{"kind": "reasoning_summary", "id": "reasoning-1", "text": "Let me look at the file."},
        {"kind": "tool", "callId": "call-a", "tool": "terminal.exec", "status": "completed", "input": json.dumps({"command": "Get-Content big.txt\nWrite-Output done"}), "output": "x" * 20_000},
        {"kind": "thinking_text", "id": "hidden", "text": "raw reasoning tokens"},
        {"kind": "thinking_text", "id": "provider", "text": "Provider reasoning text.", "source": "provider.reasoning_content"},
        {"kind": "tool", "callId": "call-b", "tool": "neyvia_workspace_read", "status": "failed", "input": json.dumps({"path": "src/app.py"}), "error": "File is locked."},
        {"kind": "tool", "callId": "call-c", "tool": "workspace.search", "status": "started", "input": json.dumps({"query": "TODO"})}]}
    store.create_conversation(conversation_id="mapping", title="Mapping", now=timestamp(0))
    store.append_turn("mapping", role="user", content="Read big.txt", turn_id="mapped-u1", now=timestamp(1), metadata={"runtime": "neyvia-agent", "attachments": [{"name": "notes.png", "mime": "image/png", "size": 3, "sha256": "a"}]})
    store.append_turn("mapping", role="assistant", content="Here is **the file**.", turn_id="mapped-a1", now=timestamp(2), source="backend-runtime-reply", metadata={"runtimeResult": {"runtime": "neyvia-agent", "status": "completed", "route": {"provider": "openai-codex", "model": "gpt-5.6-sol"}, "compartment": {"turnReceipt": receipt}}})
    store.append_turn("mapping", role="user", content="Now with Codex", turn_id="mapped-u2", now=timestamp(3), metadata={"runtime": "codex"})
    store.append_turn("mapping", role="assistant", content="Codex answers.", turn_id="mapped-a2", now=timestamp(4), metadata={"runtimeResult": {"runtime": "codex", "status": "completed", "route": {"provider": "openai-codex", "model": "gpt-5.6-luna"}}})
    store.append_turn("mapping", role="assistant", content="The executor failed.", turn_id="mapped-a3", now=timestamp(5), source="backend-runtime-error", metadata={"runtimeResult": {"runtime": "codex", "status": "failed", "route": {"provider": "openai-codex", "model": "gpt-5.6-luna"}}})
    store.append_turn("mapping", role="assistant", content="heartbeat", turn_id="mapped-hb", now=timestamp(6), meaningful=False, turn_kind="heartbeat")
    page = adapter.read(sid("mapping"))
    require([(entry.kind, entry.id) for entry in page.items] == [("user", "mapped-u1"), ("compaction", "mapped-a1#compaction-1"), ("reasoning", "mapped-a1#reasoning-1"), ("tool", "mapped-a1#tool-call-a"), ("reasoning", "mapped-a1#reasoning-2"), ("tool", "mapped-a1#tool-call-b"), ("tool", "mapped-a1#tool-call-c"), ("assistant", "mapped-a1"), ("user", "mapped-u2"), ("notice", "mapped-a2#route"), ("assistant", "mapped-a2"), ("notice", "mapped-a3#outcome")], "sessions.neyvia.items", "full native transcript projection differs")
    by_id = {item.id: item.data for item in page.items}
    require(by_id["mapped-u1"]["attachments"] == [{"id": "", "kind": "image", "label": "notes.png", "url": None, "mime": "image/png"}]
            and by_id["mapped-a1"]["text"] == "Here is **the file**." and by_id["mapped-a1"]["model"] == "gpt-5.6-sol"
            and by_id["mapped-a1#compaction-1"]["state"] == "completed" and "compacted" in by_id["mapped-a1#compaction-1"]["text"]
            and by_id["mapped-a1#reasoning-1"] == {"summary": "Let me look at the file.", "hidden": False}
            and by_id["mapped-a1#reasoning-2"]["summary"] == "Provider reasoning text.", "sessions.neyvia.items", "attachment, answer, compaction or provider reasoning projection differs")
    command, failed, stuck = by_id["mapped-a1#tool-call-a"], by_id["mapped-a1#tool-call-b"], by_id["mapped-a1#tool-call-c"]
    require((command["category"], command["status"], command["name"], command["title"], command["input"]) == ("command", "ok", "terminal.exec", "Get-Content big.txt", "Get-Content big.txt Write-Output done")
            and len(command["output"]) == 8192 and command["outputTruncated"] is True
            and (failed["category"], failed["status"], failed["output"], failed["files"]) == ("read", "error", "File is locked.", ["src/app.py"])
            and (stuck["category"], stuck["status"]) == ("search", "error") and "No result" in stuck["note"]
            and by_id["mapped-a2#route"] == {"text": "Now running on Codex with GPT-5.6 Luna.", "level": "info"}
            and by_id["mapped-a3#outcome"] == {"text": "The executor failed.", "level": "error"}
            and page.session.title == "Mapping" and (page.session.category, page.session.runtime) == ("hybrid", "codex")
            and page.context.used_tokens is None and page.context.window_tokens is None and page.has_earlier is False, "sessions.neyvia.items", "native tool/status/route/context receipt differs")
    try:
        adapter.read(sid("missing"))
    except FileNotFoundError:
        pass
    else:
        require(False, "sessions.neyvia.page", "missing native conversation became readable")
    busy_receipt = {"activitySegments": [{"kind": "tool", "callId": f"c{number}", "tool": "workspace.read", "status": "completed", "input": json.dumps({"path": f"f{number}.txt"}), "output": "ok"} for number in range(120)]}
    store.create_conversation(conversation_id="busy", title="Busy", now=timestamp(0))
    store.append_turn("busy", role="user", content="many tools", turn_id="busy-u", now=timestamp(1))
    store.append_turn("busy", role="assistant", content="done", turn_id="busy-a", now=timestamp(2), metadata={"runtimeResult": {"runtime": "neyvia-agent", "status": "completed", "compartment": {"turnReceipt": busy_receipt}}})
    busy = adapter.read(sid("busy"))
    answer_items = [item for item in busy.items if ordinal_of(item.seq) == 1]
    require([item.seq % 100 for item in answer_items] == list(range(100)) and sum(item.kind == "tool" for item in answer_items) == 98
            and answer_items[-2].data["text"] == "22 more activity rows are not shown." and answer_items[-1].kind == "assistant", "sessions.neyvia.items", "busy native turn lost slot bound or omission notice")
    return ["sessions.neyvia.summary", "sessions.neyvia.page", "sessions.neyvia.tools", "sessions.neyvia.items"]


def _codex_mapping_procedure(root):
    from .connected_sessions import codex_items as ci
    from .connected_chat_media import descriptors
    base_ms = 1_780_000_000_000
    def turn_id(ms):
        stamp = f"{ms:012x}"
        return stamp[:8] + "-" + stamp[8:] + "-7000-8000-000000000001"
    require(ci.uuid7_ms(turn_id(base_ms)) == base_ms and ci.uuid7_ms("f50a3e61-0bd0-4421-af87-2a5a9f2cc32c") is None,
            "sessions.codex.sequence", "turn clock accepted UUIDv4 or changed UUIDv7 timestamp")
    turns = [{"id": turn_id(base_ms + ordinal), "status": "completed", "items": [
        {"type": "userMessage", "id": f"u{ordinal}", "content": [{"type": "text", "text": "hello"}]},
        {"type": "agentMessage", "id": f"a{ordinal}", "text": "reply"}]} for ordinal in range(2)]
    items = ci.map_turns(turns=turns, ordinals={turn["id"]: ordinal for ordinal, turn in enumerate(turns)})
    require([ci.ordinal_from_seq(entry.seq) for entry in items] == [0, 0, 0, 1, 1, 1]
            and [entry.kind for entry in items] == ["user", "assistant", "reasoning"] * 2
            and len({entry.seq for entry in items}) == 6
            and ci.make_seq(3, 2047, 3) < ci.make_seq(4, 0)
            and ci.make_seq(5, 3) < ci.make_seq(5, 3, 1) < ci.make_seq(5, 4), "sessions.codex.sequence", "turn/page sequence identity collides")
    mapped = ci.map_thread_item(item={"type": "agentMessage", "id": "big", "text": "x" * 100_000}, seq=1, at=None)
    require(mapped[0].data["truncated"] is True and len(json.dumps(mapped[0].public())) < 64_000, "sessions.codex.text", "mapped message is not bounded")
    questions = {"questions": [{"id": str(number), "header": "h" * 4000, "question": "q" * 4000,
                   "options": [{"label": "l" * 300, "description": "d" * 1000}] * 30,
                   "isOther": False, "isSecret": False} for number in range(20)]}
    require(len(json.dumps(ci.public_request("item/tool/requestUserInput", questions, "1:2"))) < 64_000, "sessions.codex.text", "question envelope not fitted")
    changes = [{"path": "C:/scratch/a.txt", "kind": {"type": "update"}, "diff": "@@ -1,2 +1,3 @@\n keep\n-old\n+new\n+more\n"},
               {"path": "C:/scratch/b.txt", "kind": {"type": "add"}, "diff": "one\ntwo\nthree"},
               {"path": "C:/scratch/c.txt", "kind": {"type": "delete"}, "diff": "gone\n"}]
    diff = ci.diff_from_changes(changes=changes, cwd="C:/scratch")
    require([(entry["path"], entry["additions"], entry["deletions"]) for entry in diff["files"]] == [("a.txt", 2, 1), ("b.txt", 3, 0), ("c.txt", 0, 1)]
            and "+++ b/b.txt" in diff["patch"] and "+two" in diff["patch"], "sessions.codex.diff", "change types lost unified patch/counts")
    bounded = ci.diff_from_changes([{"path": "x", "kind": {"type": "add"}, "diff": "line\n" * 100_000}], limit=2000)
    require(bounded["truncated"] is True and bounded["files"][0]["additions"] == 100_000, "sessions.codex.diff", "bounded patch lost full-file counts")
    modes = ci.permission_modes()
    for mode in (None, "invalid", "ask", "auto", "full"):
        ci.turn_permission_params(mode_id=mode)
        ci.thread_permission_params(mode_id=mode)
    for approval, sandbox in (("never", "danger-full-access"), ("on-request", "read-only"), ("on-request", "workspace-write"), (None, None)):
        ci.permission_mode_for(approval_policy=approval, sandbox_mode=sandbox)
    require(len(modes) == 3, "sessions.codex.permissions", "permission catalogue incomplete")
    forms = [
        ("item/commandExecution/requestApproval", {}), ("item/fileChange/requestApproval", {}),
        ("item/permissions/requestApproval", {"permissions": {"network": {"enabled": True}, "fileSystem": None}}),
        ("item/tool/requestUserInput", {"questions": [{"id": "a"}, {"id": "b"}]}),
        ("mcpServer/elicitation/request", {"mode": "form", "requestedSchema": {"properties": {"n": {"type": "integer"}, "ok": {"type": "boolean"}}}}),
        ("mcpServer/elicitation/request", {"mode": "url"}), ("unknown", {})]
    for method, params in forms:
        for decision in ("approve", "deny", "cancel", "invalid", None):
            ci.server_request_result(method=method, params=params, response={"decision": decision, "answers": {"a": "x", "n": "3", "ok": "true"}})
    ref = "data:image/png;base64,AAAA"
    require(ci.media_token(ref=ref) == descriptors("scratch", [ref])[0]["id"], "sessions.codex.media", "chat and session media identity diverged")
    for path in ("C:/scratch/.agent_control/runs/a", "C:/scratch/.agent_control", "C:/scratch/proof/x", "C:/scratch/evidence-bundle", "C:/scratch/my-Harness-run", "C:/scratch/.sandbox-scratch/codex-live", "C:/scratch/AppData/Local/Temp/neyvia-abc", "C:/Temp/neyvia-run/work", "C:/scratch/AppData/Local/Temp/other", "C:/scratch/tmp/tmp0462cpk0"):
        require(ci.classify_origin(cwd=path) == "neyvia-harness", "sessions.codex.origin", "automation origin vector differs")
    for path in ("C:/scratch/project", "C:/scratch/Documents/Codex/a-b", "", None):
        require(ci.classify_origin(cwd=path) == "user", "sessions.codex.origin", "user origin vector differs")
    directory = root / "codex-rollouts"
    directory.mkdir()
    now = time.time()
    for number, (markers, age, expected) in enumerate([(["task_started"], 5, True), (["task_started"], 1200, True), (["task_started"], 2400, False), (["task_started", "task_complete"], 5, False), (["task_started", "turn_aborted"], 5, False), (["task_started", "task_complete", "task_started"], 5, True)]):
        path = directory / f"marker-{number}.jsonl"
        path.write_text("\n".join(json.dumps({"type": "event_msg", "payload": {"type": marker, "turn_id": "scratch-turn", "started_at": now - 100}}) for marker in markers) + "\n", encoding="utf-8")
        os.utime(path, (now - age, now - age))
        require(ci.rollout_activity(path=path, now=now)["inProgress"] is expected, "sessions.codex.rollout", "persisted terminal/stale marker differs")
    require(ci.rollout_activity(directory / "missing.jsonl")["inProgress"] is False, "sessions.codex.rollout", "missing rollout became active")
    large = directory / "outside-tail.jsonl"
    filler = json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "output": "x" * 4000}}) + "\n"
    large.write_text(json.dumps({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "outside", "started_at": now - 60}}) + "\n" + filler * 2500, encoding="utf-8")
    reads = []
    reader = ci.read_tail_rows
    def observed_tail(path, max_bytes):
        reads.append(max_bytes)
        return reader(path, max_bytes)
    ci.read_tail_rows = observed_tail
    try:
        require(ci.rollout_activity(large)["inProgress"] is True and max(reads) <= ci.ROLLOUT_TAIL_STEPS[-1], "sessions.codex.rollout", "unreadable marker did not use fresh bounded activity")
        os.utime(large, (now - 600, now - 600))
        require(ci.rollout_activity(large, now=now)["inProgress"] is False, "sessions.codex.rollout", "old unmarked file remained active")
    finally:
        ci.read_tail_rows = reader
    return ["sessions.codex.diff", "sessions.codex.permissions", "sessions.codex.requests", "sessions.codex.media", "sessions.codex.origin", "sessions.codex.rollout"]


def _opencode_inventory_procedure(root):
    import sqlite3
    from . import external_chat_inventory as inventory
    from .connected_sessions.opencode import create_adapter, REASON
    from .connected_sessions.opencode_acp import command
    from .connected_sessions.broker import ConnectedBroker, ConnectedError
    directory, project = root / "opencode-data", root / "opencode-project"
    directory.mkdir(); project.mkdir()
    former_path, former_data = os.environ.get("PATH"), os.environ.get("OPENCODE_DATA_DIR")
    # A confined, initially empty PATH is a finite CLI discovery boundary.
    binaries = root / "opencode-bin"
    binaries.mkdir()
    os.environ["PATH"] = str(binaries)
    os.environ["OPENCODE_DATA_DIR"] = str(directory)
    inventory._INVENTORY_CACHE.clear()
    adapter = create_adapter(root)
    broker = None
    try:
        require(command() is None and adapter.available() == (False, "OpenCode has no local sessions on this PC."), "sessions.opencode.inventory", "empty inventory/CLI did not report unavailable")
        with sqlite3.connect(directory / "opencode.db") as db:
            db.executescript("CREATE TABLE session(id TEXT PRIMARY KEY,title TEXT,directory TEXT,time_created INTEGER,time_updated INTEGER); CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,data TEXT,time_created INTEGER); CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,data TEXT,time_created INTEGER);")
            db.execute("INSERT INTO session VALUES ('ses_1','Investigate slow build',?,1770000000000,1770000100000)", (str(project),))
            for number, (role, text) in enumerate((("user", "why is the build slow?"),("assistant", "The bundler re-runs."),("user", "fix it"),("assistant", "Done.")), 1):
                db.execute("INSERT INTO message VALUES (?,?,?,?)", (f"m{number}","ses_1",json.dumps({"role":role}),1770000000000+number))
                db.execute("INSERT INTO part VALUES (?,?,?,?)", (f"p{number}",f"m{number}",json.dumps({"type":"text","text":text}),1770000000000+number))
        inventory._INVENTORY_CACHE.clear()
        require(adapter.available() == (True,None), "sessions.opencode.inventory", "actual local SQLite did not make history available")
        row, = adapter.list_sessions()
        require(row.app == "opencode" and row.title == "Investigate slow build" and row.cwd == str(project) and row.project == project.name and not row.capabilities.continue_session and row.capabilities.reason == REASON and row.capabilities.billing == "OpenCode configured provider" and adapter.live_status() == {}, "sessions.opencode.inventory", "local history/read-only capabilities differ")
        page = adapter.read(row.id)
        visible = [item for item in page.items if item.kind != "reasoning"]
        require([(item.kind,item.data["text"]) for item in visible] == [("user","why is the build slow?"),("assistant","The bundler re-runs."),("user","fix it"),("assistant","Done.")]
                and [(item.seq,item.kind) for item in page.items] == [(1,"user"),(2,"reasoning"),(3,"assistant"),(4,"user"),(5,"reasoning"),(6,"assistant")]
                and all(item.data.get("hidden") is True and item.data.get("exposure")=="not_reported" and item.data.get("summary") is None for item in page.items if item.kind=="reasoning") and page.cursor=="6" and page.has_earlier is False, "sessions.opencode.inventory", "native history texts or truthful missing-reasoning notices differ")
        require([item.seq for item in adapter.read(row.id,limit=2).items]==[5,6] and adapter.read(row.id,limit=2).has_earlier is True and [item.seq for item in adapter.read(row.id,before_seq=3).items]==[1,2] and [item.seq for item in adapter.read(row.id,cursor="2").items]==[3,4,5,6], "sessions.opencode.inventory", "saved native pages overlap or omit history")
        try:adapter.read(row.id.rsplit(":",1)[0]+":nope")
        except FileNotFoundError:pass
        else:require(False,"sessions.opencode.inventory","missing history accepted")
        broker=ConnectedBroker(root/"opencode-broker",adapters={"opencode":adapter},autostart=False)
        listed=broker.list_sessions()["sessions"][0]
        require(listed["capabilities"]["continue_session"] is False and listed["capabilities"]["reason"]==REASON and broker.read(row.id)["items"][0]["data"]["text"]=="why is the build slow?", "sessions.opencode.inventory", "broker read-only inventory differs")
        for expected,operation in (("cannot_continue",lambda:broker.send(row.id,"hi","scratch-opencode-01")),("cannot_start",lambda:broker.new("opencode",str(project),"hi","scratch-opencode-02"))):
            try:operation()
            except ConnectedError as error:require(error.code==expected and (expected!="cannot_continue" or error.message==REASON),"sessions.opencode.inventory","read-only refusal lost reason")
            else:require(False,"sessions.opencode.inventory","read-only history executed")
        # Discovery sees only disposable marker files. No CLI execution or
        # external subscription/account claim is made for this readiness branch.
        (binaries/"opencode.cmd").write_text("@exit /b 0\n",encoding="utf-8")
        native=binaries/"node_modules/opencode-ai/bin/opencode.exe"
        native.parent.mkdir(parents=True);native.write_bytes(b"finite native executable presence marker")
        require(command()==str(native),"sessions.opencode.inventory","native command presence not discovered")
        capabilities=adapter.capabilities()
        require(capabilities.continue_session and capabilities.new_session and capabilities.stop and capabilities.approvals and capabilities.images and capabilities.model_choice and capabilities.permission_choice and capabilities.reason is None and capabilities.billing=="OpenCode configured provider", "sessions.opencode.inventory", "present native CLI did not enable conditional capabilities")
    finally:
        if broker:broker.close()
        if former_path is None:os.environ.pop("PATH",None)
        else:os.environ["PATH"]=former_path
        if former_data is None:os.environ.pop("OPENCODE_DATA_DIR",None)
        else:os.environ["OPENCODE_DATA_DIR"]=former_data
        inventory._INVENTORY_CACHE.clear()
    return ["sessions.opencode.inventory"]


def _broker_recovery_procedure(root):
    import sqlite3
    import threading
    from .connected_sessions.broker import ConnectedBroker, ConnectedError, make_session_id
    from .connected_sessions.model import SessionSummary, Capabilities, TurnOptions
    from .connected_sessions.runs import request_fingerprint, iso
    from .chat_run_control import process_started_at
    from .external_chat_inventory import _host
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    session = make_session_id("claude-code", _host()["deviceId"], "recovery")
    class Boundary:
        def __init__(self, hold=False):
            self.calls = []
            self.hold = hold
            self.started, self.release = threading.Event(), threading.Event()
        def available(self): return True, None
        def list_sessions(self, **kwargs): return [SessionSummary(session, "claude-code", "Recovery", capabilities=Capabilities(continue_session=True, stop=True))]
        def live_status(self): return {}
        def start_turn(self, session_id, message, options, **kwargs):
            self.calls.append((session_id, message))
            self.started.set()
            if self.hold: require(self.release.wait(10), "sessions.run.recovery", "recovery boundary hold timed out")
            return session_id
        def interrupt(self, run_id): self.release.set()
    directory = root / "recovery"
    first = ConnectedBroker(directory, adapters={}, autostart=False)
    first.close()
    def insert(run_id, given, pid, started, fingerprint="bounded-recovery-observation"):
        stamp = iso(time.time())
        data = {"runId": run_id, "sessionId": given, "app": "claude-code", "state": "running", "startedAt": stamp, "updatedAt": stamp, "pendingRequest": None, "error": None, "canStop": True, "canSteer": False}
        with sqlite3.connect(directory / ".agent_control" / "connected_chats.sqlite3") as db:
            db.execute("INSERT INTO connected_session_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (run_id, given, "claude-code", fingerprint, "running", pid, "previous-owner", started, time.time(), time.time(), json.dumps(data)))
    # Only child processes owned by this scratch procedure are inspected.
    dead = subprocess.Popen([sys.executable, "-I", "-c", "pass"], **hidden_windows_subprocess_kwargs())
    dead.wait(timeout=10)
    insert("scratch-dead-01", session, dead.pid, time.time() - 60, request_fingerprint("send", session, "hi", TurnOptions()))
    boundary = Boundary()
    broker = ConnectedBroker(directory, adapters={"claude-code": boundary}, autostart=False, start_cursor=0)
    def settled(owner, run_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = owner.get_run(run_id)
            if result["state"] == "completed": return result
            time.sleep(.005)
        require(False, "sessions.run.recovery", "recovery turn did not complete")
    try:
        run = broker.get_run("scratch-dead-01")
        require(run["state"] == "interrupted" and "did not resend" in run["error"] and run["canStop"] is False and [event["state"] for event in broker.events_since(0)[0] if event["type"] == "run.state"] == ["interrupted"], "sessions.run.recovery", "dead owner not durably interrupted")
        require(broker.send(session, "hi", "scratch-dead-01")["state"] == "interrupted" and not boundary.calls, "sessions.run.recovery", "recovered request resent")
        run = broker.send(session, "hi", "scratch-dead-02")
        require(run["sessionId"] == session, "sessions.run.recovery", "recovery retained session lock")
        settled(broker, run["runId"])
    finally: broker.close()
    live = subprocess.Popen([sys.executable, "-I", "-c", "import sys; sys.stdin.buffer.read(1)"], stdin=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
    try:
        started = process_started_at(live.pid)
        require(started is not None, "sessions.run.recovery", "owned child start identity not observable")
        insert("scratch-alive-01", session, live.pid, started)
        broker = ConnectedBroker(directory, adapters={"claude-code": Boundary()}, autostart=False)
        try:
            require(broker.get_run("scratch-alive-01")["state"] == "running", "sessions.run.recovery", "live owner interrupted")
            try: broker.send(session, "hi", "scratch-alive-02")
            except ConnectedError as error: require(error.code == "session_busy", "sessions.run.recovery", "live owner lost session lock")
            else: require(False, "sessions.run.recovery", "live owner session reused")
            reused = make_session_id("claude-code", _host()["deviceId"], "reused")
            insert("scratch-reused-01", reused, live.pid, started - 50000)
            second = ConnectedBroker(directory, adapters={}, autostart=False)
            try: require(second.get_run("scratch-reused-01")["state"] == "interrupted", "sessions.run.recovery", "recycled process identity accepted")
            finally: second.close()
        finally: broker.close()
    finally:
        live.stdin.write(b"x"); live.stdin.flush(); live.stdin.close(); live.wait(timeout=10)
    held = Boundary(hold=True)
    first = ConnectedBroker(root / "same-process", adapters={"claude-code": held}, autostart=False)
    second_boundary = Boundary()
    second = None
    try:
        run = first.send(session, "hi", "scratch-restart-01")
        require(held.started.wait(3), "sessions.run.recovery", "first broker did not start")
        second = ConnectedBroker(first.root, adapters={"claude-code": second_boundary}, autostart=False)
        require(second.get_run(run["runId"])["state"] == "interrupted" and second.send(session, "hi", "scratch-restart-01")["state"] == "interrupted" and not second_boundary.calls, "sessions.run.recovery", "earlier broker in same process replayed")
    finally:
        held.release.set()
        first.close()
        if second: second.close()
    return ["sessions.run.recovery"]


def _broker_controls_procedure(root):
    import dataclasses
    import threading
    import types
    from .connected_sessions import registry as registry_module
    from .connected_sessions.broker import ConnectedBroker, ConnectedError, make_session_id
    from .connected_sessions.model import SessionSummary, Capabilities
    from .external_chat_inventory import _host
    host = _host()["deviceId"]
    sid = lambda app, value: make_session_id(app, host, value)
    session, other = sid("claude-code", "control"), sid("claude-code", "other")
    class Boundary:
        app = "claude-code"
        def __init__(self, app="claude-code", rows=None):
            self.app = app
            self.rows = rows if rows is not None else [SessionSummary(session, app, "Controls", capabilities=Capabilities(continue_session=True, stop=True)), SessionSummary(other, app, "Other", capabilities=Capabilities(continue_session=True, stop=True))]
            self.mode = "normal"
            self.calls, self.interrupts, self.answers, self.steered = [], [], [], []
            self.started, self.release = threading.Event(), threading.Event()
            self.live = {}
            self.saved_goal = None
        def available(self): return True, None
        def list_sessions(self, **kwargs): return self.rows
        def live_status(self): return self.live
        def read(self, *args, **kwargs): raise FileNotFoundError
        def options(self, session_id=None): return {"models": [{"id": "m1"}], "observedSession": session_id}
        def goal(self, session_id, action, text):
            if action == "set": self.saved_goal = {"text": text, "state": "set"}
            if action == "clear": self.saved_goal = None
            return self.saved_goal
        def start_turn(self, session_id, message, options, *, cwd, run_id, emit):
            self.calls.append((session_id, message, run_id))
            actual = session_id or sid(self.app, "created-" + run_id)
            if session_id is None: emit({"type": "session.created", "sessionId": actual})
            if self.mode == "approval":
                emit({"type": "run.state", "state": "waiting_approval", "pendingRequest": {"requestId": "control-approval", "choices": ["approve", "deny"]}})
            self.started.set()
            if self.mode in ("hold", "approval"):
                require(self.release.wait(15), "sessions.run.lifecycle", "control transport hold timed out")
            return actual
        def interrupt(self, run_id):
            self.interrupts.append(run_id)
            self.release.set()
        def answer(self, run_id, request_id, response):
            self.answers.append((run_id, request_id, response))
            self.release.set()
        def can_start_new(self): return True, None
    class Coded(RuntimeError):
        def __init__(self, code, message, owner=None):
            super().__init__(message)
            self.code, self.owner = code, owner
    boundary = Boundary()
    broker = ConnectedBroker(root / "controls", adapters={"claude-code": boundary}, autostart=False, list_ttl=0, idle_watchdog_seconds=600, start_cursor=0)
    def await_state(run_id, state):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            record = broker.get_run(run_id)
            if record["state"] == state: return record
            time.sleep(.005)
        require(False, "sessions.run.lifecycle", "control run failed to settle to " + state)
    def refusal(code, call):
        try: call()
        except ConnectedError as error:
            require(error.code == code, "sessions.broker.refusals", "control refusal lost code: " + error.code)
            return error
        require(False, "sessions.broker.refusals", "invalid control accepted")
    def reset(mode):
        boundary.mode = mode
        boundary.started.clear()
        boundary.release.clear()
    try:
        require(broker.goal(session, "get") == {"goal": None, "supported": True}, "sessions.broker.controls", "goal state not empty")
        require(broker.goal(session, "set", "Ship it")["goal"] == {"text": "Ship it", "state": "set"} and broker.goal(session, "clear")["goal"] is None, "sessions.broker.controls", "goal hook mutation lost")
        refusal("invalid_request", lambda: broker.goal(session, "set", ""))
        refusal("invalid_request", lambda: broker.goal(session, "explode"))
        boundary.goal = None
        require(broker.goal(session, "get") == {"goal": None, "supported": False}, "sessions.broker.controls", "missing goal advertised support")
        refusal("not_supported", lambda: broker.goal(session, "set", "x"))
        refusal("not_supported", lambda: broker.compact(session))
        boundary.rows[0] = dataclasses.replace(boundary.rows[0], capabilities=Capabilities(continue_session=True, compact=True, stop=True))
        broker._invalidate_lists()
        run = broker.compact(session)
        await_state(run["runId"], "completed")
        require(run["runId"].startswith("compact-") and boundary.calls[-1][1] == "/compact", "sessions.broker.controls", "compact fallback differs")
        boundary.compact = lambda session_id, *, run_id, emit: session_id
        hooked = broker.compact(session)
        await_state(hooked["runId"], "completed")
        require(len(boundary.calls) == 1, "sessions.broker.controls", "compact hook still sent slash command")
        require(broker.provider_options("claude-code")["models"][0]["id"] == "m1" and broker.provider_options("claude-code", session)["observedSession"] == session, "sessions.broker.controls", "provider options lost arguments")
        refusal("invalid_app", lambda: broker.provider_options("nope"))
        def busy(session_id): raise Coded("session_live_elsewhere", "The app has a turn open.", owner="app")
        boundary.check_send = busy
        error = refusal("session_live_elsewhere", lambda: broker.send(session, "hi", "scratch-control-pre-01"))
        require((error.status, error.extra, error.message) == (409, {"owner": "app"}, "The app has a turn open.") and len(boundary.calls) == 1, "sessions.broker.refusals", "preflight dispatched or changed refusal")
        boundary.check_send = lambda session_id: None
        await_state(broker.send(session, "hi", "scratch-control-pre-02")["runId"], "completed")
        def broken(session_id): raise RuntimeError("no code")
        boundary.check_send = broken
        boundary.live[other] = ("working", "cli")
        require(refusal("session_live_elsewhere", lambda: broker.send(other, "hi", "scratch-control-pre-03")).extra["owner"] == "cli", "sessions.broker.refusals", "broken preflight lost live fallback")
        boundary.live.clear()
        calls = []
        def preflight(session_id):
            calls.append(session_id)
            if session_id == session: raise Coded("session_live_elsewhere", "Open in desktop (idle).", owner={"kind": "interactive", "owner": "app", "pid": 4242, "status": "idle", "name": None})
        boundary.preflight = preflight
        error = refusal("session_live_elsewhere", lambda: broker.send(session, "hi", "scratch-control-owner-01"))
        require(error.extra["owner"] == "app" and error.extra["ownerDetail"]["pid"] == 4242, "sessions.broker.refusals", "owner detail lost")
        await_state(broker.send(other, "hi", "scratch-control-owner-02")["runId"], "completed")
        await_state(broker.new("claude-code", str(root), "start", "scratch-control-owner-03")["runId"], "completed")
        require(calls == [session, other, None], "sessions.broker.refusals", "new session not preflighted")
        def unavailable(session_id): raise Coded("cli_unavailable", "CLI missing.")
        boundary.preflight = unavailable
        refusal("cli_unavailable", lambda: broker.new("claude-code", str(root), "start", "scratch-control-owner-04"))
        boundary.preflight = lambda session_id: None
        reset("approval")
        run = broker.send(session, "ask", "scratch-control-retry-01")
        await_state(run["runId"], "waiting_approval")
        answer = boundary.answer
        def failed(*args): raise RuntimeError("adapter is busy")
        boundary.answer = failed
        refusal("answer_failed", lambda: broker.answer(run["runId"], "control-approval", {"decision": "deny"}))
        boundary.answer = answer
        broker.answer(run["runId"], "control-approval", {"decision": "deny"})
        await_state(run["runId"], "completed")
        require(len(boundary.answers) == 1, "sessions.broker.controls", "failed answer burned request")
        reset("approval")
        run = broker.send(session, "ask", "scratch-control-coded-01")
        await_state(run["runId"], "waiting_approval")
        def expired(*args): raise Coded("request_expired", "Stopped before answer.")
        boundary.answer = expired
        require(refusal("request_expired", lambda: broker.answer(run["runId"], "control-approval", {"decision": "approve"})).status == 409, "sessions.broker.refusals", "coded answer status lost")
        def no_goal(*args): raise Coded("goal_required", "Write goal first.")
        boundary.goal = no_goal
        require(refusal("goal_required", lambda: broker.goal(other, "set", "x")).status == 400, "sessions.broker.refusals", "coded goal status lost")
        interrupt = boundary.interrupt
        def closed(*args): raise RuntimeError("pipe closed")
        boundary.interrupt = closed
        error = refusal("stop_failed", lambda: broker.stop(run["runId"]))
        require(error.status == 502 and "pipe closed" in error.message, "sessions.broker.refusals", "stop failure lost diagnostic")
        boundary.release.set()
        await_state(run["runId"], "cancelled")
        refusal("request_not_pending", lambda: broker.answer(run["runId"], "control-approval", {"decision": "deny"}))
        boundary.interrupt, boundary.answer = interrupt, answer
        reset("hold")
        boundary.rows[0] = dataclasses.replace(boundary.rows[0], capabilities=Capabilities(continue_session=True, stop=True, steer=True))
        broker._invalidate_lists()
        boundary.steer = lambda run_id, message: boundary.steered.append((run_id, message))
        run = broker.send(session, "work", "scratch-control-steer-01")
        require(boundary.started.wait(3) and run["canSteer"] is True, "sessions.broker.controls", "steer capability not projected")
        require(broker.steer(run["runId"], "also do this")["runId"] == run["runId"] and boundary.steered == [(run["runId"], "also do this")], "sessions.broker.controls", "steer hook not called once")
        refusal("invalid_message", lambda: broker.steer(run["runId"], "  "))
        plain = broker.send(other, "work", "scratch-control-steer-02")
        require(plain["canSteer"] is False, "sessions.broker.controls", "unsupported steer advertised")
        refusal("not_supported", lambda: broker.steer(plain["runId"], "more"))
        boundary.release.set()
        await_state(run["runId"], "completed")
        await_state(plain["runId"], "completed")
        refusal("run_not_active", lambda: broker.steer(run["runId"], "too late"))
        reset("hold")
        run = broker.send(session, "quiet", "scratch-watchdog-01")
        require(boundary.started.wait(3), "sessions.run.watchdog", "quiet turn not started")
        broker.tick(now=time.monotonic() + 300)
        require(broker.get_run(run["runId"])["state"] == "running", "sessions.run.watchdog", "watchdog interrupted recent output")
        broker.tick(now=time.monotonic() + 700)
        require(broker.get_run(run["runId"])["state"] == "interrupted" and "No output for 10 minutes" in broker.get_run(run["runId"])["error"], "sessions.run.watchdog", "silent turn not interrupted")
        deadline = time.monotonic() + 3
        while run["runId"] not in boundary.interrupts and time.monotonic() < deadline: time.sleep(.005)
        require(run["runId"] in boundary.interrupts and [e["state"] for e in broker.events_since(0)[0] if e["type"] == "run.state"][-1] == "interrupted", "sessions.run.watchdog", "watchdog did not interrupt transport and publish")
        reset("approval")
        run = broker.send(other, "ask", "scratch-watchdog-02")
        await_state(run["runId"], "waiting_approval")
        broker.tick(now=time.monotonic() + 100000)
        require(broker.get_run(run["runId"])["state"] == "waiting_approval", "sessions.run.watchdog", "waiting approval was timed out")
        broker.answer(run["runId"], "control-approval", {"decision": "approve"})
        await_state(run["runId"], "completed")
    finally:
        boundary.release.set()
        broker.close()
    prior_idle = os.environ.get("NEYVIA_CONNECTED_IDLE_SECONDS")
    os.environ["NEYVIA_CONNECTED_IDLE_SECONDS"] = "60"
    default = ConnectedBroker(root / "watchdog-default", adapters={}, autostart=False)
    try: require(default.idle_watchdog_seconds == 1800, "sessions.run.watchdog", "default watchdog below thirty minutes")
    finally:
        default.close()
        if prior_idle is None: os.environ.pop("NEYVIA_CONNECTED_IDLE_SECONDS", None)
        else: os.environ["NEYVIA_CONNECTED_IDLE_SECONDS"] = prior_idle
    # Registry imports and factories are a finite transport-loading boundary.
    # Neither provider account status nor an installed provider is claimed.
    original_import = registry_module.importlib.import_module
    original_factories = dict(registry_module.FACTORIES)
    backend = object()
    opened = []
    try:
        received = []
        local = ConnectedBroker(root / "registered", backend=backend, adapters={}, load_defaults=False, autostart=False)
        opened.append(local)
        def native_factory(given):
            received.append(given)
            return Boundary("neyvia", [SessionSummary(sid("neyvia", "native"), "neyvia", "Native chat", category="native")])
        local.register_adapter("neyvia", native_factory)
        def broken_factory(given): raise ZeroDivisionError("division by zero")
        local.register_adapter("codex", broken_factory)
        listed = local.list_sessions()
        require(received == [backend] and [row["title"] for row in listed["sessions"]] == ["Native chat"] and "could not start" in next(source for source in listed["sources"] if source["app"] == "codex")["reason"], "sessions.broker.registry", "registered backend factory failed")
        calls = {}
        def lazy_import(name, package=None):
            leaf = name.rsplit(".", 1)[-1]
            if leaf in ("claude", "neyvia"):
                module = types.ModuleType(leaf)
                def create_adapter(argument):
                    calls[leaf] = argument
                    return Boundary("claude-code" if leaf == "claude" else "neyvia", [])
                module.create_adapter = create_adapter
                return module
            if name.startswith("grant_agent.connected_sessions."): raise ModuleNotFoundError("No module named " + name, name=name)
            return original_import(name, package)
        registry_module.FACTORIES.clear()
        registry_module.importlib.import_module = lazy_import
        lazy_root = root / "lazy"
        lazy = ConnectedBroker(lazy_root, backend=backend, autostart=False)
        opened.append(lazy)
        lazy.list_sessions()
        require(calls == {"claude": lazy_root, "neyvia": backend}, "sessions.broker.registry", "lazy adapter argument differs")
        registry_module.register_adapter("codex", lambda given: Boundary("codex", [SessionSummary(sid("codex", "z"), "codex", "Global")]))
        # Return no catalogue from lazy modules in this second broker.
        second = ConnectedBroker(root / "global", backend=backend, autostart=False)
        opened.append(second)
        require([row["app"] for row in second.list_sessions()["sessions"]] == ["codex"], "sessions.broker.registry", "global factory not observed")
        registry_module.FACTORIES.clear()
        def broken_import(name, package=None):
            leaf = name.rsplit(".", 1)[-1]
            if leaf == "claude": raise ModuleNotFoundError("No module named " + name, name=name)
            if leaf == "codex": raise RuntimeError("codex exploded on import")
            if leaf == "neyvia": return types.ModuleType("neyvia")
            if leaf == "opencode":
                module = types.ModuleType("opencode")
                module.create_adapter = lambda root: types.SimpleNamespace(app="opencode")
                return module
            return original_import(name, package)
        registry_module.importlib.import_module = broken_import
        missing = ConnectedBroker(root / "missing", autostart=False)
        opened.append(missing)
        listed = missing.list_sessions()
        reasons = {source["app"]: source["reason"] for source in listed["sources"]}
        require(listed["sessions"] == [] and not any(source["available"] for source in listed["sources"]) and "not part of this build" in reasons["claude-code"] and "codex exploded on import" in reasons["codex"] and "no create_adapter" in reasons["neyvia"] and "incomplete" in reasons["opencode"] and "missing" in reasons["opencode"], "sessions.broker.registry", "missing/broken module catalogue differs")
        try: missing.send(sid("claude-code", "x"), "hi", "scratch-missing-01")
        except ConnectedError as error: require((error.code, error.status) == ("adapter_unavailable", 503), "sessions.broker.registry", "missing adapter refusal differs")
        else: require(False, "sessions.broker.registry", "missing adapter accepted send")
    finally:
        registry_module.importlib.import_module = original_import
        registry_module.FACTORIES.clear(); registry_module.FACTORIES.update(original_factories)
        for owned in opened: owned.close()
    # Actual ambient adapter event sink and close ownership.
    sink_boundary = Boundary()
    sinks, closed = [], []
    sink_boundary.set_event_sink = sinks.append
    sink_boundary.close = lambda: closed.append(True)
    ambient = ConnectedBroker(root / "ambient", adapters={"claude-code": sink_boundary}, autostart=False, start_cursor=0)
    try:
        require(len(sinks) == 1, "sessions.broker.controls", "adapter sink not wired")
        sinks[0]({"type": "session.updated", "session": {"id": session, "title": "Renamed"}})
        sinks[0]({"type": "item.added", "sessionId": "native-thread", "item": {"id": "i", "seq": 4, "kind": "assistant", "data": {"output": "x" * 20000}}})
        sinks[0]("not an event"); sinks[0]({"no": "type"})
        events = ambient.events_since(0)[0]
        require([event["type"] for event in events] == ["session.updated", "item.added"] and events[1]["sessionId"] == sid("claude-code", "native-thread") and events[1]["hostDeviceId"] == host, "sessions.broker.controls", "ambient event identity/stamping differs")
    finally: ambient.close()
    require(closed == [True], "sessions.broker.controls", "adapter close not owned exactly once")
    return ["sessions.broker.controls", "sessions.broker.refusals", "sessions.broker.registry", "sessions.run.watchdog"]


def _broker_catalogue_procedure(root):
    import dataclasses
    import threading
    from .connected_sessions.broker import ConnectedBroker, ConnectedError, make_session_id
    from .connected_sessions.model import SessionSummary, Capabilities, Item, ItemsPage, ContextUsage
    from .external_chat_inventory import _host
    host = _host()["deviceId"]
    def sid(app, name):
        return make_session_id(app, host, name)
    def row(app, name, title, **values):
        return SessionSummary(id=sid(app, name), app=app, title=title, capabilities=Capabilities(continue_session=True, stop=True), **values)
    class InventoryBoundary:
        def __init__(self, rows):
            self.rows = {row.id: row for row in rows}
            self.list_count = self.live_count = 0
            self.live = {}
            self.error = None
            self.availability = (True, None)
            self.started, self.release = threading.Event(), threading.Event()
        def available(self):
            return self.availability
        def list_sessions(self, **kwargs):
            self.list_count += 1
            if self.error:
                raise self.error
            return list(self.rows.values())
        def live_status(self):
            self.live_count += 1
            return self.live
        def read(self, session_id, **kwargs):
            return ItemsPage(self.rows[session_id], [Item("observed", 3, "assistant", data={"text": "recorded"})], ContextUsage(), cursor="3", has_earlier=False)
        def start_turn(self, session_id, message, options, *, cwd, run_id, emit):
            self.started.set()
            require(self.release.wait(8), "sessions.run.lifecycle", "catalogue transport hold timed out")
            return session_id
        def interrupt(self, run_id):
            self.release.set()
    claude = InventoryBoundary([row("claude-code", "c1", "Fix login bug", updated_at="2026-03-01T10:00:00Z", cwd=str(root)),
                                row("claude-code", "c2", "Old chat", updated_at="2026-01-01T00:00:00Z", archived=True),
                                row("claude-code", "c3", "Proof run", updated_at="2026-02-15T00:00:00Z", origin="neyvia-harness")])
    codex = InventoryBoundary([row("codex", "x1", "Refactor parser", updated_at="2026-02-01T00:00:00Z", git_branch="feat/parse"), row("codex", "x2", "No time yet", updated_at=None)])
    native = InventoryBoundary([row("neyvia", "n1", "Plan the launch", updated_at="2026-04-01T00:00:00Z", category="native", runtime="neyvia-agent")])
    adapters = {"claude-code": claude, "codex": codex, "neyvia": native}
    directory = root / "catalogue"
    broker = ConnectedBroker(directory, adapters=adapters, autostart=False, list_ttl=0, start_cursor=0)
    def titles(**arguments):
        return [row["title"] for row in broker.list_sessions(**arguments)["sessions"]]
    def refusal(code, callback):
        try:
            callback()
        except ConnectedError as error:
            require(error.code == code, "sessions.broker.catalogue", "catalogue/control refusal lost code")
            return error
        require(False, "sessions.broker.catalogue", "invalid catalogue/control call accepted")
    try:
        listed = broker.list_sessions()
        require(titles() == ["Plan the launch", "Fix login bug", "Refactor parser", "No time yet"] and listed["total"] == 4 and listed["nextOffset"] is None and listed["cursor"] == broker.head()
                and listed["host"] == {key: broker.host[key] for key in ("deviceId", "deviceName")} and {source["app"]: source["available"] for source in listed["sources"]} == {"claude-code": True, "codex": True, "opencode": False, "neyvia": True}
                and next(source for source in listed["sources"] if source["app"] == "opencode")["reason"]
                and all(row["unread"] is False and row["host_device_id"] == host for row in listed["sessions"])
                and {row["category"] for row in listed["sessions"]} == {"connected", "native"}, "sessions.broker.catalogue", "merged catalogue default shape differs")
        require("Old chat" in titles(include_archived=True) and "Proof run" not in titles(include_archived=True)
                and "Proof run" in titles(include_harness=True) and titles(app="codex") == ["Refactor parser", "No time yet"]
                and titles(app="claude") == ["Fix login bug"] and titles(query="LOGIN") == ["Fix login bug"]
                and titles(query="feat/parse") == ["Refactor parser"] and titles(category="native") == ["Plan the launch"]
                and titles(category="connected") == ["Fix login bug", "Refactor parser", "No time yet"], "sessions.broker.catalogue", "archive/harness/app/query/category filters differ")
        page = broker.list_sessions(limit=2)
        require(len(page["sessions"]) == 2 and page["nextOffset"] == 2 and page["total"] == 4 and titles(limit=2, offset=2) == ["Refactor parser", "No time yet"], "sessions.broker.catalogue", "catalogue pages lose rows")
        refusal("invalid_app", lambda: broker.list_sessions(app="bogus"))
        refusal("invalid_category", lambda: broker.list_sessions(category="bogus"))
        sid1 = sid("claude-code", "c1")
        def unread():
            return next(row["unread"] for row in broker.list_sessions()["sessions"] if row["id"] == sid1)
        require(unread() is False, "sessions.broker.unread", "existing history was marked unread")
        broker.read(sid1)
        require(broker.mark_seen(sid1, 3) == {"ok": True} and unread() is False, "sessions.broker.unread", "seen marker did not acknowledge history")
        claude.rows[sid1] = dataclasses.replace(claude.rows[sid1], updated_at="2026-06-01T00:00:00Z")
        require(unread() is True, "sessions.broker.unread", "new observed activity not unread")
        broker.read(sid1)
        broker.mark_seen(sid1, 4)
        require(unread() is False, "sessions.broker.unread", "new seen timestamp not acknowledged")
        broker._remember_seq(sid1, 9)
        require(unread() is True, "sessions.broker.unread", "streamed seq not unread")
        refusal("invalid_session", lambda: broker.mark_seen("nonsense", 1))
        reopened = ConnectedBroker(directory, adapters=adapters, autostart=False, list_ttl=0)
        try:
            require(reopened.seen.get(sid1)["seq"] == 4, "sessions.broker.unread", "seen marker did not survive service restart")
        finally:
            reopened.close()
        claude.live[sid1] = ("working", "app")
        broker.tick()
        require(claude.live_count == 0, "sessions.broker.catalogue", "unsubscribed broker polled provider")
        with broker.subscription():
            head = broker.head()
            broker.tick()
            require(claude.live_count == 1 and broker.head() == head, "sessions.broker.catalogue", "first provider poll emitted false changes")
            broker.tick()
            require(claude.live_count == 1, "sessions.broker.catalogue", "provider polled faster than interval")
            claude.live[sid1] = ("idle", None)
            broker.tick(now=time.monotonic() + 3)
            changes = [event for event in broker.events_since(head)[0] if event["type"] == "session.updated"]
            require(len(changes) == 1 and changes[0]["session"]["id"] == sid1 and changes[0]["session"]["status"] == "idle" and changes[0]["session"]["live_owner"] is None, "sessions.broker.catalogue", "provider status transition lost session identity")
            other = sid("claude-code", "c2")
            claude.live[other] = ("working", "app")
            broker.tick(now=time.monotonic() + 6)
            require([event["session"]["id"] for event in broker.events_since(head)[0] if event["type"] == "session.updated"][-1] == other, "sessions.broker.catalogue", "other provider session update missing")
            del claude.live[other]
            run = broker.send(other, "mine", "scratch-catalogue-owned")
            require(claude.started.wait(3), "sessions.run.lifecycle", "owned turn not started")
            overlay = next(row for row in broker.list_sessions(include_archived=True)["sessions"] if row["id"] == other)
            require(overlay["status"] == "working" and overlay["live_owner"] == "neyvia", "sessions.broker.catalogue", "owned run not overlaid onto inventory")
            after = broker.head()
            claude.live[other] = ("working", "neyvia")
            broker.tick(now=time.monotonic() + 9)
            require(not [event for event in broker.events_since(after)[0] if event["type"] == "session.updated" and event["session"]["id"] == other], "sessions.broker.catalogue", "poll duplicated owned run updates")
            claude.release.set()
            deadline = time.monotonic() + 3
            while broker.get_run(run["runId"])["state"] != "completed" and time.monotonic() < deadline:
                time.sleep(0.01)
            # Clear the external snapshot and expire its previous overlay before
            # checking the adapter's original unknown status after this run.
            broker._live_overlay.pop(other, None)
            overlay = next(row for row in broker.list_sessions(include_archived=True)["sessions"] if row["id"] == other)
            require(overlay["status"] == "unknown" and overlay["live_owner"] is None, "sessions.broker.catalogue", "terminal run retained ownership overlay")
        require(not broker._subscribers, "sessions.events.subscription", "provider polling subscription leaked")
    finally:
        claude.release.set()
        broker.close()
    for adapter in adapters.values():
        adapter.list_count = 0
    cached = ConnectedBroker(root / "catalogue-cache", adapters=adapters, autostart=False, list_ttl=60)
    try:
        cached.list_sessions()
        cached.list_sessions(query="x")
        cached.list_sessions(app="codex")
        require(codex.list_count == claude.list_count == 1, "sessions.broker.catalogue", "filtered read bypassed shared catalogue cache")
        cached.list_sessions(force=True)
        require(codex.list_count == 2, "sessions.broker.catalogue", "forced read failed to refresh")
    finally:
        cached.close()
    claude.rows[sid1] = dataclasses.replace(claude.rows[sid1], updated_at="2026-03-01T10:00:00Z")
    codex.error = RuntimeError("database is locked")
    failing = ConnectedBroker(root / "catalogue-failure", adapters=adapters, autostart=False, list_ttl=0)
    try:
        data = failing.list_sessions()
        source = next(row for row in data["sources"] if row["app"] == "codex")
        require([row["app"] for row in data["sessions"]] == ["neyvia", "claude-code"]
                and source["available"] is False and source["state"] == "offline"
                and source["reason"] == "Codex couldn't be read right now."
                and "database is locked" in source["detail"], "sessions.broker.catalogue",
                "one failing provider hid other inventories or leaked its exception into visible copy")
        codex.error = None
        require(len(failing.list_sessions()["sessions"]) == 4, "sessions.broker.catalogue", "provider failed to recover")
        codex.error = RuntimeError("blip")
        stale = failing.list_sessions()
        problem=next(row for row in stale["sources"] if row["app"] == "codex")
        require(len(stale["sessions"]) == 4 and problem["reason"] == "Codex couldn't be read right now."
                and "blip" in problem["detail"], "sessions.broker.catalogue",
                "transient provider failure erased stale history or leaked raw visible copy")
    finally:
        failing.close()
    codex.error = None
    codex.availability = (False, "Codex is not installed.")
    unavailable = ConnectedBroker(root / "catalogue-unavailable", adapters=adapters, autostart=False, list_ttl=0)
    try:
        data = unavailable.list_sessions()
        require(next(row for row in data["sources"] if row["app"] == "codex") == {"app": "codex", "available": False, "reason": "Codex is not installed.", "state": "missing"}
                and all(row["app"] != "codex" for row in data["sessions"]), "sessions.broker.catalogue", "unavailable source lost truthful reason")
    finally:
        unavailable.close()
    independent = InventoryBoundary([row("claude-code", "owned-only", "Owned only")])
    owned = ConnectedBroker(root / "catalogue-run", adapters={"claude-code": independent}, autostart=False, list_ttl=0)
    try:
        identity = sid("claude-code", "owned-only")
        run = owned.send(identity, "work", "scratch-owned-overlay")
        require(independent.started.wait(3), "sessions.broker.catalogue", "independent turn did not start")
        active = owned.list_sessions()["sessions"][0]
        require((active["status"], active["live_owner"]) == ("working", "neyvia"), "sessions.broker.catalogue", "active owned run missing overlay")
        independent.release.set()
        deadline = time.monotonic() + 3
        while owned.get_run(run["runId"])["state"] != "completed" and time.monotonic() < deadline: time.sleep(.005)
        terminal = owned.list_sessions()["sessions"][0]
        require((terminal["status"], terminal["live_owner"]) == ("unknown", None), "sessions.broker.catalogue", "terminal owned run retained ownership")
    finally:
        independent.release.set()
        owned.close()
    return ["sessions.broker.catalogue", "sessions.broker.unread"]


def _protocol_procedure(root):
    """Exercise production broker/store/event machinery over a finite adapter boundary."""
    import threading
    from .connected_sessions.broker import ConnectedBroker, ConnectedError, make_session_id
    from .connected_sessions.model import SessionSummary, Capabilities
    from .external_chat_inventory import _host
    host = _host()["deviceId"]
    identity = make_session_id("claude-code", host, "scratch-session")
    other = make_session_id("claude-code", host, "scratch-other")
    class Transport:
        """One finite provider boundary: records the broker's actual protocol calls."""
        def __init__(self):
            self.calls, self.answers, self.interrupts = [], [], []
            self.mode = "stream"
            self.ready, self.release = threading.Event(), threading.Event()
            self.live = {}
            self.read_only = False
            self.read_calls = []
        def available(self):
            return True, None
        def list_sessions(self, **kwargs):
            return [SessionSummary(id=value, app="claude-code", title=value, cwd=str(root), capabilities=Capabilities(continue_session=not self.read_only, stop=True, approvals=True, reason="Read only." if self.read_only else None)) for value in (identity, other)]
        def live_status(self):
            return self.live
        def read(self, session_id, *, cursor=None, before_seq=None, limit=200):
            from .connected_sessions.model import Item, ItemsPage, ContextUsage
            self.read_calls.append((session_id, cursor, before_seq, limit))
            if session_id not in (identity, other):
                raise FileNotFoundError(session_id)
            items = [Item("t1", 1, "tool", data={"name": "bash", "output": "x" * 20_000, "status": "ok"}),
                     Item("u1", 2, "user", data={"text": "see", "attachments": [
                         {"id": "abc123", "kind": "image", "label": "C:/scratch/private/secret.png", "url": "C:/scratch/private/secret.png"},
                         {"id": "def456", "kind": "image", "label": "ok.png", "url": "/api/connected-chat-media?chat=x&media=y"}]})]
            return ItemsPage(self.list_sessions()[0], [item for item in items if before_seq is None or item.seq < before_seq], ContextUsage(), cursor="2", has_earlier=False)
        def tool_output(self, session_id, item_id):
            return "x" * 20_000 if item_id == "t1" else "y" * 1_500_000 if item_id == "big" else None
        def media(self, session_id, media_id):
            return (b"\x89PNG-bytes", "image/png", "shot.png") if media_id == "abc123" else None
        def start_turn(self, session_id, message, options, *, cwd, run_id, emit):
            self.calls.append((session_id, message, options, cwd, run_id))
            self.ready.set()
            if session_id is None:
                time.sleep(0.12)
            session_id = session_id or make_session_id("claude-code", host, "scratch-new")
            emit({"type": "item.added", "sessionId": session_id, "item": {"id": "user", "seq": 1, "kind": "user", "data": {"text": message}}})
            if self.mode == "fail":
                raise RuntimeError("finite transport exited with code 1")
            if self.mode == "approval":
                emit({"type": "run.state", "state": "waiting_approval", "pendingRequest": {"requestId": "scratch-approval", "command": "echo scratch", "kind": "approval", "choices": ["approve", "deny"]}})
                require(self.release.wait(8), "sessions.run.lifecycle", "approval boundary timed out")
            elif self.mode == "hold":
                require(self.release.wait(8), "sessions.run.lifecycle", "hold boundary timed out")
            else:
                emit({"type": "item.added", "sessionId": session_id, "item": {"id": "assistant", "seq": 2, "kind": "assistant", "data": {"text": ""}}})
                for text in ("Hello", ", ", "world"):
                    emit({"type": "item.delta", "sessionId": session_id, "itemId": "assistant", "textDelta": text})
                emit({"type": "item.updated", "sessionId": session_id, "item": {"id": "assistant", "seq": 2, "kind": "assistant", "data": {"text": "Hello, world"}}})
            return session_id
        def interrupt(self, run_id):
            self.interrupts.append(run_id)
            self.release.set()
        def answer(self, run_id, request_id, response):
            self.answers.append((run_id, request_id, response))
            self.release.set()
    boundary = Transport()
    broker = ConnectedBroker(root / "broker", adapters={"claude-code": boundary}, autostart=False, list_ttl=0, start_cursor=0)
    def await_state(run_id, state):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            record = broker.get_run(run_id)
            if record["state"] == state:
                return record
            time.sleep(0.005)
        require(False, "sessions.run.lifecycle", "run did not reach " + state)
    def refusal(code, action):
        try:
            action()
        except ConnectedError as error:
            require(error.code == code, "sessions.run.request", "refusal lost its machine code")
            return error
        require(False, "sessions.run.request", "invalid protocol action was accepted")
    try:
        for transport in (None, "print", "terminal"):
            require(ConnectedBroker._turn_options({"transport": transport}).transport == transport, "sessions.broker.options", "known transport changed")
        refusal("invalid_option", lambda: ConnectedBroker._turn_options({"transport": "keystrokes"}))
        page = broker.read(identity, limit=9999)
        attachments = page["items"][1]["data"]["attachments"]
        require(boundary.read_calls[-1][-1] == 200 and len(page["items"][0]["data"]["output"]) == 8192
                and page["items"][0]["data"]["outputTruncated"] is True
                and attachments[0]["url"] == f"/api/connected/media?session={identity.replace(':', '%3A')}&media=abc123"
                and attachments[0]["label"] == "secret.png" and attachments[1]["url"].startswith("/api/connected-chat-media")
                and "private" not in json.dumps(page["items"]) and page["run"] is None and page["has_earlier"] is False
                and page["session"]["id"] == identity, "sessions.broker.read", "broker page leaked host references or lost budget/identity")
        require(broker.tool_output(identity, "t1") == {"itemId": "t1", "output": "x" * 20_000, "truncated": False}
                and broker.tool_output(identity, "big") == {"itemId": "big", "output": "y" * 1_000_000, "truncated": True}, "sessions.broker.read", "full output retrieval differs")
        refusal("item_not_found", lambda: broker.tool_output(identity, "missing"))
        saved_output = boundary.tool_output
        boundary.tool_output = None
        refusal("not_supported", lambda: broker.tool_output(identity, "t1"))
        boundary.tool_output = saved_output
        require(broker.read(identity, before_seq=2)["items"][0]["id"] == "t1", "sessions.broker.read", "read lost exclusive older bound")
        refusal("session_not_found", lambda: broker.read(make_session_id("claude-code", host, "gone")))
        refusal("invalid_request", lambda: broker.read(identity, limit="many"))
        require(broker.media(identity, "abc123") == (b"\x89PNG-bytes", "image/png", "shot.png"), "sessions.broker.media", "media hook bytes changed")
        require(refusal("media_not_found", lambda: broker.media(identity, "gone")).status == 404, "sessions.broker.media", "missing media lost 404")
        saved_media = boundary.media
        boundary.media = None
        boundary.read_media = lambda session_id, media_id: (b"IMG", "image/png", "a.png")
        require(broker.media(identity, "abc") == (b"IMG", "image/png", "a.png"), "sessions.broker.media", "read_media alias not selected")
        def media_refusal(session_id, media_id):
            raise ConnectedError("media_not_found", "Image absent from recent history.", 404)
        boundary.read_media = media_refusal
        require(refusal("media_not_found", lambda: broker.media(identity, "abc")).status == 404, "sessions.broker.media", "coded media refusal lost status")
        boundary.read_media = lambda session_id, media_id: None
        require(refusal("media_not_found", lambda: broker.media(identity, "abc")).status == 404, "sessions.broker.media", "null media lost 404")
        del boundary.read_media
        boundary.media = saved_media
        boundary.read_only = True
        broker._summaries.clear()
        broker._list_cache.clear()
        denied = refusal("cannot_continue", lambda: broker.send(identity, "x", "scratch-read-only-01"))
        require(denied.message == "Read only.", "sessions.run.request", "read-only reason lost")
        boundary.read_only = False
        broker._summaries.clear()
        broker._list_cache.clear()
        refusal("too_many_images", lambda: broker.send(identity, "x", "scratch-image-refusal", {"images": [{"mime": "image/png", "data": "AAAA"}] * 7}))
        for owner in ("app", "cli"):
            boundary.live[identity] = ("working", owner)
            error = refusal("session_live_elsewhere", lambda: broker.send(identity, "x", "scratch-live-" + owner))
            require(error.extra["owner"] == owner and ("app" if owner == "app" else "terminal") in error.message
                    and broker.latest_run(identity) is None, "sessions.run.request", "foreign owner refusal lost authority boundary")
        boundary.live.clear()
        for code, action in (("invalid_message", lambda: broker.send(identity, " ", "scratch-invalid-pre-01")),
                             ("invalid_request_id", lambda: broker.send(identity, "x", "short")),
                             ("invalid_session", lambda: broker.send("bad", "x", "scratch-invalid-pre-02")),
                             ("wrong_device", lambda: broker.send("external:claude-code:other-host:session", "x", "scratch-invalid-pre-03")),
                             ("session_not_found", lambda: broker.send(make_session_id("claude-code", host, "missing"), "x", "scratch-invalid-pre-04")),
                             ("adapter_unavailable", lambda: broker.send(make_session_id("codex", host, "missing"), "x", "scratch-invalid-pre-05"))):
            refusal(code, action)
        require(boundary.calls == [], "sessions.run.request", "refused action reached adapter start")
        run = broker.send(session_id=identity, message="hello", request_id="scratch-stream-0001", options={"model": "m1", "permissionMode": "plan"})
        record = await_state(run["runId"], "completed")
        require(broker.read(identity)["run"]["state"] == "completed" and broker.read(identity)["run"]["runId"] == run["runId"], "sessions.broker.read", "read lost completed run overlay")
        require(record["canStop"] is False and record["pendingRequest"] is None and record["error"] is None,
                "sessions.run.lifecycle", "completed run retains pending controls")
        events, head, resync = broker.events_since(0)
        shape = [(event["type"], event.get("state") or (event.get("item") or {}).get("kind") or event.get("textDelta")) for event in events if event["type"] != "session.updated"]
        require(shape == [("run.state", "queued"), ("run.state", "running"), ("item.added", "user"), ("item.added", "assistant"), ("item.delta", "Hello"), ("item.delta", ", "), ("item.delta", "world"), ("item.updated", "assistant"), ("run.state", "completed")]
                and all(event["hostDeviceId"] == host for event in events) and all(event["sessionId"] == identity for event in events if event["type"].startswith("item."))
                and [event["cursor"] for event in events] == list(range(1, len(events) + 1))
                and not resync and head == events[-1]["cursor"], "sessions.events.stamp", "broker stream changed event order or stamping")
        require(boundary.calls[0][2].model == "m1" and boundary.calls[0][2].permission_mode == "plan", "sessions.run.request", "turn options changed at adapter boundary")
        require(broker.send(identity, "hello", "scratch-stream-0001", {"model": "m1", "permissionMode": "plan"})["state"] == "completed" and len(boundary.calls) == 1, "sessions.run.request", "completed replay resent the adapter")
        refusal("request_id_conflict", lambda: broker.send(identity, "changed", "scratch-stream-0001", {"model": "m1", "permissionMode": "plan"}))
        boundary.mode = "hold"
        boundary.ready.clear()
        waiting = broker.send(identity, "hold", "scratch-hold-0001")
        require(boundary.ready.wait(3), "sessions.run.lifecycle", "adapter never started")
        require(broker.read(identity)["run"]["runId"] == waiting["runId"] and broker.read(identity)["session"]["status"] == "working", "sessions.broker.read", "read lost active run overlay")
        require(broker.send(identity, "hold", "scratch-hold-0001")["runId"] == waiting["runId"] and len(boundary.calls) == 2, "sessions.run.request", "active replay resent the adapter")
        busy = refusal("session_busy", lambda: broker.send(identity, "other", "scratch-busy-0001"))
        require(busy.extra["runId"] == waiting["runId"], "sessions.run.request", "busy refusal lost owner run")
        parallel = broker.send(other, "parallel", "scratch-parallel-0001")
        broker.stop(waiting["runId"])
        await_state(waiting["runId"], "cancelled")
        require(broker.read(identity)["run"]["state"] == "cancelled", "sessions.broker.read", "read lost terminal run overlay")
        await_state(parallel["runId"], "completed")
        broker.stop(waiting["runId"])
        require(boundary.interrupts == [waiting["runId"]], "sessions.run.lifecycle", "repeat stop interrupted twice")
        refusal("run_not_found", lambda: broker.stop("missing"))
        boundary.release.clear()
        boundary.mode = "approval"
        pending = broker.send(identity, "ask", "scratch-approval-0001")
        state = await_state(pending["runId"], "waiting_approval")
        require(state["pendingRequest"]["command"] == "echo scratch", "sessions.run.lifecycle", "approval metadata missing")
        refusal("request_not_pending", lambda: broker.answer(pending["runId"], "stale", {"decision": "approve"}))
        refusal("invalid_response", lambda: broker.answer(pending["runId"], "scratch-approval", {"decision": "maybe"}))
        refusal("invalid_response", lambda: broker.answer(pending["runId"], "scratch-approval", "approve"))
        broker.answer(pending["runId"], "scratch-approval", {"decision": "approve", "answers": {"q": "a"}})
        await_state(pending["runId"], "completed")
        require(boundary.answers == [(pending["runId"], "scratch-approval", {"decision": "approve", "answers": {"q": "a"}})], "sessions.run.lifecycle", "answer changed or was delivered twice")
        refusal("request_not_pending", lambda: broker.answer(pending["runId"], "scratch-approval", {"decision": "approve"}))
        boundary.mode = "fail"
        failed = broker.send(identity, "fail", "scratch-fail-0001")
        require(await_state(failed["runId"], "failed")["error"] == "finite transport exited with code 1", "sessions.run.lifecycle", "failure receipt lost adapter error")
        boundary.mode = "stream"
        await_state(broker.send(identity, "recovered", "scratch-recovered-0001")["runId"], "completed")
        for code, action in (("invalid_message", lambda: broker.send(identity, " ", "scratch-invalid-0001")), ("invalid_request_id", lambda: broker.send(identity, "x", "short")), ("invalid_session", lambda: broker.send("bad", "x", "scratch-invalid-0002")), ("wrong_device", lambda: broker.send("external:claude-code:other-host:session", "x", "scratch-invalid-0003")), ("session_not_found", lambda: broker.send(make_session_id("claude-code", host, "missing"), "x", "scratch-invalid-0004")), ("adapter_unavailable", lambda: broker.send(make_session_id("codex", host, "missing"), "x", "scratch-invalid-0005"))):
            refusal(code, action)
        new = broker.new("claude-code", str(root), "new", "scratch-new-0001")
        require(new["sessionId"] == make_session_id("claude-code", host, "scratch-new"), "sessions.run.request", "new session returned without its adapter identity")
        await_state(new["runId"], "completed")
        require(broker.latest_run(new["sessionId"])["runId"] == new["runId"], "sessions.run.request", "new session was not persisted")
        require(boundary.calls[-1][0] is None and boundary.calls[-1][3] == str(root.resolve())
                and broker.new("claude-code", str(root), "new", "scratch-new-0001")["runId"] == new["runId"], "sessions.run.request", "new identity wait/replay/cwd differs")
        for code, app, cwd in (("invalid_cwd", "claude-code", str(root / "gone")), ("adapter_unavailable", "codex", str(root)), ("invalid_app", "bogus", str(root))):
            refusal(code, lambda app=app, cwd=cwd: broker.new(app, cwd, "hello", "scratch-new-invalid-" + code))
        boundary.can_start_new = lambda: (False, "Not today.")
        refusal("cannot_start", lambda: broker.new("claude-code", str(root), "new", "scratch-new-denied-01"))
    finally:
        boundary.release.set()
        broker.close()
    old = ConnectedBroker(root / "restart", adapters={}, autostart=False)
    old._publish({"type": "notice"})
    cursor = old.head()
    old.close()
    time.sleep(0.01)
    new = ConnectedBroker(root / "restart", adapters={}, autostart=False)
    try:
        require(new.events_since(cursor)[2] is True, "sessions.events.cursor", "restart cursor did not resync")
    finally:
        new.close()
    from .connected_sessions.events import EventBuffer
    ring = EventBuffer(host, max_events=5, start_cursor=100)
    for number in range(20):
        ring.publish({"type": "notice", "number": number})
    require(ring.since(None) == ([], 120, False) and [event["cursor"] for event in ring.since(115)[0]] == list(range(116, 121))
            and ring.since(120) == ([], 120, False) and ring.since(100) == ([], 120, True) and ring.since(500) == ([], 120, True), "sessions.events.cursor", "cursor retention boundary differs")
    before = time.monotonic()
    require(ring.wait(120, 0.12) == ([], 120, False) and 0.08 < time.monotonic() - before < 2, "sessions.events.wait", "empty wait did not honor timeout")
    timer = threading.Timer(0.12, lambda: ring.publish({"type": "notice"}))
    timer.start()
    before = time.monotonic()
    require(ring.wait(120, 3)[1] == 121 and time.monotonic() - before < 2, "sessions.events.wait", "publish did not wake waiter")
    timer.join()
    require(ring.wait(None, 3)[1] == 121, "sessions.events.wait", "new subscriber blocked")
    ring.close()
    tiny = EventBuffer(host, max_events=5000, max_bytes=20_000, start_cursor=0)
    for _ in range(50):
        tiny.publish({"type": "notice", "text": "x" * 2000})
    require(0 < len(tiny._ring) < 12 and tiny._bytes <= 20_000, "sessions.events.bounds", "ring byte cap did not evict")
    big = EventBuffer(host, start_cursor=0)
    big.publish({"type": "item.delta", "textDelta": "a" * 300_000})
    big.publish({"type": "item.added", "item": {"id": "t", "seq": 1, "kind": "tool", "data": {"name": "bash", "input": "ls", "output": "line\n" * 100_000}}})
    values = big.since(0)[0]
    require(all(value.get("truncated") is True for value in values) and values[0]["textDelta"].startswith("aaaa") and values[0]["textDelta"].endswith("[truncated]")
            and values[1]["item"]["data"]["name"] == "bash" and values[1]["item"]["data"]["input"] == "ls", "sessions.events.bounds", "oversize events lost untrimmed metadata")
    from .connected_sessions import codex_items as ci, neyvia as n
    for ordinal in (0, 1, 41, 1_000_000):
        for index in (0, 1, 2047):
            for sub in (0, 1, 3):
                seq = ci.make_seq(ordinal=ordinal, index=index, sub=sub)
                require(ci.ordinal_from_seq(seq) == ordinal and seq < 2 ** 53, "sessions.codex.sequence", "slot is not stable within JSON integer precision")
    require(ci.clip("plain") == "plain" and len(ci.clip("日本語" * 40_000).encode("utf-8")) <= ci.TEXT_LIMIT + 80, "sessions.codex.text", "UTF-8 text cap failed")
    for runtime in ("", "own", "neyvia", "neyvia-agent", "codex", "claude-code", "mixed-routes"):
        n.classify(runtime=runtime)
    identities = ["sessions.events.stamp", "sessions.events.bounds", "sessions.events.cursor", "sessions.events.wait", "sessions.run.lifecycle", "sessions.run.request", "sessions.broker.read", "sessions.broker.media", "sessions.broker.options", "sessions.codex.sequence", "sessions.codex.text", "sessions.neyvia.category"] + _codex_mapping_procedure(root) + _native_observer_procedure(root) + _broker_catalogue_procedure(root) + _broker_controls_procedure(root) + _broker_recovery_procedure(root) + _opencode_inventory_procedure(root)
    rejections = []
    for identity, action in (("sessions.run.lifecycle", lambda: check_run_record({"state": "completed", "canStop": True, "canSteer": False})), ("sessions.codex.sequence", lambda: check_seq(1, 1, 0, 999)), ("sessions.codex.text", lambda: check_clip("plain", 99, "wrong")), ("sessions.neyvia.category", lambda: check_native_category("codex", ("native", None)))):
        try:
            action()
        except ValueError:
            rejections.append({"contract": identity, "rejected": True})
        else:
            require(False, identity, "corrupt protocol receipt accepted")
    from types import SimpleNamespace
    from .connected_sessions.model import Capabilities
    from .connected_sessions.registry import ConnectedError
    for identity, action in (
        ("sessions.broker.controls", lambda: check_control_projection({"observed": True}, {}, "options")),
        ("sessions.broker.refusals", lambda: check_adapter_refusal({"exc": RuntimeError("failed"), "fallback_code": "failed", "fallback_message": "", "fallback_status": 502}, ConnectedError("wrong", "failed", 502))),
        ("sessions.broker.registry", lambda: check_registry_adapter({"app": "codex"}, (None, None))),
        ("sessions.broker.unread", lambda: check_unread(None, None, None, True)),
        ("sessions.run.watchdog", lambda: check_watchdog_selection(SimpleNamespace(idle_watchdog_seconds=1), [(object(), "running", False, 0)], 2, [])),
        ("sessions.run.recovery", lambda: check_recovered_runs([{"state": "running"}])),
        ("sessions.opencode.inventory", lambda: check_opencode_capabilities(False, Capabilities())),
    ):
        try: action()
        except ValueError: rejections.append({"contract": identity, "rejected": True})
        else: require(False, identity, "corrupt extended protocol receipt accepted")
    return identities, [{"contract": identity, "ok": True} for identity in identities], rejections


def self_check(root):
    import uuid
    started = time.perf_counter()
    root = Path(root).resolve() / "a-sessions" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [env.get("PYTHONPATH"), str(Path(__file__).resolve().parents[1])]))
    env["NEYVIA_PROOF_CREDENTIAL_GUARD"] = "1"
    area_timeout = float(os.environ.get('NEYVIA_PROOF_AREA_TIMEOUT', '240'))
    if not 0 < area_timeout < float('inf'):
        raise ValueError('Session area wall budget must be finite and positive')
    result = subprocess.run([sys.executable, "-m", __name__, "--scratch", str(root)], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=area_timeout,
                            **__import__("grant_agent.subprocess_utils", fromlist=["hidden_windows_subprocess_kwargs"]).hidden_windows_subprocess_kwargs())
    if result.returncode:
        raise RuntimeError("Connected scratch procedure failed: " + result.stderr[-4000:])
    receipt = json.loads(result.stdout)
    receipt["elapsedMs"] = round((time.perf_counter() - started) * 1000, 3)
    return receipt


def _scratch(root):
    if os.environ.get('NEYVIA_PROOF_CREDENTIAL_GUARD'):
        from .proof_credential_guard import install
        install(root)
    selected = set(json.loads(os.environ['NEYVIA_GATE_CONTRACTS'])) if os.environ.get('NEYVIA_GATE_CONTRACTS') else None
    def receipt(identities, checks, rejections):
        return {'ok': True, 'contracts': identities, 'checks': checks, 'rejections': rejections,
                'runtimeState': str(root), 'boundary': 'Real isolated selected session procedures; no external account/network'}
    # Selection stays inside the traced scratch child, including narrow paths.
    # Full-area jobs below still execute every existing procedure and check.
    if selected and selected <= {'sessions.opencode.inventory', 'sessions.broker.catalogue', 'sessions.broker.unread'}:
        identities = []
        if 'sessions.opencode.inventory' in selected: identities.extend(_opencode_inventory_procedure(root))
        if selected & {'sessions.broker.catalogue', 'sessions.broker.unread'}: identities.extend(_broker_catalogue_procedure(root))
        return receipt(identities, [{'contract': identity, 'ok': True} for identity in identities], [])
    api_contracts = {'sessions.api.authority', 'sessions.api.response', 'sessions.api.state_root',
                     'sessions.api.media', 'sessions.api.sse', 'sessions.api.poll', 'sessions.events.subscription',
                     'sessions.api.forward', 'sessions.api.allowlist'}
    if selected and selected <= api_contracts:
        return receipt(*_http_procedure(root))
    if selected and not (selected & api_contracts) and all(not identity.startswith(('sessions.workspace.', 'sessions.folders.')) for identity in selected):
        return receipt(*_protocol_procedure(root))
    from .connected_sessions import workspace as w, folders as f
    import shutil
    actual_which = shutil.which
    git = actual_which("git")
    require(bool(git), "sessions.workspace.state", "Git is unavailable")
    # Only tool availability is controlled; all repository observations and
    # mutations use the real production implementation and real hidden Git.
    w._which = lambda name: git if name == "git" else None
    f.shutil.which = lambda name: git if name == "git" else None
    os.environ["NEYVIA_PROJECTS_DIR"] = str(root / "Projects")
    # Scratch roots live below this checkout: stop Git's upward search there,
    # so a plain scratch folder cannot accidentally observe the host worktree.
    os.environ["GIT_CEILING_DIRECTORIES"] = str(root)
    f._CACHE.clear()
    w.invalidate()
    repo = root / "Projects" / "app"
    repo.mkdir(parents=True)
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    def run(where, *args):
        done = subprocess.run([git, *args], cwd=where, capture_output=True, text=True, encoding="utf-8", check=True,
                              env=w._env(read_only=False),
                              **hidden_windows_subprocess_kwargs())
        return done.stdout.strip()
    run(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Proofs"), ("user.email", "proofs@example.invalid"), ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
        run(repo, "config", key, value)
    (repo / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (repo / "b.txt").write_text("bee\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "deep.txt").write_text("deep\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", "initial")
    checks, rejections = [], []
    state = w.workspace_state(str(repo))
    require(state["repo"] == {"root": str(repo), "name": "app", "remoteUrl": None, "github": None}
            and state["branch"] == "main" and state["changes"] == [] and state["pullRequest"] is None
            and state["gh"]["installed"] is False, "sessions.workspace.state", "clean scratch receipt differs")
    (repo / "a.txt").write_text("one\nTWO\nthree\nfour\n", encoding="utf-8")
    # Observe reuse before a separate Git mutation can consume the five-second
    # cache lifetime. Later invalidation still proves the complete real delta.
    require(w.workspace_state(str(repo))["changes"] == [], "sessions.workspace.cache", "cached observer was recomputed")
    (repo / "b.txt").unlink()
    run(repo, "mv", "sub/deep.txt", "sub/deeper.txt")
    (repo / "new.txt").write_text("x\ny\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"\0binary")
    w.invalidate(str(repo))
    changes = {row["path"]: row for row in w.workspace_state(str(repo))["changes"]}
    require(changes["a.txt"] == {"path": "a.txt", "status": "modified", "additions": 2, "deletions": 1, "staged": False}
            and changes["b.txt"]["deletions"] == 1 and changes["sub/deeper.txt"]["oldPath"] == "sub/deep.txt"
            and changes["new.txt"]["additions"] == 2 and changes["blob.bin"]["additions"] is None,
            "sessions.workspace.state", "real mixed changes differ")
    page = w.file_diff(str(repo), "a.txt")
    require("-two" in page["patch"] and "+TWO" in page["patch"], "sessions.workspace.diff", "tracked content missing")
    require("+x" in w.file_diff(str(repo), "new.txt")["patch"] and "rename from sub/deep.txt" in w.file_diff(str(repo), "sub/deeper.txt")["patch"], "sessions.workspace.diff", "untracked or renamed content missing")
    require(w.file_diff(str(repo), str(repo / "a.txt"))["path"] == "a.txt"
            and w.file_diff(str(repo / "sub"), "a.txt")["path"] == "a.txt", "sessions.workspace.diff", "repository-relative resolution differs")
    before = run(repo, "rev-parse", "HEAD")
    for action in ("commit", "push", "create_pr"):
        for confirm in (None, False, "true", 1, "yes", {}):
            try:
                w.git_action(str(repo), action, message="refused", title="refused", confirm=confirm)
            except w.WorkspaceError as error:
                require(error.code == "confirmation_required", "sessions.workspace.confirm", "refusal code differs")
            else:
                require(False, "sessions.workspace.confirm", "nonliteral confirmation was accepted")
    require(run(repo, "rev-parse", "HEAD") == before and (repo / "a.txt").read_text(encoding="utf-8").startswith("one\nTWO"), "sessions.workspace.confirm", "refusal mutated the repository")
    rejections.append({"contract": "sessions.workspace.confirm", "rejected": True, "calls": 18})
    for bad in ("../secret", "sub/../../secret", str(root / "secret"), "..\\secret", "", " ", "a\0b", "."):
        try:
            w.file_diff(str(repo), bad)
        except w.WorkspaceError as error:
            require(error.code in {"path_outside_repo", "invalid_path"}, "sessions.workspace.diff", "unsafe path refusal differs")
        else:
            require(False, "sessions.workspace.diff", "unsafe path was accepted")
    rejections.append({"contract": "sessions.workspace.diff", "rejected": True, "calls": 8})
    for bad in ("", " ", "x" * 5001, None):
        try:
            w.git_action(str(repo), "commit", message=bad, confirm=True)
        except w.WorkspaceError as error:
            require(error.code == "message_required", "sessions.workspace.action", "message refusal differs")
        else:
            require(False, "sessions.workspace.action", "invalid message was accepted")
    result = w.git_action(str(repo), "commit", message="--amend everything", confirm=True)
    require(result["ok"] and run(repo, "log", "-1", "--format=%s") == "--amend everything"
            and run(repo, "status", "--porcelain") == "?? blob.bin\n?? new.txt", "sessions.workspace.action", "commit must preserve untracked files and literal message")
    require(w.git_action(str(repo), "commit", message="again", confirm=True)["ok"] is False, "sessions.workspace.action", "empty commit reported success")
    for raw in ("https://github.com/octo/demo.git", "https://github.com/octo/demo", "git@github.com:octo/demo.git", "ssh://git@github.com/octo/demo.git", "https://synthetic:synthetic@github.com/octo/de.mo.git", "https://gitlab.com/octo/demo.git", "https://github.com.evil.example/octo/demo.git", "/local/path/demo.git"):
        w._github_from_remote(raw)
    for rollup in (None, [], [{"state": "SUCCESS"}], [{"status": "IN_PROGRESS"}], [{"state": "FAILURE"}, {"state": "PENDING"}], [{"state": "ERROR"}]):
        w._checks_summary(rollup)
    run(repo, "remote", "add", "origin", "https://synthetic:synthetic@github.com/octo/demo.git")
    w.invalidate()
    state = w.workspace_state(str(repo))
    require(state["repo"]["remoteUrl"] == "https://github.com/octo/demo.git" and "synthetic" not in json.dumps(state), "sessions.workspace.remote", "synthetic userinfo leaked")
    linked = root / "Projects" / "app-fix"
    run(repo, "worktree", "add", "-q", "-b", "fix", str(linked))
    w.invalidate()
    linked_state = w.workspace_state(str(linked))
    require(linked_state["branch"] == "fix" and f._git_info(linked) == {"branch": "fix", "github": "octo/demo"}, "sessions.folders.catalogue", "real linked worktree differs")
    trees = {os.path.normcase(row["path"]): row for row in linked_state["worktrees"]}
    require(trees[os.path.normcase(str(linked))] == {"path": str(linked), "branch": "fix", "current": True}
            and trees[os.path.normcase(str(repo))] == {"path": str(repo), "branch": "main", "current": False}, "sessions.workspace.state", "worktree branch/current projection differs")
    plain = root / "Projects" / "notes"
    plain.mkdir()
    require(f._git_info(plain) is None and w.workspace_state(str(plain))["repo"] is None
            and w.workspace_state(str(root / "missing"))["exists"] is False and w.workspace_state(None)["cwd"] is None, "sessions.workspace.state", "plain/missing workspace differs")
    rows = {row["name"]: row for row in f.local_projects()}
    require(rows["app"]["branch"] == "main" and rows["app"]["github"] == "octo/demo" and rows["notes"]["isGit"] is False, "sessions.folders.catalogue", "local catalogue projection differs")
    filtered = f.candidates(recent=[{"path": str(linked), "name": "app-fix"}], query="fix")
    require([row["name"] for row in filtered["local"]] == ["app-fix"] and len(filtered["recent"]) == 1, "sessions.folders.filter", "query did not filter both views")
    require(f.github_status()["installed"] is False and f.github_repos() == [] and f.github_candidates()["repos"] == [], "sessions.folders.availability", "missing CLI must remain unavailable")
    for function, args, kwargs, fragment in ((f.clone, ("octo/app",), {"confirm": False}, "confirmation"), (f.clone, ("../evil",), {"confirm": True}, "owner/name"), (f.create_worktree, (str(repo), "fix"), {"confirm": False}, "confirmation"), (f.create_worktree, (str(repo), "../escape"), {"confirm": True}, "branch name"), (f.create_worktree, (str(plain), "fix"), {"confirm": True}, "git repository")):
        try:
            function(*args, **kwargs)
        except ValueError as error:
            require(fragment in str(error), "sessions.folders.confirm", "folder refusal differs")
        else:
            require(False, "sessions.folders.confirm", "unsafe folder action accepted")
    rejections.append({"contract": "sessions.folders.confirm", "rejected": True, "calls": 5})
    contracts = ["sessions.workspace.state", "sessions.workspace.cache", "sessions.workspace.diff", "sessions.workspace.confirm", "sessions.workspace.action", "sessions.workspace.remote", "sessions.workspace.checks", "sessions.folders.catalogue", "sessions.folders.filter", "sessions.folders.availability", "sessions.folders.confirm"]
    for identity in contracts:
        checks.append({"contract": identity, "ok": True})
    workspace_ids, workspace_checks, workspace_rejections = _workspace_observers(root, repo, run)
    contracts += workspace_ids
    checks += workspace_checks
    rejections += workspace_rejections
    shutil.which = actual_which
    if selected and all(identity.startswith(('sessions.workspace.', 'sessions.folders.')) for identity in selected):
        return receipt(contracts, checks, rejections)
    protocol_ids, protocol_checks, protocol_rejections = _protocol_procedure(root)
    contracts += protocol_ids
    checks += protocol_checks
    rejections += protocol_rejections
    http_ids, http_checks, http_rejections = _http_procedure(root)
    contracts += http_ids
    checks += http_checks
    rejections += http_rejections
    # Deliberate invalid receipts prove that the host checks are active.
    for identity, corrupt in (("sessions.workspace.remote", lambda: check_remote("https://github.com/octo/demo", None)), ("sessions.workspace.checks", lambda: check_rollup([{"state": "FAILURE"}], "passing")), ("sessions.workspace.action", lambda: check_action({"code": 1, "out": "", "err": "failed", "timedOut": False}, {"ok": True, "output": "failed"})), ("sessions.folders.catalogue", lambda: check_folder_info(linked, {"branch": "main", "github": "octo/demo"}))):
        try:
            corrupt()
        except ValueError:
            rejections.append({"contract": identity, "rejected": True})
        else:
            require(False, identity, "corrupt receipt accepted")
    return {"area": "a-sessions", "ok": True, "contracts": contracts, "checks": checks, "rejections": rejections,
            "frontier": ["Live provider account/CLI execution, actual product cookie issuance, forbidden push and live GitHub PR authority remain outside the confined transport proof. Real authenticated route decisions and HTTP/SSE/client disposal are exercised with finite auth and provider boundaries."],
            "boundary": proof_text("Real scratch Git, broker/store/events and HTTP/SSE on explicit loopback port 48469; finite adapter and in-memory auth boundaries. No provider/account/credential files or external network.")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", type=Path, required=True)
    print(json.dumps(_scratch(parser.parse_args().scratch)))
