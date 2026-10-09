from __future__ import annotations

import calendar
import errno
import json
import math
import os
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .provider_state_io import (
    ProviderStateDirectory,
    open_provider_state_directory,
)


AUTH_QUEUE_SCHEMA = "neyvia.provider-auth-queue.v1"
PROVIDER_SECRET_STORE_SCHEMA = "fluxio.provider_secrets.v1"
PROVIDER_SECRET_IDS = frozenset(
    {
        "openai",
        "openai-codex",
        "anthropic",
        "openrouter",
        "minimax",
        "minimax-cn",
        "opencode-go",
        "kimi-code",
    }
)
PROVIDER_SECRET_STORE_FIELDS = frozenset({"schema", "secrets", "updatedAt"})
LEGACY_PROVIDER_SECRET_ENVELOPE_FIELDS = frozenset({"secrets", "updatedAt"})
TERMINAL_STATES = frozenset({"connected", "skipped", "cancelled"})
KNOWN_ITEM_STATES = frozenset(
    {"pending", "active", "blocked", "connected", "skipped", "cancelled"}
)
AUTH_QUEUE_LOCK_TIMEOUT_SECONDS = 30.0
AUTH_QUEUE_LOCK_POLL_SECONDS = 0.05
AUTH_FLOW_START_LEASE_SECONDS = 120.0
AUTH_FLOW_START_CLOCK_SKEW_SECONDS = 60.0
AUTH_FLOW_START_TIMESTAMP_TOLERANCE_SECONDS = 2.0


class _WorkspaceMutationLock:
    """Process-local half of the provider-state transaction lock."""

    __slots__ = ("_lock", "__weakref__")

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def __enter__(self) -> "_WorkspaceMutationLock":
        self._lock.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._lock.release()


_PROCESS_QUEUE_LOCKS_GUARD = threading.Lock()
_PROCESS_QUEUE_LOCKS: weakref.WeakValueDictionary[str, _WorkspaceMutationLock] = (
    weakref.WeakValueDictionary()
)


def _shared_workspace_mutation_lock(path: Path) -> _WorkspaceMutationLock:
    """Share one re-entrant lock across queue objects for the same workspace.

    BSD/macOS `flock` ownership is process-oriented, so two independently opened
    descriptors in one process cannot be relied on to serialize sibling queue
    objects. The advisory file lock remains the cross-process authority; this
    weak registry closes the intra-process gap without retaining dead workspaces.
    """

    key = os.path.normcase(str(Path(path).resolve()))
    with _PROCESS_QUEUE_LOCKS_GUARD:
        shared = _PROCESS_QUEUE_LOCKS.get(key)
        if shared is None:
            shared = _WorkspaceMutationLock()
            _PROCESS_QUEUE_LOCKS[key] = shared
        return shared


FLOW_FIELDS = frozenset(
    {
        "authUrl",
        "callbackUrl",
        "command",
        "expiresInSeconds",
        "manualRequired",
        "message",
        "method",
        "host",
        "region",
        "sessionId",
        "status",
        "userCode",
        "verificationUrl",
    }
)


PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "openai-codex": {
        "label": "OpenAI / Codex",
        "method": "oauth",
        "statusCommand": "get_openai_codex_oauth_status_command",
        "startCommand": "start_codex_device_auth_command",
        "credentialPolicy": "one-refresh-owner",
        "consumers": [
            {"id": "neyvia-own", "binding": "native-owner-or-loopback-broker"},
            {"id": "codex", "binding": "native-owner-or-loopback-broker"},
            {"id": "hermes", "binding": "loopback-openai-broker"},
            {"id": "openclaw", "binding": "loopback-openai-broker"},
            {"id": "opencode", "binding": "loopback-openai-broker"},
        ],
        "warning": "",
    },
    "openrouter": {
        "label": "OpenRouter",
        "method": "oauth-pkce",
        "statusCommand": "get_openrouter_oauth_status_command",
        "startCommand": "start_openrouter_oauth_command",
        "credentialPolicy": "provider-owned-api-key",
        "consumers": [
            {"id": "neyvia-own", "binding": "secret-broker"},
            {"id": "opencode", "binding": "secret-broker"},
            {"id": "hermes", "binding": "secret-broker"},
        ],
        "warning": "",
    },
    "minimax-portal": {
        "label": "MiniMax",
        "method": "oauth-device",
        "statusCommand": "get_minimax_openclaw_auth_status_command",
        "startCommand": "start_minimax_openclaw_auth_command",
        "credentialPolicy": "provider-scoped-oauth",
        "consumers": [
            {"id": "neyvia-own", "binding": "provider-adapter"},
            {"id": "openclaw", "binding": "native-provider"},
            {"id": "hermes", "binding": "provider-adapter"},
        ],
        "warning": "",
    },
    "anthropic": {
        "label": "Anthropic / Claude Code",
        "method": "official-interactive-or-enterprise",
        "statusCommand": "get_provider_secret_presence_command",
        "startCommand": "",
        "credentialPolicy": "official-only",
        "consumers": [
            {"id": "claude-code", "binding": "official-login-api-bedrock-vertex-or-gateway"},
            {"id": "neyvia-own", "binding": "anthropic-api-or-approved-gateway"},
        ],
        "warning": (
            "Claude Free, Pro, and Max credentials must not be relayed through "
            "Neyvia's third-party compatibility proxy."
        ),
    },
    "hermes-anthropic": {
        "label": "Hermes / Claude Max OAuth",
        "method": "hermes-native-cli-oauth",
        "statusCommand": "get_hermes_anthropic_auth_status_command",
        "startCommand": "start_hermes_anthropic_oauth_command",
        "credentialPolicy": "hermes-owned-oauth",
        "consumers": [
            {"id": "hermes", "binding": "hermes-native-anthropic-provider"},
        ],
        "warning": (
            "Hermes' documented route requires Claude Max plus purchased extra-usage "
            "credits; Claude Pro is unsupported and included Max allowance is not used."
        ),
    },
}


