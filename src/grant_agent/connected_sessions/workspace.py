"""Git and GitHub state for a connected session's folder.

Every child process is hidden on Windows, time-limited, and never prompts. Reads never take
a git lock. Mutating actions (commit, push, create a pull request) run only with an explicit
``confirm: true`` and return the real command output. Neyvia never reads or stores GitHub
tokens: ``gh`` keeps its own sign-in and is only asked for read-only status.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..subprocess_utils import capture_bounded_process, hidden_windows_subprocess_kwargs
from .. import proofs_a_sessions as _proofs

_STATE_TTL = 5.0
_PR_TTL = 15.0
_GH_AUTH_TTL = 60.0
_GIT_TIMEOUT = 15
_GH_TIMEOUT = 20
_ACTION_TIMEOUT = 180
MAX_CHANGES = 300
MAX_PATCH_BYTES = 256 * 1024
MAX_OUTPUT_CHARS = 20_000
_UNTRACKED_COUNT_FILES = 50
_UNTRACKED_COUNT_BYTES = 512 * 1024

_CACHE_LOCK = threading.RLock()
_STATE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PR_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any] | None, str | None]] = {}
_GH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class WorkspaceError(Exception):
    """A refused or failed workspace request, with a stable machine code."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _which(name: str) -> str | None:
    return shutil.which(name)


def _env(*, read_only: bool) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_PAGER": "cat", "GH_PAGER": "cat",
        "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "GH_SPINNER_DISABLED": "1", "NO_COLOR": "1",
    })
    if read_only:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    if os.name == "nt":
        # Command-scoped Git configuration supports nested workspaces without
        # changing the user's global or repository configuration.
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        env[f"GIT_CONFIG_KEY_{count}"] = "core.longpaths"
        env[f"GIT_CONFIG_VALUE_{count}"] = "true"
        env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def _run(args: list[str], cwd: str | Path, timeout: float, *, read_only: bool = True) -> dict[str, Any]:
    """Run one hidden child; ``code`` is None when it could not finish."""
    try:
        env = _env(read_only=read_only)
        _proofs.check_cli_invocation(args, env)
        result = capture_bounded_process(args, cwd=cwd, env=env, input_text=None, timeout=timeout)
    except OSError as exc:
        return {"code": None, "out": "", "err": str(exc), "timedOut": False}
    return {"code": None if result["timedOut"] else result["returncode"], "out": result["stdout"] or "",
            "err": result["stderr"] or "", "timedOut": bool(result["timedOut"])}


def _run_capped(args: list[str], cwd: str | Path, timeout: float, max_bytes: int) -> tuple[int | None, bytes, bool]:
    """Run a child and keep at most ``max_bytes`` of stdout; (code, output, truncated)."""
    try:
        process = subprocess.Popen(
            args, cwd=str(cwd), env=_env(read_only=True), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs(),
        )
    except OSError:
        return None, b"", False
    timer = threading.Timer(timeout, process.kill)
    timer.start()
    try:
        data = process.stdout.read(max_bytes + 1) if process.stdout else b""
        truncated = len(data) > max_bytes
        if truncated:
            process.kill()
        process.wait(timeout=10)
        return (None if truncated else process.returncode), data[:max_bytes], truncated
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        return None, b"", False
    finally:
        timer.cancel()
        if process.stdout:
            process.stdout.close()


def _git(cwd: str | Path, *args: str, timeout: float = _GIT_TIMEOUT, read_only: bool = True) -> dict[str, Any]:
    git = _which("git")
    if not git:
        return {"code": None, "out": "", "err": "Git is not installed on this PC.", "timedOut": False, "missing": True}
    return _run([git, *args], cwd, timeout, read_only=read_only)


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [output truncated]"


def _strip_credentials(url: str) -> str:
    """Drop ``user:token@`` from a remote URL before it is shown or stored anywhere."""
    return re.sub(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@", r"\1", url.strip())


_GITHUB_REMOTE = re.compile(
    r"^(?:https?://(?:www\.)?github\.com/|(?:ssh://)?(?:[\w.-]+@)?github\.com[:/])([\w.-]+)/([\w.-]+?)(?:\.git)?/?$"
)


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_remote(args[0], result))
def _github_from_remote(url: str) -> dict[str, str] | None:
    match = _GITHUB_REMOTE.match(_strip_credentials(url))
    if not match:
        return None
    owner, name = match.group(1), match.group(2)
    return {"owner": owner, "name": name, "url": f"https://github.com/{owner}/{name}"}


