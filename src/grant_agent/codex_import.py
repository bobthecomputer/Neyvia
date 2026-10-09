from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import tomllib
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .proofs_a_cli import checked


CODEX_IMPORT_SCHEMA = "neyvia.codex_import_catalog.v1"
CODEX_IMPORT_RECEIPT_SCHEMA = "neyvia.codex_import_receipt.v1"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SKILL_BYTES = 24 * 1024 * 1024
SAFE_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".sh",
    ".ps1",
    ".html",
    ".css",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}
SENSITIVE_NAME_PARTS = {
    "auth",
    "credential",
    "secret",
    "token",
    "private-key",
    "id_rsa",
    ".env",
}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|gho|xoxb|xoxp|xoxa|xoxr)-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+-]{24,}"),
]

_POINTER_LOCKS: dict[str, threading.RLock] = {}
_POINTER_LOCKS_GUARD = threading.Lock()


@contextmanager
def _latest_pointer_guard(path: Path):
    """Serialize latest publication and pointer reads across threads/processes."""
    from .harness_jobs import _exclusive_job_lock
    path.parent.mkdir(parents=True, exist_ok=True)
    with _POINTER_LOCKS_GUARD:
        lock = _POINTER_LOCKS.setdefault(str(path.resolve()), threading.RLock())
    with lock, _exclusive_job_lock(path):
        yield


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value).strip()).strip(".-")
    return cleaned[:120] or "asset"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    prefix = f"{key}:"
    for line in parts[1].splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix.lower()):
            return stripped[len(prefix) :].strip().strip("\"'")
    return ""


def _skill_metadata(skill_path: Path) -> dict[str, Any]:
    try:
        text = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {
            "name": skill_path.parent.name,
            "description": "",
            "readError": True,
        }
    description = _frontmatter_value(text, "description")
    if not description:
        body = text.split("---", 2)[-1] if text.startswith("---") else text
        for block in re.split(r"\n\s*\n", body):
            cleaned = " ".join(line.strip() for line in block.splitlines() if line.strip())
            if cleaned and not cleaned.startswith("#"):
                description = cleaned[:600]
                break
    return {
        "name": _frontmatter_value(text, "name") or skill_path.parent.name,
        "description": description[:1000],
        "sha256": _sha256_bytes(text.encode("utf-8")),
        "sizeBytes": len(text.encode("utf-8")),
        "readError": False,
    }


