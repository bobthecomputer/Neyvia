"""INT3 test-only audit guard and exact pytest outcome recorder.

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
import re
import ntpath
import shlex
import pytest
import socket
import dis
import types
import _thread
import signal
import errno

_lock = threading.Lock()
_denial_context = threading.local()
_installed = False
_workspace = None
_extra_write_roots: tuple[Path, ...] = ()
_collected_ids: list[str] = []
_selected_ids: list[str] = []
_allowed_ports = json.loads(os.environ.get("INT3_ALLOWED_PORTS", "[48651,48652,48653,48654,48655,48656,48657,48658,48659]"))
_native_bind = socket.socket.bind
if not isinstance(_allowed_ports, list) or not _allowed_ports or any(type(port) is not int or not 1024 <= port <= 65535 or port == 47881 for port in _allowed_ports):
    raise ValueError("INT3_ALLOWED_PORTS must declare explicit non-public ports")
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
        or re.search(r"(?i)\\\.agent_control\\int3\\(?:pytest-temp|.*(?:fake|stub|fixture|runtime_bin))", program)
        for program in programs)


def _deny(kind: str, reason: str) -> None:
    destination = os.environ.get("INT3_GUARD_LOG")
    if destination and not getattr(_denial_context, 'logging', False):
        with _lock:
            _denial_context.logging = True
            try:
                with open(destination, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"event": kind, "reason": reason}) + "\n")
            except OSError:
                # A diagnostic destination can itself be refused. Never widen
                # the fence or recursively acquire this logging lock.
                pass
            finally:
                _denial_context.logging = False
    raise PermissionError("INT3 safety guard: " + reason)


def _protected_path(value: object) -> bool:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return False
    path = os.fsdecode(value).replace("/", "\\").lower()
    protected = (
        "c:\\users\\user\\projects\\neyvia\\",
        "c:\\users\\user\\projects\\neyvia-next\\",
        "nas_access_runbook",
        "nas_codex2_100_125_54_118",
    )
    credential_name = ntpath.basename(path)
    if any(item in path for item in protected) or path.rstrip("\\") in (
        "c:\\users\\user\\projects\\neyvia",
        "c:\\users\\user\\projects\\neyvia-next",
    ):
        return True
    sensitive = credential_name in ('admin_password.txt', 'admin-password.txt', 'auth.json', '.credentials.json')
    if sensitive:
        # Fresh pytest fixtures may model account-file names. Resolved targets
        # must remain in the owned fixture tree, including through junctions.
        roots = [_workspace / '.agent_control/int3/pytest-temp', _workspace / 'home', *_extra_write_roots] if _workspace else []
        return not any(Path(os.fsdecode(value)).resolve().is_relative_to(root) for root in roots)
    return False


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
    fixture_root = Path(os.environ.get("INT3_WORKSPACE_ROOT") or Path(__file__).resolve().parents[1]) / ".agent_control/int3/pytest-temp"
    # The controller may place the exact owned proof tree on D. Every Git
    # mutation still requires an independently initialized fixture repository.
    targets = [effective, *(Path(value).absolute() for value in tokens[-2:] if not value.startswith('-'))]
    fixture_root = next((root for root in _extra_write_roots if any(path.is_relative_to(root) for path in targets)), fixture_root)
    if operation == 'clone' and len(tokens) == 5 and tokens[1:3] == ['clone','-q']:
        source, destination = (Path(value).resolve() for value in tokens[3:])
        bare = (source / 'HEAD').is_file() and (source / 'config').is_file() and (source / 'objects').is_dir()
        closure = ('HEAD','config','objects') if bare else ('.git',)
        if (source.is_relative_to(fixture_root) and destination.is_relative_to(fixture_root)
                and all((source / name).resolve().is_relative_to(fixture_root) for name in closure)
                and (bare or (source / '.git').is_dir()) and not destination.exists()):
            return  # Two independently owned local fixtures; no remote URL.
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
    if event not in ('open', 'os.listdir', 'os.scandir', 'os.chdir', 'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename', 'os.replace', 'socket.connect', 'socket.bind', 'subprocess.Popen'):
        return
    def writable(value):
        if isinstance(value, (str, bytes, os.PathLike)):
            if os.fsdecode(value).lower() in ('nul', '\\\\.\\nul', os.devnull.lower()):
                return
            path = Path(os.fsdecode(value)).resolve()
            if not path.is_relative_to(_workspace) and not any(path.is_relative_to(root) for root in _extra_write_roots):
                _deny(event, 'write outside INT3 workspace')
    if event == 'open' and len(args) > 2:
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(letter in mode for letter in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            writable(args[0])
    elif event in ('os.remove', 'os.rmdir', 'os.mkdir') and args:
        writable(args[0])
    elif event in ('os.rename', 'os.replace'):
        for value in args[:2]:
            writable(value)
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
            if str(host) not in ("127.0.0.1", "localhost", "::1") or int(port) not in _allowed_ports:
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
        if os.environ.get("INT3_NO_BROWSER_LAUNCH") == "1" and name.startswith(("chrome", "msedge", "firefox")):
            _deny(event, "desktop browser launch is outside this proof scope")


def _assigned_fixture_bind(stream, address):
    """Keep disposable port-zero fixtures inside the caller's declared range."""
    if isinstance(address, tuple) and len(address) >= 2 and address[0] in ('127.0.0.1', 'localhost', '::1') and address[1] == 0:
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            stream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            stream.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        for port in _allowed_ports:
            try:
                return _native_bind(stream, (address[0], port, *address[2:]))
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE and getattr(exc, 'winerror', None) not in (10013,10048):
                    raise
        raise OSError(errno.EADDRINUSE, 'No caller-owned fixture port is available')
    return _native_bind(stream, address)


