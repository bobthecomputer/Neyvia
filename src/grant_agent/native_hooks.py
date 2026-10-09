"""Bounded, receipt-producing lifecycle hooks for Neyvia Native."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .subprocess_utils import hidden_windows_subprocess_kwargs


HOOK_SCHEMA = "neyvia.native-hook/v1"
HOOK_RECEIPT_SCHEMA = "neyvia.native-hook-receipt/v1"
VALID_EVENTS = {
    "run.before",
    "run.after",
    "run.failed",
    "plan.compiled",
    "phase.before",
    "phase.after",
    "tool.before",
    "tool.after",
    "tool.failed",
    "spawn.before",
    "spawn.after",
    "spawn.failed",
    "proof.before",
    "proof.after",
    "compact.before",
    "compact.after",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_id(value: object) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip(".-")
    if not normalized:
        raise ValueError("hook id is required")
    return normalized[:96]


@dataclass(frozen=True)
class NativeHook:
    hook_id: str
    event: str
    argv: tuple[str, ...]
    timeout_seconds: int
    blocking: bool
    allow_mutations: bool
    environment: dict[str, str]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "NativeHook":
        event = str(value.get("event") or "").strip().lower()
        if event not in VALID_EVENTS:
            raise ValueError(f"unsupported Native hook event: {event or 'missing'}")
        argv = value.get("argv") or ()
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise ValueError("hook argv must be a non-empty string array")
        environment = {
            str(key): str(item)
            for key, item in (value.get("environment") or {}).items()
            if re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", str(key))
        }
        return cls(
            hook_id=_safe_id(value.get("id")),
            event=event,
            argv=tuple(argv),
            timeout_seconds=max(1, min(120, int(value.get("timeoutSeconds") or 20))),
            blocking=bool(value.get("blocking", False)),
            allow_mutations=bool(value.get("allowMutations", False)),
            environment=environment,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema": HOOK_SCHEMA,
            "id": self.hook_id,
            "event": self.event,
            "argv": list(self.argv),
            "timeoutSeconds": self.timeout_seconds,
            "blocking": self.blocking,
            "allowMutations": self.allow_mutations,
            "environmentKeys": sorted(self.environment),
        }


class NativeHookRunner:
    def __init__(self, root: Path, *, mutations_allowed: bool = False) -> None:
        self.root = root.resolve()
        self.mutations_allowed = mutations_allowed
        self.config_paths = [
            self.root / ".neyvia" / "hooks.json",
            self.root / "config" / "neyvia_native_hooks.json",
        ]
        self.receipt_root = self.root / ".agent_control" / "neyvia_agent" / "hook_receipts"
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.hooks = self._load()

    def _load(self) -> list[NativeHook]:
        rows: list[dict[str, Any]] = []
        for path in self.config_paths:
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid Native hook config {path}: {exc}") from exc
            rows.extend(item for item in payload.get("hooks", ()) if isinstance(item, dict))
        return [NativeHook.from_mapping(row) for row in rows]

    def for_event(self, event: str) -> list[NativeHook]:
        normalized = str(event or "").strip().lower()
        if normalized not in VALID_EVENTS:
            raise ValueError(f"unsupported Native hook event: {normalized}")
        return [hook for hook in self.hooks if hook.event == normalized]

    def run(self, event: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        receipts: list[dict[str, Any]] = []
        blocked = False
        for hook in self.for_event(event):
            if hook.allow_mutations and not self.mutations_allowed:
                receipt = {
                    "schema": HOOK_RECEIPT_SCHEMA,
                    "hook": hook.public_dict(),
                    "event": event,
                    "status": "approval_required",
                    "passed": False,
                    "blocking": hook.blocking,
                    "reason": "Hook requests mutation authority that the parent run does not hold.",
                    "startedAt": _utc_now(),
                    "finishedAt": _utc_now(),
                }
            else:
                env = {
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": os.environ.get("HOME", ""),
                    "USERPROFILE": os.environ.get("USERPROFILE", ""),
                    "NEYVIA_HOOK_EVENT": event,
                    "NEYVIA_HOOK_CONTEXT": json.dumps(context or {}, ensure_ascii=False),
                    **hook.environment,
                }
                started = _utc_now()
                try:
                    completed = subprocess.run(
                        list(hook.argv),
                        cwd=str(self.root),
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=hook.timeout_seconds,
                        check=False,
                        shell=False,
                        **hidden_windows_subprocess_kwargs(),
                    )
                    status = "completed" if completed.returncode == 0 else "failed"
                    receipt = {
                        "schema": HOOK_RECEIPT_SCHEMA,
                        "hook": hook.public_dict(),
                        "event": event,
                        "status": status,
                        "passed": completed.returncode == 0,
                        "blocking": hook.blocking,
                        "returnCode": completed.returncode,
                        "timedOut": False,
                        "stdoutTail": completed.stdout[-6000:],
                        "stderrTail": completed.stderr[-6000:],
                        "startedAt": started,
                        "finishedAt": _utc_now(),
                    }
                except subprocess.TimeoutExpired as exc:
                    receipt = {
                        "schema": HOOK_RECEIPT_SCHEMA,
                        "hook": hook.public_dict(),
                        "event": event,
                        "status": "timed_out",
                        "passed": False,
                        "blocking": hook.blocking,
                        "returnCode": None,
                        "timedOut": True,
                        "stdoutTail": str(exc.stdout or "")[-6000:],
                        "stderrTail": str(exc.stderr or "")[-6000:],
                        "startedAt": started,
                        "finishedAt": _utc_now(),
                    }
                except OSError as exc:
                    receipt = {
                        "schema": HOOK_RECEIPT_SCHEMA,
                        "hook": hook.public_dict(),
                        "event": event,
                        "status": "failed_to_start",
                        "passed": False,
                        "blocking": hook.blocking,
                        "returnCode": None,
                        "timedOut": False,
                        "stdoutTail": "",
                        "stderrTail": str(exc),
                        "startedAt": started,
                        "finishedAt": _utc_now(),
                    }
            receipt["receiptHash"] = _hash(receipt)
            path = self.receipt_root / f"{event.replace('.', '-')}-{hook.hook_id}-{uuid.uuid4().hex[:10]}.json"
            path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            from .proofs_d_native import check_hook
            check_hook(hook, self.mutations_allowed, receipt, path)
            receipt["receiptPath"] = str(path)
            receipts.append(receipt)
            if hook.blocking and not receipt["passed"]:
                blocked = True
                break
        return {
            "schema": "neyvia.native-hook-run/v1",
            "event": event,
            "hooksConfigured": len(self.for_event(event)),
            "receipts": receipts,
            "receiptPaths": [row["receiptPath"] for row in receipts],
            "blocked": blocked,
            "passed": not blocked,
        }

    def catalog(self) -> dict[str, Any]:
        return {
            "schema": "neyvia.native-hook-catalog/v1",
            "hooks": [hook.public_dict() for hook in self.hooks],
            "count": len(self.hooks),
            "truthBoundary": "Hooks run only as argv arrays with bounded timeouts and receipt output; shell strings are not accepted.",
        }
