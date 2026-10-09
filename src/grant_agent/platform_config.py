from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_NAS_VOLUME_ROOT = "/volume1/Saclay"
DEFAULT_NAS_PROJECT_NAME = "vibe-coding-platform"
DEFAULT_WINDOWS_NAS_VOLUME_MIRROR = "C:/volume1/Saclay"


def _clean_path_text(value: object) -> str:
    return str(value or "").strip().replace("\x00", "")


def _path_from_env(name: str, fallback: str | Path) -> Path:
    return Path(os.environ.get(name, str(fallback)) or str(fallback)).expanduser()


def _path_key(path: Path) -> str:
    return str(path).replace("\\", "/").rstrip("/").lower()


@dataclass(frozen=True)
class PlatformConfig:
    workspace_root: Path
    nas_volume_root: Path = field(default_factory=lambda: Path(DEFAULT_NAS_VOLUME_ROOT))
    nas_project_name: str = DEFAULT_NAS_PROJECT_NAME
    windows_nas_volume_mirror: Path = field(
        default_factory=lambda: Path(DEFAULT_WINDOWS_NAS_VOLUME_MIRROR)
    )

    @classmethod
    def from_env(cls, root: str | Path | None = None) -> "PlatformConfig":
        workspace_root = Path(root or os.environ.get("FLUXIO_WORKSPACE_ROOT") or ".").expanduser()
        nas_volume = _path_from_env("FLUXIO_NAS_VOLUME_ROOT", DEFAULT_NAS_VOLUME_ROOT)
        project_name = os.environ.get("FLUXIO_NAS_PROJECT_NAME", DEFAULT_NAS_PROJECT_NAME).strip()
        if not project_name:
            project_name = DEFAULT_NAS_PROJECT_NAME
        windows_mirror = _path_from_env(
            "FLUXIO_WINDOWS_NAS_VOLUME_MIRROR",
            DEFAULT_WINDOWS_NAS_VOLUME_MIRROR,
        )
        return cls(
            workspace_root=workspace_root,
            nas_volume_root=nas_volume,
            nas_project_name=project_name,
            windows_nas_volume_mirror=windows_mirror,
        )

    @property
    def nas_projects_root(self) -> Path:
        return self.nas_volume_root / "projects"

    @property
    def nas_project_root(self) -> Path:
        return self.nas_projects_root / self.nas_project_name

    @property
    def windows_nas_projects_root(self) -> Path:
        return self.windows_nas_volume_mirror / "projects"

    @property
    def windows_nas_project_root(self) -> Path:
        return self.windows_nas_projects_root / self.nas_project_name

    def coerce_path(self, value: str | Path, *, posix: bool | None = None) -> Path:
        raw = _clean_path_text(value)
        is_posix = os.name != "nt" if posix is None else posix
        if is_posix and len(raw) >= 3:
            drive_index = -1
            for index in range(len(raw) - 2):
                if raw[index].isalpha() and raw[index + 1 : index + 3] in {":\\", ":/"}:
                    drive_index = index
            if drive_index >= 0:
                drive = raw[drive_index].lower()
                tail = raw[drive_index + 3 :].replace("\\", "/").lstrip("/")
                return Path("/mnt") / drive / tail
        return Path(raw).expanduser()

    def windows_drive_to_posix_mount(self, raw_path: object, *, posix: bool | None = None) -> Path:
        value = _clean_path_text(raw_path)
        match = re.match(r"^([A-Za-z]):[\\/](.*)$", value)
        if not match:
            return Path(value)
        is_posix = os.name != "nt" if posix is None else posix
        if not is_posix:
            return Path(value)
        drive = match.group(1).lower()
        rest = match.group(2).replace("\\", "/").lstrip("/")
        return Path(f"/mnt/{drive}/{rest}")

    def path_candidates(self, value: object) -> list[Path]:
        raw = _clean_path_text(value)
        if not raw:
            return []
        normalized = raw.replace("\\", "/")
        candidates: list[Path] = [self.coerce_path(raw)]

        if re.match(r"^[A-Za-z]:[\\/]", raw):
            candidates.append(self.windows_drive_to_posix_mount(raw))

        for embedded in re.findall(r"([A-Za-z]:[\\/][^\r\n]+)", raw):
            candidates.append(self.windows_drive_to_posix_mount(embedded))
        for embedded in re.findall(r"([A-Za-z]:/[^\r\n]+)", normalized):
            candidates.append(self.windows_drive_to_posix_mount(embedded))

        candidates.extend(self._nas_mirror_candidates(normalized))
        candidates.extend(self._workspace_relative_candidates(normalized))
        return dedupe_paths(candidates)

    def control_search_roots(self, *subdirs: str) -> list[Path]:
        names = [item.strip("/\\") for item in subdirs if str(item or "").strip("/\\")]
        if not names:
            names = [
                ".agent_control/runtime_sessions",
                ".agent_control/mission_async",
                ".agent_runs",
            ]
        base_roots = [
            self.workspace_root,
            self.nas_project_root,
            self.windows_nas_project_root,
        ]
        roots: list[Path] = []
        for base in base_roots:
            for name in names:
                roots.append(base / Path(name))
        return dedupe_paths(roots)

    def _nas_mirror_candidates(self, normalized: str) -> list[Path]:
        candidates: list[Path] = []
        nas_volume = _path_key(self.nas_volume_root)
        windows_volume = _path_key(self.windows_nas_volume_mirror)
        normalized_key = normalized.rstrip("/").lower()

        if normalized_key == nas_volume or normalized_key.startswith(f"{nas_volume}/"):
            relative = normalized[len(str(self.nas_volume_root).replace("\\", "/")) :].lstrip("/")
            candidates.append(self.windows_nas_volume_mirror / relative)
            if os.name != "nt":
                candidates.append(Path("/mnt/c") / str(self.nas_volume_root).lstrip("/") / relative)
        if normalized_key == windows_volume or normalized_key.startswith(f"{windows_volume}/"):
            relative = normalized[len(str(self.windows_nas_volume_mirror).replace("\\", "/")) :].lstrip("/")
            candidates.append(self.nas_volume_root / relative)
        return candidates

    def _workspace_relative_candidates(self, normalized: str) -> list[Path]:
        candidates: list[Path] = []
        for remote_root in (self.nas_project_root, self.windows_nas_project_root):
            root_text = str(remote_root).replace("\\", "/").rstrip("/")
            if normalized == root_text or normalized.startswith(f"{root_text}/"):
                relative = normalized[len(root_text) :].lstrip("/")
                candidates.append(self.workspace_root / relative)
        return candidates


def dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = _path_key(path)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def platform_config(root: str | Path | None = None) -> PlatformConfig:
    return PlatformConfig.from_env(root)


from .proofs_d_runtime import checked as _checked
PlatformConfig.from_env = classmethod(_checked("d.runtime.platform.roots", PlatformConfig.from_env.__func__))
PlatformConfig.path_candidates = _checked("d.runtime.platform.candidates", PlatformConfig.path_candidates)
PlatformConfig.coerce_path = _checked("d.runtime.platform.coerce", PlatformConfig.coerce_path)
