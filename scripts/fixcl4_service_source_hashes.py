"""Source boundary for the actual FIXCL4 service/provider journeys."""
from __future__ import annotations
import hashlib
from fixcl_verify import REPO, source_hashes


def service_source_hashes():
    result=source_hashes()
    paths=[REPO/'src/grant_agent'/name for name in (
        'neyvia_autopilot.py','autopilot_model.py','efficiency_cascade.py','neyvia_conductor.py','neyvia_runtime.py',
        'proof_credential_guard.py','neyvia_gamedev.py','neyvia_settings.py','proofs_d_native.py',
        'connected_sessions/codex_rpc.py')]
    paths += [REPO/'scripts'/name for name in ('fixcl4_service_source_hashes.py',
        'fixcl4_services_probe.py','fixcl4_provider_probe.py','fixcl4_conductor_probe.py')]
    paths += [REPO/'manuals'/name for name in ('autopilot.manual.json','conductor.manual.json')]
    return {**result, **{path.relative_to(REPO).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