def _repo_root(cwd: str) -> tuple[str | None, str | None]:
    """(git top-level folder, error). Error is None for a plain non-repository folder."""
    result = _git(cwd, "rev-parse", "--show-toplevel")
    if result["code"] == 0 and result["out"].strip():
        return os.path.normpath(result["out"].strip()), None
    if result.get("missing"):
        return None, result["err"]
    err = result["err"].strip()
    if "not a git repository" in err.lower():
        return None, None
    return None, _clip(err, 400) or "Git could not read this folder."


def _parse_status(raw: str) -> dict[str, Any]:
    branch: dict[str, Any] = {"oid": None, "head": None, "upstream": None, "ahead": None, "behind": None}
    entries: list[dict[str, Any]] = []
    tokens = raw.split("\0")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        if token.startswith("# "):
            key, _, value = token[2:].partition(" ")
            if key == "branch.oid":
                branch["oid"] = value
            elif key == "branch.head":
                branch["head"] = value
            elif key == "branch.upstream":
                branch["upstream"] = value
            elif key == "branch.ab":
                match = re.match(r"\+(\d+) -(\d+)", value)
                if match:
                    branch["ahead"], branch["behind"] = int(match.group(1)), int(match.group(2))
            continue
        kind = token[0]
        if kind == "1":
            parts = token.split(" ", 8)
            if len(parts) == 9:
                entries.append({"path": parts[8], "xy": parts[1]})
        elif kind == "2":
            parts = token.split(" ", 9)
            old = tokens[index] if index < len(tokens) else ""
            index += 1
            if len(parts) == 10:
                entries.append({"path": parts[9], "xy": parts[1], "oldPath": old})
        elif kind == "u":
            parts = token.split(" ", 10)
            if len(parts) == 11:
                entries.append({"path": parts[10], "xy": "UU"})
        elif kind == "?":
            entries.append({"path": token[2:], "xy": "??"})
    return {"branch": branch, "entries": entries}


def _status_word(xy: str) -> str:
    if xy == "??":
        return "untracked"
    for letter, word in (("U", "conflicted"), ("R", "renamed"), ("C", "copied"), ("D", "deleted"),
                         ("A", "added"), ("T", "typechange"), ("M", "modified")):
        if letter in xy:
            return word
    return "modified"


def _parse_numstat(raw: str) -> dict[str, tuple[int | None, int | None]]:
    counts: dict[str, tuple[int | None, int | None]] = {}
    tokens = raw.split("\0")
    index = 0
    while index < len(tokens):
        match = re.match(r"^(\d+|-)\t(\d+|-)\t(.*)$", tokens[index], re.S)
        index += 1
        if not match:
            continue
        added = None if match.group(1) == "-" else int(match.group(1))
        removed = None if match.group(2) == "-" else int(match.group(2))
        path = match.group(3)
        if path == "":  # rename or copy: the next two tokens are the old and the new path
            path = tokens[index + 1] if index + 1 < len(tokens) else ""
            index += 2
        if path:
            counts[path] = (added, removed)
    return counts


def _count_lines(path: Path) -> tuple[int | None, int | None]:
    try:
        if path.stat().st_size > _UNTRACKED_COUNT_BYTES or not path.is_file():
            return None, None
        data = path.read_bytes()
    except OSError:
        return None, None
    if b"\0" in data[:8000]:
        return None, None  # binary
    return len(data.splitlines()), 0


def _worktrees(root: str) -> list[dict[str, Any]]:
    result = _git(root, "worktree", "list", "--porcelain")
    if result["code"] != 0:
        return []
    rows, current = [], None
    for line in result["out"].splitlines() + [""]:
        if line.startswith("worktree "):
            current = {"path": os.path.normpath(line[9:]), "branch": None, "current": False}
        elif line.startswith("branch ") and current is not None:
            current["branch"] = line[7:].removeprefix("refs/heads/")
        elif line == "" and current is not None:
            current["current"] = _norm(current["path"]) == _norm(root)
            rows.append(current)
            current = None
    return rows


def _remote_url(root: str, branch: str | None, upstream: str | None) -> str | None:
    names: list[str] = []
    if branch:
        configured = _git(root, "config", "--get", f"branch.{branch}.remote")
        if configured["code"] == 0 and configured["out"].strip():
            names.append(configured["out"].strip())
    listed = _git(root, "remote")
    remotes = listed["out"].split() if listed["code"] == 0 else []
    names += [name for name in ("origin", *remotes) if name in remotes]
    for name in dict.fromkeys(names):
        if name == ".":
            continue
        url = _git(root, "remote", "get-url", name)
        if url["code"] == 0 and url["out"].strip():
            return _strip_credentials(url["out"].strip())
    return None