def parse_provider_secret_store_payload(payload: object) -> dict[str, str]:
    """Validate current and narrowly supported legacy credential-store shapes.

    Historical Neyvia builds accepted either a bare provider-to-secret mapping or
    a schema-less ``{"secrets": ...}`` envelope. Those shapes remain readable so
    an update does not strand existing credentials, but only known providers and
    string values are accepted. The next transactional write publishes the
    current schema; unsupported/future evidence fails closed instead of being
    silently discarded.
    """

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Provider credential state is malformed or uses an unsupported schema. "
            "Neyvia preserved it for recovery."
        )
    if "schema" in payload:
        if (
            payload.get("schema") != PROVIDER_SECRET_STORE_SCHEMA
            or not isinstance(payload.get("secrets"), dict)
            or set(payload) != PROVIDER_SECRET_STORE_FIELDS
            or not isinstance(payload.get("updatedAt"), str)
        ):
            raise RuntimeError(
                "Provider credential state is malformed, contains unsupported "
                "fields, or uses an unsupported schema. Neyvia preserved it for "
                "recovery."
            )
        secret_payload = payload["secrets"]
    elif "secrets" in payload:
        if (
            not isinstance(payload.get("secrets"), dict)
            or set(payload).difference(LEGACY_PROVIDER_SECRET_ENVELOPE_FIELDS)
        ):
            raise RuntimeError(
                "Legacy provider credential state contains unsupported fields. "
                "Neyvia preserved it for explicit recovery."
            )
        updated_at = payload.get("updatedAt")
        if "updatedAt" in payload and not isinstance(updated_at, str):
            raise RuntimeError(
                "Legacy provider credential state contains malformed metadata. "
                "Neyvia preserved it for explicit recovery."
            )
        secret_payload = payload["secrets"]
    else:
        if set(payload).difference(PROVIDER_SECRET_IDS):
            raise RuntimeError(
                "Legacy provider credential state contains unsupported provider "
                "fields. Neyvia preserved it for explicit recovery."
            )
        secret_payload = payload

    unknown_provider_ids = set(secret_payload).difference(PROVIDER_SECRET_IDS)
    if unknown_provider_ids:
        raise RuntimeError(
            "Provider credential state contains unsupported provider fields. "
            "Neyvia preserved it for explicit recovery."
        )
    loaded: dict[str, str] = {}
    for provider_id, raw_value in secret_payload.items():
        if not isinstance(raw_value, str):
            raise RuntimeError(
                "Provider credential state contains a non-string secret value. "
                "Neyvia refused to treat corrupt evidence as authenticated."
            )
        value = raw_value.strip()
        if value:
            loaded[provider_id] = value
    return loaded


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean_provider_ids(values: Iterable[object]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        provider_id = str(value or "").strip().lower()
        if not provider_id or provider_id in seen:
            continue
        if provider_id not in PROVIDER_SPECS:
            raise ValueError(f"Unsupported provider authentication flow: {provider_id}")
        seen.add(provider_id)
        output.append(provider_id)
    if not output:
        raise ValueError("Choose at least one provider to connect.")
    return output


def _atomic_json(
    path: Path,
    payload: dict[str, Any],
    *,
    state_directory: ProviderStateDirectory | None = None,
) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if state_directory is not None:
        state_directory.atomic_write_text(path.name, serialized)
        return
    with open_provider_state_directory(path, create=True) as directory:
        if directory is None:  # pragma: no cover - create=True is fail closed
            raise RuntimeError(
                "Provider authentication control directory was not created."
            )
        directory.atomic_write_text(path.name, serialized)



def _try_advisory_lock(descriptor: int) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
                exc, "winerror", None
            ) in {32, 33, 36}:
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise
    return True