class CodexAssetImporter:
    def __init__(
        self,
        workspace_root: str | Path,
        codex_home: str | Path | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.codex_home = Path(codex_home or (Path.home() / ".codex")).expanduser().resolve()
        self.import_root = self.workspace_root / ".agent_control" / "imports" / "codex"

    def _config(self) -> dict[str, Any]:
        path = self.codex_home / "config.toml"
        if not path.exists():
            return {}
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


    @checked('a-cli.assets.config')
    def _safe_config(self, config: dict[str, Any]) -> dict[str, Any]:
        root_allowlist = {
            "model",
            "model_reasoning_effort",
            "personality",
            "approval_policy",
            "sandbox_mode",
            "service_tier",
        }
        safe = {key: config[key] for key in root_allowlist if key in config}
        desktop = config.get("desktop") if isinstance(config.get("desktop"), dict) else {}
        safe["desktop"] = {
            key: desktop[key]
            for key in (
                "followUpQueueMode",
                "keepRemoteControlAwakeWhilePluggedIn",
                "enabled-reasoning-efforts",
            )
            if key in desktop
        }
        features = config.get("features") if isinstance(config.get("features"), dict) else {}
        safe["features"] = {
            str(key): bool(value) for key, value in features.items() if isinstance(value, bool)
        }
        plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
        safe["plugins"] = {
            str(key): {"enabled": bool(value.get("enabled"))}
            for key, value in plugins.items()
            if isinstance(value, dict) and isinstance(value.get("enabled"), bool)
        }
        marketplaces = config.get("marketplaces") if isinstance(config.get("marketplaces"), dict) else {}
        safe["marketplaces"] = {
            str(key): {
                "sourceType": str(value.get("source_type") or ""),
                "configured": True,
            }
            for key, value in marketplaces.items()
            if isinstance(value, dict)
        }
        mcp = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}
        safe["mcpServers"] = [
            {
                "name": str(name),
                "configured": True,
                "hasEnvironment": bool(isinstance(value, dict) and value.get("env")),
            }
            for name, value in sorted(mcp.items())
        ]
        safe["projectCount"] = len(config.get("projects") or {}) if isinstance(config.get("projects"), dict) else 0
        return safe

    def _standalone_skills(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        root = self.codex_home / "skills"
        personal: list[dict[str, Any]] = []
        system: list[dict[str, Any]] = []
        if not root.exists():
            return personal, system
        for skill_path in sorted(root.rglob("SKILL.md")):
            try:
                relative = skill_path.relative_to(root)
            except ValueError:
                continue
            metadata = _skill_metadata(skill_path)
            row = {
                "skillId": _slug(str(relative.parent).replace("\\", "/")),
                "relativePath": str(relative).replace("\\", "/"),
                "sourcePath": str(skill_path),
                **metadata,
            }
            if relative.parts and relative.parts[0].startswith("."):
                row["scope"] = "system"
                row["importEligible"] = False
                system.append(row)
            else:
                row["scope"] = "personal"
                row["importEligible"] = not metadata.get("readError", False)
                personal.append(row)
        return personal, system

    def _plugin_rows(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        cache_root = self.codex_home / "plugins" / "cache"
        if not cache_root.exists():
            return []
        plugin_config = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
        candidates: dict[str, tuple[float, dict[str, Any]]] = {}
        for manifest_path in cache_root.rglob("plugin.json"):
            if "plugin-backup-" in str(manifest_path).lower():
                continue
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            try:
                relative = manifest_path.relative_to(cache_root)
            except ValueError:
                continue
            marketplace = relative.parts[0] if relative.parts else "unknown"
            plugin_name = str(payload.get("name") or manifest_path.parent.parent.name)
            plugin_id = f"{plugin_name}@{marketplace}"
            configured = plugin_config.get(plugin_id) if isinstance(plugin_config, dict) else None
            skill_rows: list[dict[str, Any]] = []
            plugin_root = manifest_path.parent.parent
            for skill_path in sorted(plugin_root.rglob("SKILL.md")):
                metadata = _skill_metadata(skill_path)
                skill_rows.append(
                    {
                        "skillId": f"plugin:{plugin_id}:{_slug(skill_path.parent.name)}",
                        "name": metadata["name"],
                        "description": metadata["description"],
                        "sourcePath": str(skill_path),
                        "sha256": metadata.get("sha256", ""),
                        "loadMode": "codex-plugin-linked",
                        "adapterRequired": True,
                    }
                )
            row = {
                "pluginId": plugin_id,
                "name": plugin_name,
                "version": str(payload.get("version") or ""),
                "description": str(payload.get("description") or "")[:1200],
                "marketplace": marketplace,
                "enabled": bool(isinstance(configured, dict) and configured.get("enabled")),
                "manifestPath": str(manifest_path),
                "manifestSha256": _sha256_file(manifest_path),
                "hasApps": bool(payload.get("apps")),
                "hasMcpServers": bool(payload.get("mcpServers")),
                "hasSkills": bool(payload.get("skills") or skill_rows),
                "bundledContentVariant": str(payload.get("bundledContentVariant") or ""),
                "skillCount": len(skill_rows),
                "skills": skill_rows,
                "activation": "codex_linked",
                "nativeInNeyvia": False,
            }
            modified = manifest_path.stat().st_mtime
            previous = candidates.get(plugin_id)
            if previous is None or modified > previous[0]:
                candidates[plugin_id] = (modified, row)
        return [item[1] for item in sorted(candidates.values(), key=lambda row: row[1]["pluginId"])]

    @checked('a-cli.assets.audit')
    def audit(self) -> dict[str, Any]:
        config = self._config()
        personal_skills, system_skills = self._standalone_skills()
        plugins = self._plugin_rows(config)
        global_agents = self.codex_home / "AGENTS.md"
        sessions_root = self.codex_home / "sessions"
        memories_root = self.codex_home / "memories"
        automations_root = self.codex_home / "automations"
        return {
            "schema": CODEX_IMPORT_SCHEMA,
            "mode": "audit",
            "generatedAt": _now(),
            "codexHome": str(self.codex_home),
            "available": self.codex_home.exists(),
            "personalSkills": personal_skills,
            "systemSkills": system_skills,
            "plugins": plugins,
            "safeConfig": self._safe_config(config),
            "globalInstructions": {
                "present": global_agents.exists(),
                "path": str(global_agents) if global_agents.exists() else "",
                "sha256": _sha256_file(global_agents) if global_agents.exists() else "",
                "sizeBytes": global_agents.stat().st_size if global_agents.exists() else 0,
            },
            "privateStateInventory": {
                "sessionFiles": sum(1 for _ in sessions_root.rglob("*")) if sessions_root.exists() else 0,
                "memoryFiles": sum(1 for _ in memories_root.rglob("*")) if memories_root.exists() else 0,
                "automationFiles": sum(1 for _ in automations_root.rglob("*")) if automations_root.exists() else 0,
                "contentImported": False,
            },
            "excludedByPolicy": [
                "auth.json and all credential or secret files",
                "MCP environment values and command arguments",
                "raw sessions, logs, SQLite databases, and transcription history",
                "plugin executables, hooks, and cached dependency trees",
                "system skills owned by the Codex installation",
            ],
            "counts": {
                "personalSkills": len(personal_skills),
                "systemSkills": len(system_skills),
                "plugins": len(plugins),
                "enabledPlugins": sum(1 for item in plugins if item["enabled"]),
                "pluginSkills": sum(int(item["skillCount"]) for item in plugins),
                "mcpServers": len(self._safe_config(config).get("mcpServers", [])),
            },
        }

    def _safe_skill_files(self, skill_root: Path) -> tuple[list[Path], list[dict[str, str]]]:
        accepted: list[Path] = []
        skipped: list[dict[str, str]] = []
        total_bytes = 0
        for path in sorted(skill_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(skill_root)
            lower_name = str(relative).replace("\\", "/").lower()
            if path.is_symlink():
                skipped.append({"path": str(relative), "reason": "symlink"})
                continue
            if any(part in lower_name for part in SENSITIVE_NAME_PARTS):
                skipped.append({"path": str(relative), "reason": "sensitive_filename"})
                continue
            if path.suffix.lower() not in SAFE_EXTENSIONS:
                skipped.append({"path": str(relative), "reason": "unsupported_extension"})
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES or total_bytes + size > MAX_SKILL_BYTES:
                skipped.append({"path": str(relative), "reason": "size_limit"})
                continue
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    skipped.append({"path": str(relative), "reason": "not_utf8"})
                    continue
                if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                    skipped.append({"path": str(relative), "reason": "possible_secret"})
                    continue
            total_bytes += size
            accepted.append(path)
        return accepted, skipped

    @checked('a-cli.assets.import')
    def import_assets(self) -> dict[str, Any]:
        audit = self.audit()
        snapshot_root = self.import_root / f"snapshot-{_stamp()}-{uuid.uuid4().hex[:6]}"
        skills_root = snapshot_root / "skills"
        snapshot_root.mkdir(parents=True, exist_ok=False)
        imported_skills: list[dict[str, Any]] = []
        skipped_files: list[dict[str, str]] = []
        for skill in audit["personalSkills"]:
            source_file = Path(str(skill["sourcePath"]))
            source_root = source_file.parent
            destination_root = skills_root / _slug(str(skill["skillId"]))
            files, skipped = self._safe_skill_files(source_root)
            skipped_files.extend(
                {
                    "skillId": str(skill["skillId"]),
                    "path": item["path"],
                    "reason": item["reason"],
                }
                for item in skipped
            )
            for source in files:
                relative = source.relative_to(source_root)
                destination = destination_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            imported_skill_path = destination_root / "SKILL.md"
            if not imported_skill_path.exists():
                continue
            imported_skills.append(
                {
                    "skillId": f"codex-import:{skill['skillId']}",
                    "label": str(skill["name"]),
                    "description": str(skill["description"]),
                    "promptHint": str(skill["description"]),
                    "originType": "codex_import",
                    "editableStatus": "review_required",
                    "testStatus": "untested",
                    "promotionState": "imported",
                    "enabled": False,
                    "source": {
                        "kind": "codex_import",
                        "label": "Imported Codex skill",
                        "path": str(imported_skill_path),
                        "originalPath": str(source_file),
                        "sha256": str(skill.get("sha256") or ""),
                    },
                    "usableByHarnesses": ["fluxio_hybrid", "codex"],
                    "compatibleHarnesses": ["fluxio_hybrid", "codex"],
                    "harnessCompatibility": {
                        "schema": "fluxio.skill_harness_compatibility.v1",
                        "source": "codex-import",
                        "crossHarness": False,
                        "adapterRequired": True,
                        "notes": "Imported disabled. Review tool and runtime dependencies before enabling outside Codex.",
                    },
                    "runtimeHints": {
                        "skillFile": str(imported_skill_path),
                        "loadMode": "progressive-skill-md",
                    },
                    "tags": ["codex-import", "review-required", "progressive-disclosure"],
                }
            )

        global_instruction_copy = ""
        global_instruction = Path(str(audit["globalInstructions"].get("path") or ""))
        if global_instruction.exists() and global_instruction.stat().st_size <= MAX_FILE_BYTES:
            target = snapshot_root / "instructions" / "AGENTS.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(global_instruction, target)
            global_instruction_copy = str(target)

        linked_plugin_skills: list[dict[str, Any]] = []
        for plugin in audit["plugins"]:
            for skill in plugin.get("skills", []):
                linked_plugin_skills.append(
                    {
                        "skillId": str(skill["skillId"]),
                        "label": str(skill["name"]),
                        "description": str(skill["description"]),
                        "promptHint": str(skill["description"]),
                        "originType": "codex_plugin_link",
                        "editableStatus": "linked_read_only",
                        "testStatus": "runtime_required",
                        "promotionState": "linked",
                        "enabled": bool(plugin["enabled"]),
                        "source": {
                            "kind": "codex_plugin",
                            "label": f"Codex plugin: {plugin['name']}",
                            "path": str(skill["sourcePath"]),
                            "pluginId": str(plugin["pluginId"]),
                        },
                        "usableByHarnesses": ["codex"],
                        "compatibleHarnesses": ["codex"],
                        "harnessCompatibility": {
                            "schema": "fluxio.skill_harness_compatibility.v1",
                            "source": "codex-plugin",
                            "crossHarness": False,
                            "adapterRequired": True,
                            "notes": "Capability remains linked to Codex until Neyvia has an equivalent callable app or MCP adapter.",
                        },
                        "runtimeHints": {
                            "skillFile": str(skill["sourcePath"]),
                            "loadMode": "codex-plugin-linked",
                            "pluginId": str(plugin["pluginId"]),
                        },
                        "tags": ["codex-plugin", "linked", "adapter-required"],
                    }
                )

        catalog = {
            **audit,
            "mode": "import",
            "snapshotRoot": str(snapshot_root),
            "importedSkills": imported_skills,
            "linkedPluginSkills": linked_plugin_skills,
            "globalInstructionCopy": global_instruction_copy,
            "skippedFiles": skipped_files,
            "activationPolicy": {
                "personalSkills": "disabled_until_reviewed",
                "pluginSkills": "codex_linked_only",
                "plugins": "metadata_only_no_executables_copied",
                "secrets": "never_imported",
            },
        }
        catalog_path = snapshot_root / "catalog.json"
        _atomic_json(catalog_path, catalog)
        catalog_hash = _sha256_file(catalog_path)
        latest = {
            "schema": "neyvia.codex_import_pointer.v1",
            "catalogPath": str(catalog_path),
            "catalogSha256": catalog_hash,
            "updatedAt": _now(),
        }
        from .durability import atomic_write_json
        pointer_path = self.import_root / "latest.json"
        with _latest_pointer_guard(pointer_path):
            for attempt in range(8):
                try:
                    atomic_write_json(pointer_path, latest)
                    break
                except PermissionError as error:
                    # Windows indexers/read handles can temporarily deny the
                    # replacement even while our own callers hold the lease.
                    if os.name != "nt" or error.winerror not in {5, 32} or attempt == 7:
                        raise
                    time.sleep(0.025 * (attempt + 1))
        receipt = {
            "schema": CODEX_IMPORT_RECEIPT_SCHEMA,
            "status": "completed",
            "catalogPath": str(catalog_path),
            "catalogSha256": catalog_hash,
            "snapshotRoot": str(snapshot_root),
            "importedSkillCount": len(imported_skills),
            "linkedPluginSkillCount": len(linked_plugin_skills),
            "pluginCount": len(audit["plugins"]),
            "skippedFileCount": len(skipped_files),
            "secretsImported": False,
            "rawSessionsImported": False,
            "createdAt": _now(),
        }
        _atomic_json(snapshot_root / "import-receipt.json", receipt)
        return receipt


def load_latest_codex_import_rows(control_dir: Path) -> list[dict[str, Any]]:
    pointer_path = control_dir / "imports" / "codex" / "latest.json"
    if not pointer_path.exists():
        return []
    try:
        with _latest_pointer_guard(pointer_path):
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        catalog_path = Path(str(pointer.get("catalogPath") or "")).expanduser().resolve()
        expected_hash = str(pointer.get("catalogSha256") or "")
        if not catalog_path.exists() or (expected_hash and _sha256_file(catalog_path) != expected_hash):
            return []
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    rows = [
        *list(catalog.get("importedSkills") or []),
        *list(catalog.get("linkedPluginSkills") or []),
    ]
    return [item for item in rows if isinstance(item, dict)]
