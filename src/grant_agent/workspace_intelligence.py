"""Artifact rationale, self-defending obligations, and executable handoffs."""

from __future__ import annotations
import copy, hashlib, json, os, re, time, uuid
from pathlib import Path
from .durability import atomic_write_json, append_jsonl_durable
from .harness_jobs import _exclusive_job_lock

SCHEMA = "neyvia.workspace_intelligence.v1"
COLLABORATION_DEFAULTS = {
    "clarification": "adaptive",
    "directions": "adaptive",
    "learning": False,
    "evaluation": False,
    "rehearsal": False,
}
COLLABORATION_FEATURE_TOOLS = {
    **dict.fromkeys(("lab.competition", "lab.compare", "lab.causal", "behavior.create", "behavior.observe", "attention.create", "attention.observe"), "evaluation"),
    "lab.rehearse": "rehearsal",
    "experience.note": "learning",
}
# These update only validated task records, like the existing question tool.
# They grant no source editing, browser action, execution, or operator authority.
COLLABORATION_NOTE_TOOLS = frozenset({"intelligence.brief", "experience.note", "intelligence.ask_self", "intelligence.answer_self"})


def require_collaboration_feature(root, work_id, tool_name):
    required = COLLABORATION_FEATURE_TOOLS.get(tool_name)
    if required and (not work_id or not WorkspaceIntelligence(root, work_id).collaboration()["preferences"][required]):
        raise PermissionError(f"The user has not enabled {required} for this task. Ordinary completion checks remain available.")


def _brief_text(value, label, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label} must be text of at most {maximum} characters")
    return value.strip()


def _brief_list(value, label, maximum=12):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} entries")
    return [_brief_text(item, label, 1000) for item in value]


