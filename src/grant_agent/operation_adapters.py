"""Trusted local postcondition adapters for operations with inspectable state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .skill_iteration import resolve_codex_skill_file


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in text):
        raise ValueError("applicationId must be a safe identifier")
    return text


class ApplicationRegisterAdapter:
    tool_id = "semantic.application.register"

    def __init__(self, root: str | Path, arguments: dict[str, Any]):
        self.root = Path(root).resolve()
        self.arguments = dict(arguments)
        self.application_id = _safe_id(arguments.get("applicationId"))
        base = (self.root / ".agent_control" / "living_applications").resolve()
        self.path = (base / f"{self.application_id}.json").resolve()
        self.path.relative_to(base)

    def before(self) -> dict[str, Any]:
        return {"path": str(self.path), "exists": self.path.exists(), "applicationId": self.application_id}

    def after(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"path": str(self.path), "exists": False, "fresh": True}
        raw = self.path.read_bytes()
        return {"path": str(self.path), "exists": True, "fresh": True,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "application": json.loads(raw.decode("utf-8"))}

    def verify(self, context: dict[str, Any]) -> dict[str, Any]:
        before = context.get("before") or {}
        after = context.get("after") or {}
        if before.get("exists") or not after.get("exists"):
            return {"verified": False, "reason": "application was not a fresh creation"}
        app = after.get("application") or {}
        expected = {"applicationId": self.application_id,
                    "source": dict(self.arguments.get("source") or {}),
                    "buildRecipe": dict(self.arguments.get("buildRecipe") or {})}
        actual = {key: app.get(key) for key in expected}
        return {"verified": actual == expected and bool(after.get("sha256")),
                "sha256": after.get("sha256"), "expected": expected, "actual": actual}


class WorkspaceWriteAdapter:
    """Verify a workspace file write by observing its persisted bytes."""
    tool_id = "workspace.write"

    def __init__(self, root: str | Path, arguments: dict[str, Any]):
        self.root = Path(root).resolve()
        self.arguments = dict(arguments)
        requested = Path(str(arguments.get("path") or "")).expanduser()
        if not str(arguments.get("path") or "").strip():
            raise ValueError("workspace.write requires a non-empty path")
        candidate = requested if requested.is_absolute() else self.root / requested
        self.path = candidate.resolve(strict=False)
        self.relative = self.path.relative_to(self.root).as_posix()
        self.expected_before = str(arguments.get("expectedSha256") or "").strip().lower()
        self.expected_after = hashlib.sha256(str(arguments.get("content") or "").encode("utf-8")).hexdigest()

    def before(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"path": self.relative, "exists": False}
        raw = self.path.read_bytes()
        return {"path": self.relative, "exists": True,
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def after(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"path": self.relative, "exists": False}
        raw = self.path.read_bytes()
        return {"path": self.relative, "exists": True,
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def verify(self, context: dict[str, Any]) -> dict[str, Any]:
        before = context.get("before") or {}
        after = context.get("after") or {}
        expected_before_ok = (before.get("exists") and before.get("sha256") == self.expected_before
                              if self.expected_before else not before.get("exists"))
        verified = (bool(expected_before_ok) and bool(after.get("exists"))
                    and after.get("sha256") == self.expected_after)
        return {"verified": verified, "path": self.relative,
                "sha256": after.get("sha256"), "expectedSha256": self.expected_after,
                "expectedBeforeSha256": self.expected_before or None}


def adapter_for(root: str | Path, tool_id: str, arguments: dict[str, Any]) -> ApplicationRegisterAdapter | None:
    if tool_id in {"neyvia.scene.improve","neyvia.scene.episode","neyvia.laya.glance_learn","neyvia.laya.glance_lesson"}:
        from .scene_core import OperationAdapter
        return OperationAdapter(root,tool_id,arguments)
    if tool_id == "workspace.patch":
        try:
            from .workspace_patches import patched_text
            adapter = WorkspaceWriteAdapter(root, arguments)
            raw = adapter.path.read_bytes()
            content = patched_text(raw.decode("utf-8", errors="strict"), arguments["edits"])
            adapter.expected_after = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return adapter
        except (OSError, RuntimeError, ValueError):
            return None
    if tool_id in {"neyvia.image.crop", "neyvia.image.resize", "neyvia.image.composite"}:
        from .neyvia_image_verification import ImageEditAdapter
        return ImageEditAdapter(root, tool_id, arguments)
    if tool_id == WorkspaceWriteAdapter.tool_id:
        try:
            return WorkspaceWriteAdapter(root, arguments)
        except (OSError, RuntimeError, ValueError):
            # Invalid paths remain unverifiable; the native handler returns the
            # authoritative policy and filesystem error without any write.
            return None
    if tool_id in {"work.focus", "work.problem", "work.constraint", "work.update_problem"}:
        return WorkStateAdapter(root, tool_id, arguments)
    if tool_id == ApplicationRegisterAdapter.tool_id:
        return ApplicationRegisterAdapter(root, arguments)
    if tool_id == "skill.live.iterate":
        try:
            return SkillLiveIterateAdapter(root, arguments)
        except (OSError, RuntimeError, ValueError):
            # Invalid or outside-boundary paths remain explicitly unverifiable;
            # the native handler will produce the truthful failure receipt.
            return None
    return None


class WorkStateAdapter:
    """Prove the persisted record change, without judging the reported claim."""
    def __init__(self, root, tool_id, arguments):
        self.root=Path(root).resolve()
        self.tool_id=tool_id
        self.arguments=arguments
        self.identity=_safe_id(arguments.get("workId"))
        self.path=self.root/".agent_control"/"adaptive_work"/f"{self.identity}.json"
        self.path.resolve().relative_to((self.root/".agent_control"/"adaptive_work").resolve())

    def before(self):
        if not self.path.exists(): return {"revision":0,"problems":[],"constraints":[]}
        from .adaptive_work import AdaptiveWorkStore
        return AdaptiveWorkStore(self.root,self.identity).snapshot()

    def after(self):
        from .adaptive_work import AdaptiveWorkStore
        state=AdaptiveWorkStore(self.root,self.identity).snapshot()
        return {**state,"fileSha256":hashlib.sha256(self.path.read_bytes()).hexdigest()}

    def verify(self, context):
        before=context.get("before") or {}
        after=context.get("after") or {}
        verified=after.get("revision")==before.get("revision",0)+1
        if self.tool_id=="work.focus":
            verified=verified and (after.get("focus") or {}).get("text")==str(self.arguments["text"]).strip()
        elif self.tool_id in {"work.problem","work.constraint"}:
            key="problems" if self.tool_id=="work.problem" else "constraints"
            old=before.get(key) or []; new=after.get(key) or []
            verified=verified and len(new)==len(old)+1 and new[:-1]==old and new[-1].get("text")==str(self.arguments["text"]).strip()
        else:
            row=next((row for row in after.get("problems",[]) if row.get("id")==self.arguments["problemId"]),{})
            verified=verified and row.get("status")==self.arguments["status"] and row.get("need")==self.arguments["need"]
        return {"verified":bool(verified),"claim":"Requested working-state record persisted","sha256":after.get("fileSha256"),"workId":self.identity}


class SkillLiveIterateAdapter:
    tool_id = "skill.live.iterate"

    def __init__(self, root: str | Path, arguments: dict[str, Any]):
        self.root = Path(root).resolve()
        self.arguments = dict(arguments)
        _, self.path = resolve_codex_skill_file(arguments)
        self.path = self.path.resolve()

    def before(self) -> dict[str, Any]:
        raw = self.path.read_bytes()
        return {"path": str(self.path), "exists": True,
                "sha256": hashlib.sha256(raw).hexdigest()}

    def after(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"path": str(self.path), "exists": False}
        raw = self.path.read_bytes()
        return {"path": str(self.path), "exists": True,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "content": raw.decode("utf-8")}

    def verify(self, context: dict[str, Any]) -> dict[str, Any]:
        after = context.get("after") or {}
        expected = str(self.arguments.get("content") or self.arguments.get("instructions") or self.arguments.get("body") or "").replace("\r\n", "\n").strip() + "\n"
        expected_hash = hashlib.sha256(expected.encode("utf-8")).hexdigest()
        return {"verified": bool(after.get("exists")) and str(after.get("content") or "").replace("\r\n", "\n") == expected,
                "sha256": after.get("sha256"), "expectedSha256": expected_hash,
                "path": after.get("path")}
