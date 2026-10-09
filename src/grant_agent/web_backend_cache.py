from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ControlRoomCacheDependencies:
    """Current facade policy and callbacks, supplied explicitly at each operation."""

    bootstrap_summary_cache_ttl_seconds: float
    control_room_detail_duration_budget_ms: float
    control_room_detail_payload_budget_bytes: int
    control_room_summary_duration_budget_ms: float
    control_room_summary_payload_budget_bytes: int
    control_room_store: type
    full_summary_cache_ttl_seconds: float
    full_summary_stale_while_revalidate_seconds: float
    mission_detail_cache_max_items: int
    mission_detail_prewarm_delay_seconds: float
    mission_detail_prewarm_enabled: bool
    mission_detail_prewarm_wait_seconds: float
    mission_detail_stale_while_revalidate_seconds: float
    persisted_bootstrap_summary_cache_version: str
    persisted_full_summary_cache_version: str
    persisted_runtime_proof_status_cache_version: str
    runtime_proof_status_cache_ttl_seconds: float
    runtime_proof_status_stale_while_revalidate_seconds: float
    utc_now: Callable[..., Any]
    build_real_agent_proof_status: Callable[..., Any]


class ControlRoomCacheMixin:
    """Owns cache behavior; the backend supplies state and external callbacks."""

    def _control_room_freshness_signature(self, root: Path) -> tuple[tuple[str, int, int], ...]:
        deps = self._cache_dependencies()
        store = deps.control_room_store(root)
        rows: list[tuple[str, int, int]] = []
        watched_paths = [
            store.missions_path,
            store.events_path,
            store.workspaces_path,
            store.workspace_actions_path,
            root / ".agent_control" / "mission_watchdog.json",
            root / ".agent_control" / "mission_watchdog_problems.json",
            root / ".agent_control" / "mission_watchdog_supervisor.json",
            root / ".agent_control" / "connected_apps_state.json",
            root / ".agent_control" / "learned_skills.json",
            root / ".agent_control" / "skill_evolution_receipts.json",
            root / ".agent_control" / "skill_feedback.json",
            root / ".agent_control" / "skill_repair_receipts.json",
            root / ".agent_control" / "skill_usage.json",
            root / ".agent_control" / "user_installed_skills.json",
            root / "config" / "connected_apps.json",
            root / "config" / "skills.json",
            root / "src" / "grant_agent" / "app_capability_standard.py",
            root / "src" / "grant_agent" / "mission_control.py",
        ]
        project_skills_root = root / ".codex" / "skills"
        personal_skills_root = Path.home() / ".codex" / "skills"
        watched_paths.extend(
            [
                project_skills_root,
                personal_skills_root,
                Path.home()
                / ".codex"
                / ".neyvia"
                / "skill_evolution_receipts.json",
            ]
        )
        for skills_root in (project_skills_root, personal_skills_root):
            if not skills_root.exists():
                continue
            try:
                watched_paths.extend(sorted(skills_root.glob("*/SKILL.md")))
            except OSError:
                continue
        runtime_compartment_dir = root / ".agent_control" / "runtime_compartments"
        watched_paths.append(runtime_compartment_dir)
        if runtime_compartment_dir.exists():
            watched_paths.extend(sorted(runtime_compartment_dir.glob("*.json")))
        for path in watched_paths:
            try:
                stat = path.stat()
            except OSError:
                rows.append((str(path), 0, 0))
            else:
                rows.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
        return tuple(rows)

    @staticmethod
    def _mission_detail_cache_key(root: Path, mission_id: str, event_limit: int) -> str:
        return f"{root.resolve()}::{mission_id}::{event_limit}"

    @staticmethod
    def _mission_detail_item_limits(event_limit: int) -> dict[str, int]:
        return {
            "events": event_limit,
            "action_history": 60,
            "plan_revisions": 12,
            "derived_tasks": 80,
            "improvement_queue": 80,
            "routing_decisions": 40,
            "skill_usage": 80,
            "learned_skill_events": 80,
            "delegated_session_events": 20,
        }

    def _annotate_mission_detail_cache(
        self,
        payload: dict[str, Any],
        *,
        status: str,
        started: float,
        cached_at: float | None,
        event_limit: int,
        freshness: str = "control-files-matched",
    ) -> dict[str, Any]:
        deps = self._cache_dependencies()
        annotated = dict(payload)
        annotated["performance"] = dict(payload.get("performance", {}))
        performance = annotated.setdefault("performance", {})
        previous_duration = performance.get("durationMs")
        served_duration = round((time.perf_counter() - started) * 1000, 2)
        performance["durationMs"] = served_duration
        performance["missionDetailCache"] = {
            "schema": "fluxio.control_room.mission_detail_cache.v1",
            "status": status,
            "ageMs": round((time.monotonic() - cached_at) * 1000, 2) if cached_at else 0,
            "freshness": freshness,
            "generationDurationMs": previous_duration,
            "maxItems": deps.mission_detail_cache_max_items,
        }
        performance["payloadBytes"] = len(
            json.dumps(annotated, separators=(",", ":")).encode("utf-8")
        )
        performance["budget"] = deps.control_room_store._performance_budget_payload(
            source="control_room_mission_detail",
            duration_ms=served_duration,
            payload_bytes=performance["payloadBytes"],
            duration_budget_ms=deps.control_room_detail_duration_budget_ms,
            payload_budget_bytes=deps.control_room_detail_payload_budget_bytes,
            item_limits=self._mission_detail_item_limits(event_limit),
        )
        return annotated

    def _cached_control_room_mission_detail(
        self,
        root: Path,
        *,
        mission_id: str,
        event_limit: int,
    ) -> dict[str, Any]:
        deps = self._cache_dependencies()
        started = time.perf_counter()
        cache_key = self._mission_detail_cache_key(root, mission_id, event_limit)
        signature = self._control_room_freshness_signature(root)
        with self._mission_detail_cache_lock:
            cached = self._mission_detail_cache.get(cache_key)
            if cached:
                cached_age = time.monotonic() - cached[1]
            else:
                cached_age = 0.0
            if cached and (
                cached[0] == signature
                or cached_age < deps.mission_detail_stale_while_revalidate_seconds
            ):
                if cached[0] != signature:
                    self._queue_mission_detail_cache_refresh(
                        root,
                        mission_id=mission_id,
                        event_limit=event_limit,
                        cache_key=cache_key,
                    )
                return self._annotate_mission_detail_cache(
                    cached[2],
                    status="hit",
                    started=started,
                    cached_at=cached[1],
                    event_limit=event_limit,
                    freshness=(
                        "control-files-matched"
                        if cached[0] == signature
                        else "stale-while-revalidate"
                    ),
                )
            prewarm_in_progress = cache_key in self._mission_detail_prewarm_keys

        if prewarm_in_progress:
            deadline = time.monotonic() + deps.mission_detail_prewarm_wait_seconds
            while time.monotonic() < deadline:
                time.sleep(0.025)
                with self._mission_detail_cache_lock:
                    cached = self._mission_detail_cache.get(cache_key)
                    if cached:
                        cached_age = time.monotonic() - cached[1]
                    else:
                        cached_age = 0.0
                    if cached and (
                        cached[0] == signature
                        or cached_age < deps.mission_detail_stale_while_revalidate_seconds
                    ):
                        if cached[0] != signature:
                            self._queue_mission_detail_cache_refresh(
                                root,
                                mission_id=mission_id,
                                event_limit=event_limit,
                                cache_key=cache_key,
                            )
                        return self._annotate_mission_detail_cache(
                            cached[2],
                            status="hit",
                            started=started,
                            cached_at=cached[1],
                            event_limit=event_limit,
                            freshness=(
                                "control-files-matched"
                                if cached[0] == signature
                                else "stale-while-revalidate"
                            ),
                        )
            with self._mission_detail_cache_lock:
                self._mission_detail_prewarm_keys.discard(cache_key)
        else:
            with self._mission_detail_cache_lock:
                self._mission_detail_prewarm_keys.discard(cache_key)

        payload = self._build_control_room_mission_detail(
            root,
            mission_id=mission_id,
            event_limit=event_limit,
        )
        self._store_mission_detail_cache(cache_key, signature, payload)
        return self._annotate_mission_detail_cache(
            payload,
            status="miss",
            started=started,
            cached_at=None,
            event_limit=event_limit,
        )

    def _store_mission_detail_cache(
        self,
        cache_key: str,
        signature: tuple[tuple[str, int, int], ...],
        payload: dict[str, Any],
    ) -> None:
        deps = self._cache_dependencies()
        with self._mission_detail_cache_lock:
            self._mission_detail_cache[cache_key] = (
                signature,
                time.monotonic(),
                dict(payload, performance=dict(payload.get("performance", {}))),
            )
            if len(self._mission_detail_cache) > deps.mission_detail_cache_max_items:
                oldest_key = min(
                    self._mission_detail_cache,
                    key=lambda key: self._mission_detail_cache[key][1],
                )
                self._mission_detail_cache.pop(oldest_key, None)

    def _queue_mission_detail_cache_refresh(
        self,
        root: Path,
        *,
        mission_id: str,
        event_limit: int,
        cache_key: str,
    ) -> None:
        if cache_key in self._mission_detail_prewarm_keys:
            return
        self._mission_detail_prewarm_keys.add(cache_key)
        timer = threading.Timer(
            0.01,
            self._refresh_control_room_mission_detail_cache,
            args=(root, mission_id, event_limit, cache_key),
        )
        timer.daemon = True
        timer.start()

    def _prewarm_control_room_mission_details(self, root: Path, summary: dict[str, Any]) -> None:
        deps = self._cache_dependencies()
        if not deps.mission_detail_prewarm_enabled:
            return
        missions = summary.get("missions") if isinstance(summary.get("missions"), list) else []
        mission_ids = [
            str(item.get("mission_id") or item.get("missionId") or "").strip()
            for item in missions
            if isinstance(item, dict)
            and str(item.get("status") or "").strip().lower() == "running"
            and str(item.get("mission_id") or item.get("missionId") or "").strip()
        ][:4]
        if not mission_ids:
            return
        for index, mission_id in enumerate(mission_ids):
            prewarm_key = f"{root.resolve()}::{mission_id}::80"
            with self._mission_detail_cache_lock:
                if prewarm_key in self._mission_detail_prewarm_keys:
                    continue
                self._mission_detail_prewarm_keys.add(prewarm_key)
            self._start_mission_detail_prewarm_timer(
                root,
                mission_id,
                prewarm_key,
                delay_seconds=deps.mission_detail_prewarm_delay_seconds * (index + 1),
            )

    def _schedule_mission_detail_prewarm_timer(
        self,
        root: Path,
        mission_id: str,
        prewarm_key: str,
        *,
        delay_seconds: float,
    ) -> None:
        timer = threading.Timer(
            delay_seconds,
            self._run_mission_detail_prewarm,
            args=(root, mission_id, prewarm_key),
        )
        timer.daemon = True
        timer.start()

    def _run_mission_detail_prewarm(self, root: Path, mission_id: str, prewarm_key: str) -> None:
        try:
            signature = self._control_room_freshness_signature(root)
            with self._mission_detail_cache_lock:
                if prewarm_key not in self._mission_detail_prewarm_keys:
                    return
                cached = self._mission_detail_cache.get(prewarm_key)
                if cached and cached[0] == signature:
                    return
            payload = self._build_control_room_mission_detail(
                root,
                mission_id=mission_id,
                event_limit=80,
            )
            self._store_mission_detail_cache(prewarm_key, signature, payload)
        except Exception:
            pass
        finally:
            with self._mission_detail_cache_lock:
                self._mission_detail_prewarm_keys.discard(prewarm_key)

    def _refresh_control_room_mission_detail_cache(
        self,
        root: Path,
        mission_id: str,
        event_limit: int,
        cache_key: str,
    ) -> None:
        try:
            signature = self._control_room_freshness_signature(root)
            payload = self._build_control_room_mission_detail(
                root,
                mission_id=mission_id,
                event_limit=event_limit,
            )
            self._store_mission_detail_cache(cache_key, signature, payload)
        except Exception:
            pass
        finally:
            with self._mission_detail_cache_lock:
                self._mission_detail_prewarm_keys.discard(cache_key)

    def _annotate_control_room_summary_cache(
        self,
        payload: dict[str, Any],
        *,
        status: str,
        cached_at: float | None,
        freshness: str,
        ttl_seconds: float,
    ) -> dict[str, Any]:
        deps = self._cache_dependencies()
        annotated = copy.deepcopy(payload)
        annotated["summaryCache"] = {
            "schema": "fluxio.control_room.summary_cache.v1",
            "mode": "full",
            "status": status,
            "freshness": freshness,
            "ttlSeconds": ttl_seconds,
            "staleWhileRevalidateSeconds": deps.full_summary_stale_while_revalidate_seconds,
            "ageMs": round((time.monotonic() - cached_at) * 1000, 2) if cached_at else 0,
        }
        return annotated

    @staticmethod
    def _persisted_control_room_summary_cache_path(root: Path) -> Path:
        return root / ".agent_control" / "control_room_summary_cache.json"

    @staticmethod
    def _persisted_control_room_bootstrap_summary_cache_path(root: Path) -> Path:
        return root / ".agent_control" / "control_room_bootstrap_summary_cache.json"

    @staticmethod
    def _temporary_control_room_cache_path(root: Path, name: str) -> Path:
        digest = hashlib.sha256(str(root.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:16]
        return Path(tempfile.gettempdir()) / "fluxio-control-room-cache" / digest / name

    @classmethod
    def _control_room_summary_cache_paths(cls, root: Path, *, bootstrap: bool) -> list[Path]:
        primary = (
            cls._persisted_control_room_bootstrap_summary_cache_path(root)
            if bootstrap
            else cls._persisted_control_room_summary_cache_path(root)
        )
        temporary = cls._temporary_control_room_cache_path(
            root,
            "control_room_bootstrap_summary_cache.json"
            if bootstrap
            else "control_room_summary_cache.json",
        )
        return [primary, temporary]

    @staticmethod
    def _serializable_control_room_signature(
        signature: tuple[tuple[str, int, int], ...],
    ) -> list[list[object]]:
        return [[path, mtime_ns, size] for path, mtime_ns, size in signature]

    @staticmethod
    def _signature_from_serialized(value: object) -> tuple[tuple[str, int, int], ...]:
        if not isinstance(value, list):
            return ()
        rows: list[tuple[str, int, int]] = []
        for item in value:
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                return ()
            try:
                rows.append((str(item[0]), int(item[1]), int(item[2])))
            except (TypeError, ValueError):
                return ()
        return tuple(rows)

    def _load_persisted_control_room_summary(
        self,
        root: Path,
        signature: tuple[tuple[str, int, int], ...],
    ) -> dict[str, Any] | None:
        deps = self._cache_dependencies()
        paths = self._control_room_summary_cache_paths(root, bootstrap=False)
        path = paths[0]
        try:
            payload = None
            for candidate in paths:
                try:
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                    path = candidate
                    break
                except (OSError, json.JSONDecodeError):
                    continue
            if payload is None:
                return None
        except OSError:
            return None
        if path != paths[0]:
            pass
        if not isinstance(payload, dict):
            return None
        if payload.get("cacheVersion") != deps.persisted_full_summary_cache_version:
            return None
        if self._signature_from_serialized(payload.get("signature")) != signature:
            return None
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            return None
        return summary

    def _write_persisted_control_room_summary(
        self,
        root: Path,
        signature: tuple[tuple[str, int, int], ...],
        payload: dict[str, Any],
    ) -> None:
        deps = self._cache_dependencies()
        primary_path, temporary_path = self._control_room_summary_cache_paths(root, bootstrap=False)
        path = primary_path
        try:
            if shutil.disk_usage(path.parent).free < 2_000_000:
                path = temporary_path
        except OSError:
            path = temporary_path
        cache_payload = {
            "schema": "fluxio.control_room.persisted_summary_cache.v1",
            "cacheVersion": deps.persisted_full_summary_cache_version,
            "writtenAt": deps.utc_now(),
            "signature": self._serializable_control_room_signature(signature),
            "summary": copy.deepcopy(payload),
        }
        cache_payload["summary"].pop("summaryCache", None)
        cache_payload["summary"].pop("webBackend", None)
        cache_payload["summary"].pop("providerSecretPresence", None)
        cache_payload["summary"].pop("runtimeRouteProof", None)
        cache_payload["summary"].pop("webPushStatus", None)
        cache_payload["summary"].pop("ntfyStatus", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}")
        try:
            tmp_path.write_text(json.dumps(cache_payload, separators=(",", ":")), encoding="utf-8")
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            tmp_path.replace(path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def _load_persisted_control_room_bootstrap_summary(
        self,
        root: Path,
        signature: tuple[tuple[str, int, int], ...],
    ) -> dict[str, Any] | None:
        deps = self._cache_dependencies()
        paths = self._control_room_summary_cache_paths(root, bootstrap=True)
        payload = None
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                break
            except (OSError, json.JSONDecodeError):
                continue
        if payload is None:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("cacheVersion") != deps.persisted_bootstrap_summary_cache_version:
            return None
        if self._signature_from_serialized(payload.get("signature")) != signature:
            return None
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            return None
        return summary

    def _write_persisted_control_room_bootstrap_summary(
        self,
        root: Path,
        signature: tuple[tuple[str, int, int], ...],
        payload: dict[str, Any],
    ) -> None:
        deps = self._cache_dependencies()
        primary_path, temporary_path = self._control_room_summary_cache_paths(root, bootstrap=True)
        path = primary_path
        try:
            if shutil.disk_usage(path.parent).free < 2_000_000:
                path = temporary_path
        except OSError:
            path = temporary_path
        cache_payload = {
            "schema": "fluxio.control_room.persisted_bootstrap_summary_cache.v1",
            "cacheVersion": deps.persisted_bootstrap_summary_cache_version,
            "writtenAt": deps.utc_now(),
            "signature": self._serializable_control_room_signature(signature),
            "summary": copy.deepcopy(payload),
        }
        cache_payload["summary"].pop("summaryCache", None)
        cache_payload["summary"].pop("webBackend", None)
        cache_payload["summary"].pop("providerSecretPresence", None)
        cache_payload["summary"].pop("runtimeRouteProof", None)
        cache_payload["summary"].pop("webPushStatus", None)
        cache_payload["summary"].pop("ntfyStatus", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}")
        try:
            tmp_path.write_text(json.dumps(cache_payload, separators=(",", ":"), default=str), encoding="utf-8")
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            tmp_path.replace(path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def _cached_control_room_summary(self, root: Path) -> dict[str, Any]:
        deps = self._cache_dependencies()
        cache_key = str(root.resolve())
        signature = self._control_room_freshness_signature(root)
        now = time.monotonic()
        should_revalidate = False
        with self._summary_cache_lock:
            cached = self._full_summary_cache.get(cache_key)
            cached_age = now - cached[1] if cached else 0.0
            if cached and cached_age <= deps.full_summary_cache_ttl_seconds:
                return self._annotate_control_room_summary_cache(
                    cached[2],
                    status="hit",
                    cached_at=cached[1],
                    freshness=(
                        "control-files-matched"
                        if cached[0] == signature
                        else "control-files-changed"
                    ),
                    ttl_seconds=deps.full_summary_cache_ttl_seconds,
                )
            if cached and cached_age <= deps.full_summary_stale_while_revalidate_seconds:
                if cache_key not in self._full_summary_revalidation_keys:
                    self._full_summary_revalidation_keys.add(cache_key)
                    should_revalidate = True
                payload = self._annotate_control_room_summary_cache(
                    cached[2],
                    status="stale-while-revalidate",
                    cached_at=cached[1],
                    freshness=(
                        "control-files-matched"
                        if cached[0] == signature
                        else "control-files-changed"
                    ),
                    ttl_seconds=deps.full_summary_cache_ttl_seconds,
                )
            else:
                payload = None
        if payload is not None:
            if should_revalidate:
                self._start_control_room_summary_revalidate(root, cache_key)
            return payload

        persisted_payload = self._load_persisted_control_room_summary(root, signature)
        if persisted_payload is not None:
            cached_at = time.monotonic()
            with self._summary_cache_lock:
                self._full_summary_cache[cache_key] = (
                    signature,
                    cached_at,
                    copy.deepcopy(persisted_payload),
                )
            return self._annotate_control_room_summary_cache(
                persisted_payload,
                status="disk-hit",
                cached_at=cached_at,
                freshness="control-files-matched",
                ttl_seconds=deps.full_summary_cache_ttl_seconds,
            )

        payload = self._build_control_room_summary(root)
        refreshed_signature = self._control_room_freshness_signature(root)
        with self._summary_cache_lock:
            self._full_summary_cache[cache_key] = (
                refreshed_signature,
                time.monotonic(),
                copy.deepcopy(payload),
            )
        self._write_persisted_control_room_summary(root, refreshed_signature, payload)
        return self._annotate_control_room_summary_cache(
            payload,
            status="miss",
            cached_at=None,
            freshness="rebuilt",
            ttl_seconds=deps.full_summary_cache_ttl_seconds,
        )

    def _start_control_room_summary_revalidate(self, root: Path, cache_key: str) -> None:
        worker = threading.Thread(
            target=self._run_control_room_summary_revalidate,
            args=(root, cache_key),
            daemon=True,
        )
        worker.start()

    def _run_control_room_summary_revalidate(self, root: Path, cache_key: str) -> None:
        try:
            payload = self._build_control_room_summary(root)
            signature = self._control_room_freshness_signature(root)
            with self._summary_cache_lock:
                self._full_summary_cache[cache_key] = (
                    signature,
                    time.monotonic(),
                    copy.deepcopy(payload),
                )
            self._write_persisted_control_room_summary(root, signature, payload)
        except Exception:
            pass
        finally:
            with self._summary_cache_lock:
                self._full_summary_revalidation_keys.discard(cache_key)

    def _cached_control_room_bootstrap_summary(self, root: Path) -> dict[str, Any]:
        started = time.perf_counter()
        cache_key = str(root.resolve())
        signature = self._control_room_freshness_signature(root)
        now = time.monotonic()
        with self._summary_cache_lock:
            cached = self._bootstrap_summary_cache.get(cache_key)
            if cached and cached[0] == signature:
                return self._annotate_control_room_bootstrap_cache(
                    cached[2],
                    status="hit",
                    started=started,
                    cached_at=cached[1],
                    freshness="control-files-matched",
                )

        persisted_payload = self._load_persisted_control_room_bootstrap_summary(root, signature)
        if persisted_payload is not None:
            cached_at = time.monotonic()
            with self._summary_cache_lock:
                self._bootstrap_summary_cache[cache_key] = (
                    signature,
                    cached_at,
                    copy.deepcopy(persisted_payload),
                )
            return self._annotate_control_room_bootstrap_cache(
                persisted_payload,
                status="disk-hit",
                started=started,
                cached_at=cached_at,
                freshness="control-files-matched",
            )

        payload = self._build_control_room_bootstrap_summary(root)
        refreshed_signature = self._control_room_freshness_signature(root)
        with self._summary_cache_lock:
            self._bootstrap_summary_cache[cache_key] = (
                refreshed_signature,
                time.monotonic(),
                copy.deepcopy(payload),
            )
        self._write_persisted_control_room_bootstrap_summary(root, refreshed_signature, payload)
        return self._annotate_control_room_bootstrap_cache(
            payload,
            status="miss",
            started=started,
            cached_at=None,
            freshness="rebuilt",
        )

    def _annotate_runtime_proof_status_cache(
        self,
        payload: dict[str, Any],
        *,
        status: str,
        cached_at: float | None,
        freshness: str,
        age_ms: float | None = None,
    ) -> dict[str, Any]:
        deps = self._cache_dependencies()
        annotated = copy.deepcopy(payload)
        annotated["runtimeProofStatusCache"] = {
            "schema": "fluxio.real_agent_runtime_proof_status_cache.v1",
            "status": status,
            "freshness": freshness,
            "ttlSeconds": deps.runtime_proof_status_cache_ttl_seconds,
            "staleWhileRevalidateSeconds": deps.runtime_proof_status_stale_while_revalidate_seconds,
            "ageMs": round(age_ms, 2)
            if age_ms is not None
            else round((time.monotonic() - cached_at) * 1000, 2) if cached_at else 0,
        }
        return annotated

    @staticmethod
    def _persisted_runtime_proof_status_cache_path(root: Path) -> Path:
        return root / ".agent_control" / "real_agent_runtime_proof_status_cache.json"

    @classmethod
    def _runtime_proof_status_cache_paths(cls, root: Path) -> list[Path]:
        return [
            cls._persisted_runtime_proof_status_cache_path(root),
            cls._temporary_control_room_cache_path(root, "real_agent_runtime_proof_status_cache.json"),
        ]

    @staticmethod
    def _runtime_proof_cache_age_seconds(written_at: object) -> float | None:
        text = str(written_at or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())

    def _load_persisted_runtime_proof_status_cache(self, root: Path) -> tuple[dict[str, Any], float] | None:
        deps = self._cache_dependencies()
        for path in self._runtime_proof_status_cache_paths(root):
            try:
                cache_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(cache_payload, dict):
                continue
            if cache_payload.get("cacheVersion") != deps.persisted_runtime_proof_status_cache_version:
                continue
            status_payload = cache_payload.get("status")
            if not isinstance(status_payload, dict):
                continue
            if status_payload.get("schema") != "fluxio.real_agent_runtime_proof_status.v1":
                continue
            age_seconds = self._runtime_proof_cache_age_seconds(cache_payload.get("writtenAt"))
            if age_seconds is None or age_seconds > deps.runtime_proof_status_stale_while_revalidate_seconds:
                continue
            status_payload = copy.deepcopy(status_payload)
            status_payload.pop("runtimeProofStatusCache", None)
            return status_payload, age_seconds
        return None

    def _write_persisted_runtime_proof_status_cache(self, root: Path, payload: dict[str, Any]) -> None:
        deps = self._cache_dependencies()
        primary_path, temporary_path = self._runtime_proof_status_cache_paths(root)
        path = primary_path
        try:
            if shutil.disk_usage(path.parent).free < 2_000_000:
                path = temporary_path
        except OSError:
            path = temporary_path
        cache_status = copy.deepcopy(payload)
        cache_status.pop("runtimeProofStatusCache", None)
        cache_payload = {
            "schema": "fluxio.real_agent_runtime_proof_status_persisted_cache.v1",
            "cacheVersion": deps.persisted_runtime_proof_status_cache_version,
            "writtenAt": deps.utc_now(),
            "status": cache_status,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}")
        try:
            tmp_path.write_text(json.dumps(cache_payload, separators=(",", ":"), default=str), encoding="utf-8")
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            tmp_path.replace(path)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _cached_real_agent_runtime_proof_status(self, root: Path) -> dict[str, Any]:
        deps = self._cache_dependencies()
        cache_key = str(root.resolve())
        now = time.monotonic()
        with self._runtime_proof_status_cache_lock:
            cached = self._runtime_proof_status_cache.get(cache_key)
            cached_age = now - cached[0] if cached else 0.0
            if cached and cached_age <= deps.runtime_proof_status_cache_ttl_seconds:
                return self._annotate_runtime_proof_status_cache(
                    cached[1],
                    status="hit",
                    cached_at=cached[0],
                    freshness="fresh-cache",
                )
            if (
                cached
                and cached_age <= deps.runtime_proof_status_stale_while_revalidate_seconds
            ):
                if cache_key not in self._runtime_proof_status_revalidation_keys:
                    self._runtime_proof_status_revalidation_keys.add(cache_key)
                    self._start_runtime_proof_status_revalidate(root, cache_key)
                return self._annotate_runtime_proof_status_cache(
                    cached[1],
                    status="stale-hit",
                    cached_at=cached[0],
                    freshness="stale-while-revalidate",
                )

        persisted = self._load_persisted_runtime_proof_status_cache(root)
        if persisted is not None:
            persisted_payload, persisted_age_seconds = persisted
            cached_at = time.monotonic() - min(
                persisted_age_seconds,
                deps.runtime_proof_status_stale_while_revalidate_seconds,
            )
            with self._runtime_proof_status_cache_lock:
                self._runtime_proof_status_cache[cache_key] = (cached_at, copy.deepcopy(persisted_payload))
                if (
                    persisted_age_seconds > deps.runtime_proof_status_cache_ttl_seconds
                    and cache_key not in self._runtime_proof_status_revalidation_keys
                ):
                    self._runtime_proof_status_revalidation_keys.add(cache_key)
                    self._start_runtime_proof_status_revalidate(root, cache_key)
            return self._annotate_runtime_proof_status_cache(
                persisted_payload,
                status="disk-hit" if persisted_age_seconds <= deps.runtime_proof_status_cache_ttl_seconds else "disk-stale-hit",
                cached_at=cached_at,
                freshness="persisted-cache"
                if persisted_age_seconds <= deps.runtime_proof_status_cache_ttl_seconds
                else "persisted-stale-while-revalidate",
                age_ms=persisted_age_seconds * 1000,
            )

        payload = deps.build_real_agent_proof_status(root)
        with self._runtime_proof_status_cache_lock:
            self._runtime_proof_status_cache[cache_key] = (time.monotonic(), copy.deepcopy(payload))
        self._write_persisted_runtime_proof_status_cache(root, payload)
        return self._annotate_runtime_proof_status_cache(
            payload,
            status="miss",
            cached_at=None,
            freshness="rebuilt",
        )

    def _start_runtime_proof_status_revalidate(self, root: Path, cache_key: str) -> None:
        worker = threading.Thread(
            target=self._run_runtime_proof_status_revalidate,
            args=(root, cache_key),
            daemon=True,
        )
        worker.start()

    def _run_runtime_proof_status_revalidate(self, root: Path, cache_key: str) -> None:
        deps = self._cache_dependencies()
        try:
            payload = deps.build_real_agent_proof_status(root)
            with self._runtime_proof_status_cache_lock:
                self._runtime_proof_status_cache[cache_key] = (time.monotonic(), copy.deepcopy(payload))
            self._write_persisted_runtime_proof_status_cache(root, payload)
        except Exception:
            pass
        finally:
            with self._runtime_proof_status_cache_lock:
                self._runtime_proof_status_revalidation_keys.discard(cache_key)

    def _annotate_control_room_bootstrap_cache(
        self,
        payload: dict[str, Any],
        *,
        status: str,
        started: float,
        cached_at: float | None,
        freshness: str,
    ) -> dict[str, Any]:
        deps = self._cache_dependencies()
        annotated = copy.deepcopy(payload)
        performance = dict(annotated.get("performance", {}))
        generation_duration = performance.get("durationMs")
        served_duration = round((time.perf_counter() - started) * 1000, 2)
        annotated["summaryCache"] = {
            "schema": "fluxio.control_room.summary_cache.v1",
            "status": status,
            "freshness": freshness,
            "ttlSeconds": deps.bootstrap_summary_cache_ttl_seconds,
            "ageMs": round((time.monotonic() - cached_at) * 1000, 2) if cached_at else 0,
            "generationDurationMs": generation_duration,
        }
        performance["durationMs"] = served_duration
        performance["payloadBytes"] = len(
            json.dumps(annotated, separators=(",", ":"), default=str).encode("utf-8")
        )
        previous_budget = performance.get("budget") if isinstance(performance.get("budget"), dict) else {}
        previous_limits = previous_budget.get("itemLimits") if isinstance(previous_budget.get("itemLimits"), dict) else {}
        performance["budget"] = deps.control_room_store._performance_budget_payload(
            source="control_room_summary_bootstrap",
            duration_ms=served_duration,
            payload_bytes=performance["payloadBytes"],
            duration_budget_ms=deps.control_room_summary_duration_budget_ms,
            payload_budget_bytes=deps.control_room_summary_payload_budget_bytes,
            item_limits=dict(previous_limits),
        )
        annotated["performance"] = performance
        return annotated
