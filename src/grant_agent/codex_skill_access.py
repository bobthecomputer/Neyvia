"""On-demand, read-only access to installed Codex skill instructions.

Only skill instruction text and explicitly requested text files inside a skill
directory are exposed. This module does not read AGENTS.md, auth/session state,
plugin runtime code, or arbitrary Codex home files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any


SCHEMA = "neyvia.codex_skill_access.v1"
MAX_TEXT_BYTES = 512 * 1024
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip(".-")[:96] or "skill"


def _frontmatter(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    blocks = text.split("---", 2)
    if len(blocks) < 3:
        return ""
    prefix = key.lower() + ":"
    for line in blocks[1].splitlines():
        value = line.strip()
        if value.lower().startswith(prefix):
            return value[len(prefix):].strip().strip("\"'")
    return ""


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _read_bytes(path: Path, root: Path, *, limit: int = MAX_TEXT_BYTES) -> bytes:
    # Reject symlinks in every component, even when their final target happens
    # to land back inside the root. This keeps the source identity auditable.
    absolute_root = root.absolute()
    absolute_path = path.absolute()
    if not _within(absolute_path, absolute_root):
        raise ValueError("path_outside_allowed_root")
    current = absolute_root
    try:
        if _is_link(current):
            raise ValueError("symlink_not_allowed")
        for part in absolute_path.relative_to(absolute_root).parts:
            current = current / part
            if _is_link(current):
                raise ValueError("symlink_not_allowed")
        resolved_root = absolute_root.resolve(strict=True)
        resolved_path = absolute_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("file_not_found") from exc
    if not _within(resolved_path, resolved_root):
        raise ValueError("path_outside_allowed_root")
    if not resolved_path.is_file():
        raise ValueError("not_a_file")
    size = resolved_path.stat().st_size
    if size > limit:
        raise ValueError("file_too_large")
    return resolved_path.read_bytes()


class CodexSkillAccess:
    """Discover, describe, and read enabled Codex skills without importing them."""

    def __init__(self, codex_home: str | Path | None = None, workspace_root: str | Path | None = None) -> None:
        default_home = os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
        self.codex_home = Path(codex_home or default_home).expanduser().absolute()
        self.workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root else None
        self._catalog: dict[str, dict[str, Any]] | None = None

    def _plugin_states(self) -> dict[str, bool]:
        config_path = self.codex_home / "config.toml"
        try:
            config = tomllib.loads(_read_bytes(config_path, self.codex_home).decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError):
            return {}
        plugins = config.get("plugins") if isinstance(config, dict) else {}
        return {
            str(plugin_id): bool(value.get("enabled"))
            for plugin_id, value in (plugins.items() if isinstance(plugins, dict) else [])
            if isinstance(value, dict) and isinstance(value.get("enabled"), bool)
        }

    def _safe_walk_skill_files(self, declared_root: Path, trust_root: Path):
        """Yield SKILL.md files without traversing any symlinked directory."""
        try:
            if _is_link(declared_root) or not _within(declared_root.absolute(), trust_root.absolute()):
                return
            if not declared_root.is_dir():
                return
            stack = [declared_root]
            while stack:
                directory = stack.pop()
                try:
                    entries = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
                except OSError:
                    continue
                for item in entries:
                    if _is_link(item):
                        continue
                    if ".." in item.relative_to(trust_root).parts:
                        continue
                    if item.is_dir():
                        stack.append(item)
                    elif item.name == "SKILL.md":
                        yield item
        except OSError:
            return

    def _safe_walk_prompt_files(self, declared_root: Path, trust_root: Path):
        try:
            if _is_link(declared_root) or not _within(declared_root.absolute(), trust_root.absolute()):
                return
            if not declared_root.is_dir():
                return
            stack = [declared_root]
            while stack:
                directory = stack.pop()
                try:
                    entries = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
                except OSError:
                    continue
                for item in entries:
                    if _is_link(item) or ".." in item.relative_to(trust_root).parts:
                        continue
                    if item.is_dir():
                        stack.append(item)
                    elif item.suffix.lower() in {".md", ".txt", ".prompt"}:
                        yield item
        except (OSError, ValueError):
            return

    def _row(self, skill_id: str, skill_file: Path, trust_root: Path, origin: str,
             *, plugin_id: str = "", enabled: bool = True) -> dict[str, Any] | None:
        try:
            data = _read_bytes(skill_file, trust_root)
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        name = _frontmatter(text, "name") or skill_file.parent.name
        description = _frontmatter(text, "description")
        if not description:
            body = text.split("---", 2)[-1] if text.startswith("---") else text
            description = next((" ".join(x.strip() for x in block.splitlines() if x.strip())
                                for block in re.split(r"\n\s*\n", body)
                                if block.strip() and not block.lstrip().startswith("#")), "")[:700]
        return {
            "skillId": skill_id,
            "name": name,
            "description": description,
            "origin": origin,
            "pluginId": plugin_id,
            "enabled": enabled,
            "readiness": "ready" if enabled else "disabled",
            "instructionPath": str(skill_file),
            "instructionSha256": _sha256(data),
            "sizeBytes": len(data),
        }

    def _discover_prompts(self, states: dict[str, bool]) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        personal_root = self.codex_home / "prompts"
        for prompt_file in self._safe_walk_prompt_files(personal_root, self.codex_home):
            rel = prompt_file.relative_to(personal_root).as_posix()
            prompt_id = "codex:prompt:" + _slug(rel.rsplit(".", 1)[0])
            row = self._prompt_row(prompt_id, prompt_file, self.codex_home, "codex_personal_prompt")
            if row:
                rows[prompt_id] = row

        cache_root = self.codex_home / "plugins" / "cache"
        if cache_root.is_dir() and not _is_link(cache_root):
            for manifest in sorted(cache_root.rglob("plugin.json")):
                if _is_link(manifest) or not _within(manifest.absolute(), cache_root.absolute()):
                    continue
                try:
                    payload = json.loads(_read_bytes(manifest, cache_root, limit=128 * 1024).decode("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                relative = manifest.relative_to(cache_root)
                marketplace = relative.parts[0] if relative.parts else "unknown"
                plugin_root = manifest.parent.parent
                plugin_name = str(payload.get("name") or plugin_root.parent.name)
                plugin_id = f"{plugin_name}@{marketplace}"
                enabled = states.get(plugin_id, False)
                declared = payload.get("prompts")
                paths = declared if isinstance(declared, list) else [declared]
                for declared_path in paths:
                    if not isinstance(declared_path, str) or not declared_path.strip():
                        continue
                    prompt_root = (plugin_root / declared_path).absolute()
                    if not _within(prompt_root, plugin_root.absolute()):
                        continue
                    for prompt_file in self._safe_walk_prompt_files(prompt_root, plugin_root):
                        rel = prompt_file.relative_to(prompt_root).as_posix()
                        prompt_id = f"codex:plugin-prompt:{plugin_id}:{_slug(rel.rsplit('.', 1)[0])}"
                        row = self._prompt_row(prompt_id, prompt_file, plugin_root, "codex_plugin_prompt",
                                               plugin_id=plugin_id, enabled=enabled)
                        if row:
                            rows[prompt_id] = row
        return [rows[key] for key in sorted(rows)]

    def _prompt_row(self, prompt_id: str, path: Path, trust_root: Path, origin: str,
                    *, plugin_id: str = "", enabled: bool = True) -> dict[str, Any] | None:
        try:
            data = _read_bytes(path, trust_root)
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        return {"promptId": prompt_id, "name": path.stem, "origin": origin,
                "pluginId": plugin_id, "enabled": enabled,
                "readiness": "ready" if enabled else "disabled", "sourcePath": str(path),
                "sha256": _sha256(data), "sizeBytes": len(data)}

    def discover(self, *, include_disabled: bool = True) -> dict[str, Any]:
        rows: dict[str, dict[str, Any]] = {}
        personal_root = self.codex_home / "skills"
        for skill_file in self._safe_walk_skill_files(personal_root, self.codex_home):
            relative_dir = skill_file.parent.relative_to(personal_root).as_posix()
            skill_id = "codex:personal:" + _slug(relative_dir)
            row = self._row(skill_id, skill_file, self.codex_home, "codex_personal")
            if row:
                rows[skill_id] = row

        if self.workspace_root:
            project_skills = self.workspace_root / ".codex" / "skills"
            for skill_file in self._safe_walk_skill_files(project_skills, self.workspace_root):
                relative_dir = skill_file.parent.relative_to(project_skills).as_posix()
                skill_id = "codex:workspace:" + _slug(relative_dir)
                row = self._row(skill_id, skill_file, self.workspace_root, "codex_workspace")
                if row:
                    rows[skill_id] = row

        states = self._plugin_states()
        cache_root = self.codex_home / "plugins" / "cache"
        if cache_root.is_dir() and not _is_link(cache_root):
            for manifest in sorted(cache_root.rglob("plugin.json")):
                # Resolve only the known manifest structure under cache. Never
                # follow a plugin cache symlink or read undeclared prompt paths.
                if _is_link(manifest) or not _within(manifest.absolute(), cache_root.absolute()):
                    continue
                try:
                    manifest_bytes = _read_bytes(manifest, cache_root, limit=128 * 1024)
                    payload = json.loads(manifest_bytes.decode("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                relative = manifest.relative_to(cache_root)
                marketplace = relative.parts[0] if relative.parts else "unknown"
                plugin_root = manifest.parent.parent
                plugin_name = str(payload.get("name") or plugin_root.parent.name)
                plugin_id = f"{plugin_name}@{marketplace}"
                enabled = states.get(plugin_id, False)
                declared = payload.get("skills")
                paths = declared if isinstance(declared, list) else [declared]
                for declared_path in paths:
                    if not isinstance(declared_path, str) or not declared_path.strip():
                        continue
                    skill_dir = (plugin_root / declared_path).absolute()
                    if not _within(skill_dir, plugin_root.absolute()):
                        continue
                    for skill_file in self._safe_walk_skill_files(skill_dir, plugin_root):
                        stable_name = skill_file.parent.relative_to(skill_dir).as_posix()
                        if stable_name == ".":
                            stable_name = skill_file.parent.name
                        skill_id = f"codex:plugin:{plugin_id}:{_slug(stable_name)}"
                        row = self._row(skill_id, skill_file, plugin_root, "codex_plugin", plugin_id=plugin_id, enabled=enabled)
                        if row:
                            rows[skill_id] = row

        result = [rows[key] for key in sorted(rows)]
        prompts = self._discover_prompts(states)
        if not include_disabled:
            result = [row for row in result if row["enabled"]]
            prompts = [row for row in prompts if row["enabled"]]
        self._catalog = {row["skillId"]: row for row in result}
        return {"schema": SCHEMA, "codexHome": str(self.codex_home), "skills": result, "prompts": prompts,
                "counts": {"total": len(result), "enabled": sum(bool(x["enabled"]) for x in result),
                           "disabled": sum(not x["enabled"] for x in result), "prompts": len(prompts)}}

    def describe(self, skill_id: str) -> dict[str, Any]:
        catalog = self.discover(include_disabled=True)
        row = next((item for item in catalog["skills"] if item["skillId"] == skill_id), None)
        if row is None:
            raise KeyError("skill_not_found")
        return {"schema": SCHEMA, **row}

    def read(self, skill_id: str, relative_path: str = "SKILL.md") -> dict[str, Any]:
        info = self.describe(skill_id)
        if not info["enabled"]:
            raise PermissionError("plugin_disabled")
        requested = Path(relative_path)
        if requested.is_absolute() or not relative_path or any(part in {"..", ""} for part in requested.parts):
            raise ValueError("invalid_skill_relative_path")
        if requested.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError("unsupported_text_file_type")
        instruction = Path(info["instructionPath"])
        skill_root = instruction.parent
        target = skill_root.joinpath(*requested.parts)
        data = _read_bytes(target, skill_root)
        text = data.decode("utf-8")
        return {"schema": SCHEMA, "skillId": skill_id, "origin": info["origin"],
                "pluginId": info["pluginId"], "relativePath": requested.as_posix(),
                "sha256": _sha256(data), "sizeBytes": len(data), "text": text}

    def read_prompt(self, prompt_id: str) -> dict[str, Any]:
        catalog = self.discover(include_disabled=True)
        info = next((item for item in catalog["prompts"] if item["promptId"] == prompt_id), None)
        if info is None:
            raise KeyError("prompt_not_found")
        if not info["enabled"]:
            raise PermissionError("plugin_disabled")
        prompt_path = Path(info["sourcePath"])
        root = self.codex_home if info["origin"] == "codex_personal_prompt" else self.codex_home / "plugins" / "cache"
        data = _read_bytes(prompt_path, root)
        return {"schema": SCHEMA, "promptId": prompt_id, "origin": info["origin"],
                "pluginId": info["pluginId"], "sha256": _sha256(data), "sizeBytes": len(data),
                "text": data.decode("utf-8")}


def discover_codex_skills(codex_home: str | Path | None = None, *, workspace_root: str | Path | None = None,
                          include_disabled: bool = True) -> dict[str, Any]:
    return CodexSkillAccess(codex_home, workspace_root).discover(include_disabled=include_disabled)


def describe_codex_skill(skill_id: str, codex_home: str | Path | None = None, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    return CodexSkillAccess(codex_home, workspace_root).describe(skill_id)


def read_codex_skill(skill_id: str, relative_path: str = "SKILL.md", codex_home: str | Path | None = None,
                     *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    return CodexSkillAccess(codex_home, workspace_root).read(skill_id, relative_path)


def discover_codex_assets(codex_home: str | Path | None = None, *, workspace_root: str | Path | None = None,
                          include_disabled: bool = True) -> dict[str, Any]:
    """Discover installed skills and reusable prompts without returning their contents."""
    return CodexSkillAccess(codex_home, workspace_root).discover(include_disabled=include_disabled)


def read_codex_prompt(prompt_id: str, codex_home: str | Path | None = None, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    return CodexSkillAccess(codex_home, workspace_root).read_prompt(prompt_id)
