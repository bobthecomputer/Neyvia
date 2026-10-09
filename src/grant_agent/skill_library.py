from __future__ import annotations

from .proofs_b_engine import checked as _proofs_b_checked

import json
import re
import uuid
from dataclasses import asdict
from pathlib import Path

from .codex_import import load_latest_codex_import_rows
from .models import (
    LearnedSkill,
    SkillBrief,
    SkillPack,
    SkillPromotionCandidate,
    SkillSource,
    SkillUsageRecord,
    utc_now_iso,
)
from .skills import Skill, SkillRegistry
from .proofs_e_sv import enforced


DEFAULT_SKILL_HARNESS_COMPATIBILITY = [
    "fluxio_hybrid",
    "codex",
    "openclaw",
    "hermes",
    "legacy_autonomous_engine",
]


def personal_skill_evolution_receipts_path(home_root: Path | None = None) -> Path:
    return (home_root if home_root is not None else Path.home()) / ".codex" / ".neyvia" / "skill_evolution_receipts.json"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _safe_skill_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip(".-")
    return cleaned[:96] or "skill"


def _skill_frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    prefix = f"{key}:"
    for line in parts[1].splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            return stripped[len(prefix):].strip().strip("\"'")
    return ""


def _skill_description_from_markdown(text: str) -> str:
    frontmatter_description = _skill_frontmatter_value(text, "description")
    if frontmatter_description:
        return frontmatter_description
    body = text.split("---", 2)[-1] if text.startswith("---") else text
    for block in re.split(r"\n\s*\n", body):
        cleaned = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if cleaned and not cleaned.startswith("#"):
            return cleaned[:420]
    return ""


@enforced("sv.skills.discovery")
def load_codex_home_skill_rows(control_dir: Path | None = None, *, home_root: Path | None = None) -> list[dict]:
    if control_dir is not None:
        project_skills_root = control_dir.parent / ".codex" / "skills"
        has_initialized_skill_state = any(
            path.exists()
            for path in (
                control_dir / "workspaces.json",
                control_dir / "skill_evolution_receipts.json",
                control_dir / "user_installed_skills.json",
                project_skills_root,
            )
        )
        if not has_initialized_skill_state:
            return []
    skill_roots: list[tuple[Path, str, str]] = []
    if control_dir is not None:
        skill_roots.append((project_skills_root, "workspace", "Project skill"))
    skill_roots.append(((home_root if home_root is not None else Path.home()) / ".codex" / "skills", "codex_home_skill", "Local Codex skill"))
    rows: list[dict] = []
    seen_skill_ids: set[str] = set()
    for skills_root, source_kind, source_label in skill_roots:
        if not skills_root.exists():
            continue
        for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
            if skill_dir.name.startswith(".") or skill_dir.name in seen_skill_ids:
                continue
            skill_path = skill_dir / "SKILL.md"
            if not skill_path.exists():
                continue
            try:
                text = skill_path.read_text(encoding="utf-8")
            except OSError:
                continue
            seen_skill_ids.add(skill_dir.name)
            name = _skill_frontmatter_value(text, "name") or skill_dir.name
            description = _skill_description_from_markdown(text)
            load_mode = "project-skill-md" if source_kind == "workspace" else "local-skill-md"
            rows.append(
                {
                    "skillId": skill_dir.name,
                    "label": name.replace("-", " ").title() if name == skill_dir.name else name,
                    "description": description,
                    "promptHint": description,
                    "instructions": text,
                    "originType": "user_authored",
                    # A Markdown skill supplies guidance, not a callable
                    # Hermes/OpenCode action. Execution needs an explicit
                    # adapter and a real runtime entry point.
                    "guidanceOnly": True,
                    "executionCapable": False,
                    "editableStatus": "active",
                    "testStatus": "untested",
                    "promotionState": "reviewed",
                    "source": {
                        "kind": source_kind,
                        "label": source_label,
                        "path": str(skill_path),
                    },
                    "usableByHarnesses": ["fluxio_hybrid"],
                    "compatibleHarnesses": ["fluxio_hybrid"],
                    "harnessCompatibility": {
                        "schema": "fluxio.skill_harness_compatibility.v1",
                        "source": load_mode,
                        "originType": "user_authored",
                        "usableByHarnesses": ["fluxio_hybrid"],
                        "crossHarness": False,
                        "adapterRequired": False,
                        "notes": "Neyvia indexes this SKILL.md for the Neyvia Agent. Other harnesses need their own loader and runtime integration.",
                    },
                    "runtimeHints": {
                        "compatibleHarnesses": ["fluxio_hybrid"],
                        "skillFile": str(skill_path),
                        "loadMode": load_mode,
                        "skillContract": "SKILL.md content is available to the Neyvia skill catalog as guidance; referenced scripts still require a runnable workspace and tool.",
                    },
                    "tags": ["user-authored", "codex-skill", "guidance"],
                }
            )
    return rows


