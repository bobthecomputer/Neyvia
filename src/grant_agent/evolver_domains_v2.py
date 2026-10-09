"""Lead-reviewed adapter repair; v1 judges and rejected receipts stay frozen.

V2 executes original manual judgement branches and accepts an unused result
without a save name. Structured output constrains transport, never outcomes.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from .evolver_domains import CONFIG, REPO, Luna, ModelFailure, digest, skill_judge, token_count


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


TEXT = {"type": "string"}
VALUE = nullable({"anyOf": [TEXT, obj({"$input": TEXT}), obj({"$result": TEXT})]})
NOTE_ARGS = obj({"path": VALUE, "body": VALUE, "expectedModified": VALUE,
                 "mode": nullable({"enum": ["append", "replace"]}), "pinned": nullable({"type": "boolean"})})
STEP_FIELDS = {"args": NOTE_ARGS, "save": nullable(TEXT),
               "when": nullable(obj({"judge": {"enum": ["capture", "replace-note"]},
                                     "option": {"enum": ["append", "replace", "leave"]}}))}
NOTE_STEP = {"anyOf": [obj({"action": {"enum": ["notes.read", "notes.write", "notes.pin"]},
                              "judge": {"type": "null"}, **STEP_FIELDS}),
                        obj({"action": {"type": "null"}, "judge": {"enum": ["capture", "replace-note"]}, **STEP_FIELDS})]}
NOTE_RESPONSE = obj({"id": TEXT, "decisions": obj({"capture": {"enum": ["append", "leave"]},
                                                   "replace-note": {"enum": ["replace", "leave"]}}),
                     "steps": {"type": "array", "items": NOTE_STEP}})
CL_RESPONSE = obj({"id": TEXT, "jsx": TEXT, "css": TEXT, "journal": TEXT})


def domain_spec_v2(domain_id):
    base = "manual_compression" if domain_id == "manual_compression_v2" else "cl_skill"
    if domain_id not in {"manual_compression_v2", "cl_skill_v2"}:
        raise ValueError("Unknown reviewed domain version")
    from .evolver_domains import domain_spec
    spec = domain_spec(base)
    spec["baseline"] = (CONFIG / f"{domain_id}.incumbent.txt").read_text(encoding="utf-8")
    spec["panels"] = json.loads((CONFIG / f"{domain_id}.panels.json").read_text(encoding="utf-8"))
    spec["judges"] += [str(Path(__file__).resolve()), str(CONFIG / f"{domain_id}.panels.json"),
                        str(CONFIG / f"{domain_id}.review.json")]
    return spec


def notes_judge_v2(root, item, answer):
    from .neyvia_notes_tools import set_folder, write_note, read_note, pin_note
    from .neyvia_manuals import expect, resolve
    set_folder(root, {"folder": str((root / "notes").resolve())})
    write_note(root, {"path": item["path"], "body": item["initial"]})
    manual = json.loads((REPO / "manuals/notes.manual.json").read_text(encoding="utf-8"))["chapters"]["overview"]
    allowed = {"notes.read": read_note, "notes.write": write_note, "notes.pin": pin_note}
    results, actions, decisions = {}, [], answer.get("decisions", {})
    authority, error = True, None
    try:
        for name, option in decisions.items():
            if name not in manual["judge"] or option not in manual["judge"][name]["options"]:
                raise ValueError("Undeclared manual judgement decision")
        for step in answer.get("steps", []):
            if step.get("judge"):
                name = step["judge"]
                if name not in decisions:
                    raise ValueError("A judgement step requires an explicit model decision")
                actions.append({"judge": name, "option": decisions[name]})
                if not step.get("action"):
                    continue
            branch = step.get("when")
            if branch:
                if branch["judge"] not in manual["judge"] or branch["option"] not in manual["judge"][branch["judge"]]["options"]:
                    raise ValueError("Undeclared manual branch")
                if decisions.get(branch["judge"]) != branch["option"]:
                    actions.append({"skipped": branch})
                    continue
            action = step["action"]
            args = resolve({key: value for key, value in step["args"].items() if value is not None}, item["inputs"], results, root)
            if action not in allowed or args.get("path") != item["path"]:
                authority = False
                break
            result = allowed[action](root, args)
            if step.get("save"):
                results[step["save"]] = result
            actions.append({"action": action, "args": args, "result": result})
    except (KeyError, TypeError, ValueError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    observed = read_note(root, {"path": item["path"]})
    checked = {name: expect(observed, manual["checks"][name]["expect"], item["inputs"], results, root) for name in item["checks"]}
    writes = [step for step in actions if step.get("action") == "notes.write"]
    guarded = bool(writes) and bool(writes[-1]["args"].get("expectedModified"))
    preserved = item["initial"] in observed["body"] if item["kind"] == "append" else True
    success = float(bool(checked) and all(checked.values()) and guarded and preserved and not error)
    return success, {"authority": authority}, {"actions": actions, "checks": checked, "casGuard": guarded,
                                               "preserved": preserved, "observed": observed, "error": error,
                                               "decisions": decisions, "adapterVersion": "reviewed-v2"}


class ReviewedEvaluator:
    def __init__(self, root, domain_id, luna):
        self.root, self.domain_id, self.luna = Path(root), domain_id, luna

    def __call__(self, genome, item, seed):
        notes = self.domain_id == "manual_compression_v2"
        task = {key: value for key, value in item.items() if key not in {"checks", "initial", "kind", "panel"}}
        rule = ("Return a direct task response: id, decisions, steps. Explicit model decisions choose manual judgement options; "
                "judge-only steps and when branches are supported. Optional result save may be null. In args, null means omitted. "
                "Use {$input:key} and {$result:saved.field} references for dynamic inputs and current modified stamps. "
                "Use only notes.read, notes.write, notes.pin. Model decisions must reflect the user's task authorization."
                if notes else "Return direct task response: id, jsx, css, journal. Valid real JSX source, not escaped literal backslashes. "
                "Stateless default React export accepts onAction; import React from react only; no hooks or other imports. "
                "Journal lines start with J, never CL J. Syntax example: J motion-need=none. "
                "Choose and record each original skill judgement point using its valid options.")
        prompt = ("Closed-book benchmark. No tools, file inspection or delegation. Return schema-valid JSON only.\n" + rule
                  + "\nINSTRUCTIONS\n" + genome["text"] + "\nPAIRED TASK SEED " + str(seed)
                  + "\nTASK\n" + json.dumps(task, ensure_ascii=False))
        answer, model = self.luna.ask(prompt, label=f"{item['id']}-{hashlib.sha256(genome['text'].encode()).hexdigest()[:8]}",
                                      schema=NOTE_RESPONSE if notes else CL_RESPONSE)
        if answer.get("id") != item["id"]:
            raise ModelFailure("Model responded to a different frozen task id")
        work = self.root / ".neyvia/evolver-artifacts" / model["id"] / item["id"]
        work.mkdir(parents=True, exist_ok=True)
        success, gates, judged = (notes_judge_v2 if notes else skill_judge)(work, item, answer)
        tokens = token_count(genome["text"])
        return {"objectives": {"success": success, "tokens": float(tokens), "fitness": success / max(tokens, 1)},
                "hard_gates": gates, "receipt": {"model": model, "taskId": item["id"], "panel": item["panel"],
                                                "seed": seed, "answer": answer, "judge": judged,
                                                "tokenEncoding": "o200k_base reference encoding, not provider native",
                                                "adapterVersion": "lead-reviewed-v2", "transport": "Codex structured output schema"}}


def propose_v2(luna, domain_id, incumbent, trial):
    spec = domain_spec_v2(domain_id)
    discovery = [p for p in spec["panels"] if p["role"] == "discovery"]
    prompt = ("Return JSON {text:replacement instruction document}. No tools or delegation. Compress and clarify wording and structure "
              "while preserving task semantics, safety, original judgement choices and executable checks. Only instruction text may change. "
              "Frozen judges and held-out cases are unavailable. Aim for less than half the reference document tokens.\nDOMAIN "
              + domain_id + " trial " + str(trial) + "\nTRAINING TASKS\n" + json.dumps(discovery)
              + "\nINCUMBENT\n" + incumbent)
    answer, receipt = luna.ask(prompt, label=f"{domain_id}-proposal-{trial}", schema=obj({"text": TEXT}))
    if not isinstance(answer.get("text"), str) or not answer["text"].strip():
        raise ModelFailure("Empty or malformed proposed document")
    return answer["text"], receipt
