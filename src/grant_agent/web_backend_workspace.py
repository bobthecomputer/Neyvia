from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class WorkspaceArtifactDependencies:
    """Current facade policy and callbacks, supplied explicitly at each operation."""

    artifact_content_types: dict[str, str]
    safe_identifier: Callable[..., Any]
    sha256_hex: Callable[..., Any]
    utc_now: Callable[..., Any]
    platform_config: Callable[..., Any]
    record_delivery_receipt: Callable[..., Any]
    unquote: Callable[..., Any]
    urlparse: Callable[..., Any]


def decorate_mission_events(payload: dict[str, Any], *, sha256_hex: Callable[[str], str]) -> dict[str, Any]:
    """Give detail and delta views the same stable event identities."""

    output = copy.deepcopy(payload)
    events = output.get("events")
    if not isinstance(events, list):
        return output
    normalized: list[Any] = []
    for event in events:
        if not isinstance(event, dict):
            normalized.append(event)
            continue
        row = dict(event)
        if not str(row.get("eventId") or row.get("event_id") or "").strip():
            identity = {
                "missionId": row.get("missionId") or row.get("mission_id"),
                "at": row.get("timestamp")
                or row.get("created_at")
                or row.get("createdAt")
                or row.get("at"),
                "kind": row.get("kind") or row.get("event") or row.get("type"),
                "actor": row.get("actor") or row.get("agent") or row.get("runtime"),
                "message": row.get("message") or row.get("detail") or row.get("summary"),
            }
            row["eventId"] = sha256_hex(
                json.dumps(identity, sort_keys=True, default=str)
            )[:24]
        normalized.append(row)
    output["events"] = normalized
    from .proofs_d_host import check_event_identity
    check_event_identity(payload, output)
    return output