def _gh_state() -> dict[str, Any]:
    gh = _which("gh")
    if not gh:
        return {"installed": False, "authenticated": False, "reason": "The GitHub CLI (gh) is not installed on this PC."}
    with _CACHE_LOCK:
        cached = _GH_CACHE.get(gh)
        if cached and time.monotonic() - cached[0] < _GH_AUTH_TTL:
            return dict(cached[1])
    result = _run([gh, "auth", "status"], os.getcwd(), _GH_TIMEOUT)
    if result["code"] == 0:
        state = {"installed": True, "authenticated": True, "reason": None}
    elif result["timedOut"]:
        state = {"installed": True, "authenticated": False, "reason": "The GitHub CLI did not answer in time."}
    else:
        state = {"installed": True, "authenticated": False,
                 "reason": "The GitHub CLI is not signed in. Run `gh auth login` on this PC."}
    with _CACHE_LOCK:
        _GH_CACHE[gh] = (time.monotonic(), state)
    return dict(state)


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_rollup(args[0], result))
def _checks_summary(rollup: Any) -> str | None:
    if not isinstance(rollup, list) or not rollup:
        return None
    failing = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
    pending = {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}
    state = "passing"
    for check in rollup:
        if not isinstance(check, dict):
            continue
        status = str(check.get("status") or "").upper()
        outcome = str(check.get("conclusion") or check.get("state") or "").upper()
        if outcome in failing:
            return "failing"
        if (status and status != "COMPLETED") or outcome in pending:
            state = "pending"
    return state


def _pull_request(gh: str, root: str, branch: str) -> tuple[dict[str, Any] | None, str | None]:
    key = (_norm(root), branch)
    with _CACHE_LOCK:
        cached = _PR_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _PR_TTL:
            return cached[1], cached[2]
    result = _run([gh, "pr", "view", "--json", "number,title,url,state,statusCheckRollup"], root, _GH_TIMEOUT)
    pull: dict[str, Any] | None = None
    error: str | None = None
    if result["code"] == 0:
        try:
            data = json.loads(result["out"])
            pull = {"number": data.get("number"), "title": data.get("title"), "url": data.get("url"),
                    "state": str(data.get("state") or "").lower() or None,
                    "checks": _checks_summary(data.get("statusCheckRollup"))}
        except (ValueError, AttributeError):
            error = "The GitHub CLI returned an unreadable pull request."
    elif result["timedOut"]:
        error = "The GitHub CLI did not answer in time."
    elif "no pull requests found" not in result["err"].lower():
        error = _clip(result["err"].strip(), 300) or "The GitHub CLI could not read the pull request."
    _proofs.check_github_result(result, pull, error)
    with _CACHE_LOCK:
        _PR_CACHE[key] = (time.monotonic(), pull, error)
    return pull, error


def _empty(cwd: str | None, exists: bool) -> dict[str, Any]:
    return {
        "cwd": cwd, "exists": exists, "repo": None, "branch": None, "detached": False, "upstream": None,
        "ahead": None, "behind": None, "worktrees": [], "changes": [], "changesTruncated": False,
        "pullRequest": None, "gh": {"installed": False, "authenticated": False, "reason": None},
    }


def invalidate(cwd: str | None = None) -> None:
    with _CACHE_LOCK:
        if cwd is None:
            _STATE_CACHE.clear()
            _PR_CACHE.clear()
        else:
            _STATE_CACHE.pop(_norm(cwd), None)
            _PR_CACHE.clear()


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_state(result))
def workspace_state(cwd: str | None) -> dict[str, Any]:
    """Read-only git and GitHub picture of ``cwd``, cached for a few seconds."""
    if not cwd or not isinstance(cwd, str):
        return _empty(None, False)
    key = _norm(cwd)
    with _CACHE_LOCK:
        cached = _STATE_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _STATE_TTL:
            return json.loads(json.dumps(cached[1]))
    state = _compute_state(cwd)
    with _CACHE_LOCK:
        _STATE_CACHE[key] = (time.monotonic(), state)
    return json.loads(json.dumps(state))


