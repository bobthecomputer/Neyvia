"""Executable contracts for durable local Harness actions.

The scratch procedure uses the real store, scheduler, worker budget functions and
OS advisory locks. It never starts a provider or replaces a runtime adapter.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONTRACTS = (
    "proofs-b.harness.identity", "proofs-b.harness.lifecycle",
    "proofs-b.harness.budget", "proofs-b.harness.policy",
    "proofs-b.harness.observation", "proofs-b.harness.admission",
    "proofs-b.harness.execution", "proofs-b.harness.lock-recovery",
    "proofs-b.harness.budget-input",
    "proofs-b.harness.public-profile", "proofs-b.harness.gateway",
    "proofs-b.harness.instruction", "proofs-b.harness.catalog",
    "proofs-b.harness.model-policy",
)


def _require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def check_write(path, payload):
    schema = payload.get("schema")
    if schema not in {"neyvia.harness_job.v1", "neyvia.harness_admission_policy.v1", "neyvia.harness_execution_policy.v1"}:
        return
    previous = None
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if schema.endswith("policy.v1"):
        key = "maxOpenJobs" if "admission" in schema else "maxRunningJobs"
        limit = payload.get(key)
        _require(type(limit) is int and 1 <= limit <= 100,
                 "proofs-b.harness.policy", "hard limit outside retained range")
        if isinstance(previous, dict) and previous.get("schema") == schema:
            _require(limit <= previous[key], "proofs-b.harness.policy", "ambient limit expansion")
        return
    _require(payload.get("id") == path.stem and isinstance(payload.get("request"), dict),
             "proofs-b.harness.identity", "saved request identity differs from receipt path")
    _require(payload.get("status") in {"queued", "running", "cancelling", "blocked", "completed", "failed", "cancelled", "interrupted"},
             "proofs-b.harness.lifecycle", "unknown newly written lifecycle")
    if not isinstance(previous, dict) or previous.get("schema") != schema:
        return
    _require(previous.get("id") == payload["id"] and previous.get("request") == payload["request"],
             "proofs-b.harness.identity", "existing request identity changed")
    before, after = previous.get("status"), payload["status"]
    if before in {"completed", "failed", "cancelled", "interrupted"}:
        _require(after == before, "proofs-b.harness.lifecycle", "stopped job revived")
    if before == "blocked":
        _require(after in {"blocked", "cancelled"}, "proofs-b.harness.lifecycle", "late worker overwrote blocker")
    if before == "cancelling":
        _require(after in {"cancelling", "cancelled"}, "proofs-b.harness.lifecycle", "cancellation claim overwritten")
    old_budget, budget = previous.get("budget"), payload.get("budget")
    if isinstance(old_budget, dict) and old_budget.get("status") == "exhausted":
        _require(isinstance(budget, dict) and budget.get("status") == "exhausted"
                 and budget.get("exhaustedAt") == old_budget.get("exhaustedAt"),
                 "proofs-b.harness.budget", "budget exhaustion evidence overwritten")
    if isinstance(old_budget, dict) and isinstance(budget, dict):
        for key in ("maxTokens", "maxCostUsd"):
            if key in old_budget:
                _require(budget.get(key) == old_budget[key], "proofs-b.harness.budget", "unrelated budget dimension lost")
    if after == "cancelled" and isinstance(budget, dict):
        _require(budget.get("status") != "active", "proofs-b.harness.budget", "cancelled worker retained active budget")
    if (after == "cancelling" and payload.get("cancelError") and payload.get("cancelReason") == "operator"
            and isinstance(old_budget, dict) and old_budget.get("status") == "active"):
        _require(isinstance(budget, dict) and budget.get("status") == "active",
                 "proofs-b.harness.budget", "failed operator stop released active enforcement")
    if payload.get("budgetOutcome") == "enforcement-retrying":
        _require(after in {"cancelling", "cancelled"} and isinstance(budget, dict) and budget.get("status") == "exhausted"
                 and int(payload.get("budgetEnforcementAttempts") or 0) >= 1,
                 "proofs-b.harness.budget", "retry lost exhausted budget or actual attempt receipt")
    if previous.get("budgetEnforcementAttempts"):
        _require(int(payload.get("budgetEnforcementAttempts") or 0) >= int(previous["budgetEnforcementAttempts"]),
                 "proofs-b.harness.budget", "enforcement retry history decreased")


def check_observation(payload, observed):
    from .harness_jobs import _duration_ms, TERMINAL_JOB_STATUSES
    status = str(payload.get("status") or "queued").strip().lower() or "queued"
    metric = observed["metrics"]
    reference = payload.get("finishedAt") or payload.get("updatedAt") or payload.get("createdAt")
    expected = {
        "queueLatencyMs": _duration_ms(payload.get("createdAt"), payload.get("startedAt")),
        "executionDurationMs": _duration_ms(payload.get("startedAt"), reference),
        "totalDurationMs": _duration_ms(payload.get("createdAt"), reference),
        "terminal": status in TERMINAL_JOB_STATUSES,
        "receiptPresent": bool(isinstance(payload.get("result"), dict) and payload["result"]),
        "timelinePhaseCount": len(observed["timeline"]),
    }
    _require(metric == expected and all(observed.get(k) == v for k, v in payload.items() if k not in {"metrics", "timeline"}),
             "proofs-b.harness.observation", "projection loses source evidence or derives wrong timing")
    expected_phases = []
    for key, phase in (("createdAt", "queued"), ("startedAt", "running"), ("cancelRequestedAt", "cancelling"), ("finishedAt", status)):
        if payload.get(key):
            expected_phases.append((phase, str(payload[key]), _duration_ms(payload.get("createdAt"), payload[key]) or 0))
    _require([(r["phase"], r["at"], r["elapsedMs"]) for r in observed["timeline"]] == expected_phases,
             "proofs-b.harness.observation", "timeline differs from durable timestamps")


def check_admission(snapshot):
    terminal = {"completed", "failed", "cancelled", "interrupted"}
    counts = snapshot["statusCounts"]
    open_jobs = sum(n for status, n in counts.items() if status not in terminal)
    slots = max(0, snapshot["maxOpenJobs"] - open_jobs)
    _require(snapshot["openJobs"] == open_jobs and snapshot["availableSlots"] == slots
             and snapshot["blockedJobs"] == counts.get("blocked", 0)
             and snapshot["unreadableJobs"] == counts.get("unreadable", 0)
             and snapshot["admissionState"] == ("available" if slots else "blocked"),
             "proofs-b.harness.admission", "pressure projection frees unresolved evidence")


def check_execution_snapshot(snapshot, waiter_ids, job_id):
    expected_position = waiter_ids.index(job_id) if job_id in waiter_ids else -1
    slots = max(0, snapshot["maxRunningJobs"] - snapshot["legacyOrUnknownActive"] - snapshot["activeNewSlots"])
    _require(snapshot["availableNewSlots"] == slots and snapshot["queuePosition"] == expected_position
             and snapshot["queueDepth"] == len(waiter_ids),
             "proofs-b.harness.execution", "execution queue or reserved capacity projection differs")


def check_liveness_outcome(outcome, *, error=None, wait_result=None):
    expected = error != 87 if error is not None else wait_result != 0
    _require(type(outcome) is bool and outcome == expected,
             "proofs-b.harness.lock-recovery", "indeterminate process evidence freed ownership")


def check_budget_input(value, seconds):
    nested = value.get("budget")
    raw = nested.get("maxRuntimeSeconds") if isinstance(nested, dict) else None
    if raw is None:
        raw = value.get("maxRuntimeSeconds")
    if raw is None:
        raw = value.get("max_runtime_seconds")
    expected = 0 if raw is None or raw == "" else int(str(raw).strip())
    _require(type(seconds) is int and seconds == expected and 0 <= seconds <= threading.TIMEOUT_MAX,
             "proofs-b.harness.budget-input", "hard budget does not match explicit priority")


def check_profile(profile):
    from .harness_registry import PROFILE_FIELDS
    _require(set(profile) <= PROFILE_FIELDS | {"updatedAt"}
             and all(isinstance(v, str) for v in profile.values()),
             "proofs-b.harness.public-profile", "profile persisted fields beyond public route vocabulary")


def check_gateway(harness, profile, name, value, env):
    model = profile.get("model")
    if model and harness in {"neyvia-agent", "claude-code", "grok-build", "kimi-code", "deepseek-harness", "rook"}:
        _require(env.get("FLUXIO_HARNESS_MODEL") == model, "proofs-b.harness.gateway", "explicit model route lost")
    _require(env.get("FLUXIO_HARNESS_PROFILE") == profile.get("id"), "proofs-b.harness.gateway", "profile identity lost")
    base = str(profile.get("baseUrl") or "").rstrip("/")
    base_key = {"neyvia-agent": "OPENAI_BASE_URL", "claude-code": "ANTHROPIC_BASE_URL", "grok-build": "GROK_MODELS_BASE_URL", "kimi-code": "FLUXIO_HARNESS_BASE_URL"}.get(harness)
    if base and base_key:
        _require(env.get(base_key) == base, "proofs-b.harness.gateway", "explicit base route lost")
    if value:
        target = {"neyvia-agent": "OPENAI_API_KEY", "grok-build": "XAI_API_KEY", "deepseek-harness": "DEEPSEEK_API_KEY", "rook": name}.get(harness)
        if harness == "claude-code":
            target = "ANTHROPIC_API_KEY" if profile.get("credentialKind") == "api-key" else "ANTHROPIC_AUTH_TOKEN"
        if target:
            _require(env.get(target) == value, "proofs-b.harness.gateway", "credential reference mapped to wrong auth surface")
    if harness == "claude-code" and profile.get("compatibilityMode") == "cliproxy":
        from urllib.parse import urlparse
        parsed = urlparse(env.get("ANTHROPIC_BASE_URL", ""))
        _require(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                 and env.get("ANTHROPIC_AUTH_TOKEN") == value
                 and env.get("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY") == "1",
                 "proofs-b.harness.gateway", "explicit loopback gateway policy violated")


def check_instruction(root, target, receipt, encoded, previous):
    _require(target.is_relative_to(root) and target.read_bytes() == encoded.rstrip() + b"\n"
             and receipt["relativePath"] == target.relative_to(root).as_posix()
             and receipt["bytes"] == target.stat().st_size,
             "proofs-b.harness.instruction", "instruction receipt differs from bounded saved bytes")
    if previous is not None:
        backup = Path(receipt["backupPath"])
        _require(backup.is_relative_to(root) and backup.read_bytes() == previous,
                 "proofs-b.harness.instruction", "instruction replacement lost original backup")


def check_catalog(catalog):
    from .harness_registry import HARNESS_SPECS
    rows = catalog["harnesses"]
    _require([r["harnessId"] for r in rows] == [s.harness_id for s in HARNESS_SPECS],
             "proofs-b.harness.catalog", "catalog omitted or reordered canonical harnesses")
    for row, spec in zip(rows, HARNESS_SPECS):
        _require(row["securityOnly"] == spec.security_only and row["headlessTransport"] == spec.headless_transport
                 and row["integrationTier"] == spec.integration_tier,
                 "proofs-b.harness.catalog", "catalog misrepresented harness ownership or transport")
        if row["providerConfigured"] is False:
            _require(not any(r["available"] for r in row["capabilities"]),
                     "proofs-b.harness.catalog", "unconfigured provider advertised callable native capabilities")


def registry_projection(root):
    """Run only configuration projections in a child with a scratch runtime home.

    All runtime statuses are supplied; no installed CLI can be selected for a
    version probe. Kimi's unconditional provider-summary probe receives a missing
    scratch executable; its subprocess environment can read only the first,
    explicitly supplied scratch runtime home. No credential file exists there.
    """
    from .harness_registry import HARNESS_SPECS, build_harness_catalog, _probe_harness_command
    from .runtimes.base import runtime_bin_candidates
    uv_bin = Path.home() / ".local/bin"
    uv_bin.mkdir(parents=True)
    _require(uv_bin in runtime_bin_candidates(root), "proofs-b.harness.catalog", "home uv tools omitted")
    launcher = root / "neyvia-agent"
    launcher.write_text("intrinsic release marker; never execute", encoding="utf-8")
    detected, version, detail = _probe_harness_command(str(launcher), root, "neyvia-agent")
    _require(detected and version.startswith("Neyvia Agent ") and not detail,
             "proofs-b.harness.catalog", "native intrinsic release evidence lost")
    supplied = [{"runtime_id": spec.execution_adapter, "detected": spec.harness_id == "deepseek-harness",
                 "command": str(root / "uninstalled-runtime"), "version": "projection-only"}
                for spec in HARNESS_SPECS]
    catalog = build_harness_catalog(root, runtime_statuses=supplied, provider_env={"DEEPSEEK_API_KEY": ""})
    _require([r["harnessId"] for r in catalog["harnesses"]] == ["neyvia-agent", "fluxio-hybrid", "hermes", "openclaw", "codex", "claude-code", "grok-build", "kimi-code", "opencode", "cursor", "prime-agent", "pi", "deepseek-harness", "gptme", "rook", "wallbreaker"]
             and "GROK_MODELS_BASE_URL" in catalog["openSurfaces"]["grok-build"]["gateway"],
             "proofs-b.harness.catalog", "canonical public surfaces lost")
    row = next(r for r in catalog["harnesses"] if r["harnessId"] == "deepseek-harness")
    _require(row["providerConfigured"] is False and row["readiness"] == "provider-setup-required",
             "proofs-b.harness.catalog", "missing configured credential falsely shown ready")
    extension = next(r for r in catalog["extensions"] if r["id"] == "dsh-j-space")
    _require(extension["hostHarnessId"] == "deepseek-harness" and extension["licenseId"] == "Apache-2.0",
             "proofs-b.harness.catalog", "extension provenance lost")
    return {"ok": True, "harnessCount": len(catalog["harnesses"]), "deepseekReadiness": row["readiness"], "uvToolPathObserved": True}


class _OwnedProcessDacl:
    """Temporary access fence on an owned Popen child, never machine policy.

    Keep the creation handle and original security descriptor throughout. Its
    existing WRITE_DAC and termination rights remain valid after a deny ACE is
    added, so the caller can always restore and reap in its finally block.
    """

    def __init__(self, process):
        import ctypes
        from ctypes import wintypes
        self.process = process
        self.ctypes = ctypes
        self.wintypes = wintypes
        pointer = ctypes.c_void_p
        pointer_pointer = ctypes.POINTER(pointer)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        self.security.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
                                                 pointer_pointer, pointer_pointer, pointer_pointer,
                                                 pointer_pointer, pointer_pointer]
        self.security.GetSecurityInfo.restype = wintypes.DWORD
        self.security.SetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
                                                 pointer, pointer, pointer, pointer]
        self.security.SetSecurityInfo.restype = wintypes.DWORD
        self.security.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, pointer_pointer]
        self.security.ConvertStringSidToSidW.restype = wintypes.BOOL
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.LocalFree.argtypes = [pointer]
        self.kernel.LocalFree.restype = pointer
        self.original_acl = pointer()
        self.descriptor = pointer()
        self.sid = pointer()
        self.acls = []
        self.changed = False
        self.restore_code = None
        code = self.security.GetSecurityInfo(int(process._handle), 6, 4, None, None,
                                             ctypes.byref(self.original_acl), None,
                                             ctypes.byref(self.descriptor))
        _require(code == 0, "proofs-b.harness.lock-recovery", f"owned GetSecurityInfo failed with {code}")
        if not self.security.ConvertStringSidToSidW("S-1-1-0", ctypes.byref(self.sid)):
            self.kernel.LocalFree(self.descriptor)
            raise ValueError("Owned process SID allocation failed")

    def deny(self, mask):
        ctypes, wintypes = self.ctypes, self.wintypes
        class Trustee(ctypes.Structure):
            _fields_ = [("pMultipleTrustee", ctypes.c_void_p), ("MultipleTrusteeOperation", ctypes.c_int),
                        ("TrusteeForm", ctypes.c_int), ("TrusteeType", ctypes.c_int), ("ptstrName", wintypes.LPWSTR)]
        class ExplicitAccess(ctypes.Structure):
            _fields_ = [("grfAccessPermissions", wintypes.DWORD), ("grfAccessMode", ctypes.c_int),
                        ("grfInheritance", wintypes.DWORD), ("Trustee", Trustee)]
        self.security.SetEntriesInAclW.argtypes = [wintypes.ULONG, ctypes.POINTER(ExplicitAccess),
                                                  ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.security.SetEntriesInAclW.restype = wintypes.DWORD
        entry = ExplicitAccess(mask, 3, 0, Trustee(None, 0, 0, 5, ctypes.cast(self.sid, wintypes.LPWSTR)))
        acl = ctypes.c_void_p()
        code = self.security.SetEntriesInAclW(1, ctypes.byref(entry), self.original_acl, ctypes.byref(acl))
        self.acls.append(acl)
        _require(code == 0, "proofs-b.harness.lock-recovery", f"owned SetEntriesInAcl failed with {code}")
        code = self.security.SetSecurityInfo(int(self.process._handle), 6, 4, None, None, acl, None)
        _require(code == 0, "proofs-b.harness.lock-recovery", f"owned DACL fence failed with {code}")
        self.changed = True

    def synchronize_error(self):
        handle = self.kernel.OpenProcess(0x00100000, False, self.process.pid)
        error = self.ctypes.get_last_error()
        if handle:
            self.kernel.CloseHandle(handle)
        return bool(handle), error

    def restore(self):
        code = self.security.SetSecurityInfo(int(self.process._handle), 6, 4, None, None, self.original_acl, None)
        self.restore_code = code
        _require(code == 0, "proofs-b.harness.lock-recovery", f"owned original DACL restore failed with {code}")
        self.changed = False

    def close(self):
        try:
            if self.changed:
                self.restore()
        finally:
            for acl in self.acls:
                if acl.value:
                    self.kernel.LocalFree(acl)
            if self.sid.value:
                self.kernel.LocalFree(self.sid)
            if self.descriptor.value:
                self.kernel.LocalFree(self.descriptor)


def _owned_access_failure_procedure(root):
    """Observe actual Win32 access-denied and real watchdog retries locally."""
    if os.name != "nt":
        raise ValueError("Controlled owned-process access-denied proof requires Win32")
    from .harness_jobs import HarnessJobStore, _process_alive, _process_command_line
    from .harness_job_worker import _remaining_runtime_budget_seconds, _start_runtime_budget_watchdog
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    calls = []
    for mode in ("query-denied", "stop-retry"):
        folder = root / ("qdeny" if mode == "query-denied" else "tretry")
        folder.mkdir()
        store = HarnessJobStore(folder, max_open_jobs=1)
        max_runtime = 30 if mode == "query-denied" else 1
        created = store.create({"runtime": "neyvia-agent", "message": "Owned Win32 host access failure proof",
                                "budget": {"maxRuntimeSeconds": max_runtime, "maxTokens": 2025, "maxCostUsd": 1.5}})
        job_id = created["id"]
        source = "\n".join([
            "import json,os,sys,time",
            "deadline=time.monotonic()+30",
            "from pathlib import Path",
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})",
            "from grant_agent.harness_jobs import HarnessJobStore",
            "from grant_agent.harness_job_worker import _arm_runtime_budget",
            "store=HarnessJobStore(Path(sys.argv[1])); job=sys.argv[2]",
            "row=store.mark_started(job,pid=os.getpid())",
            "_arm_runtime_budget(store,job,row['request'],max_runtime_seconds=int(sys.argv[3]))",
            "print(json.dumps({'pid':os.getpid(),'deadlineSeconds':30}),flush=True)",
            "time.sleep(max(0,deadline-time.monotonic()))",
        ])
        child_started = time.monotonic()
        process = subprocess.Popen([sys.executable, "-c", source, str(store.root), job_id, str(max_runtime)],
                                   cwd=store.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
        fence, watchdog = None, None
        row = {"procedure": "owned-win32-access-failure", "mode": mode, "pid": process.pid,
               "jobId": job_id, "childSelfExitSeconds": 30, "creationHandleRetained": True}
        try:
            ready = []
            reader = threading.Thread(target=lambda: ready.append(process.stdout.readline()), daemon=True)
            reader.start()
            reader.join(timeout=8)
            _require(not reader.is_alive() and ready and ready[0].strip(), "proofs-b.harness.lock-recovery", "owned Win32 child did not become ready")
            _require(json.loads(ready[0])["pid"] == process.pid, "proofs-b.harness.identity", "owned Win32 child identity differs")
            fence = _OwnedProcessDacl(process)
            if mode == "query-denied":
                fence.deny(0x00100000 | 0x1000 | 0x0400 | 0x0010)
                opened, error = fence.synchronize_error()
                observed_live = _process_alive(process.pid)
                observed_command = _process_command_line(process.pid)
                _require(not opened and error == 5 and observed_live and not observed_command,
                         "proofs-b.harness.lock-recovery", "controlled query fence did not yield actual access-denied/unavailable identity")
                try:
                    store.create({"runtime": "neyvia-agent", "message": "must reject while owned identity is unavailable"})
                except RuntimeError as exc:
                    _require("admission capacity" in str(exc), "proofs-b.harness.admission", "unexpected denied admission outcome")
                else:
                    raise ValueError("Unavailable live worker identity freed admission capacity")
                observed = store.load(job_id, reconcile=False)
                _require(observed["status"] == "running" and observed["pid"] == process.pid
                         and store.capacity()["openJobs"] == 1, "proofs-b.harness.admission", "unavailable identity lost live ownership")
                row.update(openSynchronizeError=error, productionLiveness=observed_live,
                           commandLineAvailable=False, admittedReplacement=False, preservedStatus=observed["status"])
            else:
                fence.deny(0x0001)
                _require(bool(_process_command_line(process.pid)), "proofs-b.harness.budget", "termination-only fence obscured verified identity")
                try:
                    store.cancel(job_id)
                except RuntimeError as exc:
                    _require("Could not stop Harness worker" in str(exc), "proofs-b.harness.budget", "stop failed outside actual process termination boundary")
                else:
                    raise ValueError("Controlled terminate denial failed to produce a real stop failure")
                active = store.load(job_id, reconcile=False)
                _require(_process_alive(process.pid) and active["status"] == "cancelling"
                         and active["cancelReason"] == "operator" and active["budget"]["status"] == "active"
                         and active["budgetOutcome"] == "armed" and active.get("cancelError"),
                         "proofs-b.harness.budget", "failed operator stop disabled active hard budget")
                row.update(operatorStopFailed=True, activeBudgetAfterFailedStop=True, statusAfterFailedStop=active["status"])
                remaining = _remaining_runtime_budget_seconds(active["startedAt"], max_runtime)
                watchdog = _start_runtime_budget_watchdog(store, job_id, max_runtime, threading.Event(), wait_seconds=remaining)
                deadline = time.monotonic() + 90
                retries = None
                while time.monotonic() < deadline:
                    retries = store.load(job_id, reconcile=False)
                    if int(retries.get("budgetEnforcementAttempts") or 0) >= 1:
                        break
                    time.sleep(0.05)
                _require(retries and int(retries.get("budgetEnforcementAttempts") or 0) >= 1
                         and retries["budget"]["status"] == "exhausted"
                         and retries["budgetOutcome"] == "enforcement-retrying"
                         and retries["cancelReason"] == "runtime_budget"
                         and _process_alive(process.pid), "proofs-b.harness.budget", "actual denied watchdog retry was not observed before restoration")
                row.update(actualRetriesBeforeRestore=retries["budgetEnforcementAttempts"], exhaustedBeforeRestore=True)
                fence.restore()
                row["originalDaclRestoredBeforeSuccessfulRetry"] = fence.restore_code == 0
                watchdog.join(timeout=15)
                settled = store.load(job_id, reconcile=False)
                enforced_elapsed = time.monotonic() - child_started
                _require(not watchdog.is_alive() and settled["status"] == "cancelled"
                         and settled["budget"]["status"] == "exhausted" and settled["budgetOutcome"] == "enforced"
                         and settled["budget"]["maxTokens"] == 2025 and settled["budget"]["maxCostUsd"] == 1.5
                         and process.poll() is not None and enforced_elapsed < 25,
                         "proofs-b.harness.budget", "real retry after DACL restore did not enforce original budget")
                row.update(finalStatus=settled["status"], finalBudgetStatus=settled["budget"]["status"],
                           budgetOutcome=settled["budgetOutcome"], actualRetries=settled["budgetEnforcementAttempts"],
                           stoppedBeforeSafetyDeadline=True, enforcedElapsedSeconds=round(enforced_elapsed, 3))
            calls.append(row)
        finally:
            try:
                if fence is not None:
                    fence.close()
                    row["finalDaclRestoreCode"] = fence.restore_code
            finally:
                # The retained creation handle is unaffected by the temporary
                # DACL; terminate/reap even if observation or restore failed.
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=8)
                if watchdog is not None and watchdog.is_alive():
                    watchdog.join(timeout=8)
                process.stdout.close()
                process.stderr.close()
                row.update(reaped=True, aliveAfterCleanup=_process_alive(process.pid))
                _require(not row["aliveAfterCleanup"] and (watchdog is None or not watchdog.is_alive()),
                         "proofs-b.harness.lock-recovery", "owned access-failure child/watchdog survived cleanup")
    return calls


def self_check(root):
    from .harness_jobs import HarnessJobStore, _atomic_write_json, _exclusive_job_lock, _job_guard_path, _process_alive
    from .harness_execution_capacity import HarnessExecutionCapacity
    from . import harness_job_worker as worker
    started = time.perf_counter()
    checks, calls, rejections = [], [], []

    def area(name, limit=32):
        folder = root / name
        folder.mkdir(parents=True)
        return HarnessJobStore(folder, max_open_jobs=limit)

    def require(condition, contract, detail):
        _require(condition, contract, detail)

    def rejected(action, name, exception=ValueError):
        try:
            action()
        except exception:
            rejections.append({"contract": name, "rejected": True})
        else:
            raise ValueError(f"Contract {name}: adverse action accepted")

    request = {"harnessId": "neyvia-agent", "runtime": "neyvia-agent", "message": "Local durable proof; never execute a provider"}
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        reading = area("native-read-sharing")
        item = reading.create(request)
        path = reading.job_path(item["id"])
        observed_errors = []
        for persistent in (False, True):
            handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
            require(handle != ctypes.c_void_p(-1).value, CONTRACTS[0], "owned exclusive file handle failed")
            timer = None
            try:
                try:
                    path.read_text(encoding="utf-8")
                except PermissionError as exc:
                    observed_errors.append({"errno": exc.errno, "winerror": exc.winerror})
                else:
                    raise ValueError("Exclusive native handle did not deny actual read")
                if persistent:
                    rejected(lambda: reading.load(item["id"], reconcile=False), CONTRACTS[0], RuntimeError)
                else:
                    timer = threading.Timer(0.25, lambda: kernel.CloseHandle(handle))
                    timer.start()
                    require(reading.load(item["id"], reconcile=False)["id"] == item["id"],
                            CONTRACTS[0], "transient native sharing denial lost valid receipt")
            finally:
                if timer is not None:
                    timer.join(timeout=2)
                    require(not timer.is_alive(), CONTRACTS[0], "native handle release did not finish")
                else:
                    kernel.CloseHandle(handle)
        require(reading.load(item["id"], reconcile=False)["id"] == item["id"], CONTRACTS[0], "persistent failure changed receipt")
        calls.append({"procedure": "native-file-sharing-read", "actualWinErrors": observed_errors,
                      "transientReadRecovered": True, "persistentReadRejected": True, "handlesReleased": True})
    store = area("lifecycle", 2)
    created = store.create(request)
    job = created["id"]
    require(store.create(request, job_id=job)["id"] == job, CONTRACTS[0], "idempotent request duplicated")
    rejected(lambda: store.create({**request, "message": "different"}, job_id=job), CONTRACTS[0])
    blocked = store.finish(job, result={"status": "blocked", "providerId": "unconfigured", "nextAction": "Choose a configured provider"}, error="unconfigured")
    require(not blocked["metrics"]["terminal"] and blocked["timeline"][-1]["phase"] == "blocked", CONTRACTS[1], "blocker became terminal")
    require(store.mark_started(job, pid=os.getpid())["status"] == "blocked"
            and store.finish(job, result={"status": "completed"})["result"] == blocked["result"], CONTRACTS[1], "late event erased blocker")
    second = store.create({**request, "message": "second"})
    rejected(lambda: store.create({**request, "message": "third"}), CONTRACTS[5], RuntimeError)
    cancelled = store.cancel(job)
    require(cancelled["cancelOutcome"] == "blocked-cleanup" and cancelled["blockedAt"] == blocked["blockedAt"], CONTRACTS[1], "block cleanup lost history")
    cancelled_bytes = store.job_path(job).read_bytes()
    rejected(lambda: store.update(job, status="running"), CONTRACTS[1])
    rejected(lambda: store.update(job, request={"message": "replace original"}), CONTRACTS[0])
    require(store.job_path(job).read_bytes() == cancelled_bytes, CONTRACTS[1], "rejected mutation changed durable bytes")
    for status, error in (("interrupted", "connection stopped"), ("error", "adapter error")):
        item = store.create({**request, "message": status})
        result = store.finish(item["id"], result={"status": status}, error=error)
        require(result["status"] == ("failed" if status == "error" else status), CONTRACTS[1], "outcome flattened")
    require(all("metrics" in row and "timeline" in row for row in store.list()), CONTRACTS[4], "list omitted observability")
    persisted = json.loads(store.job_path(second["id"]).read_text(encoding="utf-8"))
    require("metrics" not in persisted and "timeline" not in persisted, CONTRACTS[4], "observer mutated old format")
    timed = store.update(second["id"], status="completed", pid=None,
                         createdAt="2026-09-01T12:00:00+00:00", startedAt="2026-09-01T12:00:00.250000+00:00",
                         finishedAt="2026-09-01T12:00:02.750000+00:00", result={"reply": "local receipt"})
    require((timed["metrics"]["queueLatencyMs"], timed["metrics"]["executionDurationMs"], timed["metrics"]["totalDurationMs"]) == (250, 2500, 2750), CONTRACTS[4], "historical durations differ")
    stopping = store.create({**request, "message": "cancellation wins"})["id"]
    store.update(stopping, status="cancelling", pid=None, cancelReason="operator")
    require(store.mark_started(stopping, pid=os.getpid())["status"] == "cancelling"
            and store.finish(stopping, result={"status": "completed", "reply": "late"})["status"] == "cancelled", CONTRACTS[1], "late worker won cancellation race")
    calls.append({"procedure": "blocked-late-event-cancel-and-outcomes", "jobIds": [job, second["id"]], "root": str(store.root)})

    concurrent = area("admission-concurrent", 3)
    def admit(index):
        try:
            return concurrent.create({**request, "message": f"request {index}"})["id"]
        except RuntimeError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(admit, range(8)))
    require(len({r for r in outcomes if r}) == 3 and outcomes.count(None) == 5, CONTRACTS[5], "concurrent admission oversubscribed")
    require(HarnessJobStore(concurrent.root, max_open_jobs=1).capacity()["maxOpenJobs"] == 1
            and HarnessJobStore(concurrent.root, max_open_jobs=8).capacity()["maxOpenJobs"] == 1, CONTRACTS[3], "higher instance expanded limit")
    corrupt = area("unreadable", 1)
    bad = corrupt.jobs_root / "harness-job-corrupt.json"
    bad.write_text("{bad", encoding="utf-8")
    require(corrupt.capacity()["unreadableJobs"] == 1 and corrupt.capacity()["availableSlots"] == 0, CONTRACTS[5], "unreadable evidence freed admission")
    rejected(lambda: corrupt.create(request), CONTRACTS[5], RuntimeError)
    damaged_policy = area("unreadable-policy")
    damaged_policy.capacity()
    damaged_policy._admission_policy_path().write_text("{bad", encoding="utf-8")
    rejected(damaged_policy.capacity, CONTRACTS[3], RuntimeError)
    rejected(lambda: damaged_policy.create(request), CONTRACTS[3], RuntimeError)
    for limit in (0, 101):
        rejected(lambda limit=limit: HarnessJobStore(root, max_open_jobs=limit), CONTRACTS[3])
    require(_process_alive(os.getpid()), CONTRACTS[7], "current process probe destructive")

    budget_store = area("budget")
    item = budget_store.create({**request, "budget": {"maxRuntimeSeconds": 30, "maxTokens": 1200, "maxCostUsd": 1.5}})
    ident = item["id"]
    budget_store.update(ident, status="running", pid=None, startedAt=(datetime.now(timezone.utc) - timedelta(seconds=7)).isoformat())
    remaining = worker._arm_runtime_budget(budget_store, ident, item["request"], max_runtime_seconds=30)
    require(0 <= remaining <= 23, CONTRACTS[2], "arming forgot startup delay")
    settled = budget_store.cancel(ident)
    require(settled["budget"]["status"] == "released" and settled["budget"]["maxTokens"] == 1200 and settled["budget"]["maxCostUsd"] == 1.5, CONTRACTS[2], "cancel lost budget dimensions")
    item = budget_store.create({**request, "budget": {"maxRuntimeSeconds": 1, "maxTokens": 2000}})
    ident = item["id"]
    budget_store.update(ident, status="running", pid=None, startedAt=datetime.now(timezone.utc).isoformat())
    worker._arm_runtime_budget(budget_store, ident, item["request"], max_runtime_seconds=1)
    watchdog = worker._start_runtime_budget_watchdog(budget_store, ident, 1, threading.Event())
    # Exhaustion begins at the declared deadline; durable writes and OS cleanup
    # have their own bounded settling time on a busy Windows host.
    watchdog.join(timeout=30)
    require(not watchdog.is_alive(), CONTRACTS[2], "real deadline did not settle")
    exhausted = budget_store.load(ident, reconcile=False)
    require(exhausted["status"] == "cancelled" and exhausted["budget"]["status"] == "exhausted" and exhausted["budgetOutcome"] == "enforced" and exhausted["budget"]["maxTokens"] == 2000, CONTRACTS[2], "watchdog erased exhaustion")
    require(worker._arm_runtime_budget(budget_store, ident, item["request"], max_runtime_seconds=1) is None
            and not worker._claim_runtime_budget_exhaustion(budget_store, ident, max_runtime_seconds=1, exhausted_at="later"), CONTRACTS[2], "late budget event rewrote terminal job")
    worker._settle_runtime_budget(budget_store, ident, status="released", outcome="late")
    require(budget_store.load(ident, reconcile=False)["budget"] == exhausted["budget"], CONTRACTS[2], "late settlement erased expiry")
    for value, seconds in (({}, 0), ({"maxRuntimeSeconds": 0}, 0), ({"maxRuntimeSeconds": 15}, 15), ({"max_runtime_seconds": "30"}, 30), ({"budget": {"maxRuntimeSeconds": 45}}, 45), ({"maxRuntimeSeconds": 15, "budget": {"maxRuntimeSeconds": 60}}, 60)):
        require(worker._hard_runtime_budget_seconds(value) == seconds, CONTRACTS[8], "budget priority changed")
    for raw in (-1, True, "forever", [1], int(threading.TIMEOUT_MAX) + 1):
        rejected(lambda raw=raw: worker._hard_runtime_budget_seconds({"maxRuntimeSeconds": raw}), CONTRACTS[8])
    require(worker._remaining_runtime_budget_seconds("malformed", 10) == 0, CONTRACTS[8], "malformed start extends deadline")
    exact_now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    require(worker._remaining_runtime_budget_seconds((exact_now - timedelta(seconds=7.5)).isoformat(), 10, now=exact_now) == 2.5, CONTRACTS[8], "startup allowance reset")
    item = budget_store.create({**request, "budget": {"maxRuntimeSeconds": 30, "maxTokens": 700, "maxCostUsd": 0.75}})
    ack = item["id"]
    budget_store.update(ack, status="running", pid=None, startedAt=datetime.now(timezone.utc).isoformat())
    worker._arm_runtime_budget(budget_store, ack, item["request"], max_runtime_seconds=30)
    worker._settle_runtime_budget(budget_store, ack, status="released", outcome="returned")
    settled_budget = budget_store.load(ack, reconcile=False)["budget"]
    require(settled_budget["maxTokens"] == 700 and settled_budget["maxCostUsd"] == 0.75 and settled_budget["status"] == "released", CONTRACTS[2], "normal settlement lost limits")
    budget_store.finish(ack, result={"status": "completed"})
    disarmed = threading.Event()
    disarmed.set()
    late_watchdog = worker._start_runtime_budget_watchdog(budget_store, ack, 1, disarmed, wait_seconds=0.01)
    late_watchdog.join(timeout=2)
    require(budget_store.load(ack, reconcile=False)["status"] == "completed", CONTRACTS[2], "disarmed watchdog rewrote completion")
    terminal_watchdog = worker._start_runtime_budget_watchdog(budget_store, ack, 1, threading.Event(), wait_seconds=0.01)
    terminal_watchdog.join(timeout=2)
    require(not terminal_watchdog.is_alive() and budget_store.load(ack, reconcile=False)["status"] == "completed", CONTRACTS[2], "terminal watchdog rewrote completion")
    active_disarm = budget_store.create({**request, "budget": {"maxRuntimeSeconds": 30, "maxTokens": 333}})
    budget_store.update(active_disarm["id"], status="running", pid=None, startedAt=datetime.now(timezone.utc).isoformat())
    worker._arm_runtime_budget(budget_store, active_disarm["id"], active_disarm["request"], max_runtime_seconds=30)
    disarmed = threading.Event()
    disarm_watchdog = worker._start_runtime_budget_watchdog(budget_store, active_disarm["id"], 1, disarmed)
    disarmed.set()
    disarm_watchdog.join(timeout=2)
    still_running = budget_store.load(active_disarm["id"], reconcile=False)
    require(not disarm_watchdog.is_alive() and still_running["status"] == "running" and still_running["budgetOutcome"] == "armed", CONTRACTS[2], "disarm did not preserve active run")
    item = budget_store.create(request)
    ack = item["id"]
    budget_store.update(ack, status="cancelling", pid=None, cancelReason="operator", budget={"status": "active", "maxRuntimeSeconds": 30, "maxTokens": 900})
    require(worker._arm_runtime_budget(budget_store, ack, {"budget": {"maxRuntimeSeconds": 30}}, max_runtime_seconds=30) is None, CONTRACTS[2], "budget arming overrode cancellation")
    require(budget_store.finish(ack)["budget"]["status"] == "released", CONTRACTS[2], "worker acknowledgment retained active budget")
    calls.append({"procedure": "arm-cancel-real-deadline-late-settlement", "jobId": ident, "root": str(budget_store.root)})

    execution_store = area("execution")
    capacity = HarnessExecutionCapacity(execution_store.root, max_running_jobs=1)
    older = execution_store.create({**request, "message": "oldest"})["id"]
    newer = execution_store.create({**request, "message": "newest"})["id"]
    for ident in (older, newer):
        execution_store.update(ident, status="running", pid=None, startedAt=datetime.now(timezone.utc).isoformat())
        require(worker._mark_waiting_for_execution_capacity(execution_store, ident, max_running_jobs=1), CONTRACTS[6], "live waiting transition failed")
        require(execution_store.load(ident, reconcile=False)["status"] == "running", CONTRACTS[6], "wait reopened launch admission")
        rejected(lambda ident=ident: execution_store.start(ident), CONTRACTS[6], RuntimeError)
    lease, snapshot = capacity.try_acquire(newer)
    require(lease is None and snapshot["reason"] == "fifo-predecessor", CONTRACTS[6], "newer waiter leapfrogged")
    lease, snapshot = capacity.try_acquire(older)
    require(lease is not None and lease.slot == 1, CONTRACTS[6], "first slot invalid")
    try:
        worker._claim_execution_capacity(execution_store, older, lease)
        next_lease, snapshot = capacity.try_acquire(newer)
        require(next_lease is None and snapshot["activeNewSlots"] == 1, CONTRACTS[6], "held OS lock lost capacity")
    finally:
        worker._record_execution_capacity_release(execution_store, older, lease)
        lease.release()
    released = json.loads(lease.path.read_text(encoding="utf-8"))
    require(released["slot"] == 1 and released["previousJobId"] == older and released["state"] == "available", CONTRACTS[6], "release receipt invented owner")
    durable_release = execution_store.load(older, reconcile=False)
    require(durable_release["executionCapacity"]["slot"] == 1 and durable_release["executionCapacity"]["state"] == "released"
            and durable_release["executionCapacity"]["ownerPid"] is None and durable_release["executionFinishedAt"], CONTRACTS[6], "durable release lost first slot truth")
    execution_store.finish(older, result={"status": "completed", "reply": "local execution receipt"})
    next_lease, _ = capacity.try_acquire(newer)
    require(next_lease is not None, CONTRACTS[6], "released slot unavailable")
    next_lease.release()
    execution_store.update(newer, status="cancelling", pid=None, cancelReason="operator")
    require(not worker._mark_waiting_for_execution_capacity(execution_store, newer, max_running_jobs=1), CONTRACTS[1], "waiting revived cancellation")
    execution_store.cancel(newer)
    require(HarnessExecutionCapacity(execution_store.root, max_running_jobs=4).effective_limit() == 1, CONTRACTS[3], "execution limit expanded")
    legacy_store = area("legacy-execution")
    legacy_capacity = HarnessExecutionCapacity(legacy_store.root, max_running_jobs=1)
    legacy = legacy_store.create(request)["id"]
    waiting = legacy_store.create({**request, "message": "wait behind legacy"})["id"]
    legacy_store.update(legacy, status="running", pid=None)
    worker._mark_waiting_for_execution_capacity(legacy_store, waiting, max_running_jobs=1)
    withheld, snapshot = legacy_capacity.try_acquire(waiting)
    require(withheld is None and snapshot["legacyOrUnknownActive"] == 1, CONTRACTS[6], "legacy execution unreserved")
    legacy_store.finish(legacy, result={"status": "completed"})
    malformed = legacy_store.jobs_root / "harness-job-malformed.json"
    malformed.write_text("{bad", encoding="utf-8")
    withheld, snapshot = legacy_capacity.try_acquire(waiting)
    require(withheld is None and snapshot["unreadableJobs"] == 1, CONTRACTS[6], "unreadable execution unreserved")
    rollout_store = area("late-legacy")
    rollout_capacity = HarnessExecutionCapacity(rollout_store.root, max_running_jobs=2)
    first = rollout_store.create(request)["id"]
    other = rollout_store.create({**request, "message": "other"})["id"]
    late = rollout_store.create({**request, "message": "legacy rollout"})["id"]
    for ident in (first, other):
        worker._mark_waiting_for_execution_capacity(rollout_store, ident, max_running_jobs=2)
    lease, _ = rollout_capacity.try_acquire(first)
    require(lease is not None, CONTRACTS[6], "initial rollout slot unavailable")
    try:
        worker._claim_execution_capacity(rollout_store, first, lease)
        rollout_store.update(late, status="running", pid=None)
        withheld, snapshot = rollout_capacity.try_acquire(other)
        require(withheld is None and snapshot["legacyOrUnknownActive"] == 1 and snapshot["activeNewSlots"] == 1, CONTRACTS[6], "late legacy oversubscribed remaining new slot")
    finally:
        lease.release()
    calls.append({"procedure": "fifo-os-slot-release", "jobIds": [older, newer], "root": str(execution_store.root)})

    lock_path = root / "harness-job-orphan.json"
    residue = lock_path.with_suffix(".json.lock")
    residue.write_text(f"{os.getpid()}\ncrashed-token\n", encoding="ascii")
    with _exclusive_job_lock(lock_path):
        require("crashed-token" not in residue.read_text(encoding="ascii"), CONTRACTS[7], "token orphan unrecovered")
    require(not residue.exists() and _job_guard_path(lock_path).exists(), CONTRACTS[7], "lock release left compatibility residue")
    require(len({_job_guard_path(root / f"harness-job-{i}.json") for i in range(512)}) <= 64, CONTRACTS[7], "guard files unbounded")
    # An actual owned child holds an OS slot and a durable mutation guard.
    # Killing it proves kernel cleanup and positive-death reconciliation without
    # replacing liveness probes or a provider. stdout is a bounded ready receipt.
    crash_store = area("process-crash")
    crash_job = crash_store.create(request)["id"]
    source = "\n".join([
        "import json,os,sys,time",
        "from pathlib import Path",
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})",
        "from grant_agent.harness_jobs import HarnessJobStore,_exclusive_job_lock",
        "from grant_agent.harness_execution_capacity import HarnessExecutionCapacity",
        "from grant_agent.harness_job_worker import _mark_waiting_for_execution_capacity,_claim_execution_capacity",
        "s=HarnessJobStore(Path(sys.argv[1])); job=sys.argv[2]",
        "s.mark_started(job,pid=os.getpid())",
        "_mark_waiting_for_execution_capacity(s,job,max_running_jobs=1)",
        "lease,snapshot=HarnessExecutionCapacity(s.root,max_running_jobs=1).try_acquire(job)",
        "assert lease is not None",
        "assert _claim_execution_capacity(s,job,lease)",
        "with _exclusive_job_lock(s.job_path(job)):",
        " print(json.dumps({'pid':os.getpid(),'slot':lease.slot}),flush=True)",
        " time.sleep(30)",
    ])
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    process = subprocess.Popen([sys.executable, "-c", source, str(crash_store.root), crash_job],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               **hidden_windows_subprocess_kwargs())
    try:
        # Keep readiness bounded even when the child fails before printing.
        ready = []
        reader = threading.Thread(target=lambda: ready.append(process.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout=8)
        require(not reader.is_alive() and ready and ready[0].strip(), CONTRACTS[7], "owned child did not hold guards")
        owner = json.loads(ready[0])
        require(owner["pid"] == process.pid and owner["slot"] == 1, CONTRACTS[7], "child readiness identity differs")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    require(not _process_alive(process.pid), CONTRACTS[7], "dead child observed alive")
    if os.name == "nt":
        # Release our own retained Popen process handle before asking Win32 for
        # this already-reaped child. No unrelated process is probed or signalled.
        process._handle.Close()
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        # Windows may briefly retain terminated process metadata after the last
        # owned handle closes. Observe that cleanup without altering the system.
        deadline = time.monotonic() + 3
        while True:
            handle = kernel32.OpenProcess(0x00100000, False, process.pid)
            error = ctypes.get_last_error()
            if handle:
                kernel32.CloseHandle(handle)
            if not handle or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        require(not handle and error == 87 and not _process_alive(process.pid), CONTRACTS[7], "owned dead PID did not yield positive Win32 invalid-parameter evidence")
        calls.append({"procedure": "owned-dead-win32-probe", "pid": process.pid, "openProcessError": error, "alive": False})
    legacy_lock = root / "harness-job-dead-legacy.json"
    legacy_residue = legacy_lock.with_suffix(".json.lock")
    legacy_residue.write_text(f"{process.pid}\n", encoding="ascii")
    with _exclusive_job_lock(legacy_lock):
        require(legacy_residue.read_text(encoding="ascii").splitlines()[0] == str(os.getpid()), CONTRACTS[7], "positive death did not recover legacy lock")
    recovered = crash_store.load(crash_job)
    require(recovered["status"] == "interrupted" and recovered["pid"] is None, CONTRACTS[7], "dead owner not reconciled")
    replacement = crash_store.create({**request, "message": "dispatch after crash"})["id"]
    worker._mark_waiting_for_execution_capacity(crash_store, replacement, max_running_jobs=1)
    recovered_lease, snapshot = HarnessExecutionCapacity(crash_store.root, max_running_jobs=1).try_acquire(replacement)
    require(recovered_lease is not None, CONTRACTS[6], "kernel retained dead child slot")
    recovered_lease.release()
    calls.append({"procedure": "owned-process-crash-and-kernel-recovery", "jobId": crash_job, "pid": process.pid, "exitCode": process.returncode, "root": str(crash_store.root)})
    # Recover a saved cancellation against the same positively dead owned PID.
    # The worker's real early-stop path returns before backend import/auth access.
    stops = area("stop")
    pending_stop = stops.create(request)["id"]
    stops.update(pending_stop, status="cancelling", pid=process.pid,
                 cancelRequestedAt=datetime.now(timezone.utc).isoformat(), cancelReason="operator")
    reconciled_stop = stops.load(pending_stop)
    require(reconciled_stop["status"] == "cancelled" and reconciled_stop["pid"] is None
            and reconciled_stop["cancelOutcome"] == "worker-no-longer-live", CONTRACTS[1], "dead cancellation became interruption")
    early_stop = stops.create(request)["id"]
    stops.update(early_stop, status="cancelling", pid=os.getpid(), cancelRequestedAt=datetime.now(timezone.utc).isoformat())
    require(worker.run_harness_job(stops.root, early_stop) == 0
            and stops.load(early_stop, reconcile=False)["status"] == "cancelling"
            and stops.load(early_stop, reconcile=False)["result"] is None,
            CONTRACTS[1], "actual worker crossed an existing cancellation claim")
    calls.append({"procedure": "early-cancellation-and-dead-owner-reconciliation", "cancelledJobId": pending_stop,
                  "earlyStoppedJobId": early_stop, "deadOwnedPid": process.pid, "backendImported": False})

    # Old receipts outside the dashboard's hundred-row visibility window still
    # participate in real admission/reconciliation. Seed imported history with
    # real create/finish receipts, then persist reviewed historical receipt data
    # through the production atomic writer. This models an existing workspace
    # without repeating quadratic history reconciliation during fixture setup.
    history = area("hist", 2)
    hidden = history.create({**request, "message": "hidden stale owner"})["id"]
    seed = history.create({**request, "message": "retained receipt seed"})
    history.finish(seed["id"], result={"status": "completed"})
    completed_seed = json.loads(history.job_path(seed["id"]).read_text(encoding="utf-8"))
    for index in range(99):
        ident = f"harness-job-history-{index:03d}"
        receipt = {**completed_seed, "id": ident, "request": {**request, "message": f"retained receipt {index}"}}
        _atomic_write_json(history.job_path(ident), receipt)
    history.update(hidden, status="running", pid=process.pid, startedAt=datetime.now(timezone.utc).isoformat())
    os.utime(history.job_path(hidden), (1.0, 1.0))
    require(hidden not in {r["id"] for r in history.list(limit=100)}, CONTRACTS[5], "hidden receipt remained in visible hundred-row window")
    strict_history = HarnessJobStore(history.root, max_open_jobs=1)
    newly_admitted = strict_history.create({**request, "message": "after hidden stale recovery"})
    require(newly_admitted["status"] == "queued" and strict_history.load(hidden, reconcile=False)["status"] == "interrupted",
            CONTRACTS[5], "admission ignored hidden dead receipt instead of reconciling it")
    future = area("future", 2)
    future_path = future.jobs_root / "harness-job-future.json"
    future_path.write_text(json.dumps({"schema": "neyvia.harness_job.v999", "id": future_path.stem, "status": "completed"}), encoding="utf-8")
    os.utime(future_path, (1.0, 1.0))
    seed = future.create({**request, "message": "supported receipt seed"})
    future.finish(seed["id"], result={"status": "completed"})
    completed_seed = json.loads(future.job_path(seed["id"]).read_text(encoding="utf-8"))
    for index in range(99):
        ident = f"harness-job-supported-{index:03d}"
        receipt = {**completed_seed, "id": ident, "request": {**request, "message": f"supported history {index}"}}
        _atomic_write_json(future.job_path(ident), receipt)
    future._prune()
    require(future_path.is_file() and future.capacity()["unreadableJobs"] == 1 and future.capacity()["openJobs"] == 1,
            CONTRACTS[5], "retention trusted unsupported terminal schema")
    calls.append({"procedure": "retention-hidden-owner-and-future-schema", "hiddenJobId": hidden, "historyCount": 100,
                  "historyFixture": "production atomic receipt import seeded by real create/finish",
                  "futureSchemaPreserved": True, "roots": [str(history.root), str(future.root)]})

    # A short caller-specific wait changes only waiting time, never lease safety.
    live_legacy = root / "harness-job-live-legacy.json"
    live_lease = live_legacy.with_suffix(".json.lock")
    live_lease.write_text(f"{os.getpid()}\n", encoding="ascii")
    os.utime(live_lease, (time.time() - 180, time.time() - 180))
    live_bytes = live_lease.read_bytes()
    def acquire_live_legacy():
        with _exclusive_job_lock(live_legacy, timeout_seconds=0.12):
            raise ValueError("live lease incorrectly stolen")
    rejected(acquire_live_legacy, CONTRACTS[7], RuntimeError)
    require(live_lease.read_bytes() == live_bytes, CONTRACTS[7], "live aged lease was changed")
    malformed_path = root / "harness-job-recent-malformed.json"
    malformed_lease = malformed_path.with_suffix(".json.lock")
    malformed_lease.write_text("not-a-pid\n", encoding="ascii")
    def acquire_malformed():
        with _exclusive_job_lock(malformed_path, timeout_seconds=0.12):
            raise ValueError("recent malformed lease incorrectly reclaimed")
    rejected(acquire_malformed, CONTRACTS[7], RuntimeError)
    require(malformed_lease.read_text(encoding="ascii") == "not-a-pid\n", CONTRACTS[7], "malformed fence was modified")
    contended = root / "harness-job-contention.json"
    entered, failures = threading.Event(), []
    def contender():
        try:
            with _exclusive_job_lock(contended, timeout_seconds=2):
                entered.set()
        except BaseException as exc:
            failures.append(str(exc))
    with _exclusive_job_lock(contended):
        compatibility = contended.with_suffix(".json.lock")
        os.utime(compatibility, (time.time() - 180, time.time() - 180))
        contender_thread = threading.Thread(target=contender, daemon=True)
        contender_thread.start()
        require(not entered.wait(0.12), CONTRACTS[7], "contender stole an aged compatibility lease while OS guard held")
    contender_thread.join(timeout=3)
    require(entered.is_set() and not contender_thread.is_alive() and not failures,
            CONTRACTS[7], "contender could not acquire after real guard release")
    calls.append({"procedure": "live-malformed-and-aged-contended-lease", "boundedWaitSeconds": 0.12,
                  "liveLeasePreserved": True, "malformedLeasePreserved": True, "contenderEnteredOnlyAfterRelease": True})
    # Cancel actual owned process trees, including a child process. These workers
    # run only the real store/budget functions; no runtime/provider is substituted.
    from .harness_jobs import _terminate_process_tree
    tree_store = area("trees")
    for reason in ("operator", "runtime_budget"):
        max_runtime = 1 if reason == "runtime_budget" else 60
        row = tree_store.create({**request, "budget": {"maxRuntimeSeconds": max_runtime, "maxTokens": 777}})
        tree_job = row["id"]
        tree_source = "\n".join([
            "import json,os,sys,time,subprocess",
            "from pathlib import Path",
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})",
            "from grant_agent.harness_jobs import HarnessJobStore",
            "from grant_agent.harness_job_worker import _arm_runtime_budget",
            "from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs",
            "s=HarnessJobStore(Path(sys.argv[1])); job=sys.argv[2]",
            "row=s.mark_started(job,pid=os.getpid())",
            "_arm_runtime_budget(s,job,row['request'],max_runtime_seconds=int(sys.argv[3]))",
            "child=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**hidden_windows_subprocess_kwargs())",
            "print(json.dumps({'pid':os.getpid(),'childPid':child.pid}),flush=True)",
            "time.sleep(30)",
        ])
        launch_options = hidden_windows_subprocess_kwargs(new_process_group=True)
        if os.name != "nt":
            launch_options["start_new_session"] = True
        tree_process = subprocess.Popen([sys.executable, "-c", tree_source, str(tree_store.root), tree_job, str(max_runtime)],
                                        cwd=tree_store.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, **launch_options)
        tree_owner = None
        try:
            ready = []
            reader = threading.Thread(target=lambda: ready.append(tree_process.stdout.readline()), daemon=True)
            reader.start()
            reader.join(timeout=8)
            require(not reader.is_alive() and ready and ready[0].strip(), CONTRACTS[2], "owned budget tree did not start")
            tree_owner = json.loads(ready[0])
            require(tree_owner["pid"] == tree_process.pid and _process_alive(tree_owner["childPid"]), CONTRACTS[2], "owned worker tree readiness differs")
            if reason == "operator":
                stopped_tree = tree_store.cancel(tree_job)
                require(stopped_tree["status"] == "cancelled" and stopped_tree["cancelOutcome"] == "process-tree-stopped"
                        and stopped_tree["budget"]["status"] == "released", CONTRACTS[2], "confirmed tree cancellation retained active budget")
            else:
                saved = tree_store.load(tree_job, reconcile=False)
                remaining = worker._remaining_runtime_budget_seconds(saved["startedAt"], max_runtime)
                watchdog = worker._start_runtime_budget_watchdog(tree_store, tree_job, max_runtime, threading.Event(), wait_seconds=remaining)
                watchdog.join(timeout=20)
                require(not watchdog.is_alive(), CONTRACTS[2], "real tree budget enforcement did not settle")
                stopped_tree = tree_store.load(tree_job, reconcile=False)
                require(stopped_tree["status"] == "cancelled" and stopped_tree["cancelReason"] == "runtime_budget"
                        and stopped_tree["budget"]["status"] == "exhausted" and stopped_tree["budgetOutcome"] == "enforced"
                        and stopped_tree["budget"]["maxTokens"] == 777,
                        CONTRACTS[2], "real tree termination erased exhaustion")
            tree_process.wait(timeout=5)
            require(not _process_alive(tree_process.pid) and not _process_alive(tree_owner["childPid"]), CONTRACTS[2], "owned descendant survived confirmed tree stop")
            calls.append({"procedure": "real-owned-process-tree-cancellation", "reason": reason, "jobId": tree_job,
                          "pid": tree_process.pid, "childPid": tree_owner["childPid"], "descendantsStopped": True,
                          "cancelOutcome": stopped_tree["cancelOutcome"], "budgetStatus": stopped_tree["budget"]["status"]})
        finally:
            if tree_process.poll() is None:
                _terminate_process_tree(tree_process.pid)
            tree_process.wait(timeout=5)
            tree_process.stdout.close()
            tree_process.stderr.close()
            if tree_owner is not None and _process_alive(tree_owner["childPid"]):
                _terminate_process_tree(tree_owner["childPid"])
    # Exercise the actual detached launcher under concurrent callers. The parent
    # holds the only real execution slot until the launched worker is confirmed
    # stopped, so no backend import, credential read or provider launch can occur.
    launches = area("launch")
    held_job = launches.create(request)["id"]
    launch_job = launches.create({**request, "budget": {"maxRuntimeSeconds": 60}})["id"]
    launch_capacity = HarnessExecutionCapacity(launches.root, max_running_jobs=1)
    worker._mark_waiting_for_execution_capacity(launches, held_job, max_running_jobs=1)
    held_lease, _ = launch_capacity.try_acquire(held_job)
    require(held_lease is not None, CONTRACTS[6], "parent could not gate detached launch")
    launched_pid = None
    try:
        worker._claim_execution_capacity(launches, held_job, held_lease)
        def attempt_start(_):
            try:
                return launches.start(launch_job)
            except RuntimeError as exc:
                require("not queued" in str(exc), CONTRACTS[1], "unexpected launch rejection")
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            started_rows = [r for r in pool.map(attempt_start, range(6)) if r is not None]
        require(len(started_rows) == 1 and started_rows[0]["status"] == "running", CONTRACTS[1], "concurrent start spawned duplicate workers")
        launched_pid = started_rows[0]["pid"]
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = launches.load(launch_job, reconcile=False)
            if current.get("waitingReason") == "execution-capacity":
                break
            time.sleep(0.05)
        require(current.get("waitingReason") == "execution-capacity" and current["status"] == "running", CONTRACTS[6], "native detached worker did not remain behind held capacity")
        stopped = launches.cancel(launch_job)
        require(stopped["status"] == "cancelled" and not _process_alive(launched_pid), CONTRACTS[1], "detached worker was not stopped before execution gate release")
        calls.append({"procedure": "native-detached-concurrent-start-and-cancel", "jobId": launch_job, "pid": launched_pid,
                      "startCalls": 6, "workersLaunched": 1, "providerExecutionPreventedByHeldOsSlot": True,
                      "cancelOutcome": stopped["cancelOutcome"]})
    finally:
        if launched_pid is None:
            # A concurrent caller can fail after another caller has launched.
            # Recover the actual owned identity before releasing its OS gate.
            current = launches.load(launch_job, reconcile=False)
            candidate = current.get("pid")
            from .harness_jobs import _process_command_line, _is_harness_worker_command
            if candidate and _process_alive(candidate):
                command = _process_command_line(candidate)
                require(_is_harness_worker_command(command, launch_job)
                        and str(launches.root).lower() in command.lower(),
                        CONTRACTS[1], "failed start cleanup cannot verify owned worker")
                launched_pid = candidate
        if launched_pid is not None and _process_alive(launched_pid):
            _terminate_process_tree(launched_pid)
        held_lease.release()
    # Public configuration -> ephemeral environment is an actual local action;
    # credential values here are invented sentinels, never read from a file.
    from .harness_registry import save_harness_profile, harness_gateway_environment, save_harness_instruction, read_harness_instruction
    from .runtimes.managed_cli import normalize_managed_cli_model
    profiles_root = root / "registry"
    profiles_root.mkdir()
    sentinel = "proof-only-noncredential-sentinel"
    configurations = [
        {"id": "native", "harnessId": "neyvia-agent", "providerId": "public-projection", "baseUrl": "https://gateway.invalid/v1", "model": "native-explicit", "credentialEnv": "PROOFS_B_NATIVE_REF", "compatibilityMode": "openai-compatible"},
        {"id": "anthropic", "harnessId": "claude-code", "baseUrl": "https://gateway.invalid/v1", "model": "claude-explicit", "smallModel": "claude-small", "credentialEnv": "PROOFS_B_CLAUDE_REF", "credentialKind": "api-key", "compatibilityMode": "anthropic-gateway"},
        {"id": "loopback", "harnessId": "claude-code", "baseUrl": proof_text("http://127.0.0.1:48479"), "model": "foreign-explicit", "credentialEnv": "PROOFS_B_PROXY_REF", "compatibilityMode": "cliproxy"},
        {"id": "grok", "harnessId": "grok-build", "baseUrl": proof_text("http://127.0.0.1:48479/v1"), "model": "research/custom-grok", "credentialEnv": "PROOFS_B_GROK_REF", "compatibilityMode": "openai-compatible"},
        {"id": "deepseek", "harnessId": "deepseek-harness", "credentialEnv": "PROOFS_B_DEEPSEEK_REF", "compatibilityMode": "api-key"},
        {"id": "rook", "harnessId": "rook", "model": "deepseek-explicit", "credentialEnv": "DEEPSEEK_API_KEY", "compatibilityMode": "api-key"},
    ]
    route_receipts = []
    for config in configurations:
        saved = save_harness_profile(profiles_root, {**config, "secret": sentinel, "apiKey": sentinel})
        env = harness_gateway_environment(profiles_root, config["harnessId"], saved["id"], {saved["credentialEnv"]: sentinel})
        raw_profiles = (profiles_root / ".agent_control/harness_profiles.json").read_text(encoding="utf-8")
        require(sentinel not in raw_profiles and "secret" not in saved and "apiKey" not in saved,
                "proofs-b.harness.public-profile", "runtime sentinel persisted")
        require(env[saved["credentialEnv"]] == sentinel, "proofs-b.harness.gateway", "source credential reference omitted")
        if config["id"] == "anthropic":
            require(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == config["smallModel"] and env["ANTHROPIC_API_KEY"] == sentinel,
                    "proofs-b.harness.gateway", "small Claude/auth surface omitted")
        if config["id"] == "rook":
            require(env["ROOK_DEFAULT_PROVIDER"] == "deepseek", "proofs-b.harness.gateway", "Rook exact provider selection omitted")
        route_receipts.append({"profileId": saved["id"], "harnessId": config["harnessId"], "environmentKeys": sorted(env), "credentialPersisted": False})
    remote = save_harness_profile(profiles_root, {"id": "remote-proxy", "harnessId": "claude-code", "baseUrl": "https://gateway.invalid/v1", "credentialEnv": "PROOFS_B_REMOTE_REF", "compatibilityMode": "cliproxy"})
    rejected(lambda: harness_gateway_environment(profiles_root, "claude-code", remote["id"], {"PROOFS_B_REMOTE_REF": sentinel}), "proofs-b.harness.gateway")
    missing_name = "PROOFS_B_MISSING_" + root.name.upper().replace("-", "_")
    missing = save_harness_profile(profiles_root, {"id": "missing-proxy", "harnessId": "claude-code", "baseUrl": proof_text("http://127.0.0.1:48479"), "credentialEnv": missing_name, "compatibilityMode": "cliproxy"})
    rejected(lambda: harness_gateway_environment(profiles_root, "claude-code", missing["id"], {}), "proofs-b.harness.gateway")
    first = save_harness_instruction(profiles_root, "CLAUDE.md", "# Initial local instructions")
    second = save_harness_instruction(profiles_root, "CLAUDE.md", "# Revised local instructions")
    require(Path(second["backupPath"]).read_text(encoding="utf-8") == "# Initial local instructions\n"
            and read_harness_instruction(profiles_root, "CLAUDE.md")["content"] == "# Revised local instructions\n",
            "proofs-b.harness.instruction", "instruction replacement did not preserve prior bytes")
    rejected(lambda: save_harness_instruction(profiles_root, "../CLAUDE.md", "escape"), "proofs-b.harness.instruction")
    require(normalize_managed_cli_model("grok-build", "research/custom-grok") == "research/custom-grok"
            and normalize_managed_cli_model("claude-code", "foreign-model", allow_custom=True) == "foreign-model",
            "proofs-b.harness.model-policy", "explicit permitted custom alias was rewritten")
    rejected(lambda: normalize_managed_cli_model("claude-code", "foreign-model"), "proofs-b.harness.model-policy")
    # Catalog construction may normally inspect CLI configuration. Constrain its
    # whole process environment to scratch before invoking its supplied-status
    # projection; no host environment or global configuration is changed.
    projection_root = root / "catalog-projection"
    projection_root.mkdir()
    managed = projection_root / "managed-runtime"
    (managed / "bin").mkdir(parents=True)
    (projection_root / "home").mkdir()
    child_env = dict(os.environ)
    for key in ("FLUXIO_RUNTIME_ROOT", "SYNTELOS_RUNTIME_ROOT", "SYNTHELOS_RUNTIME_ROOT"):
        child_env.pop(key, None)
    child_env.update(NEYVIA_MANAGED_RUNTIME_ROOT=str(managed.resolve()), USERPROFILE=str((projection_root / "home").resolve()))
    projection_code = (f"import json,sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); "
                       "from pathlib import Path; from grant_agent.proofs_b_harness import registry_projection; "
                       "print(json.dumps(registry_projection(Path(sys.argv[1]))))")
    projection = subprocess.run([sys.executable, "-c", projection_code, str(projection_root.resolve())], env=child_env,
                                capture_output=True, text=True, timeout=12, **hidden_windows_subprocess_kwargs())
    require(projection.returncode == 0, "proofs-b.harness.catalog", "isolated catalog projection failed: " + projection.stderr[-1000:])
    projected = json.loads(projection.stdout)
    calls.append({"procedure": "public-profile-gateway-instruction-catalog", "root": str(profiles_root.resolve()), "routes": route_receipts, "catalog": projected, "externalCalls": 0})
    calls.extend(_owned_access_failure_procedure(root))
    frontier = json.loads((Path(__file__).resolve().parents[2] / "config/proofs/proofs-b-harness.json").read_text(encoding="utf-8")).get("frontier", [])
    for contract in CONTRACTS:
        checks.append({"contract": contract, "ok": True})
    return {"ok": True, "contracts": list(CONTRACTS), "checks": checks, "calls": calls, "rejections": rejections,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "frontier": frontier}