class WorkspaceArtifactMixin:
    """Owns workspace behavior; the backend supplies state and external callbacks."""

    def _workspace_root_entries(self) -> list[dict[str, Any]]:
        deps = self._workspace_dependencies()
        config = deps.platform_config(self.root)

        def is_remote_windows_path(candidate: Path) -> bool:
            if os.name != "nt":
                return False
            raw = str(candidate).strip()
            if raw.startswith("\\\\"):
                return True
            drive_root = candidate.anchor or (f"{candidate.drive}\\" if candidate.drive else "")
            if not drive_root:
                return False
            try:
                import ctypes

                return int(ctypes.windll.kernel32.GetDriveTypeW(str(drive_root))) == 4
            except (AttributeError, OSError, TypeError, ValueError):
                return False

        def resolve_entry(root_id: str, label: str, candidate: Path) -> dict[str, Any] | None:
            remote = is_remote_windows_path(candidate)
            try:
                expanded = candidate.expanduser()
                resolved = expanded.absolute() if remote else expanded.resolve()
            except (OSError, RuntimeError):
                try:
                    resolved = candidate.expanduser().absolute()
                except (OSError, RuntimeError):
                    return None
            available = False if remote else resolved.exists() and resolved.is_dir()
            return {
                "id": root_id,
                "label": label,
                "path": str(resolved),
                # Windows may spend tens of seconds probing a disconnected mapped
                # drive or UNC share. Keep remote roots visible as connection
                # targets, but never probe them while opening the local chooser.
                "available": available,
                "availability": "connect" if remote else "available" if available else "unavailable",
            }

        def collect_nas_paths(value: Any, output: list[str]) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = str(key).replace("-", "_").lower()
                    if isinstance(child, str) and "nas" in normalized_key and "path" in normalized_key:
                        output.append(child)
                    collect_nas_paths(child, output)
                return
            if isinstance(value, list):
                for child in value:
                    collect_nas_paths(child, output)

        candidates: list[tuple[str, str, Path]] = [
            ("local", "Local workspace", self.root),
        ]
        for env_name in ("FLUXIO_WORKSPACE_ROOTS", "FLUXIO_FOLDER_ROOTS"):
            raw_roots = os.environ.get(env_name, "")
            for raw_path in re.split(r"[;\n]", raw_roots):
                path_text = str(raw_path or "").strip().strip('"')
                if path_text:
                    candidates.append(
                        (
                            f"configured-{len(candidates)}",
                            "Configured folder",
                            Path(path_text),
                        )
                    )

        home = Path.home()
        for root_id, label, path in (
            ("home", "Home", home),
            ("projects", "Projects", home / "Projects"),
            ("desktop", "Desktop", home / "Desktop"),
            ("documents", "Documents", home / "Documents"),
            ("downloads", "Downloads", home / "Downloads"),
        ):
            candidates.append((root_id, label, path))

        if os.name == "nt":
            # Do not call os.listdrives() here. Windows includes remembered and
            # disconnected network drives in that list, and merely probing them
            # can freeze a local-first chooser. Intentional configured roots are
            # already added above; only stable local drive anchors belong here.
            drive_texts: list[str] = []
            for drive_text in (self.root.drive, home.drive, "C:"):
                if drive_text:
                    drive_texts.append(drive_text)
            for drive_text in sorted({text.rstrip("\\/") for text in drive_texts if text}):
                normalized_drive = drive_text.replace("\\", "/").rstrip("/")
                drive_label = normalized_drive.rstrip(":").upper()
                if not drive_label:
                    continue
                candidates.append(
                    (
                        f"drive-{drive_label.lower()}",
                        f"Drive {drive_label}:",
                        Path(f"{normalized_drive}/"),
                    )
                )
        else:
            for root_id, label, path in (
                ("nas-volume", "NAS volume", config.nas_volume_root.parent),
                ("nas-saclay", "NAS Saclay", config.nas_volume_root),
                ("nas-projects", "NAS projects", config.nas_projects_root),
                ("mnt-projects", "Windows projects mount", Path("/mnt/c/Users/user/Projects")),
            ):
                candidates.append((root_id, label, path))

        nas_paths: list[str] = []
        workspaces_path = self.root / ".agent_control" / "workspaces.json"
        try:
            payload = json.loads(workspaces_path.read_text(encoding="utf-8"))
            collect_nas_paths(payload, nas_paths)
        except (OSError, json.JSONDecodeError):
            nas_paths = []

        for raw_path in nas_paths:
            path_text = str(raw_path or "").strip()
            if not path_text:
                continue
            candidates.append((f"nas-{len(candidates)}", "Synology NAS", Path(path_text)))
            for mirror_candidate in config.path_candidates(path_text):
                candidates.append((f"nas-{len(candidates)}", "Synology NAS mount", mirror_candidate))

        default_nas_mount = config.windows_nas_project_root if os.name == "nt" else config.nas_project_root
        candidates.append((f"nas-{len(candidates)}", "Synology NAS mount", default_nas_mount))

        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root_id, label, candidate in candidates:
            entry = resolve_entry(root_id, label, candidate)
            if not entry:
                continue
            normalized = str(entry["path"])
            if normalized in seen:
                continue
            seen.add(normalized)
            entries.append(entry)
        return entries

    def _workspace_roots(self, root_entries: list[dict[str, Any]] | None = None) -> list[str]:
        entries = root_entries if root_entries is not None else self._workspace_root_entries()
        return [entry["path"] for entry in entries if entry.get("available")]

    def _resolve_execution_workspace(self, raw_path: object) -> Path:
        requested = Path(str(raw_path or self.root)).expanduser().resolve()
        allowed = [self.root.resolve()]
        for env_name in ("FLUXIO_WORKSPACE_ROOTS", "FLUXIO_FOLDER_ROOTS"):
            for raw_root in re.split(r"[;\n]", os.environ.get(env_name, "")):
                value = str(raw_root or "").strip().strip('"')
                if value:
                    allowed.append(Path(value).expanduser().resolve())
        workspaces_path = self.root / ".agent_control" / "workspaces.json"
        try:
            workspaces = json.loads(workspaces_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            workspaces = []
        rows = (
            workspaces
            if isinstance(workspaces, list)
            else workspaces.get("workspaces", [])
            if isinstance(workspaces, dict)
            else []
        )
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            value = str(row.get("root_path") or row.get("rootPath") or "").strip()
            if value:
                allowed.append(Path(value).expanduser().resolve())
        if not any(requested == root or root in requested.parents for root in allowed):
            raise RuntimeError(
                f"Directory is outside configured workspace roots: {requested}"
            )
        if not requested.is_dir():
            raise RuntimeError(f"Directory does not exist: {requested}")
        return requested

    def _project_mission_artifact_roots(self) -> list[Path]:
        deps = self._workspace_dependencies()
        config = deps.platform_config(self.root)
        projects_roots: list[Path] = []
        for candidate in (self.root, *self.root.parents):
            if candidate.name == "projects":
                projects_roots.append(candidate)
                break
        mirror_candidates = (
            [config.windows_nas_projects_root]
            if os.name == "nt"
            else [
                config.nas_projects_root,
                Path("/mnt/c") / str(config.nas_projects_root).lstrip("/"),
            ]
        )
        projects_roots.extend(mirror_candidates)
        roots: list[Path] = []
        seen: set[str] = set()
        for projects_root in projects_roots:
            if not projects_root.exists() or not projects_root.is_dir():
                continue
            for control_dir in projects_root.glob("*/.agent_control/mission_artifacts"):
                try:
                    resolved = control_dir.expanduser().resolve()
                except OSError:
                    continue
                if not resolved.exists() or not resolved.is_dir():
                    continue
                key = str(resolved)
                if key in seen:
                    continue
                seen.add(key)
                roots.append(resolved)
        return roots

    def _artifact_allowed_roots(self) -> list[Path]:
        deps = self._workspace_dependencies()
        config = deps.platform_config(self.root)
        candidates = [
            self.root / ".agent_control" / "image_playground_artifacts",
            self.root / ".agent_control" / "generated_image_artifacts",
            self.root / ".agent_control" / "design_references",
            self.root / ".agent_control" / "mission_artifacts",
            self.root / ".agent_control" / "runtime_compartments",
            self.root / ".agent_control" / "runtime_sessions",
            self.root / ".agent_control" / "mission_async",
            self.root / ".agent_runs",
        ]
        candidates.extend(
            config.control_search_roots(
                ".agent_control/design_references",
                ".agent_control/mission_artifacts",
                ".agent_control/runtime_sessions",
                ".agent_control/mission_async",
                ".agent_runs",
            )
        )
        candidates.extend(self._project_mission_artifact_roots())
        roots: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = candidate.expanduser().resolve()
            except OSError:
                continue
            if not resolved.exists():
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            roots.append(resolved)
        return roots

    def _candidate_artifact_paths(self, raw_path: object) -> list[Path]:
        deps = self._workspace_dependencies()
        config = deps.platform_config(self.root)
        raw = str(raw_path or "").strip()
        if raw.startswith("file://"):
            raw = deps.unquote(deps.urlparse(raw).path)
        raw = raw.replace("\x00", "")
        candidates: list[Path] = []
        if raw:
            source = Path(raw).expanduser()
            candidates.append(source if source.is_absolute() else self.root / source)
            normalized = raw.replace("\\", "/")
            candidates.extend(config.path_candidates(raw))
            direct_hits: list[Path] = []
            seen_direct: set[str] = set()
            for candidate in candidates:
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if not resolved.exists() or not resolved.is_file():
                    continue
                key = str(resolved)
                if key in seen_direct:
                    continue
                seen_direct.add(key)
                direct_hits.append(resolved)
            if direct_hits:
                return direct_hits
            name = Path(normalized).name
            if name:
                for search_root in (
                    self.root / ".agent_control" / "image_playground_artifacts",
                    self.root / ".agent_control" / "generated_image_artifacts",
                    self.root / ".agent_control" / "runtime_compartments",
                    *config.control_search_roots(
                        ".agent_control/design_references",
                        ".agent_control/mission_artifacts",
                        ".agent_control/runtime_sessions",
                        ".agent_control/mission_async",
                        ".agent_runs",
                    ),
                    *self._project_mission_artifact_roots(),
                ):
                    if search_root.exists():
                        candidates.extend(search_root.rglob(name))
        deduped: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(resolved)
        return deduped

    def _resolve_artifact_path(self, raw_path: object) -> Path:
        deps = self._workspace_dependencies()
        allowed_roots = self._artifact_allowed_roots()
        for candidate in self._candidate_artifact_paths(raw_path):
            if not candidate.exists() or not candidate.is_file():
                continue
            if candidate.suffix.lower() not in deps.artifact_content_types:
                continue
            for root in allowed_roots:
                try:
                    candidate.relative_to(root)
                    return candidate
                except ValueError:
                    continue
        raise RuntimeError("Artifact was not found under an allowed workspace or NAS mirror root.")

    def _artifact_id(self, path: Path) -> str:
        deps = self._workspace_dependencies()
        return deps.sha256_hex(str(path.resolve()))[:24]

    def _resolve_artifact_id(self, raw_id: object) -> Path:
        deps = self._workspace_dependencies()
        artifact_id = str(raw_id or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{24}", artifact_id):
            raise RuntimeError("Artifact id is invalid.")
        for root in self._artifact_allowed_roots():
            for candidate in root.rglob("*"):
                if not candidate.is_file() or candidate.suffix.lower() not in deps.artifact_content_types:
                    continue
                if self._artifact_id(candidate) == artifact_id:
                    return candidate
        raise RuntimeError("Artifact was not found under an allowed workspace or NAS mirror root.")

    def _artifact_url(self, path: Path) -> str:
        return f"/api/artifact?id={self._artifact_id(path)}"

    def _decorate_mission_artifacts(self, detail: dict[str, Any]) -> dict[str, Any]:
        """Add loadable artifact URLs only after the normal artifact gate accepts them."""

        deps = self._workspace_dependencies()
        def decorate(value: Any, *, artifact_context: bool = False) -> Any:
            if isinstance(value, list):
                return [
                    decorate(item, artifact_context=artifact_context)
                    for item in value
                ]
            if artifact_context and isinstance(value, str):
                value = {"path": value, "label": Path(value).name or value}
            if not isinstance(value, dict):
                return copy.deepcopy(value)
            row = {
                key: decorate(
                    item,
                    # The current mapping may be an artifact record, but its
                    # scalar fields are ordinary values. Only a nested
                    # ``artifacts`` collection starts a new artifact context;
                    # propagating the flag into ``path`` turns the path string
                    # into another artifact mapping forever.
                    artifact_context=key == "artifacts",
                )
                for key, item in value.items()
            }
            if not artifact_context:
                return row
            raw_path = next(
                (
                    row.get(key)
                    for key in (
                        "artifactPath",
                        "path",
                        "localPath",
                        "resolvedPath",
                        "targetPath",
                    )
                    if str(row.get(key) or "").strip()
                ),
                None,
            )
            try:
                if not raw_path:
                    raise RuntimeError("Artifact path is empty.")
                target = self._resolve_artifact_path(raw_path)
            except (RuntimeError, OSError, ValueError):
                if str(row.get("servedUrl") or "").startswith("/api/artifact"):
                    row["servedUrl"] = ""
                row.pop("safeEndpoint", None)
                from .proofs_d_host import check_artifact_row
                check_artifact_row(row, approved=False)
                return row
            row["servedUrl"] = self._artifact_url(target)
            row["safeEndpoint"] = "/api/artifact"
            row["mediaType"] = deps.artifact_content_types[target.suffix.lower()].split(";", 1)[0]
            row["artifactId"] = row.get("artifactId") or self._artifact_id(target)
            from .proofs_d_host import check_artifact_row
            check_artifact_row(row, approved=True)
            return row

        decorated = decorate(detail)
        if not isinstance(decorated, dict):
            return {}
        candidates: list[Any] = []
        for value in (
            decorated.get("artifacts"),
            (decorated.get("proof") or {}).get("artifacts")
            if isinstance(decorated.get("proof"), dict)
            else None,
            ((decorated.get("proofDigest") or {}).get("latest") or {}).get("artifacts")
            if isinstance((decorated.get("proofDigest") or {}).get("latest"), dict)
            else None,
            (decorated.get("artifactGate") or {}).get("artifacts")
            if isinstance(decorated.get("artifactGate"), dict)
            else None,
        ):
            if isinstance(value, list):
                candidates.extend(value)
        if candidates:
            deduped: list[Any] = []
            seen: set[str] = set()
            for candidate in decorate(candidates, artifact_context=True):
                key = str(
                    candidate.get("artifactId")
                    or candidate.get("servedUrl")
                    or candidate.get("path")
                    or candidate
                ) if isinstance(candidate, dict) else str(candidate)
                if key and key not in seen:
                    seen.add(key)
                    deduped.append(candidate)
            decorated["artifacts"] = deduped
        return decorated

    @staticmethod
    def _validated_chat_changed_file(
        token: object,
        *,
        workspace_path: Path,
    ) -> tuple[str, Path] | None:
        """Normalize a structured changed-file value within the workspace."""

        normalized = str(token or "").strip().strip(".,;:)]}").replace("\\", "/")
        if not normalized or any(ord(char) < 32 for char in normalized):
            return None
        if normalized.startswith(("a/", "b/")):
            normalized = normalized[2:]
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized.startswith(".volume1/"):
            normalized = "/" + normalized[1:]
        if normalized.startswith("agent_control/"):
            normalized = f".{normalized}"
        # A Windows drive path in command/model text is not workspace evidence.
        # It is valid only when the selected workspace is on that same host path.
        if re.match(r"^[A-Za-z]:/", normalized) and os.name != "nt":
            return None
        raw_path = Path(normalized).expanduser()
        workspace_root = workspace_path.expanduser().resolve()
        candidate = raw_path if raw_path.is_absolute() else workspace_root / raw_path
        try:
            resolved = candidate.resolve()
            display_path = resolved.relative_to(workspace_root).as_posix()
        except (OSError, ValueError):
            return None
        if not display_path or display_path == ".":
            return None
        return display_path, resolved

    def _chat_textual_artifact_evidence(
        self,
        result: dict[str, Any],
        *,
        workspace_path: Path,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        deps = self._workspace_dependencies()
        text_parts = [
            result.get("reply"),
            result.get("message"),
            result.get("output"),
            result.get("stdout"),
        ]
        raw_payload = result.get("raw")
        if isinstance(raw_payload, dict):
            text_parts.extend(
                [
                    raw_payload.get("reply"),
                    raw_payload.get("message"),
                    raw_payload.get("output"),
                    raw_payload.get("stdout"),
                ]
            )
        text = "\n".join(str(item or "") for item in text_parts if str(item or "").strip())
        if not text:
            return [], []

        changed_files: list[str] = []
        proof_artifacts: list[dict[str, Any]] = []
        seen_files: set[str] = set()
        seen_artifacts: set[str] = set()
        workspace_root = workspace_path.expanduser().resolve()

        def workspace_relative_path(token: object) -> tuple[str, Path] | None:
            """Accept only a path inside this workspace, never a shell fragment."""

            return self._validated_chat_changed_file(
                token,
                workspace_path=workspace_root,
            )

        def path_tokens(line: str) -> list[str]:
            return re.findall(
                r"(?:[ab]/)?(?:[A-Za-z]:[\\/]|/volume1/|/mnt/[A-Za-z]/|\.volume1/|\.agent_control/|agent_control/)[^\s`\"'<>]+",
                line,
            )

        # Only diff-shaped lines are workspace-change evidence. In particular,
        # do not scan arbitrary model prose or command output for path-looking
        # strings: a quoted PowerShell executable is not a changed file.
        diff_lines = [
            line
            for line in text.splitlines()
            if re.search(r"^\s*(?:diff --git|---\s|\+\+\+\s)", line)
            or re.search(r"(?:^|\s)[ab]/[^\s]+\s+->\s+[ab]/", line)
        ]
        for line in diff_lines:
            for token in path_tokens(line):
                resolved_path = workspace_relative_path(token)
                if resolved_path is None:
                    continue
                display_path, _resolved = resolved_path
                if display_path not in seen_files:
                    seen_files.add(display_path)
                    changed_files.append(display_path)

        # Artifact proof may still be attached from an explicitly labelled
        # Artifact/Path line, but that is deliberately separate from
        # filesChanged: merely mentioning a path does not prove a workspace edit.
        artifact_tokens = [
            token
            for line in text.splitlines()
            if re.search(r"^\s*(?:artifact|path|output artifact)\s*:", line, re.I)
            for token in path_tokens(line)
        ]
        for token in artifact_tokens:
            resolved_path = workspace_relative_path(token)
            if resolved_path is None:
                continue
            _display_path, resolved = resolved_path
            if resolved.suffix.lower() not in deps.artifact_content_types:
                continue
            try:
                artifact_path = self._resolve_artifact_path(str(resolved))
            except RuntimeError:
                continue
            artifact_key = str(artifact_path)
            if artifact_key in seen_artifacts:
                continue
            seen_artifacts.add(artifact_key)
            proof_artifacts.append(
                {
                    "kind": "runtime_output_artifact",
                    "path": str(artifact_path),
                    "previewUrl": self._artifact_url(artifact_path),
                    "status": "recorded",
                }
            )
        return changed_files[:20], proof_artifacts[:20]

    def _write_preview_bridge_proof(self, payload: dict[str, Any]) -> dict[str, Any]:
        deps = self._workspace_dependencies()
        mission_id = deps.safe_identifier(
            payload.get("missionId") or payload.get("mission_id") or "preview_program_bridge",
            "preview_program_bridge",
        )
        checked_at = deps.utc_now()
        stamp = re.sub(r"[^0-9]", "", checked_at)[:14] or str(int(time.time()))
        proof_dir = self.root / ".agent_control" / "mission_artifacts" / mission_id / "preview_bridge_proof"
        proof_dir.mkdir(parents=True, exist_ok=True)

        screenshots = payload.get("screenshots") if isinstance(payload.get("screenshots"), dict) else {}
        checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
        folder_browser = payload.get("folderBrowser") if isinstance(payload.get("folderBrowser"), dict) else {}
        all_checks_passed = bool(checks) and all(
            isinstance(item, dict) and bool(item.get("passed"))
            for item in checks
        )
        clicked_count = int(payload.get("clicks") or payload.get("clickCount") or 0)
        proof = {
            "schema": "fluxio.preview_bridge_proof.v1",
            "missionId": mission_id,
            "checkedAt": checked_at,
            "status": "passed" if all_checks_passed else "incomplete",
            "source": str(payload.get("source") or "scripts/verify_workbench_program_bridge.py"),
            "baseUrl": str(payload.get("baseUrl") or ""),
            "backendUrl": str(payload.get("backendUrl") or ""),
            "programUrl": str(payload.get("programUrl") or ""),
            "previewUrl": str(payload.get("previewUrl") or payload.get("programUrl") or ""),
            "reportPath": str(payload.get("reportPath") or ""),
            "screenshots": screenshots,
            "checks": checks,
            "clickProof": {
                "clicks": clicked_count,
                "passed": clicked_count > 0,
            },
            "folderBrowser": folder_browser,
            "proofArtifacts": [],
        }
        proof_path = proof_dir / f"{stamp}_preview_bridge_proof.json"
        tmp_path = proof_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
        tmp_path.replace(proof_path)
        proof_artifact = {
            "kind": "preview_bridge_proof",
            "path": str(proof_path),
            "previewUrl": self._artifact_url(proof_path),
            "status": proof["status"],
        }
        proof["proofArtifacts"] = [proof_artifact]
        proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")

        screenshot_path = str(
            screenshots.get("agentPreviewAfterClick")
            or screenshots.get("previewAfterClick")
            or screenshots.get("agentPreviewWindow")
            or screenshots.get("folderBrowser")
            or ""
        )
        receipt_payload: dict[str, Any]
        try:
            receipt = deps.record_delivery_receipt(
                self.root,
                mission_id=mission_id,
                channel="preview_bridge_verifier",
                destination="control_room",
                event_kind="preview.bridge.proof_attached",
                event_message=(
                    "Preview bridge proof attached: Agent exposed Preview, rendered the local "
                    "program, delivered a mouse click, and opened the folder browser."
                    if all_checks_passed
                    else "Preview bridge proof was recorded but at least one verifier check is incomplete."
                ),
                status="delivered" if all_checks_passed else "error",
                error_message="" if all_checks_passed else "One or more preview bridge checks did not pass.",
                delivery_url=proof_artifact["previewUrl"],
                origin_runtime=str(payload.get("runtime") or "bridge-verifier"),
                origin_provider=str(payload.get("provider") or "local"),
                origin_model=str(payload.get("model") or "cdp"),
                transport_provider="local_http_cdp",
                producer="scripts/verify_workbench_program_bridge.py",
                mission_title=str(payload.get("missionTitle") or "Preview program bridge proof"),
                source_session_id=str(payload.get("sessionId") or mission_id),
                evidence_path=str(proof_path),
                screenshot_path=screenshot_path,
            )
            receipt_payload = asdict(receipt)
        except Exception as exc:  # pragma: no cover - receipt backend can be absent in focused harnesses
            receipt_payload = {
                "status": "error",
                "errorMessage": str(exc),
                "evidencePath": str(proof_path),
                "screenshotPath": screenshot_path,
            }

        return {
            "schema": "fluxio.preview_bridge_attachment.v1",
            "attached": True,
            "missionId": mission_id,
            "proofPath": str(proof_path),
            "proofUrl": proof_artifact["previewUrl"],
            "proofArtifacts": [proof_artifact],
            "receipt": receipt_payload,
            "checksPassed": all_checks_passed,
        }

    def _resolve_workspace_directory(
        self,
        raw_path: object,
        raw_root: object = None,
        root_entries: list[dict[str, Any]] | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        all_root_entries = root_entries if root_entries is not None else self._workspace_root_entries()
        root_entries = [entry for entry in all_root_entries if entry.get("available")]
        if not root_entries:
            raise RuntimeError("No configured workspace roots are available.")

        def resolved_root_path(entry: dict[str, Any]) -> Path:
            return Path(str(entry["path"])).resolve()

        def is_inside_root(path: Path, root: Path) -> bool:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                return False

        requested_root = str(raw_root or "").strip()
        selected_root = root_entries[0]
        if requested_root:
            selected_root = next(
                (
                    entry
                    for entry in root_entries
                    if requested_root
                    in {
                        str(entry.get("id") or ""),
                        str(entry.get("label") or ""),
                        str(entry.get("path") or ""),
                    }
                ),
                None,
            )
            if not selected_root:
                raise RuntimeError(f"Workspace root is not configured or available: {requested_root}")

        requested = str(raw_path or "").strip()
        if not requested:
            target = resolved_root_path(selected_root)
        else:
            target = Path(requested).expanduser()
            if not target.is_absolute():
                target = resolved_root_path(selected_root) / target
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise RuntimeError(f"Could not resolve directory path: {target}") from exc
        if requested_root:
            root_path = resolved_root_path(selected_root)
            if not is_inside_root(resolved, root_path):
                raise RuntimeError(f"Directory is outside configured workspace root: {resolved}")
        else:
            matching_roots = [
                entry
                for entry in sorted(root_entries, key=lambda item: len(str(item.get("path") or "")), reverse=True)
                if is_inside_root(resolved, resolved_root_path(entry))
            ]
            if not matching_roots:
                raise RuntimeError(f"Directory is outside configured workspace roots: {resolved}")
            selected_root = matching_roots[0]
        if not resolved.exists():
            raise RuntimeError(f"Directory does not exist: {resolved}")
        if not resolved.is_dir():
            raise RuntimeError(f"Path is not a directory: {resolved}")
        return resolved, selected_root

    def _list_workspace_directory(self, raw_path: object, raw_root: object = None) -> dict[str, Any]:
        root_entries = self._workspace_root_entries()
        current, selected_root = self._resolve_workspace_directory(raw_path, raw_root, root_entries)
        root_path = Path(str(selected_root["path"])).resolve()
        try:
            parent = current.parent.resolve()
        except OSError:
            parent = current.parent
        parent_path = "" if current == root_path or parent == current else str(parent)
        try:
            parent.relative_to(root_path)
        except ValueError:
            parent_path = ""
        directory_entries: list[dict[str, str | bool | int]] = []
        file_entries: list[dict[str, str | bool | int]] = []
        try:
            children = list(current.iterdir())
        except PermissionError as exc:
            raise RuntimeError(f"Permission denied for directory: {current}") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not list directory: {current}") from exc

        for child in children:
            try:
                resolved = child.resolve()
            except OSError:
                continue
            is_directory = child.is_dir()
            try:
                size = 0 if is_directory else child.stat().st_size
            except OSError:
                size = 0
            entry = {
                "name": child.name,
                "path": str(resolved),
                "isDirectory": is_directory,
                "type": "directory" if is_directory else "file",
                "size": size,
                "root": str(selected_root.get("id") or "local"),
            }
            if entry["isDirectory"]:
                directory_entries.append(entry)
            else:
                file_entries.append(entry)

        directory_entries.sort(key=lambda item: str(item["name"]).lower())
        file_entries.sort(key=lambda item: str(item["name"]).lower())

        return {
            "currentPath": str(current),
            "parentPath": parent_path,
            "root": str(selected_root.get("id") or "local"),
            "rootPath": str(root_path),
            "roots": self._workspace_roots(root_entries),
            "rootEntries": root_entries,
            "entries": [*directory_entries, *file_entries],
        }

    def _search_workspace_directories(
        self,
        raw_query: object,
        raw_path: object = None,
        raw_root: object = None,
        raw_limit: object = None,
        raw_max_depth: object = None,
    ) -> dict[str, Any]:
        query = str(raw_query or "").strip().lower()
        try:
            limit = max(1, min(100, int(raw_limit or 50)))
        except (TypeError, ValueError):
            limit = 50
        try:
            max_depth = max(0, min(8, int(raw_max_depth or 4)))
        except (TypeError, ValueError):
            max_depth = 4
        root_entries = self._workspace_root_entries()
        current, selected_root = self._resolve_workspace_directory(raw_path, raw_root, root_entries)
        root_path = Path(str(selected_root["path"])).resolve()
        root_id = str(selected_root.get("id") or "local")
        root_label = str(selected_root.get("label") or "Workspace root")
        skip_names = {
            "$recycle.bin",
            ".cache",
            ".git",
            ".hg",
            ".idea",
            ".mypy_cache",
            ".next",
            ".pytest_cache",
            ".svn",
            ".venv",
            "__pycache__",
            "appdata",
            "build",
            "coverage",
            "dist",
            "node_modules",
            "program files",
            "program files (x86)",
            "programdata",
            "system volume information",
            "venv",
            "windows",
        }
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        deadline = time.monotonic() + 2.0
        scanned_directories = 0
        max_scanned_directories = 8000

        def add_match(path: Path, depth: int) -> None:
            if len(entries) >= limit:
                return
            normalized = str(path)
            if normalized in seen:
                return
            seen.add(normalized)
            try:
                relative_path = str(path.relative_to(root_path))
            except ValueError:
                relative_path = path.name
            entries.append(
                {
                    "name": path.name or normalized,
                    "path": normalized,
                    "isDirectory": True,
                    "type": "directory",
                    "size": 0,
                    "root": root_id,
                    "rootLabel": root_label,
                    "relativePath": "." if relative_path == "." else relative_path,
                    "depth": depth,
                }
            )

        if query and query in (current.name or str(current)).lower():
            add_match(current, 0)

        stack: list[tuple[Path, int]] = [(current, 0)]
        while query and stack and len(entries) < limit:
            if scanned_directories >= max_scanned_directories or time.monotonic() >= deadline:
                break
            directory, depth = stack.pop()
            scanned_directories += 1
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name.lower(), reverse=True)
            except PermissionError:
                continue
            except OSError:
                continue
            for child in children:
                if len(entries) >= limit:
                    break
                if time.monotonic() >= deadline:
                    break
                child_name = child.name.lower()
                if child_name in skip_names or child_name.startswith("$"):
                    continue
                try:
                    if child.is_symlink() or not child.is_dir():
                        continue
                except OSError:
                    continue
                child_depth = depth + 1
                if query in child_name:
                    add_match(child, child_depth)
                if child_depth < max_depth:
                    stack.append((child, child_depth))

        return {
            "query": query,
            "currentPath": str(current),
            "root": root_id,
            "rootPath": str(root_path),
            "roots": self._workspace_roots(root_entries),
            "rootEntries": root_entries,
            "entries": entries,
            "limit": limit,
            "maxDepth": max_depth,
            "scannedDirectories": scanned_directories,
            "partial": bool(stack and len(entries) < limit),
        }