def _compute_state(cwd: str) -> dict[str, Any]:
    if not os.path.isdir(cwd):
        return _empty(cwd, False)
    state = _empty(cwd, True)
    # `gh auth status` asks GitHub, so it runs beside the local git reads.
    gh_result: dict[str, Any] = {}
    gh_thread = threading.Thread(target=lambda: gh_result.update(_gh_state()), name="connected-gh-auth", daemon=True)
    gh_thread.start()
    root, problem = _repo_root(cwd)
    if problem:
        state["gitError"] = problem
    if root is None:
        gh_thread.join(_GH_TIMEOUT + 5)
        state["gh"] = dict(gh_result) or state["gh"]
        return state

    status = _git(root, "status", "--porcelain=v2", "--branch", "-z")
    parsed = _parse_status(status["out"]) if status["code"] == 0 else {"branch": {}, "entries": []}
    head = parsed["branch"].get("head")
    detached = head in (None, "(detached)")
    branch = None if detached else head
    upstream = parsed["branch"].get("upstream")
    state.update(branch=branch, detached=bool(head == "(detached)"), upstream=upstream,
                 ahead=parsed["branch"].get("ahead") if upstream else None,
                 behind=parsed["branch"].get("behind") if upstream else None)

    entries = parsed["entries"]
    has_head = parsed["branch"].get("oid") not in (None, "(initial)")
    if has_head:
        counts = _parse_numstat(_git(root, "diff", "--numstat", "-z", "HEAD", "--")["out"])
    else:
        counts = _parse_numstat(_git(root, "diff", "--numstat", "-z", "--cached", "--")["out"])
        counts.update(_parse_numstat(_git(root, "diff", "--numstat", "-z", "--")["out"]))
    changes, counted, observed_untracked = [], 0, {}
    for entry in entries[:MAX_CHANGES]:
        path = entry["path"]
        if entry["xy"] == "??":
            if counted < _UNTRACKED_COUNT_FILES:
                added, removed = _count_lines(Path(root) / path)
                counted += 1
            else:
                added, removed = None, None
            observed_untracked[path] = (added, removed)
        else:
            added, removed = counts.get(path, (None, None))
        row: dict[str, Any] = {"path": path.replace("\\", "/"), "status": _status_word(entry["xy"]),
                               "additions": added, "deletions": removed, "staged": entry["xy"][:1] not in (".", "?")}
        if entry.get("oldPath"):
            row["oldPath"] = entry["oldPath"]
        changes.append(row)
    state["changes"] = changes
    state["changesTruncated"] = len(entries) > MAX_CHANGES
    state["worktrees"] = _worktrees(root)

    remote = _remote_url(root, branch, upstream)
    github = _github_from_remote(remote) if remote else None
    state["repo"] = {"root": root, "name": github["name"] if github else Path(root).name,
                     "remoteUrl": remote, "github": github}

    gh_thread.join(_GH_TIMEOUT + 5)
    gh_state = dict(gh_result) or state["gh"]
    state["gh"] = gh_state
    if gh_state["installed"] and gh_state["authenticated"] and github and branch:
        # Direct API with ETag/conditional reads and one shared rate gate (github_client, after T3 Code);
        # the gh CLI stays only as the fallback when the API path cannot answer.
        from ..github_client import pull_request_state
        pull, error = pull_request_state(remote, branch)
        if error and pull is None and not error.startswith("GitHub is limiting"):
            pull, error = _pull_request(_which("gh") or "gh", root, branch)
        state["pullRequest"] = pull
        if error:
            state["pullRequestError"] = error
    _proofs.check_state(state, parsed=parsed, counts=counts, root=root, untracked=observed_untracked)
    return state


