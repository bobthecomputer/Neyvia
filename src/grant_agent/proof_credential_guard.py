"""Proof workers refuse saved credentials outside their disposable state."""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs, split_process_command

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_ROOTS: set[Path] = set()
_INSTALLED = False
_PROVIDER_TRANSPORTS: set[str] = set()
_NAMES = {"auth.json", "auth-profiles.json", "oauth_creds.json", "account.json",
          "provider_secrets.json", "nas_access_runbook.md", ".claude.json",
          ".credentials.json", "openclaw.json", "neyvia_web_admin.json",
          "grand_agent_web_admin.json"}
_PATTERN = re.compile(r"(?:credential|password|api[_-]?key|secret|nas_codex2_)", re.I)
_PROVIDER_PROGRAMS = {"codex", "claude", "claude-code", "hermes", "opencode", "openclaw", "ssh", "tailscale"}
_PROVIDER_DATA_DIRS = {".codex", ".claude", ".hermes", ".openclaw", ".minimax", ".gemini", "opencode"}


def check_access(path):
    if isinstance(path, int):
        return
    if isinstance(path, bytes):
        path = path.decode(sys.getfilesystemencoding(), errors="surrogateescape")
    if str(path).startswith("file:"):
        from urllib.parse import unquote, urlsplit
        parsed = urlsplit(str(path))
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
    candidate = Path(path).resolve()
    # Repository-owned instruction text is public source. Do not admit saved
    # provider settings, arbitrary skill attachments, or paths escaping via a
    # junction: the resolved file must remain under this repository's skills.
    if (candidate.name == "SKILL.md"
            and candidate.is_relative_to(REPO / ".codex/skills")):
        return
    # Runtime source, manuals and public schemas are data, not saved accounts.
    if candidate.suffix.lower() in {".py", ".pyc", ".pyd", ".dll", ".js", ".mjs", ".ts"}:
        return
    sensitive = (any(part.lower() in _PROVIDER_DATA_DIRS for part in candidate.parts)
                 or candidate.name.lower() in _NAMES or _PATTERN.search(candidate.name)
                 or candidate.name.lower().startswith(".env") and candidate.name != ".env.example"
                 or candidate.suffix.lower() == ".json" and re.search(r"(?:^|[_.-])(?:auth|oauth|tokens)(?:[_.-]|$)", candidate.name, re.I)
                 or candidate.parent.name.lower() == ".ssh" and candidate.name.startswith("id_"))
    if sensitive and not any(candidate.is_relative_to(root) for root in _ROOTS):
        raise PermissionError("Proof authority refuses saved credential access outside disposable state")


def _audit(event, args):
    if event in {"open", "sqlite3.connect"} and args and isinstance(args[0], (str, bytes, int)):
        check_access(args[0])
    elif event == "subprocess.Popen" and len(args) > 1:
        check_process(args[1])


def check_process(command):
    import subprocess
    encoded = command if isinstance(command, str) else subprocess.list2cmdline([str(value) for value in command])
    if encoded in _PROVIDER_TRANSPORTS:
        return
    if isinstance(command, str):
        # Windows CreateProcess quotes executable paths with spaces. Inspect
        # all argv paths, including a Node-hosted provider script, after the
        # exact authorized transport comparison above.
        candidates = split_process_command(command)
    else:
        candidates = [str(value) for value in command]
    for value in candidates:
        target = Path(value.strip('"'))
        name = target.stem.lower()
        vendor = value.replace("\\", "/").lower()
        provider = (name in _PROVIDER_PROGRAMS
                    or any(marker in vendor for marker in ("/@openai/codex/", "/@anthropic-ai/claude-code/")))
        if provider and not any(target.resolve().is_relative_to(root) for root in _ROOTS):
            raise PermissionError("Proof authority refuses an unscoped provider/device process")