def _release_advisory_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _exclusive_queue_lock(path: Path) -> Iterator[ProviderStateDirectory]:
    """Serialize state transitions while retaining the anchored directory."""

    descriptor = -1
    acquired = False
    with open_provider_state_directory(path, create=True) as directory:
        if directory is None:  # pragma: no cover - create=True is fail closed
            raise RuntimeError(
                "Provider authentication control directory was not created."
            )
        try:
            try:
                descriptor = directory.open_file(
                    path.name,
                    os.O_RDWR,
                    mode=0o600,
                    create_if_missing=True,
                )
            except OSError as exc:
                raise RuntimeError(
                    "Provider authentication state cannot obtain its crash-safe "
                    f"mutation guard: {type(exc).__name__}: {exc}"
                ) from exc
            fchmod = getattr(os, "fchmod", None)
            if callable(fchmod):
                try:
                    fchmod(descriptor, 0o600)
                except OSError:
                    pass
            if os.name == "nt" and os.fstat(descriptor).st_size < 1:
                os.write(descriptor, b"\0")
                try:
                    os.fsync(descriptor)
                except OSError:
                    pass
            deadline = time.monotonic() + AUTH_QUEUE_LOCK_TIMEOUT_SECONDS
            while not acquired:
                try:
                    acquired = _try_advisory_lock(descriptor)
                except OSError as exc:
                    raise RuntimeError(
                        "The workspace filesystem cannot provide crash-safe provider "
                        f"authentication locking: {type(exc).__name__}: {exc}"
                    ) from exc
                if acquired:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Timed out waiting for provider authentication state. Another "
                        "Neyvia process is still changing the connection queue."
                    )
                time.sleep(AUTH_QUEUE_LOCK_POLL_SECONDS)
            yield directory
        finally:
            if descriptor >= 0:
                if acquired:
                    try:
                        _release_advisory_lock(descriptor)
                    except OSError:
                        pass
                try:
                    os.close(descriptor)
                except OSError:
                    pass


class _ClaimedQueueState(dict[str, Any]):
    """Public queue view with non-enumerable startup-claim ownership."""

    __slots__ = ("_flow_start_provider_id", "_flow_start_claim_id")

    def __init__(
        self,
        payload: dict[str, Any],
        provider_id: str,
        claim_id: str,
    ) -> None:
        super().__init__(payload)
        self._flow_start_provider_id = provider_id
        self._flow_start_claim_id = claim_id


