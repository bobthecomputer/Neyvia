"""Git effects for Parallel; all removal is confined to this run's worktree root."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import shutil
import subprocess
from functools import lru_cache


def git(folder, *args, check=True):
    result = subprocess.run(['git', '-C', str(folder), *args], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=120)
    if check and result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Git command failed')
    return result


def clean(folder):
    # The owned worktree container is Git metadata in practice, not user work.
    return not git(folder, 'status', '--porcelain', '--untracked-files=all', '--', '.',
                   ':(exclude).neyvia-worktrees').stdout.strip()


def ahead(folder, base, branch='HEAD'):
    if branch == 'HEAD':
        metadata = Path(folder) / '.git'
        if metadata.is_file():
            metadata = Path(metadata.read_text(encoding='utf-8').strip().removeprefix('gitdir: '))
            if not metadata.is_absolute():
                metadata = Path(folder) / metadata
        head = (metadata / 'HEAD').read_bytes()
        common = metadata
        if (metadata / 'commondir').is_file():
            common = (metadata / (metadata / 'commondir').read_text().strip()).resolve()
        if head.startswith(b'ref: '):
            ref = common / head.decode().strip()[5:]
            stamp = ref.read_bytes() if ref.is_file() else (common / 'packed-refs').read_bytes()
        else:
            stamp = head
        return _head_ahead(str(Path(folder).resolve()), base, head, stamp)
    return int(git(folder, 'rev-list', '--count', base + '..' + branch).stdout.strip())


@lru_cache(maxsize=512)
def _head_ahead(folder, base, head, stamp):
    # Cache only while the actual HEAD/ref bytes are unchanged, never by time.
    return int(git(folder, 'rev-list', '--count', base + '..HEAD').stdout.strip())


def merged(repo, branch, integration):
    return git(repo, 'merge-base', '--is-ancestor', branch, integration, check=False).returncode == 0


def worktrees(repo):
    return [line[9:] for line in git(repo, 'worktree', 'list', '--porcelain').stdout.splitlines()
            if line.startswith('worktree ')]


def unlink_reparse_points(path):
    """Do not recurse into symlinks/junctions, including broken links."""
    for item in os.scandir(path):
        info = item.stat(follow_symlinks=False)
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            if stat.S_ISDIR(info.st_mode):
                os.rmdir(item.path)
            else:
                os.unlink(item.path)
        elif item.is_dir(follow_symlinks=False):
            unlink_reparse_points(item.path)


def owned_worktree(repo, run, raw):
    expected = Path(repo) / '.neyvia-worktrees' / run
    target = Path(raw)
    if any(p.is_symlink() or p.is_junction() for p in (expected, expected.parent)):
        raise ValueError('Refusing removal through a reparse worktree container')
    # Check both lexical and resolved locations before any unlink or deletion.
    if target.parent != expected or target.resolve().parent != expected.resolve():
        raise ValueError('Refusing worktree removal outside the owned run')
    if target.is_symlink() or target.is_junction():
        raise ValueError('Worktree root is a reparse point')
    return target


def worktree_status(repo, run, raw):
    """An orphan must not inherit the parent checkout's Git status."""
    target = owned_worktree(repo, run, raw)
    if not target.exists():
        return 'missing'
    marker = target / '.git'
    if not marker.exists():
        return 'orphan'
    if not marker.is_file() or marker.is_symlink():
        raise ValueError('Expected owned linked-worktree metadata: ' + str(target))
    pointer = marker.read_text(encoding='utf-8').strip()
    if not pointer.startswith('gitdir: '):
        raise ValueError('Invalid linked-worktree metadata: ' + str(target))
    metadata = Path(pointer[8:])
    if not metadata.is_absolute():
        metadata = target / metadata
    if not metadata.is_dir():
        return 'orphan'
    top = git(target, 'rev-parse', '--show-toplevel').stdout.strip()
    if Path(top).resolve() != target.resolve():
        raise ValueError('Worktree points to a different checkout: ' + str(target))
    return 'clean' if clean(target) else 'dirty'


def remove_worktree(repo, run, raw, *, uninitialized=False):
    target = owned_worktree(repo, run, raw)
    status = worktree_status(repo, run, raw)
    if status == 'dirty' and not uninitialized:
        raise ValueError('Worktree has uncommitted work: ' + str(target))
    method = 'already_absent' if status == 'missing' else 'orphan_removed'
    if target.exists():
        unlink_reparse_points(target)
        if status in {'clean', 'dirty'}:
            result = git(repo, 'worktree', 'remove', *(['--force'] if uninitialized else []), str(target), check=False)
            method = 'git_removed'
            if result.returncode:
                # Git can unregister a tree before failing to delete its folder.
                # A still-registered healthy tree must keep its original refusal.
                if target.exists() and worktree_status(repo, run, raw) != 'orphan':
                    raise ValueError(result.stderr.strip() or result.stdout.strip())
                method = 'partial_remove_recovered'
        if target.exists():
            # Revalidate after Git's effects and unlink again before recursion.
            owned_worktree(repo, run, raw)
            unlink_reparse_points(target)
            shutil.rmtree(target)
    git(repo, 'worktree', 'prune', '--expire', 'now')
    if target.exists():
        raise ValueError('Worktree removal did not remove ' + str(target))
    if str(target).replace('\\', '/').casefold() in {p.replace('\\', '/').casefold() for p in worktrees(repo)}:
        raise ValueError('Owned worktree registration remains: ' + str(target))
    return {'worktree': str(target), 'status': 'removed', 'method': method}


def conflict_sides(folder, files):
    result = {}
    for name in files:
        result[name] = {side: git(folder, 'show', ':' + number + ':' + name, check=False).stdout[-12000:]
                        for side, number in [('base', '1'), ('ours', '2'), ('theirs', '3')]}
    return result


def verify_resolution(folder, files):
    if git(folder, 'diff', '--name-only', '--diff-filter=U').stdout.strip():
        raise ValueError('Stage all conflict resolutions before resolved')
    if git(folder, 'diff', '--name-only').stdout.strip():
        raise ValueError('Resolution has unstaged changes')
    for name in files:
        blob = git(folder, 'show', ':' + name, check=False)
        if blob.returncode == 0 and any(line.startswith(('<<<<<<< ', '=======', '>>>>>>> '))
                                        for line in blob.stdout.splitlines()):
            raise ValueError('Conflict markers remain in ' + name)
