"""Fail-closed, object-only Git reference adapter."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .capability_contracts import canonical_hash, utc_now
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_b_adapters import checked as _proofs_b_checked


GIT_REFERENCE_RESULT_SCHEMA = "neyvia.git_reference_result.v1"
GIT_REFERENCE_RECEIPT_SCHEMA = "neyvia.git_reference_receipt.v1"
GIT_REFERENCE_TELEMETRY_SCHEMA = "neyvia.git_reference_telemetry.v1"

OPERATIONS = frozenset(
    {
        "repository.inspect",
        "repository.history",
        "repository.show",
        "commit.ancestry-verify",
    }
)
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@{}^~+-]{0,127}$")
INCLUDE_SECTION = re.compile(r"(?im)^\s*\[\s*include(?:if)?(?:\s|\])")
REMOTE_URL = re.compile(r"^remote\.([A-Za-z0-9._-]+)\.url$")
FORBIDDEN_KEYS = frozenset(
    {
        "core.alternaterefscommand",
        "core.attributesfile",
        "core.fsmonitor",
        "core.hookspath",
        "core.partialclonefilter",
        "core.sshcommand",
        "extensions.partialclone",
    }
)
FORBIDDEN_PREFIXES = (
    "filter.",
    "protocol.",
    "include.",
    "includeif.",
    "credential.",
    "url.",
    "http.",
    "https.",
    "uploadpack.",
    "fetch.",
    "submodule.",
)


class GitReferenceError(RuntimeError):
    pass


class GitReferenceAdapter:
    MAX_PATHS = 64
    MAX_COMMITS = 100
    MAX_OUTPUT_BYTES = 1_048_576
    MAX_TIMEOUT_SECONDS = 20.0
    MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
    MAX_CONFIG_BYTES = 1_048_576
    MAX_SCAN_ENTRIES = 50_000

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        executable: str | Path,
        expected_sha256: str = "",
        expected_version: str = "",
    ) -> None:
        self.root = Path(workspace_root).absolute()
        self.root = self._safe_path(
            self.root,
            exists=True,
            boundary=self.root.parent,
        )
        self.executable = Path(executable).absolute()
        self.expected_sha256 = str(expected_sha256 or "").strip().lower()
        self.expected_version = str(expected_version or "").strip()
        identity = self.probe_executable_identity(
            self.executable,
            expected_sha256=self.expected_sha256,
            expected_version=self.expected_version,
        )
        self.version, self.executable_sha256 = identity["version"], identity["sha256"]

    @staticmethod
    def _contains(parent: Path, child: Path) -> bool:
        try:
            return os.path.commonpath((str(parent), str(child))) == str(parent)
        except ValueError:
            return False

    @staticmethod
    def _reparse(path: Path) -> bool:
        info = os.lstat(path)
        return os.path.islink(path) or bool(
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )

    def _safe_path(self, path: Path, *, exists: bool, boundary: Path) -> Path:
        lexical, stop = Path(path), boundary.resolve()
        current = lexical
        while True:
            if current.exists() or os.path.lexists(current):
                if self._reparse(current):
                    raise PermissionError(f"symlink or reparse path is forbidden: {current}")
            elif exists and current == lexical:
                raise FileNotFoundError(current)
            if current == stop or current.parent == current:
                break
            current = current.parent
        resolved = lexical.resolve()
        if not self._contains(stop, resolved) and resolved != stop:
            raise PermissionError(f"path escapes boundary: {lexical}")
        return resolved

    @staticmethod
    def _env() -> dict[str, str]:
        windows = os.environ.get("SystemRoot", r"C:\Windows")
        return {
            "SystemRoot": windows,
            "WINDIR": os.environ.get("WINDIR", windows),
            "PATH": str(Path(windows) / "System32"),
            "TEMP": os.environ.get("TEMP", str(Path(windows) / "Temp")),
            "TMP": os.environ.get("TMP", str(Path(windows) / "Temp")),
            "HOME": "",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "LC_ALL": "C",
            "LANG": "C",
        }

    @staticmethod
    def _remaining(deadline: float) -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("Git reference request exceeded its deadline")
        return value

    @classmethod
    def _hash_file(cls, path: Path, deadline: float, maximum: int) -> str:
        if path.stat().st_size > maximum:
            raise GitReferenceError(f"file exceeds inspection bound: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(65_536):
                cls._remaining(deadline)
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def probe_executable_identity(
        cls,
        executable: str | Path,
        *,
        expected_sha256: str = "",
        expected_version: str = "",
        deadline: float | None = None,
    ) -> dict[str, str]:
        end = deadline or time.monotonic() + 5.0
        selected = Path(executable).absolute()
        if (
            not selected.is_file()
            or os.path.islink(selected)
            or bool(
                getattr(os.lstat(selected), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
        ):
            raise FileNotFoundError(selected)
        digest = cls._hash_file(selected, end, cls.MAX_EXECUTABLE_BYTES)
        if expected_sha256 and digest != str(expected_sha256).lower():
            raise GitReferenceError("Git executable SHA-256 differs from the manifest")
        try:
            completed = subprocess.run(
                [str(selected), "--version"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=cls._env(),
                shell=False,
                check=False,
                timeout=cls._remaining(end),
                **hidden_windows_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                "Git reference request exceeded its deadline"
            ) from exc
        if completed.returncode or len(completed.stdout) + len(completed.stderr) > 4096:
            raise GitReferenceError("Git version probe failed its bounds")
        version = completed.stdout.decode("utf-8", "replace").strip()
        if expected_version and version != f"git version {expected_version}":
            raise GitReferenceError("Git executable version differs from the manifest")
        return {"version": version, "sha256": digest}

    def _git(
        self,
        repository: Path,
        arguments: list[str],
        *,
        deadline: float,
        budget: dict[str, int],
        accept: set[int] = {0},
    ) -> dict[str, Any]:
        limit = max(1, budget["remaining"])
        command = [
            str(self.executable),
            "--no-pager",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            f"core.attributesFile={os.devnull}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "credential.interactive=never",
            "-c",
            "diff.external=",
            "-c",
            "submodule.recurse=false",
            "-c",
            "protocol.allow=never",
            "-C",
            str(repository),
            *arguments,
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            shell=False,
            **hidden_windows_subprocess_kwargs(),
        )
        data = {"stdout": bytearray(), "stderr": bytearray()}
        overflow, lock = threading.Event(), threading.Lock()

        def read(name: str, stream: Any) -> None:
            while chunk := stream.read(65_536):
                with lock:
                    used = len(data["stdout"]) + len(data["stderr"])
                    data[name].extend(chunk[: max(0, limit + 1 - used)])
                    if len(data["stdout"]) + len(data["stderr"]) > limit:
                        overflow.set()

        readers = [
            threading.Thread(target=read, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=read, args=("stderr", process.stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()
        timeout = False
        while process.poll() is None:
            if overflow.is_set():
                process.kill()
                break
            try:
                self._remaining(deadline)
            except TimeoutError:
                timeout = True
                process.kill()
                break
            time.sleep(0.01)
        process.wait()
        for reader in readers:
            reader.join(timeout=0.5)
        if timeout:
            raise TimeoutError("Git reference request exceeded its deadline")
        if overflow.is_set():
            raise GitReferenceError("Git request exceeded its total output budget")
        used = len(data["stdout"]) + len(data["stderr"])
        budget["remaining"] -= used
        stdout = bytes(data["stdout"]).decode("utf-8", "replace")
        stderr = bytes(data["stderr"]).decode("utf-8", "replace")
        if process.returncode not in accept:
            raise GitReferenceError(
                f"Git exited {process.returncode}: {(stderr or stdout).strip()[:1024]}"
            )
        return {"code": process.returncode, "stdout": stdout, "stderr": stderr}

    @staticmethod
    def _forbidden_config(key: str) -> bool:
        normalized = key.casefold()
        return (
            normalized in FORBIDDEN_KEYS
            or normalized.startswith(FORBIDDEN_PREFIXES)
            or (
                normalized.startswith("diff.")
                and normalized.endswith((".command", ".textconv", ".cachetextconv"))
            )
            or (
                normalized.startswith("remote.")
                and normalized.endswith((".promisor", ".partialclonefilter"))
            )
        )

    def _config(
        self, repository: Path, git_dir: Path, deadline: float, budget: dict[str, int]
    ) -> dict[str, str]:
        config_path = git_dir / "config"
        if not config_path.is_file() or config_path.stat().st_size > self.MAX_CONFIG_BYTES:
            raise GitReferenceError("local Git config is missing or oversized")
        text = config_path.read_text("utf-8", errors="replace")
        self._remaining(deadline)
        if INCLUDE_SECTION.search(text):
            raise GitReferenceError("Git config includes are forbidden")
        raw = self._git(
            repository,
            ["config", "--local", "--no-includes", "--null", "--list"],
            deadline=deadline,
            budget=budget,
        )["stdout"]
        result: dict[str, str] = {}
        for record in raw.split("\x00"):
            if not record:
                continue
            key, separator, value = record.partition("\n")
            if not separator:
                key, _, value = record.partition("=")
            key = key.strip().casefold()
            if self._forbidden_config(key):
                raise GitReferenceError(f"forbidden Git config extension: {key}")
            result[key] = value
        return result

    def _attributes(self, repository: Path, git_dir: Path, deadline: float) -> None:
        if (git_dir / "info" / "attributes").exists():
            raise GitReferenceError(".git/info/attributes is forbidden")
        count = 0
        for directory, children, files in os.walk(repository, followlinks=False):
            self._remaining(deadline)
            current = Path(directory)
            if current == git_dir:
                children[:] = []
                continue
            children[:] = [
                name
                for name in children
                if current / name != git_dir and not self._reparse(current / name)
            ]
            count += len(children) + len(files)
            if count > self.MAX_SCAN_ENTRIES:
                raise GitReferenceError("attribute scan exceeded its bound")
            if ".gitattributes" in files:
                raise GitReferenceError("repository .gitattributes is forbidden")

    def _repository(
        self, value: object, deadline: float, budget: dict[str, int]
    ) -> tuple[dict[str, Path], dict[str, str]]:
        text = str(value or "").strip()
        if not text:
            raise ValueError("repository is required")
        lexical = Path(text)
        if not lexical.is_absolute():
            lexical = self.root / lexical
        repository = self._safe_path(lexical, exists=True, boundary=self.root)
        dot_git = repository / ".git"
        if dot_git.is_file():
            raise GitReferenceError("linked/external gitdir repositories are forbidden")
        git_dir = self._safe_path(dot_git, exists=True, boundary=self.root)
        if not git_dir.is_dir():
            raise GitReferenceError("standalone .git directory is required")
        config = self._config(repository, git_dir, deadline, budget)

        path_queries = (("--show-toplevel",), ("--absolute-git-dir",),
                        ("--git-common-dir",), ("--git-path", "objects"))
        paths = {}
        if not any(char in str(repository) for char in "\r\n"):
            # Git emits these four values in argument order. One invocation
            # preserves all storage guards and avoids three process startups
            # inside the caller's existing shared request deadline.
            values = self._git(repository, ["rev-parse", *(arg for query in path_queries for arg in query)],
                               deadline=deadline, budget=budget)["stdout"].rstrip("\n").split("\n")
            if len(values) != len(path_queries):
                raise GitReferenceError("ambiguous Git storage path response")
            paths = dict(zip(path_queries, values))

        def path_from_git(*args: str) -> Path:
            text_value = paths[args].strip() if paths else self._git(
                repository, ["rev-parse", *args], deadline=deadline, budget=budget
            )["stdout"].strip()
            selected = Path(text_value)
            return repository / selected if not selected.is_absolute() else selected

        top = self._safe_path(
            path_from_git("--show-toplevel"),
            exists=True,
            boundary=self.root,
        )
        absolute_git = self._safe_path(
            path_from_git("--absolute-git-dir"),
            exists=True,
            boundary=self.root,
        )
        common = self._safe_path(
            path_from_git("--git-common-dir"),
            exists=True,
            boundary=self.root,
        )
        objects = self._safe_path(
            path_from_git("--git-path", "objects"),
            exists=True,
            boundary=self.root,
        )
        if top != repository or absolute_git != git_dir or common != git_dir:
            raise GitReferenceError("linked or external Git storage is forbidden")
        for selected in (git_dir, objects, git_dir / "config"):
            self._safe_path(selected, exists=True, boundary=self.root)
        for name in ("alternates", "http-alternates"):
            if (objects / "info" / name).exists():
                raise GitReferenceError("Git object alternates are forbidden")
        pack = objects / "pack"
        if pack.exists():
            self._safe_path(pack, exists=True, boundary=self.root)
            if any(path.suffix.casefold() == ".promisor" for path in pack.iterdir()):
                raise GitReferenceError("promisor object storage is forbidden")
        self._attributes(repository, git_dir, deadline)
        receipt_dir = self.root / ".agent_control" / "capability_os" / "git" / "receipts"
        self._safe_path(receipt_dir, exists=False, boundary=self.root)
        return {
            "repository": repository,
            "git": git_dir,
            "objects": objects,
            "config": git_dir / "config",
            "receipts": receipt_dir,
        }, config

    def _capture(
        self, context: dict[str, Path], deadline: float, budget: dict[str, int]
    ) -> dict[str, str]:
        version = re.match(r"git version (\d+)\.(\d+)\.", self.version)
        if version and tuple(map(int, version.groups())) >= (2, 46):
            # Root-ref enumeration includes HEAD in the same Git observation as
            # ordinary refs. Keep the original refs digest bytes (no pseudorefs)
            # while avoiding two process startups per complete request.
            raw = self._git(
                context["repository"],
                ["for-each-ref", "--include-root-refs", "--format=%(refname)%00%(objectname)"],
                deadline=deadline,
                budget=budget,
            )["stdout"]
            head_oid = None
            refs = []
            for record in raw.split("\n"):
                if not record:
                    continue
                name, separator, oid = record.partition("\x00")
                if not separator or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
                    raise GitReferenceError("ambiguous Git reference snapshot")
                if name == "HEAD":
                    head_oid = oid
                elif name.startswith("refs/"):
                    refs.append(record + "\n")
            if head_oid is None:
                # Unborn or invalid HEAD keeps the previous explicit probe and
                # its accepted refusal code; no cached identity is substituted.
                head = self._git(
                    context["repository"], ["rev-parse", "--verify", "HEAD"],
                    deadline=deadline, budget=budget, accept={0, 128},
                )
                head_oid = head["stdout"].strip() if head["code"] == 0 else ""
            return {
                "head": head_oid,
                "configSha256": self._hash_file(context["config"], deadline, self.MAX_CONFIG_BYTES),
                "refsSha256": hashlib.sha256("".join(refs).encode()).hexdigest(),
            }
        head = self._git(
            context["repository"],
            ["rev-parse", "--verify", "HEAD"],
            deadline=deadline,
            budget=budget,
            accept={0, 128},
        )
        refs = self._git(
            context["repository"],
            ["for-each-ref", "--format=%(refname)%00%(objectname)"],
            deadline=deadline,
            budget=budget,
        )["stdout"].encode()
        return {
            "head": head["stdout"].strip() if head["code"] == 0 else "",
            "configSha256": self._hash_file(
                context["config"], deadline, self.MAX_CONFIG_BYTES
            ),
            "refsSha256": hashlib.sha256(refs).hexdigest(),
        }

    def _identity(
        self,
        context: dict[str, Path],
        capture: dict[str, str],
        deadline: float,
        budget: dict[str, int],
    ) -> dict[str, str]:
        branch = self._git(
            context["repository"],
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            deadline=deadline,
            budget=budget,
            accept={0, 1},
        )
        return {
            "repository": context["repository"].relative_to(self.root).as_posix(),
            "head": capture["head"],
            "branch": branch["stdout"].strip() if branch["code"] == 0 else "",
        }

    @staticmethod
    def _ref(value: object, name: str, required: bool = False) -> str:
        text = str(value or "").strip()
        if not text and not required:
            return ""
        if not text or text.startswith("-") or not REF.fullmatch(text):
            raise ValueError(f"{name} is not a bounded Git reference")
        return text

    def _oid(
        self,
        context: dict[str, Path],
        ref: str,
        deadline: float,
        budget: dict[str, int],
    ) -> str:
        value = self._git(
            context["repository"],
            ["rev-parse", "--verify", f"{ref}^{{commit}}"],
            deadline=deadline,
            budget=budget,
        )["stdout"].strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40,64}", value):
            raise GitReferenceError("reference did not resolve to a commit")
        return value

    def _paths(self, repository: Path, raw: object) -> list[str]:
        if raw is None:
            return []
        if not isinstance(raw, list) or len(raw) > self.MAX_PATHS:
            raise ValueError(f"paths must be an array of at most {self.MAX_PATHS}")
        result: list[str] = []
        for value in raw:
            text = str(value or "").strip().replace("\\", "/")
            if not text or text.startswith("-") or "\x00" in text:
                raise ValueError("path must be a non-option repository path")
            resolved = (repository / text).resolve()
            if not self._contains(repository, resolved):
                raise PermissionError("path escapes repository")
            result.append(resolved.relative_to(repository).as_posix())
        return sorted(set(result))

    @staticmethod
    def _redact_url(value: str) -> str:
        text = str(value or "").strip()
        try:
            parsed, scheme = urlsplit(text), urlsplit(text).scheme.casefold()
            host = parsed.hostname or ""
        except (TypeError, ValueError):
            return "[redacted-invalid-remote]"
        if scheme and host:
            return f"{scheme}://{host}"
        if "@" in text and ":" in text:
            host = text.split("@", 1)[1].split(":", 1)[0].strip()
            return f"ssh://{host}" if host else "[redacted-invalid-remote]"
        return "[local-remote]"

    def _operation(
        self,
        operation: str,
        context: dict[str, Path],
        config: dict[str, str],
        before: dict[str, str],
        args: dict[str, Any],
        deadline: float,
        budget: dict[str, int],
    ) -> dict[str, Any]:
        base = self._identity(context, before, deadline, budget)
        if operation == "repository.inspect":
            remotes = []
            for key, value in config.items():
                match = REMOTE_URL.match(key)
                if match:
                    remotes.append({"name": match.group(1), "url": self._redact_url(value)})
            return {
                **base,
                "standaloneRepository": True,
                "objectStorageContained": True,
                "remotes": sorted(remotes, key=lambda row: (row["name"], row["url"])),
                "git": {
                    "executable": str(self.executable),
                    "version": self.version,
                    "executableSha256": self.executable_sha256,
                    "hashScope": "launcher-executable",
                },
                "networkAccessed": False,
            }
        if operation == "repository.history":
            requested = self._ref(args.get("ref"), "ref") or "HEAD"
            oid, paths = self._oid(context, requested, deadline, budget), self._paths(
                context["repository"], args.get("paths")
            )
            limit = max(1, min(int(args.get("maxCommits", 20)), self.MAX_COMMITS))
            raw = self._git(
                context["repository"],
                [
                    "log",
                    "--no-decorate",
                    "--no-show-signature",
                    f"--max-count={limit}",
                    "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%s%x1e",
                    oid,
                    "--",
                    *paths,
                ],
                deadline=deadline,
                budget=budget,
            )["stdout"]
            commits = []
            for record in raw.split("\x1e"):
                fields = record.strip().split("\x1f")
                if len(fields) == 6:
                    commits.append(
                        {
                            "commit": fields[0],
                            "parents": fields[1].split() if fields[1] else [],
                            "authorName": fields[2],
                            "authorEmail": fields[3],
                            "authoredAt": fields[4],
                            "subject": fields[5],
                        }
                    )
            return {
                **base,
                "requestedRef": requested,
                "resolvedCommit": oid,
                "paths": paths,
                "commits": commits,
                "commitCount": len(commits),
                "limit": limit,
                "networkAccessed": False,
            }
        if operation == "repository.show":
            requested = self._ref(args.get("ref"), "ref", True)
            oid, paths = self._oid(context, requested, deadline, budget), self._paths(
                context["repository"], args.get("paths")
            )
            content = self._git(
                context["repository"],
                [
                    "show",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-color",
                    "--no-renames",
                    "--no-show-signature",
                    "--format=fuller",
                    oid,
                    "--",
                    *paths,
                ],
                deadline=deadline,
                budget=budget,
            )["stdout"]
            return {
                **base,
                "requestedRef": requested,
                "resolvedCommit": oid,
                "paths": paths,
                "content": content,
                "contentBytes": len(content.encode()),
                "networkAccessed": False,
            }
        requested_a = self._ref(args.get("ancestor"), "ancestor", True)
        requested_d = self._ref(args.get("descendant"), "descendant", True)
        ancestor = self._oid(context, requested_a, deadline, budget)
        descendant = self._oid(context, requested_d, deadline, budget)
        check = self._git(
            context["repository"],
            ["merge-base", "--is-ancestor", ancestor, descendant],
            deadline=deadline,
            budget=budget,
            accept={0, 1},
        )
        return {
            **base,
            "requestedAncestor": requested_a,
            "requestedDescendant": requested_d,
            "ancestor": ancestor,
            "descendant": descendant,
            "isAncestor": check["code"] == 0,
            "networkAccessed": False,
        }

    @_proofs_b_checked("git")
    def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            timeout = float(arguments.get("timeoutSeconds", 15.0))
            maximum = int(arguments.get("maxBytes", self.MAX_OUTPUT_BYTES))
        except (TypeError, ValueError) as exc:
            raise ValueError("timeoutSeconds and maxBytes must be numeric") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeoutSeconds must be finite and positive")
        if maximum < 1 or maximum > self.MAX_OUTPUT_BYTES:
            raise ValueError(f"maxBytes must be between 1 and {self.MAX_OUTPUT_BYTES}")
        deadline, budget = time.monotonic() + min(timeout, self.MAX_TIMEOUT_SECONDS), {
            "remaining": maximum
        }
        operation = str(arguments.get("operation") or "").strip().lower()
        if operation not in OPERATIONS:
            raise ValueError("operation must be one of: " + ", ".join(sorted(OPERATIONS)))
        start_identity = self.probe_executable_identity(
            self.executable,
            expected_sha256=self.expected_sha256,
            expected_version=self.expected_version,
            deadline=deadline,
        )
        self.version, self.executable_sha256 = (
            start_identity["version"],
            start_identity["sha256"],
        )
        context, config = self._repository(arguments.get("repository"), deadline, budget)
        before = self._capture(context, deadline, budget)
        result = self._operation(
            operation, context, config, before, arguments, deadline, budget
        )
        after = self._capture(context, deadline, budget)
        if before != after:
            raise GitReferenceError("repository changed during the request")
        if self.probe_executable_identity(
            self.executable,
            expected_sha256=self.expected_sha256,
            expected_version=self.expected_version,
            deadline=deadline,
        ) != start_identity:
            raise GitReferenceError("Git executable changed during the request")
        result["consistency"] = {"checked": True, "stable": True, "before": before, "after": after}
        payload = {
            "schema": GIT_REFERENCE_RESULT_SCHEMA,
            "operation": operation,
            **result,
            "policy": {
                "surface": "object-only-v1",
                "readOnly": True,
                "network": "denied",
                "lazyFetch": "denied",
                "helpersAttributesFilters": "rejected",
                "alternatesPromisorsLinkedWorktrees": "rejected",
                "shellInterpolation": False,
                "workspaceContained": True,
                "requestDeadlineSeconds": min(timeout, self.MAX_TIMEOUT_SECONDS),
            },
        }
        result_hash = canonical_hash(payload)
        receipt = {
            "schema": GIT_REFERENCE_RECEIPT_SCHEMA,
            "createdAt": utc_now(),
            "operation": operation,
            "resultHash": result_hash,
            "tool": {
                "version": self.version,
                "executableSha256": self.executable_sha256,
                "hashScope": "launcher-executable",
            },
            "lineage": {
                "sources": [
                    {
                        "role": "repository",
                        "path": result["repository"],
                        "head": result["head"],
                        "refsSha256": before["refsSha256"],
                        "configSha256": before["configSha256"],
                    }
                ],
                "output": {"role": "git-reference-result", "sha256": result_hash},
            },
            "networkAccessed": False,
        }
        self._remaining(deadline)
        receipts = context["receipts"]
        receipts.mkdir(parents=True, exist_ok=True)
        self._safe_path(receipts, exists=True, boundary=self.root)
        suffix = hashlib.sha256(
            f"{time.time_ns()}:{os.getpid()}:{threading.get_ident()}".encode()
        ).hexdigest()[:12]
        receipt["receiptId"] = f"gitref_{result_hash[:16]}_{suffix}"
        path = receipts / f"{receipt['receiptId']}.json"
        content = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(content)
        self._remaining(deadline)
        os.replace(temporary, path)
        self._safe_path(path, exists=True, boundary=self.root)
        receipt_hash = hashlib.sha256(content).hexdigest()
        return {
            "ok": True,
            "status": "completed",
            "summary": f"Completed bounded Git operation {operation}.",
            **payload,
            "telemetry": {
                "schema": GIT_REFERENCE_TELEMETRY_SCHEMA,
                "operation": operation,
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "resultBytes": len(json.dumps(payload, sort_keys=True).encode()),
                "remainingOutputBudgetBytes": budget["remaining"],
                "networkAccessed": False,
            },
            "receipt": {
                "receiptId": receipt["receiptId"],
                "path": path.relative_to(self.root).as_posix(),
                "sha256": receipt_hash,
            },
            "artifacts": [
                {
                    "role": "git-reference-receipt",
                    "kind": "json",
                    "path": path.relative_to(self.root).as_posix(),
                    "sha256": receipt_hash,
                    "derivedFrom": result_hash,
                    "verifiedBy": "bounded-local-git-reference-receipt",
                }
            ],
        }