def _safe_relpath(root: str, path: str) -> str:
    """Repo-relative POSIX path for ``path``, refusing anything that leaves the repo."""
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        raise WorkspaceError("invalid_path", "A file path is required.")
    candidate = Path(path) if os.path.isabs(path) else Path(root) / path
    real_root, real = os.path.realpath(root), os.path.realpath(candidate)
    try:
        inside = os.path.commonpath([_norm(real_root), _norm(real)]) == _norm(real_root)
    except ValueError:  # different drives
        inside = False
    if not inside or _norm(real) == _norm(real_root):
        raise WorkspaceError("path_outside_repo", "That path is outside this session's repository.")
    return Path(os.path.relpath(real, real_root)).as_posix()


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_diff(result))
def file_diff(cwd: str | None, path: str) -> dict[str, Any]:
    """Bounded unified diff of one file against HEAD (or the whole file when untracked)."""
    if not cwd or not os.path.isdir(cwd):
        raise WorkspaceError("no_workspace", "This session has no folder on this PC.", 404)
    root, problem = _repo_root(cwd)
    if root is None:
        raise WorkspaceError("not_a_repo", problem or "This session's folder is not a git repository.")
    rel = _safe_relpath(root, path)
    git = _which("git")
    if not git:
        raise WorkspaceError("git_missing", "Git is not installed on this PC.", 503)
    tracked = _git(root, "ls-files", "--error-unmatch", "--", rel)["code"] == 0
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD")["code"] == 0
    common = ["--no-color", "--no-ext-diff", "--unified=3"]
    if tracked or (head and _git(root, "cat-file", "-e", f"HEAD:{rel}")["code"] == 0):
        # A staged rename only reads as one when both of its paths are named.
        moved = [entry["oldPath"] for entry in _parse_status(
            _git(root, "status", "--porcelain=v2", "-z")["out"])["entries"]
            if entry.get("oldPath") and entry["path"] == rel]
        paths = [rel, *moved[:1]]
        args = ([git, "diff", *common, "-M", "HEAD", "--", *paths] if head
                else [git, "diff", *common, "-M", "--cached", "--", *paths])
    else:
        args = [git, "diff", *common, "--no-index", "--", "/dev/null", rel]
    code, data, truncated = _run_capped(args, root, _GIT_TIMEOUT, MAX_PATCH_BYTES)
    if code is None and not truncated:
        raise WorkspaceError("diff_failed", "Git did not produce a diff for this file.", 502)
    patch = data.decode("utf-8", errors="replace")
    if truncated:
        patch = patch.rsplit("\n", 1)[0] + "\n... [diff truncated]\n"
    return {"path": rel, "patch": patch, "truncated": truncated}


def git_action(cwd: str | None, action: str, *, message: str | None = None, title: str | None = None,
               body: str | None = None, confirm: Any = False) -> dict[str, Any]:
    """Commit tracked changes, push the branch, or open a pull request. Needs ``confirm: true``."""
    if action not in {"commit", "push", "create_pr"}:
        raise WorkspaceError("unknown_action", "Choose commit, push or create_pr.")
    if confirm is not True:
        raise WorkspaceError("confirmation_required", "This action changes your repository. Confirm it to continue.")
    if not cwd or not os.path.isdir(cwd):
        raise WorkspaceError("no_workspace", "This session has no folder on this PC.", 404)
    root, problem = _repo_root(cwd)
    if root is None:
        raise WorkspaceError("not_a_repo", problem or "This session's folder is not a git repository.")
    if not _which("git"):
        raise WorkspaceError("git_missing", "Git is not installed on this PC.", 503)
    try:
        if action == "commit":
            text = str(message or "").strip()
            if not text or len(text) > 5000:
                raise WorkspaceError("message_required", "A commit message of 1 to 5,000 characters is required.")
            result = _git(root, "commit", "-a", "-m", text, timeout=_ACTION_TIMEOUT, read_only=False)
            return _action_result(result)
        if action == "push":
            branch = _git(root, "symbolic-ref", "--short", "HEAD")["out"].strip()
            if not branch:
                raise WorkspaceError("detached_head", "Switch to a branch before pushing.")
            upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
            if upstream["code"] == 0 and upstream["out"].strip():
                result = _git(root, "push", timeout=_ACTION_TIMEOUT, read_only=False)
            else:
                remotes = _git(root, "remote")["out"].split()
                remote = "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None
                if not remote:
                    raise WorkspaceError("no_remote", "This repository has no remote to push to.")
                result = _git(root, "push", "--set-upstream", remote, branch, timeout=_ACTION_TIMEOUT, read_only=False)
            return _action_result(result)
        heading = str(title or "").strip()
        if not heading or len(heading) > 500:
            raise WorkspaceError("title_required", "A pull request title of 1 to 500 characters is required.")
        gh = _which("gh")
        if not gh:
            raise WorkspaceError("gh_missing", "The GitHub CLI (gh) is not installed on this PC.", 503)
        if not _gh_state()["authenticated"]:
            raise WorkspaceError("gh_not_signed_in", "The GitHub CLI is not signed in. Run `gh auth login` on this PC.", 503)
        result = _run([gh, "pr", "create", "--title", heading, "--body", str(body or "")], root, _ACTION_TIMEOUT)
        outcome = _action_result(result)
        urls = re.findall(r"https://github\.com/\S+", result["out"])
        if urls and outcome["ok"]:
            outcome["url"] = urls[-1].rstrip(".,")
        return outcome
    finally:
        invalidate(cwd)


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_action(args[0], result))
def _action_result(result: dict[str, Any]) -> dict[str, Any]:
    output = "\n".join(part for part in (result["out"].strip(), result["err"].strip()) if part)
    if result["timedOut"]:
        output = (output + "\n" if output else "") + "The command did not finish in time and was stopped."
    return {"ok": result["code"] == 0, "output": _clip(output)}