def authorize_provider_transport(root, command):
    """Admit one explicitly selected installed provider's exact argv locally.

    This grants no file access and cannot relax the saved-credential reader.
    The caller supplies the already authorized transport, never model output.
    Nothing is persisted into global settings or inherited as a blanket grant.
    """
    import hashlib
    import subprocess
    root = Path(root).resolve()
    bases = (REPO / '.agent_control/proofs', REPO / '.agent_control/proofs-a')
    if not _INSTALLED or not any(root.is_relative_to(base) for base in bases):
        raise ValueError('Provider transport authorization requires installed task-local proof authority')
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(value, str) or not value for value in command):
        raise ValueError('Supply the complete explicit provider argv')
    encoded = subprocess.list2cmdline(command)
    _PROVIDER_TRANSPORTS.add(encoded)
    return {'workspace': str(root), 'argvSha256': hashlib.sha256(encoded.encode()).hexdigest(),
            'scope': 'one exact authorized provider transport; saved credential files remain refused'}


def install(workspace):
    global _INSTALLED
    workspace = Path(workspace).resolve()
    # A repository root never makes its unrelated .agent_control secrets safe.
    task_roots = (REPO / ".agent_control/proofs", REPO / ".agent_control/proofs-a")
    from .proof_ports import c7_run_root
    task_roots += (c7_run_root(),)
    if any(workspace.is_relative_to(root) for root in task_roots):
        _ROOTS.add(workspace)
    _ROOTS.add(workspace / ".agent_control/proofs")
    for root in task_roots:
        _ROOTS.add(root)
    # Accessed paths are compared after resolve(); a disposable proof tree that
    # a run relocates through a junction (e.g. large outputs kept off C:) is
    # still the same disposable state, so admit its resolved target as well.
    _ROOTS.update({root.resolve() for root in list(_ROOTS)})
    if not _INSTALLED:
        sys.addaudithook(_audit)
        _INSTALLED = True


def self_check(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fixture = root / "synthetic-credentials.json"
    fixture.write_text('{"synthetic": true}\n', encoding="utf-8")
    if fixture.read_text(encoding="utf-8").strip() != '{"synthetic": true}':
        raise RuntimeError("Owned synthetic credential fixture failed readback")
    refused = []
    # These nonexistent task paths exercise the actual audit hook before open;
    # no saved credential file is read, inspected or needed for the check.
    for name in ("auth.json", "oauth_creds.json", ".claude.json", "nas_codex2_synthetic.txt", "NAS_ACCESS_RUNBOOK.md"):
        candidate = REPO / "config/proofs-a/forbidden-open" / name
        try:
            candidate.open("r", encoding="utf-8")
        except PermissionError:
            refused.append(name)
        else:
            raise RuntimeError("Credential open escaped the proof authority guard")
    try:
        (REPO / "config/proofs-a/forbidden-open/.claude/settings.json").open("r", encoding="utf-8")
    except PermissionError:
        refused.append(".claude/settings.json")
    else:
        raise RuntimeError("Saved provider settings escaped the proof authority guard")
    import sqlite3
    try:
        sqlite3.connect(str(REPO / "config/proofs-a/forbidden-open/.codex/private.db"))
    except PermissionError:
        refused.append(".codex/private.db (SQLite)")
    else:
        raise RuntimeError("Saved provider database escaped the proof authority guard")
    import subprocess
    try:
        subprocess.Popen([str(REPO / "config/proofs-a/forbidden-launch/codex.exe"), "--version"], **hidden_windows_subprocess_kwargs())
    except PermissionError:
        refused_process = True
    else:
        raise RuntimeError("Unscoped provider executable escaped the proof authority guard")
    return {"ok": True, "contracts": ["proofs.saved-credential-boundary"], "refusedBeforeOpen": refused,
            "unscopedProviderRefusedBeforeLaunch": refused_process,
            "authority": "Python proof-worker/owned-backend saved credential guard; only synthetic fixtures and ephemeral owner state admitted"}


def prepare_broker_fixture(root):
    """Select an explicit empty vault config through the existing root seam.

    Capability proofs exercise no vault/account behavior. They must not fall
    back to the repository's private-account broker configuration.
    """
    root = Path(root).resolve()
    task_roots = (REPO / ".agent_control/proofs", REPO / ".agent_control/proofs-a")
    if not any(root.is_relative_to(base) for base in (*task_roots, *_ROOTS)):
        raise ValueError("Broker fixtures require disposable proof state")
    path = root / "config/neyvia_secret_broker.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write('{"stack": {}, "policy": {}, "accounts": [], "handles": [], "destinations": []}\n')
    return path