def _hash(v):
    return hashlib.sha256(
        json.dumps(
            v, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _safe(v):
    raw = str(v)
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip(".-")[:100] or "work"
    return (
        slug
        if slug == raw
        else slug + "-" + hashlib.sha256(raw.encode()).hexdigest()[:10]
    )


class WorkspaceIntelligence:
    def __init__(self, root: str | Path, work_id: str):
        self.root = Path(root).resolve()
        self.work_id = _safe(work_id)
        self.base = self.root / ".agent_control" / "workspace_intelligence"
        self.base.mkdir(parents=True, exist_ok=True)
        self.path = self.base / f"{self.work_id}.json"
        self.events = self.base / f"{self.work_id}.events.jsonl"
        with _exclusive_job_lock(self.path):
            if not self.path.exists():
                self._write(
                    {
                        "schema": SCHEMA,
                        "workId": self.work_id,
                        "revision": 0,
                        "rationales": [],
                        "obligations": [],
                    }
                )

    def _read(self):
        try:
            state = json.loads(self.path.read_text(encoding="utf8"))
        except FileNotFoundError:
            raise ValueError("missing workspace intelligence")
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError("corrupt workspace intelligence") from e
        if state.get("schema") != SCHEMA or state.get("workId") != self.work_id:
            raise ValueError("workspace identity mismatch")
        expected = state.get("integritySha256")
        if expected != _hash(
            {k: v for k, v in state.items() if k != "integritySha256"}
        ):
            raise ValueError("workspace integrity mismatch")
        return state

    def _write(self, s):
        s["integritySha256"] = _hash(
            {k: v for k, v in s.items() if k != "integritySha256"}
        )
        atomic_write_json(self.path, s)

    def _mutate(self, kind, payload, fn):
        if len(json.dumps(payload).encode()) > 128000:
            raise ValueError("Workspace record is too large")
        with _exclusive_job_lock(self.path):
            s = self._read()
            fn(s)
            s["revision"] = int(s.get("revision", 0)) + 1
            self._write(s)
            append_jsonl_durable(
                self.events,
                {"kind": kind, "revision": s["revision"], "payload": payload},
            )
            return copy.deepcopy(s)

    def snapshot(self):
        return copy.deepcopy(self._read())

    def collaboration(self):
        state = self._read()
        saved = state.get("collaboration") or {}
        return {
            "revision": saved.get("revision", 0),
            "preferences": {**COLLABORATION_DEFAULTS, **saved.get("preferences", {})},
            "brief": copy.deepcopy(state.get("brief")),
            "artifactPath": self.path.relative_to(self.root).as_posix(),
        }

    def ask_self(self, question, decision):
        question = _brief_text(question, "question", 1200)
        decision = _brief_text(decision, "decision this question changes", 1200)
        if not question or not decision:
            raise ValueError("A concrete question and affected decision are required")
        row = {"id": "self-" + uuid.uuid4().hex[:16], "question": question,
               "decision": decision, "answer": None, "checks": [], "revision": 0,
               "status": "open", "source": "agent_report", "authorityGranted": False}
        def update(state):
            rows = state.setdefault("selfQuestions", [])
            if len(rows) >= 200:
                raise ValueError("This task already has 200 self-checks; retrieve and reuse existing questions")
            rows.append(row)
        self._mutate("self_question", row, update)
        return row

    def answer_self(self, question_id, answer, checks, expected_revision):
        answer = _brief_text(answer, "answer", 4000)
        if not answer or not isinstance(checks, list) or not 1 <= len(checks) <= 12 or any(not isinstance(item, str) for item in checks) or len(set(checks)) != len(checks):
            raise ValueError("An answer and distinct saved artifact obligation IDs are required")
        observations = {row["id"]: row for row in self.evaluate_obligations()}
        if any(identity not in observations for identity in checks):
            raise ValueError("Every check must identify an existing task obligation")
        verified = all(observations[identity]["status"] == "verified" and not observations[identity]["artifactChanged"] for identity in checks)
        updated = {}
        def update(state):
            row = next((item for item in state.get("selfQuestions", []) if item["id"] == question_id), None)
            if row is None:
                raise ValueError("Unknown self-question")
            if type(expected_revision) is not int or row["revision"] != expected_revision:
                raise ValueError("Self-question changed; retrieve it before answering")
            row.update(answer=answer, checks=checks, revision=expected_revision + 1,
                       status="supported_report" if verified else "needs_recheck",
                       evidence=[observations[identity] for identity in checks])
            updated.update(row)
        self._mutate("self_answer", {"questionId": question_id, "answer": answer, "checks": checks}, update)
        return {**updated, "boundary": "Declared artifact checks support a reported answer; semantic correctness is not independently established"}

    def self_questions(self, max_characters=2400):
        if type(max_characters) is not int or not 600 <= max_characters <= 16000:
            raise ValueError("Self-question view budget must be 600 to 16000 characters")
        rows = copy.deepcopy(self._read().get("selfQuestions", []))
        observed = {item["id"]: item for item in self.evaluate_obligations()} if any(row.get("checks") for row in rows) else {}
        for row in rows:
            if row.get("answer") and not all(observed.get(key, {}).get("status") == "verified" and not observed[key]["artifactChanged"] for key in row["checks"]):
                row["status"] = "needs_recheck"
        packet = {"workId": self.work_id, "questions": [], "omittedCount": 0,
                  "retrieval": {"tool": "intelligence.read", "workId": self.work_id, "arguments": {}},
                  "authorityGranted": False}
        for row in sorted(rows, key=lambda item: item["status"] == "supported_report"):
            packet["questions"].append(row)
            if len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"))) > max_characters - 80:
                packet["questions"].pop()
        packet["omittedCount"] = len(rows)-len(packet["questions"])
        return packet

    def collaboration_context(self, *, max_characters=10000):
        if type(max_characters) is not int or not 800 <= max_characters <= 24000:
            raise ValueError("Collaboration context budget must be 800 to 24000 characters")
        packet = {"workId": self.work_id, **self.collaboration(), "sourceTrust": "scoped_task_data",
                  "authorityGranted": False, "retrieval": {"tool": "intelligence.collaboration", "workId": self.work_id, "arguments": {}}}
        raw = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        if len(raw) > max_characters:
            brief = packet["brief"] or {}
            packet["brief"] = {"revision": brief.get("revision"), "requiresRetrieval": True,
                               "reason": "The exact brief and corrections exceed this view budget"}
            packet["requiresBriefRetrieval"] = True
        else:
            packet["requiresBriefRetrieval"] = False
        return packet

    def configure_collaboration(self, preferences, *, expected_revision, operator_identity):
        if not isinstance(operator_identity, str) or not operator_identity.strip():
            raise PermissionError("An authenticated operator must change collaboration preferences")
        if not isinstance(preferences, dict) or set(preferences) - set(COLLABORATION_DEFAULTS):
            raise ValueError("Unknown collaboration preferences")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("A collaboration revision is required")
        for key, value in preferences.items():
            if key in {"learning", "evaluation", "rehearsal"}:
                if type(value) is not bool:
                    raise ValueError(f"{key} must be boolean")
            elif not isinstance(value, str) or value not in ({"adaptive", "thorough", "minimal"} if key == "clarification" else {"adaptive", "varied", "focused"}):
                raise ValueError(f"Unsupported {key} preference")

        def update(state):
            old = state.get("collaboration") or {}
            if old.get("revision", 0) != expected_revision:
                raise ValueError("Collaboration preferences changed; reload before saving")
            state["collaboration"] = {
                "revision": expected_revision + 1,
                "preferences": {**COLLABORATION_DEFAULTS, **old.get("preferences", {}), **preferences},
                "source": operator_identity,
                "updatedAt": time.time(),
            }
        self._mutate("collaboration_configured", {"preferences": preferences, "operator": operator_identity}, update)
        return self.collaboration()

    def propose_brief(self, understanding, *, expected_revision=0, assumptions=None, directions=None, open_questions=None):
        retain_assumptions, retain_directions, retain_questions = assumptions is None, directions is None, open_questions is None
        understanding = _brief_text(understanding, "understanding", 6000)
        if not understanding:
            raise ValueError("An understanding is required")
        assumptions = _brief_list(assumptions if assumptions is not None else [], "assumptions")
        questions = _brief_list(open_questions if open_questions is not None else [], "open questions")
        directions = [] if directions is None else directions
        if not isinstance(directions, list) or len(directions) > 4:
            raise ValueError("Provide at most four distinct directions")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("A brief revision is required")
        normalized = []
        for item in directions:
            if not isinstance(item, dict) or set(item) != {"id", "title", "approach", "tradeoff"}:
                raise ValueError("Each direction requires id, title, approach, and tradeoff")
            row = {key: _brief_text(value, key, 1500 if key in {"approach", "tradeoff"} else 120) for key, value in item.items()}
            if not all(row.values()) or any(old["id"] == row["id"] for old in normalized):
                raise ValueError("Directions require nonempty fields and unique identities")
            normalized.append(row)

        def update(state):
            old = state.get("brief") or {}
            if old.get("revision", 0) != expected_revision:
                raise ValueError("The brief changed; reload before revising it")
            next_directions = old.get("directions", []) if retain_directions else normalized
            # A model proposal cannot erase an operator correction or reinterpret
            # a previously selected direction under the same identifier.
            selected = old.get("selection")
            if selected:
                before = next((d for d in old.get("directions", []) if d["id"] == selected["id"]), None)
                after = next((d for d in next_directions if d["id"] == selected["id"]), None)
                if before != after:
                    raise ValueError("Preserve the selected direction; request a user correction before changing it")
            state["brief"] = {
                "revision": expected_revision + 1, "understanding": understanding,
                "assumptions": old.get("assumptions", []) if retain_assumptions else assumptions, "directions": next_directions,
                "openQuestions": old.get("openQuestions", []) if retain_questions else questions, "selection": selected,
                "corrections": old.get("corrections", []),
                "source": "agent_proposal", "updatedAt": time.time(),
                "authorityGranted": False,
            }
        self._mutate("brief_proposed", {"understanding": understanding}, update)
        return self.collaboration()

    def review_brief(self, *, expected_revision, operator_identity, direction_id=None, correction=None):
        if not isinstance(operator_identity, str) or not operator_identity.strip():
            raise PermissionError("An authenticated operator must review the brief")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("An existing brief revision is required")
        if direction_id is None and correction is None:
            raise ValueError("Choose a direction or supply a correction")
        if correction is not None:
            correction = _brief_text(correction, "correction", 6000)
            if not correction:
                raise ValueError("The correction cannot be empty")

        def update(state):
            brief = state.get("brief") or {}
            if brief.get("revision") != expected_revision:
                raise ValueError("The brief changed; reload before applying your answer")
            if direction_id is not None:
                if not any(d["id"] == direction_id for d in brief.get("directions", [])):
                    raise ValueError("Direction does not belong to this brief")
                brief["selection"] = {"id": direction_id, "source": operator_identity, "selectedAt": time.time()}
            if correction:
                if len(brief.get("corrections", [])) >= 100:
                    raise ValueError("This brief has reached its correction limit; preserve it and begin a new work item")
                brief.setdefault("corrections", []).append({"text": correction, "source": operator_identity, "createdAt": time.time()})
            brief["revision"] += 1
            brief["updatedAt"] = time.time()
        self._mutate("brief_reviewed", {"directionId": direction_id, "correction": correction, "operator": operator_identity}, update)
        return self.collaboration()

    def rationale(self, element_id, purpose, protected_decisions=(), evidence_refs=()):
        if not str(element_id).strip() or not str(purpose).strip():
            raise ValueError("Element and purpose are required")
        row = {
            "id": str(element_id),
            "purpose": str(purpose),
            "protectedDecisions": list(protected_decisions),
            "evidenceRefs": list(evidence_refs),
            "version": uuid.uuid4().hex,
            "createdAt": time.time(),
        }
        return self._mutate("rationale", row, lambda s: s["rationales"].append(row))

    def list_rationales(self, limit=50):
        return self.snapshot()["rationales"][-max(1, min(int(limit), 200)) :]

    def read_rationale(self, element_id):
        return next(
            (
                x
                for x in reversed(self.snapshot()["rationales"])
                if x["id"] == str(element_id)
            ),
            None,
        )

    def attach_obligation(self, artifact, sha256, criterion, *, scope=""):
        path = (self.root / str(artifact)).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("artifact outside workspace")
        if not path.is_file():
            raise FileNotFoundError(path)
        if not sha256 or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise ValueError("artifact hash mismatch")
        if not isinstance(criterion, dict) or criterion.get("type") not in {
            "file_contains",
            "json_path",
        }:
            raise ValueError("unsupported obligation criterion")
        if criterion["type"] == "file_contains" and not criterion.get("text"):
            raise ValueError("Nonempty text required")
        if criterion["type"] == "json_path" and (
            not criterion.get("path") or "equals" not in criterion
        ):
            raise ValueError("JSON path and expected value required")
        row = {
            "id": "obl-" + uuid.uuid4().hex[:12],
            "artifact": str(path.relative_to(self.root)),
            "sha256": str(sha256),
            "criterion": criterion,
            "scope": scope,
            "createdAt": time.time(),
        }
        return self._mutate("obligation", row, lambda s: s["obligations"].append(row))

    def evaluate_obligations(self, limit=200):
        out = []
        for o in self.snapshot()["obligations"][-max(1, min(int(limit), 200)) :]:
            p = (self.root / o["artifact"]).resolve()
            safe = self.root in p.parents and p != self.root
            digest = (
                hashlib.sha256(p.read_bytes()).hexdigest()
                if safe and p.is_file()
                else None
            )
            result = False
            if safe and digest is not None:
                c = o["criterion"]
                if c.get("type") == "file_contains":
                    result = c.get("text", "") in p.read_text(encoding="utf8")
                elif c.get("type") == "json_path":
                    try:
                        cur = json.loads(p.read_text(encoding="utf8"))
                        for part in str(c.get("path", "")).strip(".").split("."):
                            cur = cur[part] if isinstance(cur, dict) else cur[int(part)]
                        result = cur == c.get("equals")
                    except (OSError, ValueError, KeyError, IndexError, TypeError):
                        result = False
            out.append(
                {
                    "id": o["id"],
                    "artifact": o["artifact"],
                    "status": "verified" if result else "failed",
                    "observedSha256": digest,
                    "artifactChanged": digest != o["sha256"],
                    "claim": "declared artifact criterion only",
                }
            )
        return out

    def export_handoff(self, objective, protected_decisions, answers):
        if (
            not str(objective).strip()
            or not protected_decisions
            or set(protected_decisions) != set(answers)
        ):
            raise ValueError(
                "Objective and answers for every protected decision are required"
            )
        obligations = self.snapshot()["obligations"]
        value = {
            "schema": "neyvia.workspace_handoff.v1",
            "handoffId": uuid.uuid4().hex,
            "workId": self.work_id,
            "objective": objective,
            "protectedDecisions": list(protected_decisions),
            "answers": dict(answers),
            "artifacts": [
                {
                    "path": o["artifact"],
                    "sha256": o["sha256"],
                    "retrieval": str(self.root / o["artifact"]),
                    "obligationId": o["id"],
                }
                for o in obligations
            ],
        }
        value["integritySha256"] = _hash(value)
        atomic_write_json(
            self.base / (self.work_id + "-handoff-" + value["handoffId"] + ".json"),
            value,
        )
        return copy.deepcopy(value)

    def resume_handoff(self, handoff, objective, answers):
        identity = handoff.get("handoffId") if isinstance(handoff, dict) else handoff
        if not re.fullmatch("[a-f0-9]{32}", str(identity)):
            raise ValueError("Invalid handoff identity")
        saved = json.loads(
            (self.base / (self.work_id + "-handoff-" + identity + ".json")).read_text(
                encoding="utf-8"
            )
        )
        if saved.get("integritySha256") != _hash(
            {k: v for k, v in saved.items() if k != "integritySha256"}
        ):
            raise ValueError("Handoff integrity mismatch")
        if isinstance(handoff, dict) and handoff != saved:
            raise ValueError("Handoff differs from saved version")
        handoff = saved
        if handoff.get("objective") != objective or dict(
            handoff.get("answers", {})
        ) != dict(answers):
            return {"ok": False, "reason": "protected_answers_mismatch"}
        for a in handoff.get("artifacts", []):
            p = (self.root / a["path"]).resolve()
            if (
                not p.is_file()
                or self.root not in p.parents
                or hashlib.sha256(p.read_bytes()).hexdigest() != a["sha256"]
            ):
                return {
                    "ok": False,
                    "reason": "artifact_missing_or_changed",
                    "artifact": a["path"],
                }
        return {
            "ok": True,
            "workId": self.work_id,
            "objective": objective,
            "protectedDecisions": handoff.get("protectedDecisions", []),
        }
