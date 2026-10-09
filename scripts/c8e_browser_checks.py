"""Observe genuine Harness worker capacity waits without provider dispatch.

The controlled prerequisite is an occupied original OS execution slot. The
worker produces its own queue state; no result/status/waiting record is seeded.
The provider-dependent blocked receipt remains explicitly unproved.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import uuid

REPO = Path(__file__).resolve().parents[1]
FENCE_TEXT = ("import os\ntry:\n"
              " from c8e_browser_checks import install_capacity_worker\n"
              " install_capacity_worker()\n"
              "except BaseException:\n os._exit(73)\n")
MARKER_NAME = 'browser-capacity-fixture.json'
_RETAINED_GUARDS = []


def prepare_fixture(root):
    root = Path(root).resolve(strict=True)
    root.relative_to(REPO / '.agent_control/proofs/C8')
    fence = root / 'c8/harness-fence'
    fence.mkdir(parents=True, exist_ok=True)
    (fence / 'sitecustomize.py').write_bytes(FENCE_TEXT.encode('utf-8'))
    value = {'schema': 'neyvia.c8e.capacity-fixture.v1', 'root': str(root),
             'helperSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'fenceSha256': hashlib.sha256(FENCE_TEXT.encode()).hexdigest()}
    (root / 'c8' / MARKER_NAME).write_text(json.dumps(value), encoding='utf-8')
    return value


def install_capacity_worker():
    """Fence the unmodified worker before its imports, via task sitecustomize."""
    expected = REPO / 'src/grant_agent/harness_job_worker.py'
    if (len(sys.argv) != 5 or Path(sys.argv[0]).resolve() != expected
            or sys.argv[1] != '--root' or sys.argv[3] != '--job-id'):
        raise PermissionError('Only the original capacity-wait worker is admitted')
    root = Path(sys.argv[2]).resolve(strict=True)
    root.relative_to(REPO / '.agent_control/proofs/C8')
    if Path.cwd().resolve() != root:
        raise PermissionError('Capacity worker cwd must equal its own root')
    marker = json.loads((root / 'c8' / MARKER_NAME).read_text(encoding='utf-8'))
    if (marker['root'] != str(root) or marker['helperSha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            or (root / 'c8/harness-fence/sitecustomize.py').read_text(encoding='utf-8') != FENCE_TEXT):
        raise PermissionError('Capacity worker source/fence binding differs')
    job_path = root / '.agent_control/harness_jobs' / (sys.argv[4] + '.json')
    job = json.loads(job_path.read_text(encoding='utf-8'))
    if (job['id'] != sys.argv[4] or job['status'] not in ('queued', 'running')
            or job['request'].get('c8eCapacityOnly') is not True
            or Path(job['workspacePath']).resolve() != root):
        raise PermissionError('No authentic own capacity-only request exists')
    # Values are never inspected or printed. The worker cannot inherit an
    # operator transport, provider login, saved account home or mutable cache.
    for key in list(os.environ):
        if any(part in key.upper() for part in ('TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'API_KEY', 'APIKEY', 'AUTH_FILE', 'BASE_URL')):
            os.environ.pop(key, None)
    home = root / 'c8/harness-home'
    home.mkdir(exist_ok=True)
    names = {'USERPROFILE': home, 'APPDATA': home / 'appdata', 'LOCALAPPDATA': home / 'localappdata',
             'CODEX_HOME': home / 'codex', 'HERMES_HOME': home / 'hermes',
             'OPENCLAW_STATE_DIR': home / 'openclaw', 'TEMP': home / 'temp',
             'TMP': home / 'temp', 'TMPDIR': home / 'temp'}
    for key, directory in names.items():
        directory.mkdir(exist_ok=True)
        os.environ[key] = str(directory)
    os.environ.pop('HOME', None)
    os.environ.update(NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0',
                      NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_RUNTIME_AUTO_UPDATE='0',
                      PYTHONDONTWRITEBYTECODE='1')
    from c8_scope import install
    install(allow_children=False, writable_root=root)
    from grant_agent.proof_credential_guard import install as credential_guard
    credential_guard(root)
    (root / 'c8/harness-fence-entered.json').write_text(json.dumps({
        'pid': os.getpid(), 'jobId': job['id'], 'root': str(root),
        'helperSha256': marker['helperSha256'], 'childrenDenied': True,
        'savedCredentialsGuarded': True, 'homes': {k: str(v) for k, v in names.items()}}), encoding='utf-8')


def _check(identity, passed, observed, boundary='production-state'):
    return {'id': identity, 'passed': bool(passed), 'fresh': True,
            'boundary': boundary, 'observed': observed}


def before_manual(worker, binding, inputs, root):
    from grant_agent.harness_execution_capacity import HarnessExecutionCapacity
    from grant_agent.harness_jobs import (_try_advisory_job_lock,
                                        _release_advisory_job_lock, _process_alive)
    root = Path(root).resolve(strict=True)
    marker = prepare_fixture(root)
    controller = HarnessExecutionCapacity(root, max_running_jobs=1)
    if controller.effective_limit() != 1:
        raise RuntimeError('Own capacity policy did not retain the one-slot limit')
    guard_path = controller._slot_path(1)
    descriptor = os.open(guard_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_BINARY', 0), 0o600)
    if not _try_advisory_job_lock(descriptor):
        os.close(descriptor)
        raise RuntimeError('Own disposable execution slot was unexpectedly occupied')
    job = None
    checks = []
    observed = {'fixture': marker, 'slotPath': str(guard_path),
                'controlledPrerequisite': 'Original OS advisory slot held before the genuine worker starts'}
    contracts = []
    stopped = False
    saved_url = worker.page.url
    try:
        message = 'C8e actual capacity wait ' + uuid.uuid4().hex
        job = worker.tool('backend:start_harness_job_command', {
            'harnessId': 'neyvia-agent', 'harnessLabel': 'Neyvia capacity witness',
            'runtime': 'neyvia-agent', 'mode': 'direct', 'message': message,
            'workspacePath': str(root), 'c8eCapacityOnly': True,
            'exactRoute': True, 'allowRuntimeFallback': False, 'maxRuntimeSeconds': 90})
        def fresh_job():
            return worker.tool('backend:get_harness_job_command', {'jobId': job['id']})
        current = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current = fresh_job()
            if current.get('waitingReason') == 'execution-capacity':
                break
            if current.get('status') in ('failed', 'completed', 'cancelled', 'blocked'):
                break
            worker.page.wait_for_timeout(100)
        fence = json.loads((root / 'c8/harness-fence-entered.json').read_text(encoding='utf-8'))
        unexpected_lease, capacity_snapshot = controller.try_acquire(job['id'])
        if unexpected_lease is not None:
            unexpected_lease.release()
            raise RuntimeError('Held original OS slot unexpectedly allowed execution')
        no_slot = (current['status'] == 'running' and current.get('waitingReason') == 'execution-capacity'
                   and not current.get('result') and not current.get('error')
                   and current.get('executionCapacity', {}).get('state') != 'active'
                   and capacity_snapshot['activeNewSlots'] == 1
                   and capacity_snapshot['availableNewSlots'] == 0
                   and fence['pid'] == current['pid'] and fence['childrenDenied'] is True)
        checks.append(_check('c8e.browser.real-worker-waits-before-provider', no_slot,
                             {'freshJob': current, 'enteredFence': fence, 'originalControllerSnapshot': capacity_snapshot}))
        target = urlsplit(worker.args.candidate_url)
        worker.page.goto(f'{target.scheme}://{target.netloc}/control/?ui=classic&surface=harnesses', wait_until='domcontentloaded')
        surface = worker.page.locator('[data-harnesses-surface=true]')
        surface.wait_for(timeout=30000)
        row = surface.locator('.neyvia-harnesses__jobs button').filter(has_text=message)
        row.wait_for(timeout=30000)
        row.click()
        receipt = surface.locator('[data-harness-receipt=true]')
        receipt.wait_for(timeout=30000)
        row_text = row.inner_text(); label = row.get_attribute('aria-label'); receipt_text = receipt.inner_text()
        visible_label = no_slot and 'WAITING FOR CAPACITY' in row_text.upper() and 'waiting for capacity' in label and 'WAITING FOR CAPACITY' in receipt_text.upper()
        explanation = no_slot and 'Provider/model execution is waiting for a workspace capacity slot' in receipt_text and 'no execution slot is claimed yet' in receipt_text
        checks.append(_check('c8e.browser.real-capacity-mounted-label', visible_label,
                             {'row': row_text, 'ariaLabel': label, 'receipt': receipt_text}, 'rendered-user-action'))
        checks.append(_check('c8e.browser.real-capacity-mounted-explanation', explanation,
                             {'receipt': receipt_text, 'freshJob': fresh_job()}, 'rendered-user-action'))
        observed['mounted'] = {'url': worker.page.url, 'screenshot': worker.screenshot('effect-browser-capacity')}
        contracts = [
            _check('proofs-b.browser.capacity-label', visible_label, checks[-2], 'rendered-user-action'),
            _check('proofs-b.browser.capacity-explanation', explanation, checks[-1], 'rendered-user-action'),
            _check('proofs-b.browser.blocked-receipt', False, {'missingCase': 'Genuine started worker-produced blocked result with preserved structured result, Prepare retry and explicit blocked cleanup. Route absence yields failed, not blocked; no result was seeded.'}, 'rendered-user-action')]
        # This is the real user cleanup action on the actual mounted run.
        surface.get_by_role('button', name='Stop', exact=True).click()
    finally:
        if job is not None:
            try:
                current = worker.tool('backend:get_harness_job_command', {'jobId': job['id']})
                if current.get('status') not in ('cancelled', 'completed', 'failed'):
                    worker.tool('backend:cancel_harness_job_command', {'jobId': job['id']})
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    current = worker.tool('backend:get_harness_job_command', {'jobId': job['id']})
                    if current.get('status') == 'cancelled' and not _process_alive(int(job.get('pid') or 0)):
                        stopped = True
                        break
                    worker.page.wait_for_timeout(100)
                observed['actualCleanup'] = current
                checks.append(_check('c8e.browser.cancelled-own-worker-before-slot-release', stopped,
                                     {'job': current, 'originalWorkerPid': job.get('pid')}))
            finally:
                if stopped:
                    _release_advisory_job_lock(descriptor)
                    os.close(descriptor)
                else:
                    # Never release a slot while an unconfirmed worker could
                    # dispatch. The child fence still forbids all providers.
                    _RETAINED_GUARDS.append(descriptor)
        else:
            _release_advisory_job_lock(descriptor)
            os.close(descriptor)
        proof = {'passed': False, 'checks': checks, 'contractEffects': contracts,
                 'observed': observed, 'boundary': 'Original detached worker, actual OS slot and mounted HarnessesSurface; provider execution remains denied',
                 'missingPrerequisite': 'Actual worker-produced blocked receipt and retry/blocked-cleanup effect; genuine capacity cases are partial and the seeded browser verifier is not accepted.'}
        worker.effect_evidence = proof
        worker.step_results['c8eBrowserCapacity'] = proof
        if stopped:
            worker.page.goto(saved_url, wait_until='domcontentloaded')
    return proof


def witness(worker, binding, inputs, root):
    proof = worker.step_results['c8eBrowserCapacity']
    return proof['checks'], {**proof['observed'], 'contractEffects': proof['contractEffects']}
