from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


_IGNORED_DIRECTORY_NAMES = {
    ".agent_control",
    ".codex",
    ".git",
    ".kimi-code",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "output",
    "target",
    "test-output",
    "test-results",
    "tmp-ui-checks",
}
_IGNORED_SECRET_SUFFIXES = (".key", ".p12", ".pem", ".pfx")
_IGNORED_ARCHIVE_SUFFIXES = (".tar", ".zip")
_IGNORED_SECRET_SUFFIXES_CASEFOLDED = tuple(
    suffix.casefold() for suffix in _IGNORED_SECRET_SUFFIXES
)
_IGNORED_ARCHIVE_SUFFIXES_CASEFOLDED = tuple(
    suffix.casefold() for suffix in _IGNORED_ARCHIVE_SUFFIXES
)
_DISPOSABLE_DIRECTORY_PREFIXES = (
    ".pytest-local-",
    "focused-test-tmp-",
    "pytest-of-",
)
_ROOT_DISPOSABLE_DIRECTORY_PREFIXES = (
    ".tmp-pytest-",
    "focused-test-",
    "pytest-dynamic-basetemp-",
)
_ROOT_DISPOSABLE_DIRECTORY_NAMES = frozenset({".tmp-test-deps"})
_IGNORED_DIRECTORY_NAMES_CASEFOLDED = frozenset(
    name.casefold() for name in _IGNORED_DIRECTORY_NAMES
)
_EXPLICIT_INCLUDE_FORBIDDEN_DIRECTORY_NAMES = frozenset(
    _IGNORED_DIRECTORY_NAMES_CASEFOLDED - {"dist"}
)


def _copy_ignore(
    _directory: str,
    names: list[str],
    *,
    source_root: Path | None = None,
) -> set[str]:
    return {
        name
        for name in names
        if name.casefold() in _IGNORED_DIRECTORY_NAMES_CASEFOLDED
        or _is_disposable_verification_directory(
            Path(_directory), name, source_root=source_root
        )
        or (
            source_root is not None
            and Path(_directory) == source_root
            and name.casefold() == "verification-workspaces"
        )
        or _is_read_only_workspace_control_directory(Path(_directory), name)
        or _is_link_like(Path(_directory) / name)
        or name.casefold().endswith(
            (*_IGNORED_SECRET_SUFFIXES_CASEFOLDED, *_IGNORED_ARCHIVE_SUFFIXES_CASEFOLDED)
        )
        or (
            name.casefold().startswith(".env")
            and name.casefold() != ".env.example"
        )
    }


def _is_disposable_verification_directory(
    parent: Path,
    name: str,
    *,
    source_root: Path | None = None,
) -> bool:
    """Ignore Neyvia-owned test scratch without hiding verification evidence."""

    normalized_name = name.casefold()
    if (
        source_root is not None
        and parent == source_root
        and (
            normalized_name in _ROOT_DISPOSABLE_DIRECTORY_NAMES
            or normalized_name.startswith(
                tuple(
                    prefix.casefold() for prefix in _ROOT_DISPOSABLE_DIRECTORY_PREFIXES
                )
            )
        )
    ):
        return True
    if normalized_name.startswith(
        tuple(prefix.casefold() for prefix in _DISPOSABLE_DIRECTORY_PREFIXES)
    ):
        return True
    if normalized_name in {"pytest-cache", "pytest-results"}:
        return True
    return (
        parent.name.casefold() == "verification-workspaces"
        and normalized_name.startswith("neyvia-")
        and normalized_name.endswith(("-pytest", "-cache"))
    )


def _is_read_only_workspace_control_directory(parent: Path, name: str) -> bool:
    return (
        parent.name.casefold() == ".agent_control"
        and name.casefold() == "read_only_workspaces"
    )


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except PermissionError:
        raise
    except OSError:
        return True


def _resolve_include_path(
    source_root: Path,
    raw_path: object,
) -> tuple[Path, Path] | None:
    """Return a safe source/destination-relative pair for one explicit path."""

    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    relative = Path(raw_path.strip())
    if (
        relative.is_absolute()
        or bool(relative.drive)
        or not relative.parts
        or any(part in {"..", ""} for part in relative.parts)
    ):
        return None

    source_path = source_root.joinpath(relative)
    cursor = source_root
    for part in relative.parts:
        part_folded = part.casefold()
        if (
            part_folded in _EXPLICIT_INCLUDE_FORBIDDEN_DIRECTORY_NAMES
            or part_folded == "verification-workspaces"
            or part_folded.endswith(
                (*_IGNORED_SECRET_SUFFIXES_CASEFOLDED, *_IGNORED_ARCHIVE_SUFFIXES_CASEFOLDED)
            )
            or (
                part_folded.startswith(".env")
                and part_folded != ".env.example"
            )
            or _is_disposable_verification_directory(
                cursor, part, source_root=source_root
            )
        ):
            return None
        cursor = cursor / part
        if _is_link_like(cursor):
            return None

    try:
        resolved_path = source_path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if (
        resolved_path == source_root
        or not resolved_path.is_relative_to(source_root)
        or not (resolved_path.is_file() or resolved_path.is_dir())
    ):
        return None
    return resolved_path, relative


def _copy_explicit_include(
    source_root: Path,
    mirror: Path,
    include_paths: Sequence[object] | None,
) -> None:
    """Copy only explicitly assigned, validated paths into the mirror."""

    if not isinstance(include_paths, (list, tuple)):
        return
    for raw_path in include_paths:
        resolved_path = _resolve_include_path(source_root, raw_path)
        if resolved_path is None:
            continue
        source_path, relative = resolved_path
        destination = mirror / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(
                source_path,
                destination,
                symlinks=False,
                dirs_exist_ok=True,
                ignore=lambda directory, names: _copy_ignore(
                    directory,
                    names,
                    source_root=source_root,
                ),
            )
        else:
            shutil.copy2(source_path, destination, follow_symlinks=False)


@contextmanager
def isolated_read_only_workspace(
    source: Path,
    *,
    state_root: Path,
    include_paths: Sequence[object] | None = None,
) -> Iterator[Path]:
    """Yield a disposable source mirror for a non-mutating agent turn.

    Provider permission controls remain the first line of defense. The mirror
    ensures an unexpected write never reaches the operator's real checkout.
    """

    resolved_source = source.expanduser().resolve(strict=True)
    if not resolved_source.is_dir():
        raise ValueError(f"Read-only source is not a directory: {resolved_source}")
    temporary_parent = state_root / ".agent_control" / "read_only_workspaces"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="neyvia-readonly-",
        dir=str(temporary_parent),
    ) as temporary:
        # A stable short leaf keeps packaged Windows workspaces below the
        # legacy CreateProcess working-directory limit.
        mirror = Path(temporary) / "workspace"
        shutil.copytree(
            resolved_source,
            mirror,
            symlinks=False,
            ignore=lambda directory, names: _copy_ignore(
                directory,
                names,
                source_root=resolved_source,
            ),
        )
        _copy_explicit_include(resolved_source, mirror, include_paths)
        yield mirror