class ProviderAuthQueue:
    """Durable, secret-free coordinator for sequential provider sign-in."""

    def __init__(
        self,
        root: Path,
        *,
        presence: Callable[[list[str]], dict[str, bool]] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / ".agent_control" / "provider_auth_queue.json"
        self.guard_path = self.root / ".agent_control" / "provider_auth_queue.guard"
        self.secret_store_path = self.root / ".agent_control" / "provider_secrets.json"
        self._presence = presence or (lambda provider_ids: {item: False for item in provider_ids})
        self._lock = _shared_workspace_mutation_lock(self.guard_path)
        self._state_directory_local = threading.local()

    def _empty(self) -> dict[str, Any]:
        now = _utc_now()
        return {
            "schema": AUTH_QUEUE_SCHEMA,
            "queueId": uuid.uuid4().hex,
            "status": "idle",
            "createdAt": now,
            "updatedAt": now,
            "activeProviderId": "",
            "items": [],
        }

    def _active_state_directory(self) -> ProviderStateDirectory | None:
        return getattr(self._state_directory_local, "directory", None)

    def _state_exists(self) -> bool:
        directory = self._active_state_directory()
        if directory is not None:
            return directory.exists(self.path.name)
        with open_provider_state_directory(self.path, create=False) as opened:
            return bool(opened is not None and opened.exists(self.path.name))

    def _load(self) -> dict[str, Any]:
        directory = self._active_state_directory()
        if directory is not None:
            return self._load_from_directory(directory)
        with open_provider_state_directory(self.path, create=False) as opened:
            if opened is None:
                return self._empty()
            return self._load_from_directory(opened)

    def _load_from_directory(
        self,
        directory: ProviderStateDirectory,
    ) -> dict[str, Any]:
        try:
            raw = directory.read_text(self.path.name, missing_ok=True)
            if raw is None:
                return self._empty()
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Provider authentication queue state is unreadable. Neyvia preserved "
                "the evidence instead of replacing it with a clean screen."
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema") != AUTH_QUEUE_SCHEMA:
            raise RuntimeError(
                "Provider authentication queue state uses an unsupported schema. "
                "Neyvia preserved it for recovery instead of overwriting it."
            )
        items = payload.get("items")
        if not isinstance(items, list):
            raise RuntimeError(
                "Provider authentication queue items are malformed. Neyvia preserved "
                "the durable state for recovery."
            )
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise RuntimeError(
                    "Provider authentication queue item "
                    f"{index + 1} is malformed. Neyvia preserved the durable state "
                    "for recovery."
                )
            provider_id = item.get("providerId")
            state = item.get("state")
            if (
                not isinstance(provider_id, str)
                or provider_id != provider_id.strip().lower()
                or provider_id not in PROVIDER_SPECS
                or not isinstance(state, str)
                or state != state.strip().lower()
                or state not in KNOWN_ITEM_STATES
            ):
                raise RuntimeError(
                    "Provider authentication queue item "
                    f"{index + 1} has unsupported identity or lifecycle state, "
                    "including a noncanonical value. Neyvia preserved the durable "
                    "state for recovery."
                )
            if not isinstance(item.get("flow", {}), dict):
                raise RuntimeError(
                    "Provider authentication queue item "
                    f"{index + 1} has malformed flow evidence. Neyvia preserved "
                    "the durable state for recovery."
                )
            claim = item.get("flowStartClaim")
            if claim is not None:
                claim_is_valid = isinstance(claim, dict)
                claim_id = claim.get("claimId") if isinstance(claim, dict) else None
                claimed_at = claim.get("claimedAt") if isinstance(claim, dict) else None
                expires_raw = (
                    claim.get("expiresAtEpoch") if isinstance(claim, dict) else None
                )
                try:
                    parsed_claim_id = uuid.UUID(hex=claim_id) if isinstance(claim_id, str) else None
                except (ValueError, AttributeError):
                    parsed_claim_id = None
                try:
                    if not isinstance(claimed_at, str):
                        raise ValueError("missing claimedAt")
                    parsed_claimed_at = time.strptime(
                        claimed_at,
                        "%Y-%m-%dT%H:%M:%SZ",
                    )
                    if (
                        time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ",
                            parsed_claimed_at,
                        )
                        != claimed_at
                    ):
                        raise ValueError("noncanonical claimedAt")
                    claimed_at_epoch = float(calendar.timegm(parsed_claimed_at))
                except (OverflowError, TypeError, ValueError):
                    claim_is_valid = False
                    claimed_at_epoch = 0.0
                if (
                    parsed_claim_id is None
                    or parsed_claim_id.hex != claim_id
                    or parsed_claim_id.version != 4
                    or parsed_claim_id.variant != uuid.RFC_4122
                    or isinstance(expires_raw, bool)
                    or not isinstance(expires_raw, (int, float))
                ):
                    claim_is_valid = False
                    expires_at = 0.0
                else:
                    expires_at = float(expires_raw)
                now = time.time()
                max_future = (
                    now
                    + AUTH_FLOW_START_LEASE_SECONDS
                    + AUTH_FLOW_START_CLOCK_SKEW_SECONDS
                )
                observed_lease_seconds = expires_at - claimed_at_epoch
                if (
                    not math.isfinite(expires_at)
                    or not math.isfinite(claimed_at_epoch)
                    or expires_at <= 0
                    or claimed_at_epoch <= 0
                    or claimed_at_epoch > now + AUTH_FLOW_START_CLOCK_SKEW_SECONDS
                    or observed_lease_seconds < 0
                    or observed_lease_seconds
                    > (
                        AUTH_FLOW_START_LEASE_SECONDS
                        + AUTH_FLOW_START_TIMESTAMP_TOLERANCE_SECONDS
                    )
                    or expires_at > max_future
                ):
                    claim_is_valid = False
                if not claim_is_valid:
                    raise RuntimeError(
                        "Provider authentication queue item "
                        f"{index + 1} has malformed startup-claim evidence. Neyvia "
                        "preserved the durable state for recovery."
                    )
        payload.setdefault("queueId", uuid.uuid4().hex)
        from .proofs_d_runtime_auth import check_queue_payload
        check_queue_payload(payload)
        return payload

    def _save(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["schema"] = AUTH_QUEUE_SCHEMA
        payload["queueId"] = str(payload.get("queueId") or uuid.uuid4().hex)
        payload["updatedAt"] = _utc_now()
        _atomic_json(
            self.path,
            payload,
            state_directory=self._active_state_directory(),
        )
        from .proofs_d_runtime_auth import check_queue_save
        directory = self._active_state_directory()
        if directory is not None:
            check_queue_save(payload, directory, self.path.name)
        return payload

    @contextmanager
    def _mutation(self, action: str = "", arguments: dict[str, Any] | None = None) -> Iterator[None]:
        with self._lock:
            with _exclusive_queue_lock(self.guard_path) as directory:
                previous = self._active_state_directory()
                previous_observations = getattr(self._state_directory_local, "proof_presence", None)
                self._state_directory_local.directory = directory
                self._state_directory_local.proof_presence = {}
                try:
                    before_exists = directory.exists(self.path.name)
                    import copy
                    before = copy.deepcopy(self._load()) if action else None
                    yield
                    if action and directory.exists(self.path.name):
                        from .proofs_d_runtime_auth import check_queue_transition
                        after = self._load()
                        if action == "start" or before_exists:
                            check_queue_transition(action, arguments or {}, before, after,
                                                   self._state_directory_local.proof_presence)
                finally:
                    self._state_directory_local.proof_presence = previous_observations
                    if previous is None:
                        try:
                            del self._state_directory_local.directory
                        except AttributeError:
                            pass
                    else:
                        self._state_directory_local.directory = previous

    @staticmethod
    def _new_item(provider_id: str, *, connected: bool) -> dict[str, Any]:
        spec = PROVIDER_SPECS[provider_id]
        now = _utc_now()
        return {
            "providerId": provider_id,
            "operationId": uuid.uuid4().hex,
            "label": spec["label"],
            "method": spec["method"],
            "state": "connected" if connected else "pending",
            "createdAt": now,
            "startedAt": "",
            "completedAt": now if connected else "",
            "lastCheckedAt": now,
            "message": "Already connected." if connected else "Waiting in the connection queue.",
            "flow": {},
        }

    def _fresh_openrouter_secret_presence(self) -> bool | None:
        """Read cross-process-current OpenRouter evidence through the anchor."""

        if str(os.environ.get("OPENROUTER_API_KEY") or "").strip():
            return True

        def read_from(directory: ProviderStateDirectory) -> bool | None:
            try:
                raw = directory.read_text(
                    self.secret_store_path.name,
                    missing_ok=True,
                )
                if raw is None:
                    return None
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "Provider credential state is unreadable. Neyvia preserved the "
                    "authentication queue instead of guessing connection health."
                ) from exc
            loaded = parse_provider_secret_store_payload(payload)
            return bool(loaded.get("openrouter"))

        directory = self._active_state_directory()
        if directory is not None:
            return read_from(directory)
        with open_provider_state_directory(
            self.secret_store_path,
            create=False,
        ) as opened:
            if opened is None:
                return None
            return read_from(opened)

    def _presence_for(self, provider_ids: list[str]) -> dict[str, bool]:
        observed = self._presence(provider_ids)
        if not isinstance(observed, dict):
            raise RuntimeError(
                "Provider presence inspection returned malformed evidence. Neyvia "
                "preserved the authentication queue instead of guessing."
            )
        result = {
            provider_id: bool(observed.get(provider_id, False))
            for provider_id in provider_ids
        }
        if "openrouter" in result:
            # The web backend callback can close over a process-local dictionary.
            # Once present, the durable secret store is the cross-process truth.
            fresh_openrouter = self._fresh_openrouter_secret_presence()
            if fresh_openrouter is not None:
                result["openrouter"] = fresh_openrouter
        observed_for_proof = getattr(self._state_directory_local, "proof_presence", None)
        if observed_for_proof is not None:
            observed_for_proof.update(result)
        return result

    @staticmethod
    def _activate_next(payload: dict[str, Any]) -> None:
        active = next(
            (item for item in payload["items"] if item.get("state") == "active"),
            None,
        )
        if active:
            payload["status"] = "running"
            payload["activeProviderId"] = active["providerId"]
            return
        blocked = next(
            (item for item in payload["items"] if item.get("state") == "blocked"),
            None,
        )
        if blocked:
            payload["status"] = "blocked"
            payload["activeProviderId"] = blocked["providerId"]
            return
        pending = next(
            (item for item in payload["items"] if item.get("state") == "pending"),
            None,
        )
        if pending:
            pending["state"] = "active"
            pending["startedAt"] = pending.get("startedAt") or _utc_now()
            pending["message"] = "Ready to connect."
            payload["status"] = "running"
            payload["activeProviderId"] = pending["providerId"]
            return
        payload["activeProviderId"] = ""
        if payload["items"] and all(
            item.get("state") in TERMINAL_STATES for item in payload["items"]
        ):
            payload["status"] = (
                "completed"
                if any(item.get("state") == "connected" for item in payload["items"])
                else "cancelled"
            )
        else:
            payload["status"] = "idle"

    @staticmethod
    def _has_unfinished_work(payload: dict[str, Any]) -> bool:
        return any(
            item.get("state") in {"active", "pending", "blocked"}
            for item in payload.get("items", [])
            if isinstance(item, dict)
        )

    @staticmethod
    def _active_item(payload: dict[str, Any]) -> dict[str, Any] | None:
        active_id = str(payload.get("activeProviderId") or "")
        return next(
            (
                item
                for item in payload.get("items", [])
                if isinstance(item, dict)
                and str(item.get("providerId") or "") == active_id
                and item.get("state") in {"active", "blocked"}
            ),
            None,
        )

    @classmethod
    def _claim_active_flow_start(
        cls,
        payload: dict[str, Any],
    ) -> tuple[tuple[str, str] | None, bool]:
        """Reserve one empty provider-flow startup across backend processes.

        The opaque claim ID is retained only on the owning in-process queue view.
        It is not enumerated into JSON/UI state, but lets the backend release the
        exact claim if synchronous provider startup raises.
        """

        item = cls._active_item(payload)
        if item is None:
            return None, False
        flow = item.get("flow")
        if isinstance(flow, dict) and flow:
            item.pop("flowStartClaim", None)
            return None, False
        claim = item.get("flowStartClaim")
        now = time.time()
        if isinstance(claim, dict):
            try:
                expires_at = float(claim.get("expiresAtEpoch") or 0)
            except (TypeError, ValueError):
                expires_at = 0
            if expires_at > now:
                return None, True
        claim_id = uuid.uuid4().hex
        item["flowStartClaim"] = {
            "claimId": claim_id,
            "claimedAt": _utc_now(),
            "expiresAtEpoch": now + AUTH_FLOW_START_LEASE_SECONDS,
        }
        return (str(item["providerId"]), claim_id), False

    def release_flow_start_claim(
        self,
        provider_id: str,
        claim_id: str,
    ) -> None:
        """Release only the exact unfulfilled startup claim.

        Claim identity prevents an old failing starter from clearing a newer
        backend's replacement claim after bounded crash recovery.
        """

        clean_provider_id = str(provider_id or "").strip().lower()
        clean_claim_id = str(claim_id or "").strip()
        if not clean_provider_id or not clean_claim_id:
            return
        with self._mutation("release_claim", {"provider_id": clean_provider_id, "claim_id": clean_claim_id}):
            payload = self._load()
            item = next(
                (
                    row
                    for row in payload["items"]
                    if row.get("providerId") == clean_provider_id
                    and row.get("state") in {"active", "blocked"}
                ),
                None,
            )
            if not item or item.get("flow"):
                return
            claim = item.get("flowStartClaim")
            if not isinstance(claim, dict) or claim.get("claimId") != clean_claim_id:
                return
            item.pop("flowStartClaim", None)
            item["message"] = (
                "Provider connection startup did not complete. Retry is available."
            )
            self._save(payload)

    def start(self, provider_ids: Iterable[object]) -> dict[str, Any]:
        clean_ids = _clean_provider_ids(provider_ids)
        with self._mutation("start", {"provider_ids": clean_ids}):
            existing = self._load()
            if self._state_exists() and self._has_unfinished_work(existing):
                raise RuntimeError(
                    "A provider authentication queue is already in progress. Finish "
                    "or cancel it before starting another connection sequence."
                )
            presence = self._presence_for(clean_ids)
            payload = self._empty()
            payload["items"] = [
                self._new_item(provider_id, connected=presence[provider_id])
                for provider_id in clean_ids
            ]
            self._activate_next(payload)
            claim_owner, waiting = self._claim_active_flow_start(payload)
            return self._present(
                self._save(payload),
                flow_start_waiting=waiting,
                claim_owner=claim_owner,
            )

    def status(self, *, refresh_presence: bool = True) -> dict[str, Any]:
        with self._mutation("status", {"refresh_presence": refresh_presence}):
            payload = self._load()
            changed = False
            if refresh_presence and payload["items"]:
                provider_ids = [
                    str(item.get("providerId") or "")
                    for item in payload["items"]
                    if item.get("state") in {"active", "pending", "blocked", "connected"}
                ]
                presence = self._presence_for(provider_ids)
                now = _utc_now()
                for item in payload["items"]:
                    provider_id = str(item.get("providerId") or "")
                    if provider_id not in presence:
                        continue
                    item["lastCheckedAt"] = now
                    changed = True
                    if presence[provider_id]:
                        if item.get("state") != "connected":
                            item["state"] = "connected"
                            item["completedAt"] = now
                            item["message"] = "Connection evidence detected."
                            item["flow"] = {}
                            item.pop("blockedAt", None)
                            item.pop("blockerKind", None)
                            item.pop("flowStartClaim", None)
                        continue
                    if item.get("state") == "connected":
                        item["state"] = "blocked"
                        item["completedAt"] = ""
                        item["blockedAt"] = now
                        item["blockerKind"] = "provider-auth-evidence-missing"
                        item["message"] = (
                            "Neyvia can no longer observe the credential or provider "
                            "profile evidence that supported this connection. Reconnect "
                            "or repair provider setup before relying on this route."
                        )
                        item["flow"] = {}
                        item.pop("flowStartClaim", None)
            self._activate_next(payload)
            claim_owner, waiting = self._claim_active_flow_start(payload)
            if claim_owner or changed:
                self._save(payload)
            return self._present(
                payload,
                flow_start_waiting=waiting,
                claim_owner=claim_owner,
            )

    def record_flow(
        self,
        provider_id: str,
        flow: dict[str, Any],
        *,
        startup_claim_id: str = "",
    ) -> dict[str, Any]:
        clean_id = str(provider_id or "").strip().lower()
        clean_claim_id = str(startup_claim_id or "").strip()
        with self._mutation("record_flow", {"provider_id": clean_id, "flow": flow, "startup_claim_id": clean_claim_id}):
            payload = self._load()
            item = next(
                (row for row in payload["items"] if row.get("providerId") == clean_id),
                None,
            )
            if item and item.get("state") == "connected":
                return self._present(payload)
            if not item or item.get("state") not in {"active", "blocked"}:
                raise ValueError(f"{clean_id or 'Provider'} is not the active connection.")
            existing_flow = item.get("flow") if isinstance(item.get("flow"), dict) else {}
            durable_claim = item.get("flowStartClaim")
            if isinstance(durable_claim, dict):
                if clean_claim_id != str(durable_claim.get("claimId") or ""):
                    raise RuntimeError(
                        "Provider authentication startup ownership changed before "
                        "the flow was recorded. Neyvia refused to publish stale "
                        "external-flow evidence."
                    )
            elif clean_claim_id or not existing_flow:
                raise RuntimeError(
                    "Provider authentication startup ownership is no longer current. "
                    "Neyvia refused to publish stale external-flow evidence."
                )
            safe_flow = {
                key: value
                for key, value in flow.items()
                if key in FLOW_FIELDS and value not in (None, "")
            }
            existing_session = str(existing_flow.get("sessionId") or "")
            incoming_session = str(safe_flow.get("sessionId") or "")
            if existing_session and not incoming_session:
                # Session ownership is process-local for some provider helpers. A
                # different backend can observe only a sessionless "not found" status;
                # that observation must never erase the owning backend's durable flow.
                return self._present(payload)
            if existing_session and incoming_session and existing_session != incoming_session:
                raise RuntimeError(
                    "A different provider authentication session is already recorded "
                    "for this operation. Neyvia refused to overwrite it."
                )
            if item.get("state") == "blocked":
                item["state"] = "active"
                item["startedAt"] = _utc_now()
                item.pop("blockedAt", None)
                item.pop("blockerKind", None)
                payload["status"] = "running"
            item["flow"] = safe_flow
            item.pop("flowStartClaim", None)
            item["message"] = str(
                safe_flow.get("message") or "Connection request started."
            )
            return self._present(self._save(payload))

    def mark_connected(
        self,
        provider_id: str,
        message: str = "",
        *,
        startup_claim_id: str = "",
    ) -> dict[str, Any]:
        clean_id = str(provider_id or "").strip().lower()
        clean_claim_id = str(startup_claim_id or "").strip()
        with self._mutation("mark_connected", {"provider_id": clean_id, "startup_claim_id": clean_claim_id}):
            payload = self._load()
            item = next(
                (row for row in payload["items"] if row.get("providerId") == clean_id),
                None,
            )
            if not item or item.get("state") not in {"active", "blocked", "connected"}:
                return self._present(payload)
            if item.get("state") == "connected":
                return self._present(payload)
            if clean_claim_id:
                durable_claim = item.get("flowStartClaim")
                if (
                    not isinstance(durable_claim, dict)
                    or clean_claim_id != str(durable_claim.get("claimId") or "")
                ):
                    raise RuntimeError(
                        "Provider authentication startup ownership changed before "
                        "connection completion. Neyvia refused to publish a stale "
                        "starter result."
                    )
            item["state"] = "connected"
            now = _utc_now()
            item["completedAt"] = now
            item["lastCheckedAt"] = now
            item["message"] = message or "Connection evidence detected."
            item["flow"] = {}
            item.pop("blockedAt", None)
            item.pop("blockerKind", None)
            item.pop("flowStartClaim", None)
            self._activate_next(payload)
            # Completion callbacks frequently call mark_connected only for its side
            # effect and discard the return value. Do not lease the next provider to
            # a caller that may never launch it. The next status/advance poll claims
            # startup durably before receiving an executable nextAction.
            return self._present(self._save(payload), suppress_next_action=True)

    def skip(self, provider_id: str) -> dict[str, Any]:
        clean_id = str(provider_id or "").strip().lower()
        with self._mutation("skip", {"provider_id": clean_id}):
            payload = self._load()
            item = next(
                (
                    row
                    for row in payload["items"]
                    if row.get("providerId") == clean_id
                    and row.get("state") in {"active", "pending", "blocked"}
                ),
                None,
            )
            if not item:
                raise ValueError(f"{clean_id or 'Provider'} cannot be skipped.")
            item["state"] = "skipped"
            item["completedAt"] = _utc_now()
            item["message"] = "Skipped by the operator."
            item["flow"] = {}
            item.pop("blockedAt", None)
            item.pop("blockerKind", None)
            item.pop("flowStartClaim", None)
            self._activate_next(payload)
            claim_owner, waiting = self._claim_active_flow_start(payload)
            return self._present(
                self._save(payload),
                flow_start_waiting=waiting,
                claim_owner=claim_owner,
            )

    def cancel(self) -> dict[str, Any]:
        with self._mutation("cancel"):
            payload = self._load()
            now = _utc_now()
            for item in payload["items"]:
                if item.get("state") in {"active", "pending", "blocked"}:
                    item["state"] = "cancelled"
                    item["completedAt"] = now
                    item["message"] = "Connection queue cancelled."
                    item["flow"] = {}
                    item.pop("blockedAt", None)
                    item.pop("blockerKind", None)
                    item.pop("flowStartClaim", None)
            payload["status"] = "cancelled"
            payload["activeProviderId"] = ""
            return self._present(self._save(payload))

    @staticmethod
    def _present(
        payload: dict[str, Any],
        *,
        flow_start_waiting: bool = False,
        suppress_next_action: bool = False,
        claim_owner: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        active_id = str(payload.get("activeProviderId") or "")
        active_spec = PROVIDER_SPECS.get(active_id)
        active_item = next(
            (
                item
                for item in payload.get("items", [])
                if item.get("providerId") == active_id
            ),
            None,
        )
        providers = []
        for item in payload.get("items", []):
            spec = PROVIDER_SPECS.get(str(item.get("providerId") or ""), {})
            public_item = dict(item)
            public_item.pop("flowStartClaim", None)
            providers.append(
                {
                    **public_item,
                    "credentialPolicy": spec.get("credentialPolicy", ""),
                    "consumers": spec.get("consumers", []),
                    "warning": spec.get("warning", ""),
                }
            )
        next_action = None
        if (
            active_spec
            and active_item
            and not flow_start_waiting
            and not suppress_next_action
        ):
            next_action = {
                "providerId": active_id,
                "label": active_spec["label"],
                "method": active_spec["method"],
                "startCommand": active_spec["startCommand"],
                "statusCommand": active_spec["statusCommand"],
                "manualRequired": not bool(active_spec["startCommand"]),
                "flow": active_item.get("flow") or {},
                "reason": active_item.get("blockerKind") or "",
            }
        public_payload = dict(payload)
        presented: dict[str, Any] = {
            **public_payload,
            "items": providers,
            "nextAction": next_action,
            "providerFlowStarting": bool(flow_start_waiting),
            "secretMaterialStored": False,
            "automaticAdvance": True,
        }
        if claim_owner and next_action is not None:
            provider_id, claim_id = claim_owner
            presented = _ClaimedQueueState(presented, provider_id, claim_id)
        from .proofs_d_runtime_auth import check_queue_present
        check_queue_present(payload, presented, flow_start_waiting=flow_start_waiting,
                            suppress_next_action=suppress_next_action, claim_owner=claim_owner)
        return presented