def install() -> None:
    global _installed, _workspace, _extra_write_roots
    if not _installed:
        _workspace = Path(os.environ.get('INT3_WORKSPACE_ROOT') or Path(__file__).resolve().parents[1]).resolve()
        declared = json.loads(os.environ.get('INT3_EXTRA_WRITE_ROOTS', '[]'))
        if not isinstance(declared, list):
            raise ValueError('Explicit extra write roots must be a list')
        owned_runs = Path(r'D:\NeyviaRuns\INTN\self-check').resolve()
        _extra_write_roots = tuple(Path(value).resolve() for value in declared)
        if any(not root.is_relative_to(owned_runs) or root == owned_runs for root in _extra_write_roots):
            raise ValueError('Extra write roots must be specific owned self-check output directories')
        sys.addaudithook(_audit)
        socket.socketpair = _explicit_socketpair
        if os.environ.get('INT3_MAP_EPHEMERAL_BIND') == '1':
            socket.socket.bind = _assigned_fixture_bind
        _installed = True


def _explicit_socketpair(family=None, type=socket.SOCK_STREAM, proto=0):
    """Actual Windows wakeup sockets, assigned INT3 ports only."""
    family = socket.AF_INET if family is None else family
    if family not in (socket.AF_INET, socket.AF_INET6) or type != socket.SOCK_STREAM or proto:
        raise ValueError('INT3 socketpair supports TCP only')
    host = '127.0.0.1' if family == socket.AF_INET else '::1'
    listener = socket.socket(family, type, proto)
    client = accepted = None
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        declared = os.environ.get("NEYVIA_PROOF_SOCKETPAIR_PORTS", "48654,48655,48656,48657,48658,48659")
        wakeup_ports = json.loads(declared) if declared.startswith("[") else [int(port) for port in declared.split(",")]
        for port in wakeup_ports:
            try:
                listener.bind((host, port))
                break
            except OSError:
                pass
        else:
            raise OSError('INT3 wakeup ports occupied')
        listener.listen(1)
        listener.settimeout(5)
        client = socket.socket(family, type, proto)
        client.setblocking(False)
        try:
            client.connect(listener.getsockname())
        except (BlockingIOError, InterruptedError):
            pass
        client.setblocking(True)
        accepted, _ = listener.accept()
        if accepted.getpeername() != client.getsockname():
            raise ConnectionError('Unexpected INT3 socketpair peer')
        return accepted, client
    except BaseException:
        if accepted is not None:
            accepted.close()
        if client is not None:
            client.close()
        raise
    finally:
        listener.close()


install()
_reports: list[dict[str, object]] = []
_coverage_lines = {}
_coverage_root = ''

def _line_trace(frame, event, arg):
    filename = frame.f_code.co_filename
    if not filename.startswith(_coverage_root):
        return None
    if event == 'line':
        _coverage_lines.setdefault(filename, set()).add(frame.f_lineno)
    return _line_trace

