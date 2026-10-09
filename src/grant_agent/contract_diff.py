"""Git-backed changed-line inventory for impact-scoped contract coverage."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _git(repo: Path, *args: str) -> bytes:
    command = ["git", "-c", "core.quotepath=false", "-C", str(repo), *args]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {detail}")
    return result.stdout


def _records(raw: bytes):
    """Read --name-status -z records, including two-path rename records."""
    fields = raw.split(b"\0")
    at = 0
    while at < len(fields) and fields[at]:
        status = os.fsdecode(fields[at]); at += 1
        count = 2 if status.startswith(("R", "C")) else 1
        paths = [os.fsdecode(value) for value in fields[at:at + count]]
        at += count
        if len(paths) == count:
            yield status, paths


def _repo_path(repo: Path, relative: str) -> Path | None:
    """Return a contained working path; reject path traversal and absolute names."""
    candidate = (repo / relative).resolve()
    try:
        candidate.relative_to(repo.resolve())
    except ValueError:
        return None
    return candidate


def _line_inventories(repo: Path, diff_args: tuple[str, ...], relatives: list[str]) -> dict[str, tuple[list[int], bool, str | None]]:
    """Read one unified diff and map its new-side hunks to repository paths.

    Running Git once per changed file made release admission scale with the
    number of changed paths. A single patch keeps both process startup and Git
    object traversal bounded. Git's unquoted ``+++ b/<path>`` header preserves
    ordinary spaces and Unicode; unusual newline-containing paths safely get
    file-level coverage because Git quotes those headers.
    """
    if not relatives:
        return {}
    # Windows CreateProcess caps the complete command line at 32,767 UTF-16
    # characters. Keep each pathspec batch far below that limit, including Git
    # and ref arguments. This preserves batched execution for large changesets.
    batches, batch, size = [], [], 0
    for relative in relatives:
        pathspec = f":(literal){relative}"
        if batch and size + len(pathspec) + 1 > 9000:
            batches.append(batch); batch=[]; size=0
        batch.append((relative, pathspec)); size += len(pathspec) + 1
    if batch:
        batches.append(batch)
    by_header = {"+++ b/" + name: name for name in relatives}
    collected: dict[str, set[int]] = {name: set() for name in relatives}
    deleted_only: set[str] = set()
    for entries in batches:
        raw = _git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                   "--no-renames", "--unified=0", *diff_args, "--",
                   *(pathspec for _, pathspec in entries))
        current = None
        for row in raw.decode("utf-8", "replace").splitlines():
            if row.startswith("+++ "):
                current = by_header.get(row)
                if current is None and row.endswith("\t"):
                    # Git adds a tab delimiter for paths needing an extended
                    # header terminator (including some non-ASCII names).
                    current = by_header.get(row[:-1])
                continue
            if current is None:
                continue
            match = _HUNK.match(row)
            if not match:
                continue
            start = int(match.group(3)); count = int(match.group(4) or "1")
            if count:
                collected[current].update(range(start, start + count))
            else:
                # Removed lines have no new-side location. Keep file-level scrutiny.
                deleted_only.add(current)
    result = {}
    for relative in relatives:
        lines = collected[relative]
        if lines:
            result[relative] = (sorted(lines), True, None)
        elif relative in deleted_only:
            result[relative] = ([], False, "removed_lines_have_no_new_side_lines")
        else:
            # Includes binary changes and paths Git had to quote in its patch.
            result[relative] = ([], False, "binary_or_no_line_mapping")
    return result


def _untracked_lines(path: Path) -> tuple[list[int], bool, str | None]:
    try:
        data = path.read_bytes()
        if b"\0" in data:
            return [], False, "binary_file"
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeError):
        return [], False, "non_utf8_or_unreadable_file"
    return list(range(1, len(text.splitlines()) + 1)), True, None


def changed_lines(repo, since, *, committed_only=False, paths=None):
    """Return changed paths and new-side line numbers from ``since``.

    Working mode compares the base ref with the index and working tree, then
    includes untracked files. ``committed_only`` compares ``since`` to HEAD.
    Git deletions are explicitly labelled; consumers can exempt only those
    paths. Binary files and line-only deletions request file-level coverage.
    Optional ``paths`` limits the scan to repository-relative names.
    """
    root = Path(repo).resolve()
    if not root.is_dir():
        raise ValueError("repo must be an existing directory")
    if committed_only:
        diff_args = (since, "HEAD")
    else:
        diff_args = (since,)
    raw = _git(root, "diff", "--name-status", "-z", "--no-renames", *diff_args, "--")
    wanted = None if paths is None else {str(item).replace("\\", "/") for item in paths}
    result = {}
    tracked = {}
    for status, entries in _records(raw):
        relative = entries[0].replace("\\", "/")
        if wanted is not None and relative not in wanted:
            continue
        if status == "D":
            result[relative] = {"status": "deleted", "lines": [], "lineData": False,
                                "source": "git"}
            continue
        if status == "A":
            candidate = _repo_path(root, relative)
            if candidate is None:
                continue
            line_nums, has_lines, reason = _untracked_lines(candidate)
            result[relative] = {"status": "added", "lines": line_nums,
                                "lineData": has_lines, "source": "git",
                                **({"fallback": reason} if reason else {})}
            continue
        tracked[relative] = "changed"
    inventories = _line_inventories(root, diff_args, list(tracked))
    for relative in tracked:
        line_nums, has_lines, reason = inventories[relative]
        result[relative] = {"status": "changed", "lines": line_nums,
                            "lineData": has_lines, "source": "git",
                            **({"fallback": reason} if reason else {})}
    if not committed_only:
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
        for raw_path in untracked.split(b"\0"):
            if not raw_path:
                continue
            relative = os.fsdecode(raw_path).replace("\\", "/")
            if wanted is not None and relative not in wanted:
                continue
            candidate = _repo_path(root, relative)
            if candidate is None or not candidate.is_file():
                continue
            line_nums, has_lines, reason = _untracked_lines(candidate)
            result[relative] = {"status": "added", "lines": line_nums,
                                "lineData": has_lines, "source": "working_tree",
                                **({"fallback": reason} if reason else {})}
    return result


def trace_scope(repo, since, *, committed_only=False, details=None):
    """Restrict trace events to current behavioural Python/configuration changes.

    Configuration rows are invalidation inputs only. Filtering path roles before
    reading patch hunks avoids collecting archived evidence and generated output.
    """
    import json
    from .contract_coverage import classify

    root = Path(repo).resolve()
    policy = json.loads((root / 'config/contract_path_policy.json').read_text(encoding='utf-8'))
    suffixes = {'.py', '.pyw', '.json', '.cl', '.toml', '.yaml', '.yml', '.xml'}
    if details is None:
        refs = (since, 'HEAD') if committed_only else (since,)
        names = [entries[0] for status, entries in _records(_git(root, 'diff', '--name-status', '-z', '--no-renames', *refs, '--'))
                 if status != 'D']
        if not committed_only:
            names.extend(os.fsdecode(name) for name in _git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0') if name)
        paths = [name for name in names if Path(name).suffix.lower() in suffixes
                 and classify(name, policy)['kind'] in {'behaviour', 'unknown'}]
        details = changed_lines(root, since, committed_only=committed_only, paths=paths)
    return {name: row for name, row in details.items()
            if row.get('status') != 'deleted' and Path(name).suffix.lower() in suffixes
            and classify(name, policy)['kind'] in {'behaviour', 'unknown'}}