class SkillLibrary:
    def __init__(self, root: Path, registry: SkillRegistry, *, home_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.registry = registry
        self.control_dir = self.root / ".agent_control"
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.learned_path = self.control_dir / "learned_skills.json"
        self.user_installed_path = self.control_dir / "user_installed_skills.json"
        self.usage_path = self.control_dir / "skill_usage.json"
        self.feedback_path = self.control_dir / "skill_feedback.json"
        self.repair_receipts_path = self.control_dir / "skill_repair_receipts.json"
        self.evolution_receipts_path = (
            self.control_dir / "skill_evolution_receipts.json"
        )
        self.personal_evolution_receipts_path = (
            personal_skill_evolution_receipts_path(home_root)
        )
        from .harness_jobs import _exclusive_job_lock

        # Windows readers must finish before feedback replaces either store.
        with _exclusive_job_lock(self.feedback_path, timeout_seconds=10):
            self.learned_skills = self._load_learned_skills()
            self.feedback_records = self._load_skill_rows(self.feedback_path)
        self.user_installed_skills = self._load_skill_rows(self.user_installed_path)
        existing_ids = {
            str(item.get("skillId") or item.get("skill_id") or item.get("id") or item.get("label") or "").strip()
            for item in self.user_installed_skills
            if isinstance(item, dict)
        }
        for item in load_codex_home_skill_rows(self.control_dir, home_root=home_root):
            skill_id = str(item.get("skillId") or item.get("label") or "").strip()
            if skill_id and skill_id not in existing_ids:
                self.user_installed_skills.append(item)
                existing_ids.add(skill_id)
        for item in load_latest_codex_import_rows(self.control_dir):
            skill_id = str(item.get("skillId") or item.get("label") or "").strip()
            if skill_id and skill_id not in existing_ids:
                self.user_installed_skills.append(item)
                existing_ids.add(skill_id)
        self.usage_records = self._load_usage_records()
        self.repair_receipts = self._load_skill_rows(self.repair_receipts_path)
        evolution_rows = [
            *self._load_skill_rows(self.evolution_receipts_path),
            *self._load_skill_rows(self.personal_evolution_receipts_path),
        ]
        self.evolution_receipts = []
        seen_evolution_receipts: set[str] = set()
        for item in evolution_rows:
            receipt_key = str(
                item.get("receiptId")
                or "|".join(
                    [
                        str(item.get("scope") or ""),
                        str(item.get("skillId") or ""),
                        str(item.get("revision") or ""),
                        str(item.get("savedAt") or ""),
                    ]
                )
            )
            if receipt_key in seen_evolution_receipts:
                continue
            seen_evolution_receipts.add(receipt_key)
            self.evolution_receipts.append(item)
        self._operator_value_samples_by_alias: dict[str, list[dict]] | None = None

    @_proofs_b_checked("proofs-b.engine.skill-load")
    def _load_skill_rows(self, path: Path) -> list[dict]:
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return []
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _load_usage_records(self) -> list[SkillUsageRecord]:
        payload = self._load_skill_rows(self.usage_path)
        return [SkillUsageRecord(**item) for item in payload]

    def _load_learned_skills(self) -> list[LearnedSkill]:
        payload = self._load_skill_rows(self.learned_path)
        learned: list[LearnedSkill] = []
        for item in payload:
            source = SkillSource(**item.get("source", {"kind": "learned", "label": "Learned"}))
            learned.append(
                LearnedSkill(
                    skill_id=item["skill_id"],
                    label=item["label"],
                    description=item.get("description", ""),
                    prompt_hint=item.get("prompt_hint", ""),
                    source=source,
                    confidence=float(item.get("confidence", 0.0)),
                    status=item.get("status", "learned"),
                    disabled=bool(item.get("disabled", False)),
                    usage_count=int(item.get("usage_count", 0)),
                    tags=item.get("tags", []),
                    permissions=item.get("permissions", []),
                    audit=item.get("audit", []),
                    created_at=item.get("created_at", utc_now_iso()),
                    updated_at=item.get("updated_at", utc_now_iso()),
                    last_used_at=item.get("last_used_at"),
                )
            )
        return learned

    def _save_learned_skills(self) -> None:
        from .durability import atomic_write_json

        atomic_write_json(self.learned_path, [asdict(item) for item in self.learned_skills])

    def _save_usage_records(self) -> None:
        self.usage_path.write_text(
            json.dumps([asdict(item) for item in self.usage_records], indent=2),
            encoding="utf-8",
        )

    def _save_feedback_records(self) -> None:
        from .durability import atomic_write_json

        atomic_write_json(self.feedback_path, self.feedback_records)

    def _save_repair_receipts(self) -> None:
        self.repair_receipts_path.write_text(
            json.dumps(self.repair_receipts[-100:], indent=2),
            encoding="utf-8",
        )

    def curated_packs(self) -> list[SkillPack]:
        packs: list[SkillPack] = []
        for skill in self.registry.skills:
            packs.append(
                SkillPack(
                    pack_id=f"curated:{skill.name}",
                    label=skill.name.replace("_", " ").title(),
                    description=skill.description,
                    source=SkillSource(kind="curated", label="Curated"),
                    recommended=True,
                    installed=True,
                    skills=[skill.name],
                    permissions=skill.permissions,
                    audience="all",
                    action_kinds=skill.action_kinds,
                    profile_suitability=skill.profile_suitability,
                    guidance_only=skill.guidance_only,
                    execution_capable=skill.execution_capable,
                )
            )
        return packs

    def learned_skill_rows(self) -> list[dict]:
        return [asdict(item) for item in self.learned_skills]

    def _usage_summary(self, skill_id: str) -> dict[str, str | int | None]:
        records = [item for item in self.usage_records if item.skill_id == skill_id]
        helped = [item for item in records if item.helped]
        last_used_at = max((item.created_at for item in records), default=None)
        last_helped_at = max((item.created_at for item in helped), default=None)
        return {
            "usageCount": len(records),
            "helpedCount": len(helped),
            "lastUsedAt": last_used_at,
            "lastHelpedAt": last_helped_at,
        }

    def _evolution_summary(
        self,
        row: dict,
        skill_id: str,
        *,
        usage: dict[str, str | int | None],
        feedback: dict,
    ) -> dict:
        aliases = self._feedback_aliases(row, skill_id)
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        source_kind = str(source.get("kind") or row.get("sourceKind") or "").strip()
        row_scope = (
            "personal"
            if source_kind == "codex_home_skill"
            else "project"
            if source_kind == "workspace"
            else ""
        )
        evolution_receipts = [
            item
            for item in self.evolution_receipts
            if str(item.get("skillId") or "") in aliases
            and (
                not str(item.get("scope") or "").strip()
                or (
                    row_scope
                    and str(item.get("scope") or "").strip() == row_scope
                )
            )
        ]
        version_receipts = [
            item
            for item in evolution_receipts
            if str(item.get("eventKind") or "") != "created"
        ]
        repair_receipts = [
            item
            for item in self.repair_receipts
            if str(item.get("skillId") or "") in aliases
        ]
        history = [
            {
                "kind": (
                    "creation"
                    if str(item.get("eventKind") or "") == "created"
                    else "version"
                ),
                "status": item.get("status") or "saved",
                "revision": int(item.get("revision") or 0),
                "changedAt": item.get("savedAt") or "",
                "note": item.get("changeNote") or "Reviewed skill version saved.",
                "receiptId": item.get("receiptId") or "",
            }
            for item in evolution_receipts
        ]
        history.extend(
            {
                "kind": "repair",
                "status": item.get("status") or "review",
                "revision": 0,
                "changedAt": item.get("generatedAt") or "",
                "note": item.get("nextAction") or "Repair reviewed by the operator.",
                "receiptId": item.get("receiptId") or "",
            }
            for item in repair_receipts
        )
        history = sorted(
            history,
            key=lambda item: str(item.get("changedAt") or ""),
            reverse=True,
        )[:6]
        operator_value = (
            feedback.get("operatorValue")
            if isinstance(feedback.get("operatorValue"), dict)
            else {}
        )
        selection_policy = (
            feedback.get("selectionPolicy")
            if isinstance(feedback.get("selectionPolicy"), dict)
            else {}
        )
        promotion_gate = (
            feedback.get("promotionGate")
            if isinstance(feedback.get("promotionGate"), dict)
            else {}
        )
        trend = str(feedback.get("trend") or "unmeasured")
        selection_state = str(selection_policy.get("state") or "unmeasured")
        clean_slices = int(feedback.get("lowLossSliceCount") or 0)
        value_samples = int(operator_value.get("sampleCount") or 0)
        usage_count = int(usage.get("usageCount") or row.get("usageCount") or 0)
        helped_count = int(usage.get("helpedCount") or row.get("helpedCount") or 0)
        needs_repair = (
            trend in {"repair", "operator_value_repair", "operator_value_deprioritize"}
            or selection_state == "deprioritize"
        )
        review_ready = bool(promotion_gate.get("eligible"))
        proven = (
            selection_state == "prefer"
            and clean_slices >= 3
            and value_samples >= 2
        )
        if needs_repair:
            state = "needs_repair"
            label = "Needs repair"
            level = 1
        elif trend == "stagnant":
            state = "stagnant"
            label = "Stable, not improving"
            level = 2
        elif proven:
            state = "proven"
            label = "Proven and improving"
            level = 4
        elif review_ready:
            state = "review_ready"
            label = "Ready for human review"
            level = 3
        elif usage_count or int(feedback.get("sliceCount") or 0) or value_samples:
            state = "learning"
            label = "Learning from use"
            level = 2
        else:
            state = "new"
            label = "Ready to learn"
            level = 1
        next_action = str(feedback.get("nextAction") or "").strip()
        if not next_action:
            next_action = (
                "Use this skill on a real task, verify the result, and record whether it helped."
                if state == "new"
                else "Collect another verified task and operator-value closeout before raising trust."
            )
        return {
            "schema": "fluxio.skill_evolution_summary.v1",
            "state": state,
            "label": label,
            "maturityLevel": level,
            "revisionCount": len(version_receipts),
            "latestRevision": max(
                (int(item.get("revision") or 0) for item in version_receipts),
                default=0,
            ),
            "usageCount": usage_count,
            "helpedCount": helped_count,
            "cleanSliceCount": clean_slices,
            "requiredCleanSlices": int(
                promotion_gate.get("requiredLowLossSlices") or 3
            ),
            "operatorValueSampleCount": value_samples,
            "requiredOperatorValueSamples": int(
                promotion_gate.get("requiredOperatorValueSamples") or 2
            ),
            "operatorValueAverage": operator_value.get("averageScore"),
            "nextAction": next_action,
            "history": history,
            "humanReviewRequired": True,
            "trustPolicy": (
                "Usage alone never raises trust; clean verification and operator value are required."
            ),
        }

    def _feedback_aliases(self, row: dict, skill_id: str) -> set[str]:
        aliases = {str(skill_id or "").strip()}
        for key in ("skillId", "skill_id", "packId", "pack_id", "label", "name"):
            value = str(row.get(key) or "").strip()
            if value:
                aliases.add(value)
                if ":" in value:
                    aliases.add(value.split(":", 1)[1])
        skills = row.get("skills", []) if isinstance(row.get("skills"), list) else []
        for value in skills:
            text = str(value or "").strip()
            if text:
                aliases.add(text)
        return {item for item in aliases if item}

    def _operator_value_index(self) -> dict[str, list[dict]]:
        if self._operator_value_samples_by_alias is not None:
            return self._operator_value_samples_by_alias
        missions_path = self.control_dir / "missions.json"
        try:
            missions = json.loads(missions_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            missions = []
        if not isinstance(missions, list):
            missions = []
        samples_by_alias: dict[str, list[dict]] = {}
        for mission in missions:
            if not isinstance(mission, dict):
                continue
            state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
            feedback = (
                state.get("operator_value_feedback")
                if isinstance(state.get("operator_value_feedback"), dict)
                else {}
            )
            if not feedback:
                continue
            used_skills: set[str] = set()
            for item in mission.get("skill_usage", []) if isinstance(mission.get("skill_usage"), list) else []:
                if not isinstance(item, dict):
                    continue
                for key in ("skill_id", "skillId", "label"):
                    value = str(item.get(key) or "").strip()
                    if value:
                        used_skills.add(value)
            try:
                score = int(feedback.get("score"))
            except (TypeError, ValueError):
                score = -1
            outcome = str(feedback.get("outcome") or "").strip().lower()
            trust_signal = str(
                feedback.get("trustSignal") or feedback.get("trust_signal") or ""
            ).strip().lower()
            if score < 0 and not outcome and not trust_signal:
                continue
            sample = {
                "missionId": str(mission.get("mission_id") or mission.get("missionId") or ""),
                "score": score,
                "outcome": outcome,
                "trustSignal": trust_signal,
                "recordedAt": str(feedback.get("recordedAt") or mission.get("updated_at") or ""),
            }
            for alias in used_skills:
                samples_by_alias.setdefault(alias, []).append(sample)
        self._operator_value_samples_by_alias = samples_by_alias
        return samples_by_alias

    def _operator_value_summary(self, aliases: set[str]) -> dict:
        index = self._operator_value_index()
        samples = []
        seen = set()
        for alias in aliases:
            for sample in index.get(alias, []):
                sample_key = (
                    sample.get("missionId", ""),
                    sample.get("recordedAt", ""),
                    sample.get("score", -1),
                    sample.get("outcome", ""),
                    sample.get("trustSignal", ""),
                )
                if sample_key in seen:
                    continue
                seen.add(sample_key)
                samples.append(sample)
        if not samples:
            return {
                "sampleCount": 0,
                "averageScore": None,
                "promoteCount": 0,
                "reviewCount": 0,
                "deprioritizeCount": 0,
                "state": "unmeasured",
                "selectionWeight": 0,
                "latestMissionId": "",
            }
        scored = [item["score"] for item in samples if int(item.get("score", -1)) >= 0]
        average = round(sum(scored) / max(len(scored), 1), 1) if scored else None
        promote_count = sum(
            1
            for item in samples
            if item.get("trustSignal") == "promote"
            or item.get("outcome") == "useful"
            or int(item.get("score", -1)) >= 80
        )
        deprioritize_count = sum(
            1
            for item in samples
            if item.get("trustSignal") == "deprioritize"
            or item.get("outcome") == "not_useful"
            or 0 <= int(item.get("score", -1)) < 50
        )
        review_count = len(samples) - promote_count - deprioritize_count
        if deprioritize_count > promote_count or (average is not None and average < 55):
            state = "deprioritize"
            selection_weight = -55
        elif promote_count >= max(1, review_count + deprioritize_count) and (
            average is None or average >= 75
        ):
            state = "prefer"
            selection_weight = 28
        else:
            state = "review"
            selection_weight = -6
        latest = sorted(samples, key=lambda item: item.get("recordedAt") or "")[-1]
        return {
            "sampleCount": len(samples),
            "averageScore": average,
            "promoteCount": promote_count,
            "reviewCount": review_count,
            "deprioritizeCount": deprioritize_count,
            "state": state,
            "selectionWeight": selection_weight,
            "latestMissionId": latest.get("missionId", ""),
        }

    @enforced("sv.skills.feedback-summary")
    def _feedback_summary(self, row: dict, skill_id: str) -> dict:
        aliases = self._feedback_aliases(row, skill_id)
        operator_value = self._operator_value_summary(aliases)
        records = [
            item
            for item in self.feedback_records
            if str(item.get("skillId") or item.get("skill_id") or "") in aliases
        ]
        if not records:
            if int(operator_value.get("sampleCount", 0) or 0) > 0:
                state = str(operator_value.get("state") or "review")
                next_action = (
                    "Prefer this skill for matching slices; operator closeouts rated it useful."
                    if state == "prefer"
                    else "Hold this skill back until a better value-scored closeout or validation slice exists."
                    if state == "deprioritize"
                    else "Collect more operator-value closeouts or mission-slice gap before promoting this skill."
                )
                return {
                    "sliceCount": 0,
                    "averageSystemLoss": None,
                    "latestSystemLoss": None,
                    "latestImprovementScore": None,
                    "trend": f"operator_value_{state}",
                    "consecutiveRepairCount": 0,
                    "consecutiveReinforceCount": 0,
                    "zeroImprovementStreak": 0,
                    "lowLossSliceCount": 0,
                    "operatorValue": operator_value,
                    "promotionGate": {
                        "eligible": state == "prefer" and int(operator_value.get("sampleCount", 0) or 0) >= 2,
                        "requiredLowLossSlices": 3,
                        "requiredOperatorValueSamples": 2,
                        "humanReviewRequired": True,
                    },
                    "selectionPolicy": {
                        "state": state,
                        "reason": "Operator mission closeouts are the current skill trust signal.",
                        "selectionWeight": int(operator_value.get("selectionWeight", 0) or 0),
                    },
                    "nextAction": next_action,
                    "lastMissionId": operator_value.get("latestMissionId", ""),
                    "lastStepId": "",
                    "lastUsedAt": "",
                    "repairProposal": {},
                }
            return {
                "sliceCount": 0,
                "averageSystemLoss": None,
                "latestSystemLoss": None,
                "latestImprovementScore": None,
                "trend": "unmeasured",
                "consecutiveRepairCount": 0,
                "consecutiveReinforceCount": 0,
                "zeroImprovementStreak": 0,
                "lowLossSliceCount": 0,
                "promotionGate": {
                    "eligible": False,
                    "requiredLowLossSlices": 3,
                    "humanReviewRequired": True,
                },
                "selectionPolicy": {
                    "state": "measure",
                    "reason": "No mission-slice gap has been recorded yet.",
                    "selectionWeight": 0,
                },
                "operatorValue": operator_value,
                "nextAction": "Run the skill in a mission slice to collect gap feedback.",
            }
        records = sorted(records, key=lambda item: str(item.get("createdAt") or item.get("created_at") or ""))
        losses = [
            float(item.get("systemLoss", 0.0) or 0.0)
            for item in records
        ]
        latest = records[-1]
        latest_loss = losses[-1]
        latest_improvement = float(latest.get("improvementScore", 0.0) or 0.0)
        recent_actions = [
            str(item.get("nextAction") or "").strip()
            for item in records[-5:]
        ]
        consecutive_repair_count = 0
        for action in reversed(recent_actions):
            if action != "repair":
                break
            consecutive_repair_count += 1
        consecutive_reinforce_count = 0
        for action in reversed(recent_actions):
            if action != "reinforce":
                break
            consecutive_reinforce_count += 1
        consecutive_zero_improvement_count = 0
        for item in reversed(records):
            improvement = float(item.get("improvementScore", 0.0) or 0.0)
            if abs(improvement) > 0.05:
                break
            consecutive_zero_improvement_count += 1
        low_loss_slice_count = sum(
            1
            for item in records
            if float(item.get("systemLoss", 1.0) or 1.0) <= 0.15
            and str(item.get("nextAction") or "") == "reinforce"
        )
        if (
            latest_loss <= 0.15
            and consecutive_zero_improvement_count >= 2
        ):
            trend = "stagnant"
            next_action = (
                "Branch this skill for the repeating context or change its fitness "
                "test; repeated zero lift does not justify reinforcement."
            )
            selection_policy = {
                "state": "review",
                "reason": (
                    "Recent mission slices remained low-loss but produced no "
                    "measurable improvement."
                ),
                "selectionWeight": -12,
            }
        elif latest_loss <= 0.15 and latest_improvement >= 0:
            trend = "reinforce"
            next_action = "Keep using this skill for matching slices; it is lowering the measured gap."
            selection_policy = {
                "state": "prefer",
                "reason": "Recent mission slices lowered the system gap.",
                "selectionWeight": 24 + min(18, consecutive_reinforce_count * 6),
            }
        elif latest_loss >= 0.55:
            trend = "repair"
            next_action = "Review prompt guidance and verification fit before reusing this skill."
            selection_policy = {
                "state": "deprioritize",
                "reason": "Recent mission slice produced a high system gap.",
                "selectionWeight": -80 - min(40, consecutive_repair_count * 10),
            }
        else:
            trend = "watch"
            next_action = "Keep this skill in review until more slice feedback accumulates."
            selection_policy = {
                "state": "review",
                "reason": "Slice results are mixed or not strong enough to promote.",
                "selectionWeight": -8,
            }
        if int(operator_value.get("sampleCount", 0) or 0) > 0:
            operator_state = str(operator_value.get("state") or "review")
            operator_weight = int(operator_value.get("selectionWeight", 0) or 0)
            selection_policy["operatorValueWeight"] = operator_weight
            selection_policy["selectionWeight"] = int(selection_policy.get("selectionWeight", 0) or 0) + operator_weight
            if operator_state == "deprioritize":
                trend = "operator_value_repair"
                next_action = "Operator closeouts rated this skill low; keep it in review until a clean value-scored validation slice."
                selection_policy["state"] = "deprioritize"
                selection_policy["reason"] = "Operator mission closeouts lowered skill trust."
            elif operator_state == "prefer" and trend not in {"repair", "stagnant"}:
                selection_policy["state"] = "prefer"
                selection_policy["reason"] = "Low system gap and operator-value closeouts both support reuse."
        return {
            "sliceCount": len(records),
            "averageSystemLoss": round(sum(losses) / max(len(losses), 1), 3),
            "latestSystemLoss": round(latest_loss, 3),
            "latestImprovementScore": round(latest_improvement, 1),
            "trend": trend,
            "consecutiveRepairCount": consecutive_repair_count,
            "consecutiveReinforceCount": consecutive_reinforce_count,
            "zeroImprovementStreak": consecutive_zero_improvement_count,
            "lowLossSliceCount": low_loss_slice_count,
            "promotionGate": {
                "eligible": (
                    low_loss_slice_count >= 3
                    and consecutive_zero_improvement_count < 2
                    and sum(losses) / max(len(losses), 1) <= 0.15
                    and (
                        int(operator_value.get("sampleCount", 0) or 0) == 0
                        or (
                            str(operator_value.get("state") or "") == "prefer"
                            and float(operator_value.get("averageScore") or 0) >= 75
                        )
                    )
                ),
                "requiredLowLossSlices": 3,
                "requiredOperatorValueSamples": 2,
                "humanReviewRequired": True,
            },
            "operatorValue": operator_value,
            "selectionPolicy": selection_policy,
            "nextAction": next_action,
            "lastMissionId": latest.get("missionId", ""),
            "lastStepId": latest.get("stepId", ""),
            "lastUsedAt": latest.get("createdAt", ""),
            "repairProposal": (
                self._build_skill_repair_proposal(row, latest, latest_loss)
                if trend == "repair"
                else {}
            ),
        }

    @staticmethod
    def _system_loss_hold(feedback_summary: dict) -> dict:
        selection_policy = (
            feedback_summary.get("selectionPolicy", {})
            if isinstance(feedback_summary.get("selectionPolicy"), dict)
            else {}
        )
        promotion_gate = (
            feedback_summary.get("promotionGate", {})
            if isinstance(feedback_summary.get("promotionGate"), dict)
            else {}
        )
        trend = str(feedback_summary.get("trend") or "").strip()
        state = str(selection_policy.get("state") or "").strip()
        repair_proposal = (
            feedback_summary.get("repairProposal", {})
            if isinstance(feedback_summary.get("repairProposal"), dict)
            else {}
        )
        held = (
            state == "deprioritize"
            or trend in {"repair", "operator_value_repair", "operator_value_deprioritize"}
            or bool(repair_proposal)
        ) and not bool(promotion_gate.get("eligible"))
        return {
            "schema": "fluxio.skill_system_loss_hold.v1",
            "held": held,
            "reason": (
                selection_policy.get("reason")
                or feedback_summary.get("nextAction")
                or "Skill is held until clean validation evidence clears the repair gate."
            )
            if held
            else "",
            "requiredAction": (
                repair_proposal.get("nextAction")
                or "Run a clean value-scored validation slice before mission selection can use this skill."
            )
            if held
            else "",
            "trend": trend,
            "selectionState": state,
        }

    def _build_skill_repair_proposal(
        self,
        row: dict,
        latest_feedback: dict,
        latest_loss: float,
    ) -> dict:
        skill_id = str(
            row.get("skillId")
            or row.get("skill_id")
            or latest_feedback.get("skillId")
            or latest_feedback.get("skill_id")
            or ""
        )
        label = str(row.get("label") or latest_feedback.get("label") or skill_id)
        failures = [
            str(item)
            for item in latest_feedback.get("verificationFailures", [])
            if str(item).strip()
        ][:4]
        prompt_hint = str(row.get("promptHint") or row.get("prompt_hint") or "").strip()
        if prompt_hint:
            prompt_patch = (
                f"{prompt_hint}\n\nRepair note: before using this skill again, ground the "
                "slice in current repo evidence, run the listed verification command, and stop "
                "on the first unexplained failure."
            )
        else:
            prompt_patch = (
                "Before using this skill again, ground the slice in current repo evidence, "
                "state the intended file scope, run the listed verification command, and stop "
                "on the first unexplained failure."
            )
        return {
            "proposalId": f"skill_repair:{skill_id}",
            "skillId": skill_id,
            "label": label,
            "status": "proposed",
            "reason": (
                f"Latest mission slice recorded system gap {round(latest_loss, 3)}, "
                "so reuse is held until a clean validation slice proves the repair."
            ),
            "beforeVerification": {
                "missionId": latest_feedback.get("missionId", ""),
                "stepId": latest_feedback.get("stepId", ""),
                "systemLoss": round(latest_loss, 3),
                "verificationFailures": failures,
                "executionOk": bool(latest_feedback.get("executionOk")),
            },
            "repairPatch": {
                "kind": "prompt_hint_addendum",
                "promptHint": prompt_patch,
                "routePolicy": "deprioritize_until_clean_validation_slice",
                "verificationFocus": failures or ["run the mission default verification command"],
            },
            "afterVerification": {
                "requiredCleanSlices": 1,
                "maxSystemLoss": 0.15,
                "requiredVerificationFailures": 0,
                "requiresChangedFilesWhenExecutionSucceeds": True,
            },
            "nextAction": "repair_before_reuse",
        }

    @staticmethod
    def _normalize_harness_compatibility(item: dict, *, origin_type: str) -> dict:
        existing_contract = item.get("harnessCompatibility") if isinstance(item.get("harnessCompatibility"), dict) else {}
        raw = (
            item.get("usableByHarnesses")
            or item.get("usable_by_harnesses")
            or item.get("compatibleHarnesses")
            or item.get("compatible_harnesses")
            or item.get("harnesses")
            or (existing_contract.get("usableByHarnesses") if isinstance(existing_contract, dict) else None)
            or (item.get("harnessCompatibility") if isinstance(item.get("harnessCompatibility"), list) else None)
        )
        if isinstance(raw, str):
            harnesses = [part.strip() for part in re.split(r"[,;\s]+", raw) if part.strip()]
        elif isinstance(raw, list):
            harnesses = [str(part).strip() for part in raw if str(part).strip()]
        else:
            harnesses = []
        if not harnesses:
            harnesses = list(DEFAULT_SKILL_HARNESS_COMPATIBILITY)
        deduped: list[str] = []
        seen: set[str] = set()
        for harness in harnesses:
            normalized = harness.lower().replace("-", "_")
            if normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        return {
            "schema": "fluxio.skill_harness_compatibility.v1",
            "source": str(existing_contract.get("source") or "shared_skill_library"),
            "originType": origin_type,
            "usableByHarnesses": deduped,
            "crossHarness": len(deduped) >= 2,
            "adapterRequired": bool(item.get("adapterRequired") or item.get("adapter_required") or existing_contract.get("adapterRequired")),
            "notes": str(
                existing_contract.get("notes")
                or (
                    "Explicit harness compatibility supplied by the skill row."
                    if raw
                    else "Default shared-library contract: expose the skill to Neyvia hybrid, Codex, OpenClaw, Hermes, and the legacy autonomous engine until a row opts out."
                )
            ),
        }

    def _enrich_catalog_row(
        self,
        row: dict,
        *,
        default_origin_type: str,
        default_editable_status: str,
        default_test_status: str,
        default_promotion_state: str,
    ) -> dict:
        item = dict(row)
        source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
        skill_id = (
            item.get("skillId")
            or item.get("skill_id")
            or item.get("packId")
            or item.get("pack_id")
            or item.get("label")
            or item.get("name")
            or ""
        )
        usage = self._usage_summary(str(skill_id))

        if item.get("disabled"):
            editable_status = "disabled"
        elif item.get("archived"):
            editable_status = "archived"
        else:
            editable_status = (
                item.get("editableStatus")
                or item.get("editable_status")
                or item.get("status")
                or default_editable_status
            )

        origin_type = (
            item.get("originType")
            or item.get("origin_type")
            or source.get("kind")
            or default_origin_type
        )
        test_status = (
            item.get("testStatus")
            or item.get("test_status")
            or default_test_status
        )
        promotion_state = (
            item.get("promotionState")
            or item.get("promotion_state")
            or default_promotion_state
        )

        if "skill_id" in item and "skillId" not in item:
            item["skillId"] = item["skill_id"]
        if "pack_id" in item and "packId" not in item:
            item["packId"] = item["pack_id"]
        if "prompt_hint" in item and "promptHint" not in item:
            item["promptHint"] = item["prompt_hint"]

        harness_contract = self._normalize_harness_compatibility(item, origin_type=str(origin_type))
        usable_harnesses = list(harness_contract.get("usableByHarnesses") or DEFAULT_SKILL_HARNESS_COMPATIBILITY)
        runtime_hints = item.get("runtimeHints") if isinstance(item.get("runtimeHints"), dict) else {}
        runtime_hints = {
            **runtime_hints,
            "compatibleHarnesses": runtime_hints.get("compatibleHarnesses")
            if isinstance(runtime_hints.get("compatibleHarnesses"), list) and runtime_hints.get("compatibleHarnesses")
            else usable_harnesses,
            "harnessCompatibility": harness_contract,
            "skillContract": runtime_hints.get("skillContract") or "SKILL.md instructions are passed as runtime context, not assumed as a Codex-only feature.",
        }

        item.update(
            {
                "editableStatus": editable_status,
                "testStatus": test_status,
                "promotionState": promotion_state,
                "lastUsedAt": item.get("lastUsedAt") or item.get("last_used_at") or usage["lastUsedAt"],
                "lastHelpedAt": item.get("lastHelpedAt") or item.get("last_helped_at") or usage["lastHelpedAt"],
                "originType": origin_type,
                "usableByHarnesses": usable_harnesses,
                "compatibleHarnesses": usable_harnesses,
                "harnessCompatibility": harness_contract,
                "runtimeHints": runtime_hints,
                "usageCount": item.get("usageCount", usage["usageCount"]),
                "helpedCount": item.get("helpedCount", usage["helpedCount"]),
            }
        )
        item["feedbackSummary"] = self._feedback_summary(item, str(skill_id))
        item["systemLossHold"] = self._system_loss_hold(item["feedbackSummary"])
        item["evolutionSummary"] = self._evolution_summary(
            item,
            str(skill_id),
            usage=usage,
            feedback=item["feedbackSummary"],
        )
        return item

    def _normalized_user_installed_skills(self) -> list[dict]:
        rows: list[dict] = []
        for item in self.user_installed_skills:
            source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
            origin_type = (
                item.get("originType")
                or item.get("origin_type")
                or source.get("kind")
                or "user_authored"
            )
            promotion_state = "imported" if origin_type == "imported" else "reviewed"
            rows.append(
                self._enrich_catalog_row(
                    item,
                    default_origin_type=origin_type,
                    default_editable_status="active",
                    default_test_status="untested",
                    default_promotion_state=promotion_state,
                )
            )
        return rows

    @staticmethod
    def _management_summary(sections: list[list[dict]]) -> dict[str, int]:
        items = [item for section in sections for item in section]
        return {
            "totalSkills": len(items),
            "needsTestCount": sum(
                1 for item in items if item.get("testStatus") in {"untested", "pending", "sample_ready"}
            ),
            "reviewedReusableCount": sum(
                1 for item in items if item.get("promotionState") == "reviewed"
            ),
            "learnedCount": sum(1 for item in items if item.get("originType") == "learned"),
            "disabledCount": sum(
                1 for item in items if item.get("editableStatus") in {"disabled", "archived"}
            ),
            "feedbackSliceCount": sum(
                int(item.get("feedbackSummary", {}).get("sliceCount") or 0)
                for item in items
            ),
            "repairCount": sum(
                1
                for item in items
                if item.get("feedbackSummary", {}).get("trend") == "repair"
            ),
        }

    def build_runtime_contract(
        self,
        *,
        task_brief: str = "",
        selected_skill_id: str = "",
    ) -> dict:
        selected = selected_skill_id.strip()
        task = task_brief.strip() or "Route the current mission through the most relevant executable skill."
        retrieved = self.retrieve(task, top_k=4)
        retrieved_ids = {
            str(item.get("skillId") or item.get("skill_id") or "").strip()
            for item in retrieved
        }
        registry_rows: list[dict] = []
        for skill in self.registry.skills:
            skill_id = skill.name
            schema_status = "declared" if skill.schema else "missing"
            registry_rows.append(
                {
                    "skillId": skill_id,
                    "label": skill.name.replace("_", " ").title(),
                    "description": skill.description,
                    "sourceKind": "curated",
                    "inputSchema": skill.schema or {
                        "type": "object",
                        "properties": {
                            "taskBrief": {"type": "string"},
                        },
                        "required": ["taskBrief"],
                    },
                    "inputContractStatus": schema_status,
                    "permissions": skill.permissions,
                    "actionKinds": skill.action_kinds,
                    "guidanceOnly": skill.guidance_only,
                    "executionCapable": skill.execution_capable,
                }
            )
        learned_rows = [
            {
                "skillId": item.skill_id,
                "label": item.label,
                "description": item.description,
                "sourceKind": "learned",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "taskBrief": {"type": "string"},
                        "missionId": {"type": "string"},
                    },
                    "required": ["taskBrief"],
                },
                "inputContractStatus": "generated_minimal",
                "permissions": item.permissions,
                "actionKinds": item.tags,
                "guidanceOnly": False,
                "executionCapable": not item.disabled,
            }
            for item in self.learned_skills
        ]
        user_rows = []
        for item in self.user_installed_skills:
            skill_id = str(item.get("skillId") or item.get("skill_id") or item.get("name") or item.get("label") or "").strip()
            if not skill_id:
                continue
            schema = item.get("schema") if isinstance(item.get("schema"), dict) else {}
            user_rows.append(
                {
                    "skillId": skill_id,
                    "label": str(item.get("label") or item.get("name") or skill_id),
                    "description": str(item.get("description") or item.get("summary") or ""),
                    "sourceKind": str(item.get("sourceKind") or item.get("originType") or "user_installed"),
                    "inputSchema": schema or {
                        "type": "object",
                        "properties": {"taskBrief": {"type": "string"}},
                        "required": ["taskBrief"],
                    },
                    "inputContractStatus": "declared" if schema else "generated_minimal",
                    "permissions": item.get("permissions", []) if isinstance(item.get("permissions"), list) else [],
                    "actionKinds": item.get("actionKinds", []) if isinstance(item.get("actionKinds"), list) else [],
                    "executionCapable": bool(
                        item.get("executionCapable", item.get("execution_capable", False))
                    ) and not bool(item.get("disabled", False)),
                    "guidanceOnly": bool(
                        item.get("guidanceOnly", item.get("guidance_only", False))
                    ) or not bool(
                        item.get("executionCapable", item.get("execution_capable", False))
                    ),
                }
            )
        rows = registry_rows + user_rows + learned_rows
        if selected:
            rows.sort(key=lambda item: 0 if item["skillId"] == selected else 1)
        elif retrieved_ids:
            rows.sort(key=lambda item: 0 if item["skillId"] in retrieved_ids else 1)
        skill_contracts = []
        for index, item in enumerate(rows[:8]):
            skill_id = str(item.get("skillId") or f"skill_{index}")
            execution_capable = bool(item.get("executionCapable"))
            guidance_only = bool(item.get("guidanceOnly"))
            runtime_lane = "hermes" if execution_capable and not guidance_only else "hermes-guidance"
            if item.get("sourceKind") in {"openclaw", "workspace", "user_installed"} and not execution_capable:
                runtime_lane = "openclaw"
            safe_id = _safe_skill_id(skill_id)
            feedback_summary = self._feedback_summary(item, skill_id)
            hold = self._system_loss_hold(feedback_summary)
            skill_contracts.append(
                {
                    "skillId": skill_id,
                    "label": item.get("label") or skill_id,
                    "sourceKind": item.get("sourceKind") or "curated",
                    "selected": skill_id == selected or (not selected and skill_id in retrieved_ids),
                    "input": {
                        "schema": item.get("inputSchema") or {},
                        "status": item.get("inputContractStatus") or "missing",
                        "required": list((item.get("inputSchema") or {}).get("required", [])),
                    },
                    "output": {
                        "artifactRequired": True,
                        "artifactPath": f".agent_control/skill_runtime_proofs/{safe_id}.json",
                        "schema": "fluxio.skill_runtime_result.v1",
                    },
                    "route": {
                        "runtimeLane": runtime_lane,
                        "primaryRuntimeLane": "hermes",
                        "fallbackRuntimeLane": "openclaw",
                        "opencodeFallback": True,
                        "reason": "Executable skills run through Hermes by default; OpenClaw/OpenCode stay fallback or workspace-skill lanes.",
                    },
                    "guardrails": [
                        "require_input_schema",
                        "write_output_artifact",
                        "attach_proof_to_mission",
                        "deprioritize_when_system_loss_hold_is_active",
                    ],
                    "systemLossHold": hold,
                    "permissions": item.get("permissions", []),
                    "executionCapable": execution_capable,
                    "guidanceOnly": guidance_only,
                }
            )
        missing_schema_count = sum(
            1 for item in skill_contracts if item.get("input", {}).get("status") == "missing"
        )
        generated_schema_count = sum(
            1 for item in skill_contracts if item.get("input", {}).get("status") == "generated_minimal"
        )
        held_count = sum(1 for item in skill_contracts if item.get("systemLossHold", {}).get("held"))
        return {
            "schema": "fluxio.skill_runtime_contract.v1",
            "generatedAt": utc_now_iso(),
            "primaryRuntimeLane": "hermes",
            "fallbackRuntimeLanes": ["openclaw", "opencode"],
            "taskBrief": task,
            "skillCount": len(rows),
            "contractCount": len(skill_contracts),
            "executionReadyCount": sum(1 for item in skill_contracts if item.get("executionCapable") and not item.get("systemLossHold", {}).get("held")),
            "missingSchemaCount": missing_schema_count,
            "generatedSchemaCount": generated_schema_count,
            "heldSkillCount": held_count,
            "skills": skill_contracts,
            "loop": {
                "steps": ["select_skill", "validate_input", "run_hermes_lane", "write_artifact", "verify_output", "attach_proof"],
                "stopWhen": "artifact_and_verifier_pass_or_guardrail_blocks",
            },
            "nextAction": (
                "Add explicit input schemas for generated-minimal skills before broad autonomous routing."
                if generated_schema_count or missing_schema_count
                else "Use the selected Hermes skill lane and attach its proof artifact to the mission."
            ),
        }

    @enforced("sv.skills.brief")
    def build_skill_brief(
        self,
        *,
        task_brief: str,
        mission_id: str = "",
        top_k: int = 6,
    ) -> SkillBrief:
        task = task_brief.strip()
        selected = self.retrieve(task, top_k=max(1, min(int(top_k or 1), 12)))
        repo_specific = self._repo_specific_skill_rows(task)
        allowed_tools = self._deduped_values(
            value
            for row in selected
            for value in row.get("permissions", []) if isinstance(row.get("permissions"), list)
        )[:16]
        forbidden_areas = self._forbidden_areas_for_task(task)
        relevant_examples = self._relevant_examples(selected, task)[:12]
        constraints = self._skill_brief_constraints(selected, repo_specific)
        known_failures = self._known_skill_failures(selected, task)[:8]
        prior_successes = self._prior_successful_recipes(selected)[:8]
        return SkillBrief(
            brief_id=f"skill_brief_{uuid.uuid4().hex[:12]}",
            mission_id=mission_id,
            task_brief=self._compact_text(task, 500),
            selected_skills=[self._brief_skill_row(item) for item in selected],
            repo_specific_skills=repo_specific[:8],
            allowed_tools=allowed_tools,
            forbidden_areas=forbidden_areas,
            relevant_examples=relevant_examples,
            constraints=constraints,
            known_failures=known_failures,
            prior_successful_recipes=prior_successes,
            skill_count=len(selected),
        )

    def _repo_specific_skill_rows(self, task_brief: str) -> list[dict]:
        query_tokens = _tokenize(task_brief)
        rows = self._normalized_user_installed_skills()
        rows.extend(
            self._enrich_catalog_row(
                asdict(item),
                default_origin_type="learned",
                default_editable_status="disabled" if item.disabled else "active",
                default_test_status="untested",
                default_promotion_state="learning",
            )
            for item in self.learned_skills
            if not item.disabled
        )

        def score(row: dict) -> tuple[int, int]:
            source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
            source_kind = str(row.get("sourceKind") or row.get("originType") or source.get("kind") or "")
            repo_bonus = 1 if source_kind in {"workspace", "codex_home_skill", "user_authored", "learned"} else 0
            text_tokens = _tokenize(
                " ".join(
                    [
                        str(row.get("skillId") or row.get("skill_id") or ""),
                        str(row.get("label") or ""),
                        str(row.get("description") or ""),
                        " ".join(str(value) for value in row.get("tags", []) or []),
                    ]
                )
            )
            return len(query_tokens & text_tokens), repo_bonus

        ranked = sorted(rows, key=score, reverse=True)
        output: list[dict] = []
        for row in ranked:
            skill_id = str(row.get("skillId") or row.get("skill_id") or row.get("id") or row.get("label") or "").strip()
            if not skill_id:
                continue
            output.append(
                {
                    "skillId": self._compact_text(skill_id, 120),
                    "label": self._compact_text(row.get("label") or skill_id, 120),
                    "sourceKind": self._compact_text(row.get("sourceKind") or row.get("originType") or "repo_specific", 80),
                    "description": self._compact_text(row.get("description") or row.get("prompt_hint") or "", 220),
                    "path": self._compact_text(
                        (row.get("source", {}) if isinstance(row.get("source"), dict) else {}).get("path") or "",
                        240,
                    ),
                }
            )
            if len(output) >= 8:
                break
        return output

    def _brief_skill_row(self, row: dict) -> dict:
        skill_id = str(row.get("skillId") or row.get("skill_id") or row.get("label") or "skill")
        feedback = row.get("feedbackSummary", {}) if isinstance(row.get("feedbackSummary"), dict) else {}
        hold = row.get("systemLossHold", {}) if isinstance(row.get("systemLossHold"), dict) else {}
        return {
            "skillId": self._compact_text(skill_id, 120),
            "label": self._compact_text(row.get("label") or skill_id, 120),
            "sourceKind": self._compact_text(row.get("sourceKind") or "unknown", 80),
            "description": self._compact_text(row.get("description") or "", 220),
            "permissions": self._deduped_values(row.get("permissions", []) if isinstance(row.get("permissions"), list) else [])[:12],
            "actionKinds": self._deduped_values(row.get("actionKinds", []) if isinstance(row.get("actionKinds"), list) else [])[:12],
            "guidanceOnly": bool(row.get("guidanceOnly", False)),
            "executionCapable": bool(row.get("executionCapable", False)),
            "selectionReason": self._compact_text(feedback.get("nextAction") or "Selected by task relevance.", 220),
            "knownFailureHold": bool(hold.get("held")),
        }

    def _forbidden_areas_for_task(self, task_brief: str) -> list[str]:
        lowered = task_brief.lower()
        areas = [
            "Do not load every skill file blindly; use only selected skill summaries.",
            "Do not commit secrets or local auth material.",
            "Do not mark mission work complete without proof artifacts.",
        ]
        if "nas" in lowered or "sync" in lowered:
            areas.append("Do not claim NAS sync without matching remote hashes.")
        if "delete" not in lowered and "destructive" not in lowered:
            areas.append("Avoid destructive filesystem actions unless the mission explicitly requires them.")
        return areas[:8]

    def _relevant_examples(self, selected: list[dict], task_brief: str) -> list[str]:
        by_id = {str(item.get("skillId") or ""): item for item in selected}
        examples: list[str] = []
        for skill in self.registry.skills:
            if skill.name not in by_id:
                continue
            for example in skill.examples:
                examples.append(self._compact_text(example, 180))
        query_tokens = _tokenize(task_brief)
        examples.sort(
            key=lambda value: len(query_tokens & _tokenize(value)),
            reverse=True,
        )
        return self._deduped_values(examples)

    def _skill_brief_constraints(self, selected: list[dict], repo_specific: list[dict]) -> list[str]:
        constraints = [
            f"Select from {len(selected)} ranked skill(s), not the full skill catalog.",
            "Carry only skill ids and short summaries into planner/executor context.",
        ]
        if repo_specific:
            constraints.append("Prefer repo-specific skills when their description matches the mission.")
        if any(bool(row.get("systemLossHold", {}).get("held")) for row in selected if isinstance(row.get("systemLossHold"), dict)):
            constraints.append("Held skills require repair or operator review before use.")
        return constraints[:8]

    def _known_skill_failures(self, selected: list[dict], task_brief: str) -> list[dict]:
        selected_ids = {
            str(item.get("skillId") or item.get("skill_id") or "")
            for item in selected
        }
        task_tokens = _tokenize(task_brief)
        registry_text_by_id = {
            skill.name: " ".join([skill.name, skill.description, " ".join(skill.action_kinds)])
            for skill in self.registry.skills
        }
        failures: list[dict] = []
        for record in reversed(self.feedback_records):
            skill_id = str(record.get("skillId") or record.get("skill_id") or "")
            registry_text = registry_text_by_id.get(skill_id, "").lower()
            matches_task = bool(task_tokens & _tokenize(registry_text)) or any(
                len(token) >= 5 and token[:5] in registry_text
                for token in task_tokens
            )
            if skill_id not in selected_ids and not matches_task:
                continue
            try:
                loss = float(record.get("systemLoss", 0.0) or 0.0)
            except (TypeError, ValueError):
                loss = 0.0
            if loss < 0.55 and record.get("nextAction") != "repair":
                continue
            failures.append(
                {
                    "skillId": self._compact_text(skill_id, 120),
                    "missionId": self._compact_text(record.get("missionId") or "", 120),
                    "systemLoss": loss,
                    "reason": self._compact_text("; ".join(str(item) for item in record.get("verificationFailures", [])[:3]), 240),
                    "nextAction": self._compact_text(record.get("nextAction") or "review", 120),
                }
            )
        return failures

    def _prior_successful_recipes(self, selected: list[dict]) -> list[dict]:
        selected_ids = {
            str(item.get("skillId") or item.get("skill_id") or "")
            for item in selected
        }
        recipes: list[dict] = []
        for record in reversed(self.usage_records):
            if not record.helped or record.skill_id not in selected_ids:
                continue
            recipes.append(
                {
                    "skillId": self._compact_text(record.skill_id, 120),
                    "label": self._compact_text(record.label, 120),
                    "missionId": self._compact_text(record.mission_id, 120),
                    "stepId": self._compact_text(record.step_id, 120),
                    "sourceKind": self._compact_text(record.source_kind, 80),
                    "createdAt": record.created_at,
                }
            )
        return recipes

    @staticmethod
    def _deduped_values(values) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value or "").split())
            if not text or text in seen:
                continue
            seen.add(text)
            output.append(text)
        return output

    @staticmethod
    def _compact_text(value, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    @enforced("sv.skills.catalog")
    def build_catalog(
        self,
        recommended_packs: list[SkillPack] | None = None,
    ) -> dict[str, list[dict]]:
        curated = [
            self._enrich_catalog_row(
                asdict(item),
                default_origin_type="curated",
                default_editable_status="active",
                default_test_status="reviewed",
                default_promotion_state="reviewed",
            )
            for item in self.curated_packs()
        ]
        learned = [
            self._enrich_catalog_row(
                asdict(item),
                default_origin_type="learned",
                default_editable_status="disabled" if item.disabled else "active",
                default_test_status="untested",
                default_promotion_state="learning",
            )
            for item in self.learned_skills
        ]
        user_installed = self._normalized_user_installed_skills()
        recommended = [
            self._enrich_catalog_row(
                asdict(item),
                default_origin_type="curated",
                default_editable_status="available",
                default_test_status="recommended",
                default_promotion_state="recommended",
            )
            for item in (recommended_packs or [])
        ]
        sections = [recommended, curated, user_installed, learned]
        feedback_loop = self._build_feedback_loop(sections)
        runtime_contract = self.build_runtime_contract()
        codex_import_rows = [
            item
            for item in user_installed
            if str(item.get("originType") or "") in {"codex_import", "codex_plugin_link"}
        ]
        return {
            "curatedPacks": curated,
            "recommendedPacks": recommended,
            "userInstalledSkills": user_installed,
            "learnedSkills": learned,
            "managementSummary": self._management_summary(sections),
            "feedbackLoop": feedback_loop,
            "runtimeContract": runtime_contract,
            "codexImportSummary": {
                "personalSkillCount": sum(
                    1 for item in codex_import_rows if item.get("originType") == "codex_import"
                ),
                "linkedPluginSkillCount": sum(
                    1 for item in codex_import_rows if item.get("originType") == "codex_plugin_link"
                ),
                "progressiveDisclosure": True,
            },
        }

    def _build_feedback_loop(self, sections: list[list[dict]]) -> dict:
        items = [item for section in sections for item in section]
        measured = [
            item
            for item in items
            if int(item.get("feedbackSummary", {}).get("sliceCount") or 0) > 0
        ]
        value_measured = [
            item
            for item in items
            if int(item.get("feedbackSummary", {}).get("operatorValue", {}).get("sampleCount") or 0) > 0
        ]
        repair = [
            item
            for item in measured + value_measured
            if item.get("feedbackSummary", {}).get("trend") in {"repair", "operator_value_repair", "operator_value_deprioritize"}
            or item.get("feedbackSummary", {}).get("operatorValue", {}).get("state") == "deprioritize"
        ]
        reinforce = [
            item
            for item in measured + value_measured
            if item.get("feedbackSummary", {}).get("trend") in {"reinforce", "operator_value_prefer"}
            or item.get("feedbackSummary", {}).get("operatorValue", {}).get("state") == "prefer"
        ]
        stagnant = [
            item
            for item in measured
            if item.get("feedbackSummary", {}).get("trend") == "stagnant"
        ]
        latest = sorted(
            self.feedback_records,
            key=lambda item: str(item.get("createdAt") or item.get("created_at") or ""),
            reverse=True,
        )[:8]
        active_repair_skill_ids = [
            str(item.get("skillId") or item.get("skill_id") or "")
            for item in repair[:8]
            if item.get("skillId") or item.get("skill_id")
        ]
        preferred_skill_ids = [
            str(item.get("skillId") or item.get("skill_id") or item.get("packId") or "")
            for item in reinforce[:8]
            if item.get("skillId") or item.get("skill_id") or item.get("packId")
        ]
        branch_candidate_skill_ids = [
            str(item.get("skillId") or item.get("skill_id") or "")
            for item in stagnant[:8]
            if item.get("skillId") or item.get("skill_id")
        ]
        repair_proposals = [
            item.get("feedbackSummary", {}).get("repairProposal", {})
            for item in repair[:6]
        ]
        repair_proposals = [item for item in repair_proposals if item]
        return {
            "enabled": True,
            "cadence": "mission_slice_end",
            "scoreInputs": ["execution_result", "verification_result", "changed_files", "operator_value_closeout"],
            "systemLossRouting": {
                "enabled": True,
                "deprioritizeThreshold": 0.55,
                "preferThreshold": 0.15,
                "minimumPromotionSlices": 3,
                "minimumOperatorValueSamples": 2,
                "humanReviewRequired": True,
                "activeRepairSkillIds": active_repair_skill_ids,
                "preferredSkillIds": preferred_skill_ids,
                "branchCandidateSkillIds": branch_candidate_skill_ids,
                "repairProposalPolicy": "automatic_before_after_validation",
                "stagnationPolicy": "branch_or_change_fitness_after_two_zero_lift_slices",
                "operatorValuePolicy": "prefer_useful_closeouts_deprioritize_low_value_closeouts",
            },
            "totalFeedbackSlices": len(self.feedback_records),
            "operatorValueSkillCount": len(value_measured),
            "measuredSkillCount": len(measured),
            "reinforceCount": len(reinforce),
            "repairCount": len(repair),
            "stagnatingCount": len(stagnant),
            "repairProposals": repair_proposals,
            "appliedRepairReceipts": self.repair_receipts[-8:],
            "appliedRepairCount": len(self.repair_receipts),
            "latest": latest,
            "nextActions": [
                item.get("feedbackSummary", {}).get("nextAction", "")
                for item in repair[:3] + stagnant[:3] + measured[:3]
                if item.get("feedbackSummary", {}).get("nextAction")
            ][:4],
        }

    @staticmethod
    def _slice_system_loss(
        *,
        execution_ok: bool,
        verification_failures: list[str],
        changed_files: list[str],
    ) -> float:
        loss = 0.05
        if not execution_ok:
            loss += 0.45
        loss += min(0.45, 0.15 * len(verification_failures))
        if execution_ok and not verification_failures and changed_files:
            loss -= 0.03
        if execution_ok and not changed_files:
            loss += 0.08
        return round(max(0.0, min(1.0, loss)), 3)

    @enforced("sv.skills.feedback")
    def record_slice_feedback(
        self,
        *,
        mission_id: str,
        step_id: str,
        selected_skills: list[dict],
        execution_ok: bool,
        verification_failures: list[str],
        changed_files: list[str],
    ) -> list[dict]:
        # The enforced feedback guard covers reload, append, atomic replacement
        # and checked readback across instances and processes. Denied or corrupt
        # durable history must never be replaced with an empty fallback.
        try:
            raw = self.feedback_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            feedback = []
        else:
            feedback = json.loads(raw)
            if not isinstance(feedback, list) or any(
                not isinstance(item, dict) for item in feedback
            ):
                raise ValueError("Skill feedback store must contain a list of records.")
        self.feedback_records = feedback
        if self.learned_path.exists():
            # Validate before the permissive catalog loader; write admission
            # cannot discard unreadable or malformed durable skill state.
            learned = json.loads(self.learned_path.read_text(encoding="utf-8"))
            if not isinstance(learned, list):
                raise ValueError("Learned skill store must contain a list of records.")
            self.learned_skills = self._load_learned_skills()
        skills = selected_skills or [
            {
                "skillId": "repo_scan",
                "label": "Repo Scan",
                "sourceKind": "curated",
            }
        ]
        system_loss = self._slice_system_loss(
            execution_ok=execution_ok,
            verification_failures=verification_failures,
            changed_files=changed_files,
        )
        created_at = utc_now_iso()
        records: list[dict] = []
        for skill in skills:
            skill_id = str(skill.get("skillId") or skill.get("skill_id") or skill.get("label") or "skill")
            prior = [
                item
                for item in self.feedback_records
                if str(item.get("skillId") or "") == skill_id
            ]
            prior_loss = (
                float(prior[-1].get("systemLoss", system_loss) or system_loss)
                if prior
                else None
            )
            improvement_score = (
                round((prior_loss - system_loss) * 100, 1)
                if prior_loss is not None
                else round((1.0 - system_loss) * 10, 1)
            )
            prior_zero_improvement_streak = 0
            for item in reversed(prior):
                prior_improvement = float(
                    item.get("improvementScore", 0.0) or 0.0
                )
                if abs(prior_improvement) > 0.05:
                    break
                prior_zero_improvement_streak += 1
            if system_loss >= 0.55:
                next_action = "repair"
            elif (
                system_loss <= 0.15
                and abs(improvement_score) <= 0.05
                and prior_zero_improvement_streak >= 1
            ):
                next_action = "branch"
            elif improvement_score >= 0 and system_loss <= 0.15:
                next_action = "reinforce"
            else:
                next_action = "review"
            record = {
                "feedbackId": f"skill_feedback_{uuid.uuid4().hex[:10]}",
                "missionId": mission_id,
                "stepId": step_id,
                "skillId": skill_id,
                "label": skill.get("label") or skill_id,
                "sourceKind": skill.get("sourceKind") or skill.get("source_kind") or "unknown",
                "systemLoss": system_loss,
                "previousSystemLoss": prior_loss,
                "improvementScore": improvement_score,
                "executionOk": bool(execution_ok),
                "verificationFailureCount": len(verification_failures),
                "verificationFailures": verification_failures[:4],
                "changedFileCount": len(changed_files),
                "nextAction": next_action,
                "createdAt": created_at,
            }
            self.feedback_records.append(record)
            records.append(record)
            for learned in self.learned_skills:
                if learned.skill_id == skill_id:
                    if next_action == "reinforce":
                        delta = 0.03 * (1.0 - system_loss)
                    elif next_action == "repair":
                        delta = -(0.05 * system_loss)
                    else:
                        delta = 0.0
                    learned.confidence = round(max(0.0, min(1.0, learned.confidence + delta)), 3)
                    learned.audit.append(
                        f"{created_at}: slice feedback {next_action} loss={system_loss}"
                    )
                    learned.updated_at = created_at
        self.feedback_records = self.feedback_records[-500:]
        self._save_feedback_records()
        self._save_learned_skills()
        return records

    def apply_repair_proposal(
        self,
        *,
        proposal_id: str = "",
        skill_id: str = "",
        reviewer: str = "operator",
        validation_mission_id: str = "",
        validation_step_id: str = "",
    ) -> dict:
        catalog = self.build_catalog()
        proposals = catalog.get("feedbackLoop", {}).get("repairProposals", [])
        proposal = next(
            (
                item
                for item in proposals
                if str(item.get("proposalId") or "") == proposal_id
                or str(item.get("skillId") or "") == skill_id
            ),
            {},
        )
        resolved_skill_id = str(skill_id or proposal.get("skillId") or "").strip()
        learned = next(
            (item for item in self.learned_skills if item.skill_id == resolved_skill_id),
            None,
        )
        now = utc_now_iso()
        if not proposal:
            receipt = {
                "schema": "fluxio.skill_repair_apply_receipt.v1",
                "receiptId": f"skill_repair_apply_{uuid.uuid4().hex[:10]}",
                "generatedAt": now,
                "proposalId": proposal_id,
                "skillId": resolved_skill_id,
                "status": "error",
                "error": "repair_proposal_not_found",
                "nextAction": "Record a high-gap slice so a repair proposal exists before applying it.",
            }
            self.repair_receipts.append(receipt)
            self._save_repair_receipts()
            return receipt
        if learned is None:
            receipt = {
                "schema": "fluxio.skill_repair_apply_receipt.v1",
                "receiptId": f"skill_repair_apply_{uuid.uuid4().hex[:10]}",
                "generatedAt": now,
                "proposalId": str(proposal.get("proposalId") or proposal_id),
                "skillId": resolved_skill_id,
                "status": "skipped",
                "error": "skill_not_editable_learned_skill",
                "nextAction": "Convert or promote this skill into an editable learned skill before applying repair patches.",
            }
            self.repair_receipts.append(receipt)
            self._save_repair_receipts()
            return receipt

        repair_patch = proposal.get("repairPatch", {}) if isinstance(proposal.get("repairPatch"), dict) else {}
        prompt_hint = str(repair_patch.get("promptHint") or learned.prompt_hint).strip()
        previous_prompt_hint = learned.prompt_hint
        learned.prompt_hint = prompt_hint
        learned.status = "repair_applied"
        if "repair-applied" not in learned.tags:
            learned.tags.append("repair-applied")
        learned.audit.append(
            f"{now}: applied repair proposal {proposal.get('proposalId') or proposal_id} by {reviewer}"
        )
        learned.updated_at = now
        self._save_learned_skills()
        receipt = {
            "schema": "fluxio.skill_repair_apply_receipt.v1",
            "receiptId": f"skill_repair_apply_{uuid.uuid4().hex[:10]}",
            "generatedAt": now,
            "proposalId": str(proposal.get("proposalId") or proposal_id),
            "skillId": learned.skill_id,
            "label": learned.label,
            "status": "applied",
            "reviewer": reviewer,
            "validationMissionId": validation_mission_id,
            "validationStepId": validation_step_id,
            "beforePromptHint": previous_prompt_hint,
            "afterPromptHint": learned.prompt_hint,
            "afterVerification": proposal.get("afterVerification", {}),
            "nextAction": "Run one clean validation slice before preferring this repaired skill again.",
        }
        self.repair_receipts.append(receipt)
        self._save_repair_receipts()
        return receipt

    def retrieve(
        self,
        task_brief: str,
        top_k: int = 4,
    ) -> list[dict]:
        candidate_count = max(top_k * 3, top_k + 4)
        curated = self.registry.retrieve(task_brief=task_brief, top_k=candidate_count)
        learned_candidates = [
            item for item in self.learned_skills if not item.disabled
        ]
        query_tokens = _tokenize(task_brief)

        def learned_score(item: LearnedSkill) -> tuple[int, float, int]:
            text_tokens = _tokenize(
                " ".join([item.label, item.description, item.prompt_hint, " ".join(item.tags)])
            )
            return len(query_tokens & text_tokens), item.confidence, item.usage_count

        ranked_learned = sorted(
            learned_candidates, key=learned_score, reverse=True
        )[:candidate_count]
        merged: list[dict] = []
        for index, skill in enumerate(curated):
            row = {
                "skillId": skill.name,
                "label": skill.name.replace("_", " ").title(),
                "description": skill.description,
                "permissions": skill.permissions,
                "sourceKind": "curated",
                "actionKinds": skill.action_kinds,
                "profileSuitability": skill.profile_suitability,
                "guidanceOnly": skill.guidance_only,
                "executionCapable": skill.execution_capable,
                "_baseRank": index,
            }
            feedback_summary = self._feedback_summary(row, skill.name)
            row["feedbackSummary"] = feedback_summary
            row["selectionPolicy"] = feedback_summary.get("selectionPolicy", {})
            row["systemLossHold"] = self._system_loss_hold(feedback_summary)
            merged.append(row)
        for index, skill in enumerate(ranked_learned):
            row = {
                "skillId": skill.skill_id,
                "label": skill.label,
                "description": skill.description,
                "permissions": skill.permissions,
                "sourceKind": "learned",
                "confidence": skill.confidence,
                "actionKinds": skill.tags,
                "profileSuitability": ["builder", "advanced", "experimental"],
                "guidanceOnly": False,
                "executionCapable": True,
                "_baseRank": index + len(curated),
            }
            feedback_summary = self._feedback_summary(row, skill.skill_id)
            row["feedbackSummary"] = feedback_summary
            row["selectionPolicy"] = feedback_summary.get("selectionPolicy", {})
            row["systemLossHold"] = self._system_loss_hold(feedback_summary)
            merged.append(row)

        def retrieval_priority(item: dict) -> tuple[float, float, int]:
            text_tokens = _tokenize(
                " ".join(
                    [
                        str(item.get("skillId") or ""),
                        str(item.get("label") or ""),
                        str(item.get("description") or ""),
                        " ".join(str(value) for value in item.get("actionKinds", []) or []),
                    ]
                )
            )
            relevance = len(query_tokens & text_tokens)
            selection_weight = float(
                item.get("selectionPolicy", {}).get("selectionWeight", 0.0) or 0.0
            )
            confidence = float(item.get("confidence", 0.5) or 0.5)
            return (
                relevance * 100.0 + selection_weight + confidence * 10.0,
                -float(item.get("_baseRank", 0)),
                -len(str(item.get("skillId") or "")),
            )

        eligible = [
            item
            for item in merged
            if not bool(item.get("systemLossHold", {}).get("held"))
        ]
        ranked = sorted(eligible, key=retrieval_priority, reverse=True)
        for item in ranked:
            item.pop("_baseRank", None)
        return ranked[:top_k]

    def record_usage(
        self,
        skill_id: str,
        label: str,
        step_id: str,
        mission_id: str,
        helped: bool,
        source_kind: str,
    ) -> SkillUsageRecord:
        record = SkillUsageRecord(
            skill_id=skill_id,
            label=label,
            step_id=step_id,
            mission_id=mission_id,
            helped=helped,
            source_kind=source_kind,
        )
        self.usage_records.append(record)
        self._save_usage_records()
        for learned in self.learned_skills:
            if learned.skill_id == skill_id:
                learned.usage_count += 1
                learned.last_used_at = record.created_at
                learned.updated_at = record.created_at
        self._save_learned_skills()
        return record

    def suggest_promotions(
        self,
        mission_id: str,
        objective: str,
        selected_skills: list[dict],
        verification_failures: list[str],
    ) -> list[SkillPromotionCandidate]:
        if verification_failures:
            return []

        candidates: list[SkillPromotionCandidate] = []
        lowered = objective.lower()
        if "test" in lowered or "verify" in lowered:
            candidates.append(
                SkillPromotionCandidate(
                    candidate_id=f"promo_{uuid.uuid4().hex[:10]}",
                    label="Verification Loop",
                    reason="Successful missions repeatedly benefit from a shared verification routine.",
                    confidence=0.74,
                    evidence=[item["label"] for item in selected_skills],
                )
            )
        if "repo" in lowered or "workspace" in lowered or "control" in lowered:
            candidates.append(
                SkillPromotionCandidate(
                    candidate_id=f"promo_{uuid.uuid4().hex[:10]}",
                    label="Repo Grounding Loop",
                    reason="The harness repeatedly grounded itself in workspace structure before acting.",
                    confidence=0.68,
                    evidence=[mission_id],
                )
            )
        return candidates

    def promote_candidates(
        self,
        candidates: list[SkillPromotionCandidate],
    ) -> list[LearnedSkill]:
        promoted: list[LearnedSkill] = []
        for candidate in candidates:
            existing = next(
                (item for item in self.learned_skills if item.label == candidate.label),
                None,
            )
            if existing:
                existing.confidence = max(existing.confidence, candidate.confidence)
                existing.usage_count += 1
                existing.audit.append(
                    f"{utc_now_iso()}: reinforced by promotion candidate {candidate.candidate_id}"
                )
                existing.updated_at = utc_now_iso()
                promoted.append(existing)
                continue

            learned = LearnedSkill(
                skill_id=f"learned_{uuid.uuid4().hex[:10]}",
                label=candidate.label,
                description=candidate.reason,
                prompt_hint="Apply this learned pattern when the mission matches previous successful evidence.",
                source=SkillSource(kind="learned", label="Learned"),
                confidence=candidate.confidence,
                usage_count=1,
                audit=[
                    f"{utc_now_iso()}: promoted from candidate {candidate.candidate_id}"
                ],
                tags=["learned", "reviewable"],
            )
            self.learned_skills.append(learned)
            promoted.append(learned)
        self._save_learned_skills()
        return promoted

    @staticmethod
    def recommended_packs_from_skills(
        recommendations: list[dict],
    ) -> list[SkillPack]:
        packs: list[SkillPack] = []
        for item in recommendations:
            packs.append(
                SkillPack(
                    pack_id=f"recommended:{item['recommendation_id']}",
                    label=item["label"],
                    description=item["reason"],
                    source=SkillSource(kind="recommended", label="Recommended"),
                    recommended=True,
                    installed=False,
                    skills=[item["recommendation_id"]],
                    permissions=["file_read"],
                    audience="guided",
                    action_kinds=["workspace_search", "file_read"],
                    profile_suitability=["beginner", "builder"],
                    guidance_only=False,
                    execution_capable=True,
                )
            )
        return packs
