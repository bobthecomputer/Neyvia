"""Where a new chat can run: recent folders, local git projects, GitHub repos.

GitHub data comes only from the user's own signed-in `gh` CLI; Neyvia never
reads or stores a token. Cloning and worktree creation require confirm=True.
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

from ..subprocess_utils import hidden_windows_subprocess_kwargs
from .. import proofs_a_sessions as _proofs

_CACHE: dict[str, tuple[float, Any]] = {}
_LOCK = threading.Lock()
_GITHUB = re.compile(r"github\.com[:/](?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$", re.IGNORECASE)
_BRANCH = re.compile(r"^[\w][\w./-]{0,120}$")


def projects_root() -> Path:
    configured = os.environ.get("NEYVIA_PROJECTS_DIR")
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return Path(configured).expanduser() if configured else home / "Projects"


def _run(args: list[str], cwd: Path | None = None, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, **hidden_windows_subprocess_kwargs())


def _cached(key: str, ttl: float, produce):
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
    value = produce()
    with _LOCK:
        _CACHE[key] = (time.monotonic(), value)
    return value


def _git_dir(path: Path) -> Path | None:
    marker = path / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():  # a worktree: ".git" names the real git dir
        text = marker.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            target = Path(text[7:].strip())
            return target if target.is_absolute() else (path / target).resolve()
    return None


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_folder_info(args[0], result))
def _git_info(path: Path) -> dict[str, Any] | None:
    """Branch and GitHub remote read from git's own files: no process per folder."""
    git_dir = _git_dir(path)
    if git_dir is None:
        return None
    branch = None
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if head.startswith("ref: refs/heads/"):
            branch = head[len("ref: refs/heads/"):]
    except OSError:
        pass
    config_dir = git_dir
    commondir = git_dir / "commondir"
    if commondir.is_file():
        config_dir = (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve()
    github = None
    try:
        section = ""
        for line in (config_dir / "config").read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line
            elif section == '[remote "origin"]' and line.startswith("url"):
                match = _GITHUB.search(line.split("=", 1)[1].strip())
                github = f"{match['owner']}/{match['name']}" if match else None
    except OSError:
        pass
    return {"branch": branch, "github": github}


def local_projects(limit: int = 60) -> list[dict[str, Any]]:
    def produce():
        root = projects_root()
        if not root.is_dir():
            return []
        rows = []
        for child in root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            try:
                updated = child.stat().st_mtime
            except OSError:
                continue
            rows.append((updated, child))
        rows.sort(reverse=True)
        result, selected, infos = [], rows[:limit], []
        for updated, child in selected:
            info = _git_info(child)
            infos.append(info)
            result.append({
                "path": str(child), "name": child.name, "isGit": info is not None,
                "branch": (info or {}).get("branch"), "github": (info or {}).get("github"),
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(updated)),
            })
        _proofs.check_catalogue(selected, infos, result)
        return result
    # Picker calls are already debounced. Observe the directory on every open
    # so folders created by another process are immediately selectable.
    return produce()


def github_status() -> dict[str, Any]:
    def produce():
        gh = shutil.which("gh")
        if not gh:
            return {"installed": False, "authenticated": False, "reason": "GitHub CLI isn't installed on this PC."}
        status = _run([gh, "auth", "status"], timeout=10)
        ok = status.returncode == 0
        return {"installed": True, "authenticated": ok,
                "reason": None if ok else "Sign in on your PC with `gh auth login` to see your repositories."}
    return _cached("gh-status", 60, produce)


def github_repos(limit: int = 40) -> list[dict[str, Any]]:
    status = github_status()
    if not status["authenticated"]:
        return []

    def produce():
        result = _run([shutil.which("gh") or "gh", "repo", "list", "--limit", str(limit), "--json",
                       "nameWithOwner,description,updatedAt,url,isPrivate,defaultBranchRef"], timeout=20)
        if result.returncode != 0:
            return []
        try:
            rows = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []
        local = {row["github"].lower(): row["path"] for row in local_projects() if row.get("github")}
        return [{
            "repo": row.get("nameWithOwner"), "description": (row.get("description") or "")[:200],
            "updatedAt": row.get("updatedAt"), "url": row.get("url"), "private": bool(row.get("isPrivate")),
            "defaultBranch": (row.get("defaultBranchRef") or {}).get("name"),
            "localPath": local.get(str(row.get("nameWithOwner") or "").lower()),
        } for row in rows if row.get("nameWithOwner")]
    return _cached("gh-repos", 120, produce)


def _matches(needle: str, *values: Any) -> bool:
    return not needle or any(needle in str(value or "").lower() for value in values)


def candidates(recent: list[dict[str, Any]] | None = None, query: str = "") -> dict[str, Any]:
    """Fast part of the folder picker: recent chat folders and local projects."""
    needle = query.strip().lower()
    local = local_projects()
    # A typed absolute path is independent of the Projects catalogue and drive.
    path = Path(query.strip()).expanduser()
    direct = None
    if query.strip() and path.is_absolute() and path.is_dir():
        info = _git_info(path)
        direct = {"path": str(path), "name": path.name or str(path), "isGit": info is not None,
                  "branch": (info or {}).get("branch"), "github": (info or {}).get("github")}
    result = {
        "recent": [row for row in (recent or []) if _matches(needle, row.get("path"), row.get("name"))][:8],
        "local": [row for row in local if _matches(needle, row["name"], row.get("github"))][:30],
        "projectsRoot": str(projects_root()),
        "direct": direct,
    }
    _proofs.check_candidates(recent, local, query, result, projects_root())
    return result


def github_candidates(query: str = "") -> dict[str, Any]:
    """Slow part (one `gh` call, cached): the user's GitHub repositories."""
    needle = query.strip().lower()
    return {"gh": github_status(), "repos": [row for row in github_repos() if _matches(needle, row["repo"], row.get("description"))][:30]}


def clone(repo: str, *, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("Cloning needs confirmation.")
    if not re.fullmatch(r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*", repo or ""):
        raise ValueError("Choose a repository as owner/name.")
    if not github_status()["authenticated"]:
        raise ValueError("Sign in to GitHub CLI on your PC first (`gh auth login`).")
    target = projects_root() / repo.split("/", 1)[1]
    if target.exists():
        return {"path": str(target), "existed": True}
    projects_root().mkdir(parents=True, exist_ok=True)
    result = _run([shutil.which("gh") or "gh", "repo", "clone", repo, str(target)], timeout=600)
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout or "Clone failed.").strip()[-800:])
    with _LOCK:
        _CACHE.pop("local", None)
        _CACHE.pop("gh-repos", None)
    return {"path": str(target), "existed": False}


def create_worktree(path: str, branch: str, *, confirm: bool, state_root: Path | None = None) -> dict[str, Any]:
    """Create `<repo>-<branch>` beside the repository on a new branch."""
    if not confirm:
        raise ValueError("Creating a worktree needs confirmation.")
    repo = Path(path).resolve()
    if not (repo / ".git").exists():
        raise ValueError("That folder isn't a git repository.")
    if not _BRANCH.fullmatch(branch or "") or ".." in branch:
        raise ValueError("Use a simple branch name, like fix/login-copy.")
    target = repo.parent / f"{repo.name}-{branch.replace('/', '-')}"
    if target.exists():
        raise ValueError(f"{target} already exists.")
    from .folder_jobs import start
    return start(state_root or repo, repo, target, branch)
