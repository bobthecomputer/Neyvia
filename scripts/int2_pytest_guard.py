"""INT2 test-only audit guard and exact pytest outcome recorder.

Use as a pytest plugin via the isolated runner; never install globally.
Denials fail the attempted operation and are recorded, never simulated successes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time
import ctypes
import re
import ntpath
import shlex
import pytest

_lock = threading.Lock()
_installed = False
_collected_ids: list[str] = []
_selected_ids: list[str] = []
_provider_commands = ("codex", "claude", "opencode", "hermes", "openclaw", "cursor", "cursor-agent",
                      "kimi", "grok", "prime-agent", "pi", "dsh", "gptme", "wallbreaker", "rook")
_provider_pattern = re.compile(r"(?:^|[\\\s\"'])(?:" + "|".join(re.escape(name) for name in _provider_commands)
                               + r")(?:\.cmd|\.bat|\.exe)?(?:$|[\s\"'])")


def _invoked_programs(executable: object, command: object) -> list[str]:
    """Inspect command/program positions; provider words in prompts are data."""
    if isinstance(command, (list, tuple)):
        tokens = [str(value) for value in command]
    else:
        try:
            tokens = shlex.split(str(command), posix=False)
        except ValueError:
            tokens = [str(command).split(" ", 1)[0]]
    if not tokens:
        return [str(executable or "")]
    programs = [tokens[0].strip("\"'")]
    stem = ntpath.splitext(ntpath.basename(programs[0]))[0].lower()
    if stem == "cmd":
        for index, token in enumerate(tokens[:-1]):
            if token.lower() in ("/c", "/k"):
                nested = " ".join(tokens[index + 1:]).strip().strip("\"'")
                matched = re.match(r"(?i)^([a-z]:\\.*?\.(?:cmd|exe|bat))(?=\s|[\"']|$)", nested)
                programs.append(matched.group(1) if matched else nested.split(" ", 1)[0].strip("\"'"))
                break
    elif stem in ("python", "python3", "python313", "py", "node"):
        for token in tokens[1:]:
            value = token.strip("\"'")
            if value in ("-c", "-e", "--eval"):
                break
            if value.startswith("-"):
                continue
            if value.lower().endswith((".py", ".js", ".mjs", ".cjs")):
                programs.append(value)
            break
    return programs


def _disposable_provider_fixture(command: str) -> bool:
    """Permit explicit test stubs, never a bare command resolved from global PATH."""
    names = "|".join(re.escape(name) for name in _provider_commands)
    programs = re.findall(r"(?i)[a-z]:\\[^\r\n\"']*?\\(?:" + names + r")\.(?:cmd|bat|exe)", command)
    return bool(programs) and all(
        re.search(r"(?i)\\temp\\tmp[^\\\s\"]+\\", program)
        or re.search(r"(?i)\\\.agent_control\\int2\\(?:pytest-temp|.*(?:fake|stub|fixture|runtime_bin))", program)
        for program in programs)


def _deny(kind: str, reason: str) -> None:
    destination = os.environ.get("INT2_GUARD_LOG")
    if destination:
        with _lock:
            with open(destination, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"event": kind, "reason": reason}) + "\n")
    raise PermissionError("INT2 safety guard: " + reason)


def _protected_path(value: object) -> bool:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return False
    path = os.fsdecode(value).replace("/", "\\").lower()
    protected = (
        "c:\\users\\user\\projects\\neyvia\\",
        "c:\\users\\user\\projects\\neyvia-next\\",
        "nas_access_runbook",
        "nas_codex2_100_125_54_118",
        "\\.codex\\auth.json",
        "\\.claude\\.credentials.json",
    )
    return any(item in path for item in protected) or path.rstrip("\\") in (
        "c:\\users\\user\\projects\\neyvia",
        "c:\\users\\user\\projects\\neyvia-next",
    )


def _guard_git(command: object, cwd: object) -> None:
    """Git mutations may touch only independently initialized fixture repos."""
    if isinstance(command, (list, tuple)):
        tokens = [str(value).strip("\"'") for value in command]
    else:
        raw = str(command).lstrip()
        head = re.match(r"^(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))", raw)
        program = next((value for value in head.groups() if value is not None), "") if head else ""
        stem = ntpath.splitext(ntpath.basename(program))[0].lower()
        if stem not in ("git", "cmd"):
            return  # Windows-quoted prompt/code arguments are data for non-Git programs.
        if stem == "cmd":
            shell = re.search(r"(?i)(?:^|\s)/(?:c|k)\s+(.+)", raw, re.S)
            if shell:
                nested = shell.group(1).strip().strip("\"'")
                _guard_git(nested, cwd)
                return
        try:
            tokens = [value.strip("\"'") for value in shlex.split(raw, posix=False)]
        except ValueError:
            _deny("subprocess.Popen", "unparseable Git command")
            return
    if not tokens:
        return
    stem = ntpath.splitext(ntpath.basename(tokens[0]))[0].lower()
    if stem == "cmd":
        for index, token in enumerate(tokens[:-1]):
            if token.lower() in ("/c", "/k"):
                _guard_git(" ".join(tokens[index + 1:]).strip().strip("\"'"), cwd)
                break
        return
    if stem != "git":
        return
    commands = {"commit", "reset", "checkout", "switch", "merge", "push", "fetch", "pull", "add", "rm", "clean", "stash", "rebase", "cherry-pick", "revert", "tag", "branch", "worktree", "update-ref", "init", "clone", "remote", "config", "gc"}
    operation = next((value for value in tokens[1:] if value in commands), None)
    if operation is None:
        return
    effective = Path(str(cwd or os.getcwd())).absolute()
    for index, token in enumerate(tokens[:-1]):
        if token == "-C":
            effective = (effective / tokens[index + 1]).absolute()
    fixture_root = Path(os.environ.get("INT2_WORKSPACE_ROOT") or Path(__file__).resolve().parents[1]) / ".agent_control/int2/pytest-temp"
    if operation == "init" and not effective.is_relative_to(fixture_root):
        candidate = Path(tokens[-1]).absolute()
        if candidate.is_relative_to(fixture_root):
            effective = candidate
    git_marker = effective / ".git"
    marker_contained = git_marker.is_dir() and git_marker.resolve().is_relative_to(fixture_root)
    if git_marker.is_file() and effective.is_relative_to(fixture_root):
        text = git_marker.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir: "):
            marker_contained = (effective / text.removeprefix("gitdir: ")).resolve().is_relative_to(fixture_root)
    if (not effective.is_relative_to(fixture_root)
            or operation != "init" and not marker_contained
            or any(value in tokens for value in ("--global", "--system", "--git-dir", "--work-tree"))
            or any(value.startswith(("--git-dir=", "--work-tree=")) for value in tokens)):
        _deny("subprocess.Popen", f"Git {operation} outside independently initialized disposable fixture: {effective}")


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event in ("open", "os.listdir", "os.scandir", "os.chdir", "os.remove", "os.rmdir", "os.mkdir"):
        if args and _protected_path(args[0]):
            _deny(event, "protected path")
    elif event in ("os.rename", "os.replace"):
        if any(_protected_path(value) for value in args[:2]):
            _deny(event, "protected path")
    elif event in ("socket.connect", "socket.bind"):
        address = args[1]
        if isinstance(address, tuple) and len(address) >= 2:
            host, port = address[:2]
            if str(host) not in ("127.0.0.1", "localhost", "::1") or not 48601 <= int(port) <= 48609:
                _deny(event, "network outside assigned localhost ports")
        else:
            _deny(event, "non-INET socket")
    elif event == "subprocess.Popen":
        executable, command, cwd, _env = args
        _guard_git(command, cwd)
        command_text = str(command).lower().replace("/", "\\")
        if _protected_path(executable) or _protected_path(cwd) or _protected_path(command_text):
            _deny(event, "subprocess protected path")
        forbidden = ("tailscale", "schtasks", "supervisor", "npm install", "pip install", "winget install")
        if any(word in command_text for word in forbidden):
            _deny(event, "subprocess forbidden service or installation")
        name = Path(str(executable)).name.lower()
        for program in _invoked_programs(executable, command):
            normalized = program.lower().replace("/", "\\")
            stem = ntpath.splitext(ntpath.basename(normalized))[0]
            global_package = "\\@openai\\codex\\" in normalized or "\\@anthropic-ai\\claude-code\\" in normalized
            if (stem in _provider_commands or global_package or stem == "wsl") and not _disposable_provider_fixture(normalized):
                _deny(event, "global provider command or Windows wrapper")
        if name.startswith(("godot", "unity", "blender", "roblox")):
            _deny(event, "live provider or editor process")


def install() -> None:
    global _installed
    if not _installed:
        sys.addaudithook(_audit)
        _installed = True


install()
_reports: list[dict[str, object]] = []


def pytest_collection_modifyitems(session: object, config: object, items: list[object]) -> None:
    global _collected_ids, _selected_ids
    _collected_ids = [item.nodeid for item in items]
    selected_path = os.environ.get("INT2_SELECTED_IDS_FILE")
    if selected_path:
        selected = set(json.loads(Path(selected_path).read_text(encoding="utf-8")))
        kept = [item for item in items if item.nodeid in selected]
        deselected = [item for item in items if item.nodeid not in selected]
        items[:] = kept
        config.hook.pytest_deselected(items=deselected)
    _selected_ids = [item.nodeid for item in items]


def pytest_runtest_logreport(report: object) -> None:
    _reports.append({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome})
    destination = os.environ.get("INT2_OUTCOME_LOG")
    if destination:
        with open(destination + ".progress.jsonl", "a", encoding="utf-8") as stream:
            stream.write(json.dumps(_reports[-1]) + "\n")


class INT2TestDeadline(BaseException):
    """A test exceeded the identical INT2 baseline/final execution budget."""


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: object, nextitem: object):
    destination = os.environ.get("INT2_OUTCOME_LOG")
    if destination:
        Path(destination + ".active.json").write_text(json.dumps({"nodeid": item.nodeid,
                                                                "started": time.time()}), encoding="utf-8")
    main_thread = threading.get_ident()
    deadline = float(os.environ.get("INT2_TEST_DEADLINE", "120"))
    def expire():
        inject = ctypes.pythonapi.PyThreadState_SetAsyncExc
        inject.argtypes = (ctypes.c_ulong, ctypes.py_object)
        inject.restype = ctypes.c_int
        inject(main_thread, INT2TestDeadline)
    timer = threading.Timer(deadline, expire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def pytest_collectreport(report: object) -> None:
    if report.failed:
        _reports.append({"nodeid": report.nodeid, "phase": "collect", "outcome": "failed"})


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    destination = os.environ.get("INT2_OUTCOME_LOG")
    if destination:
        failed = sorted({row["nodeid"] for row in _reports if row["outcome"] == "failed"})
        Path(destination).write_text(json.dumps({"exitstatus": int(exitstatus), "reports": _reports,
                                              "failed_ids": failed, "collected_ids": _collected_ids,
                                              "selected_ids": _selected_ids}, indent=2) + "\n", encoding="utf-8")