def pytest_sessionstart(session):
    global _coverage_root
    _coverage_root = str(Path.cwd() / 'src' / 'grant_agent')
    if os.environ.get("INT3_LINE_COVERAGE") != "0":
        sys.settrace(_line_trace)
        threading.settrace(_line_trace)

def _line_coverage():
    def code_lines(code):
        lines = {line for _, line in dis.findlinestarts(code) if line is not None and line > 0}
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                lines.update(code_lines(constant))
        return lines
    rows = []
    for path in (Path.cwd() / 'src/grant_agent').rglob('*.py'):
        try:
            executable = code_lines(compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec'))
        except (SyntaxError, UnicodeError):
            continue
        observed = _coverage_lines.get(str(path), set()) & executable
        rows.append({'file': path.relative_to(Path.cwd()).as_posix(), 'executable': len(executable), 'executed': len(observed), 'executedLines': sorted(observed)})
    total = sum(row['executable'] for row in rows)
    hit = sum(row['executed'] for row in rows)
    return {'method': 'stdlib sys/threading.settrace line events against dis.findlinestarts executable-line inventory; current pytest process and its threads only; collection/imports before sessionstart and subprocess execution excluded', 'executable': total, 'executed': hit, 'percent': 100 * hit / total if total else 0, 'files': rows}


def pytest_collection_modifyitems(session: object, config: object, items: list[object]) -> None:
    global _collected_ids, _selected_ids
    _collected_ids = [item.nodeid for item in items]
    selected_path = os.environ.get("INT3_SELECTED_IDS_FILE")
    if selected_path:
        selected = set(json.loads(Path(selected_path).read_text(encoding="utf-8")))
        kept = [item for item in items if item.nodeid in selected]
        deselected = [item for item in items if item.nodeid not in selected]
        items[:] = kept
        config.hook.pytest_deselected(items=deselected)
    _selected_ids = [item.nodeid for item in items]


def pytest_runtest_logreport(report: object) -> None:
    _reports.append({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome})
    destination = os.environ.get("INT3_OUTCOME_LOG")
    if destination:
        with open(destination + ".progress.jsonl", "a", encoding="utf-8") as stream:
            stream.write(json.dumps(_reports[-1]) + "\n")


class INT3TestDeadline(BaseException):
    """A test exceeded the identical INT3 baseline/final execution budget."""


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: object, nextitem: object):
    destination = os.environ.get("INT3_OUTCOME_LOG")
    if destination:
        Path(destination + ".active.json").write_text(json.dumps({"nodeid": item.nodeid,
                                                                "started": time.time()}), encoding="utf-8")
    deadline = float(os.environ.get("INT3_TEST_DEADLINE", "120"))
    previous_handler = signal.getsignal(signal.SIGINT)
    expired = False
    def deadline_signal(signum, frame):
        nonlocal expired
        if expired:
            expired = False
            raise INT3TestDeadline('INT3 test exceeded its configured execution deadline')
        if callable(previous_handler):
            previous_handler(signum, frame)
        elif previous_handler == signal.SIG_DFL:
            signal.default_int_handler(signum, frame)
    def expire():
        nonlocal expired
        expired = True
        _thread.interrupt_main(signal.SIGINT)
    signal.signal(signal.SIGINT, deadline_signal)
    timer = threading.Timer(deadline, expire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
        signal.signal(signal.SIGINT, previous_handler)
        # Preserve source-only coverage after an interrupted test.
        if os.environ.get("INT3_LINE_COVERAGE") != "0":
            sys.settrace(_line_trace)


def pytest_collectreport(report: object) -> None:
    if report.failed:
        _reports.append({"nodeid": report.nodeid, "phase": "collect", "outcome": "failed"})


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    sys.settrace(None)
    threading.settrace(None)
    destination = os.environ.get("INT3_OUTCOME_LOG")
    if destination:
        failed = sorted({row["nodeid"] for row in _reports if row["outcome"] == "failed"})
        coverage = _line_coverage() if os.environ.get("INT3_LINE_COVERAGE") != "0" else {"method": "disabled by caller; outcomes only"}
        Path(destination + '.coverage.json').write_text(json.dumps(coverage, indent=2) + '\n', encoding='utf-8')
        Path(destination).write_text(json.dumps({"exitstatus": int(exitstatus), "reports": _reports,
                                              "failed_ids": failed, "collected_ids": _collected_ids,
                                              "selected_ids": _selected_ids}, indent=2) + "\n", encoding="utf-8")
