"""Pure cases for the connections screen's invariants (track CONN): no process, network or credential is touched."""
from __future__ import annotations

from pathlib import Path
import json
import sys
import time
from unittest.mock import patch

from . import neyvia_connections as connections

CONTRACT = "conn.screen.invariants"
_ARGV = ["wt", "-w", "new", "--title", "Claude Code sign-in", "cmd", "/k", "claude auth login"]


def _good() -> list[dict]:
    return [
        {"id": "claude-code", "state": "needs-signin", "why": "Not signed in to Claude.", "provable": True,
         "fix": {"kind": "terminal", "label": "Sign in with Claude", "command": "claude auth login", "argv": _ARGV}},
        {"id": "codex", "state": "connected", "why": "Signed in.", "provable": True, "fix": None,
         "proof": {"ok": True, "steps": [{"step": "tool call", "ok": True, "detail": "1 tool call(s) in the turn"}]}},
        {"id": "gptme", "state": "not-installed", "why": "gptme is not on this PC.", "fix": {"kind": "install", "label": "Install", "command": "pipx install gptme"}},
        {"id": "api-keys", "state": "connected", "why": "OpenRouter key saved.", "fix": {"kind": "keys", "label": "Add or change keys"}},
        {"id": "local-models", "state": "checking", "why": "Looking…", "fix": None},
    ]


def _refused(mutate) -> bool:
    cards = _good()
    mutate(cards)
    try:
        connections.check_cards(cards)
    except ValueError:
        return True
    return False


def _screen_invariants() -> dict:
    connections.check_cards(_good())
    cases = {
        "signed-out receipt": lambda c: c[0].update(proof={"ok": True}),
        "needs sign-in without a next step": lambda c: c[0].update(fix=None),
        "connected without a reason": lambda c: c[1].update(why=""),
        "sign-in that is not a terminal": lambda c: c[0]["fix"].update(argv=["cmd", "/c", "claude auth login"]),
        "secret in the payload": lambda c: c[3].update(why="Key sk saved, apiKey=abc"),
        "unknown state": lambda c: c[2].update(state="mystery"),
        "repeated id": lambda c: c[2].update(id="codex"),
    }
    missed = [name for name, mutate in cases.items() if not _refused(mutate)]
    if missed:
        raise AssertionError(f"{CONTRACT}: the screen invariants let through: {', '.join(missed)}")
    return {"contract": CONTRACT, "refused": sorted(cases)}


def _install_lifecycle(root):
    from . import connections_install as installer
    from .neyvia_workspace_tools import WorkspaceTools
    service = WorkspaceTools(root)
    events, calls = [], []
    # The package transport is a real hidden disposable helper. It performs no
    # network install and cannot launch an installed provider or desktop window.
    def package(ident, folder, emit, approval):
        calls.append((ident, approval))
        emit('Local package transport fixture')
        result = installer.run_hidden([sys.executable, '-I', '-c',
            "import sys; print('fixture-harness 1.0'); sys.exit(" + ('1' if len(calls) == 1 else '0') + ")"],
            folder, emit, timeout=15)
        if result.returncode:
            raise RuntimeError('Controlled package transport failure')
        return result.stdout.strip()
    def terminal():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            row = installer.progress(service, 'codex') or {}
            if row.get('state') in {'failed', 'completed'}:
                return row
            time.sleep(.02)
        raise AssertionError('Install fixture did not settle')
    try:
        with patch.object(installer, 'install_package', package), patch.object(installer, 'neyvia_managed_runtime_root', lambda: root/'managed'):
            result = installer.install(service, {'id':'codex','fromClick':True}, events.append)
            assert result.get('needsConsent') and not calls
            approval = result.get('approvalId') or result.get('approval', {}).get('id')
            if not approval:
                raise AssertionError('Consent request has no exact approval identity: '+str(result))
            wrong = installer.install(service, {'id':'codex','fromClick':True,'consent':True,'approvalId':'unrelated'}, events.append)
            assert wrong.get('needsConsent') and not calls
            installer.install(service, {'id':'codex','fromClick':True,'consent':True,'approvalId':approval}, events.append)
            failed = terminal(); assert failed['state']=='failed' and not events
            installer._jobs.pop((str(root),'codex'))  # a restarted backend reads the durable failure/consent
            installer.install(service, {'id':'codex','fromClick':True}, events.append)
            completed = terminal(); assert completed['state']=='completed' and completed['version']=='fixture-harness 1.0'
            assert events==['codex'] and len(calls)==2 and calls[0][1]==calls[1][1]==approval
            receipt = json.loads((root/'managed/connections/codex.json').read_text(encoding='utf-8'))
            assert receipt.get('version')==completed['version']
        return {'consentRequired':True,'unrelatedConsentRefused':True,'failurePersisted':True,
                'restartRetrySameConsent':True,'verifiedVersion':completed['version'],
                'boundary':'Real install state/approval/progress persistence and hidden child process; finite package transport fixture, no provider install'}
    finally:
        service.close()


def self_check(scratch=None) -> dict:
    from .contract_gate import wants
    cases=[]
    for identity, action in [(CONTRACT, _screen_invariants), ('conn.install.lifecycle', lambda: _install_lifecycle(Path(scratch)))]:
        if not wants(identity):
            continue
        try:
            cases.append({'id':identity,'contracts':[identity],'ok':True,'observed':action()})
        except Exception as error:
            cases.append({'id':identity,'contracts':[identity],'ok':False,'error':str(error)})
    return {'ok':bool(cases) and all(row['ok'] for row in cases),'cases':cases,
            'contracts':[row['id'] for row in cases if row['ok']]}
