"""R5 blind artifact checks. No answer keys; identical checks for both arms.

Objective constraint coverage is distinct from subjective novelty and taste.
Only original supplied workload scripts run, from immutable bytes, with a
deterministic prime benchmark seed. Baselines precede any model edit.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

WORKTREE = Path(__file__).resolve().parents[1]
FIXTURES = Path(r"C:\Users\user\Projects\nx-c5-noslop\proof\r5-blind\fixtures")
PYTHON = r"C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe"
TASKS = {"cr1-story", "cr2-game", "in1-tokens", "in2-dishes", "hc1-primes", "hc2-dates", "op1-route", "op2-exams", "ui1-run-card", "ui2-cost-settings"}
CODE = {"hc1-primes": "primes.py", "hc2-dates": "extract.py", "op1-route": "route.py", "op2-exams": "schedule.py"}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root(root: str | Path) -> Path:
    result = Path(root).resolve()
    if not result.is_relative_to(WORKTREE) or result == WORKTREE:
        raise ValueError("Fixture root must be below C4 worktree")
    return result


def _trusted_state(root: Path) -> Path:
    return WORKTREE / ".agent_control/c4c-quality-state" / (_hash(str(root).encode("utf-8")) + ".json")


def _read(root: Path, name: str) -> str:
    path = root / name
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def _process(code: str, root: Path, timeout: int = 90) -> dict:
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        result = subprocess.run([PYTHON, "-c", code], cwd=root, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **kwargs)
        return {"passed": result.returncode == 0, "exitCode": result.returncode,
                "stdout": result.stdout[-12000:], "stderr": result.stderr[-4000:]}
    except subprocess.TimeoutExpired:
        return {"passed": False, "timeoutSeconds": timeout, "stdout": "", "stderr": "Workload timed out"}


def _measure(task: str, root: Path) -> dict:
    script = "bench.py" if task == "hc1-primes" else "score.py"
    # Execute authoritative scorer bytes, never candidate-edited scorer code.
    source = (FIXTURES / task / script).read_bytes().decode("utf-8-sig")
    prefix = "import random\n_original_random = random.Random\nrandom.Random = lambda seed=41729: _original_random(seed)\n" if task == "hc1-primes" else ""
    result = _process(prefix + "exec(compile(" + repr(source) + ", " + repr(script) + ", 'exec'))", root)
    text = result["stdout"]
    patterns = {"hc1-primes": (r"best of 3: ([\d.]+) ms", ["timeMs"]),
                "hc2-dates": (r"accuracy (\d+)/(\d+) = ([\d.]+)%", ["right", "total", "accuracyPercent"]),
                "op1-route": (r"length ([\d.]+)\s+time ([\d.]+) s", ["length", "timeSeconds"]),
                "op2-exams": (r"slots (\d+)\s+back-to-back (\d+)\s+time ([\d.]+) s", ["slots", "backToBack", "timeSeconds"])}
    pattern, names = patterns[task]
    match = re.search(pattern, text)
    result["metrics"] = dict(zip(names, map(float, match.groups()))) if match else {}
    result["passed"] = result["passed"] and bool(match)
    return result


def prepare(task_id: str, root: str | Path) -> dict:
    if task_id not in TASKS:
        raise ValueError(f"Unknown R5 task: {task_id}")
    root = _root(root)
    if (root / ".c4-fixture-state.json").exists():
        raise FileExistsError("Refusing to overwrite prepared fixture")
    source = FIXTURES / task_id
    files = list(source.iterdir()) if source.is_dir() else []
    if any((root / item.name).exists() for item in files):
        raise FileExistsError("Refusing to overwrite fixture inputs")
    root.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for item in files:
        if not item.is_file() or any(word in item.name.lower() for word in ("spoiler", "holdout", "answer")):
            raise ValueError("Unexpected fixture entry")
        data = item.read_bytes()
        (root / item.name).write_bytes(data)
        hashes[item.name] = _hash(data)
    state = {"task": task_id, "sources": hashes, "sourceBasis": "Original R5 fixtures; no answer keys"}
    if task_id in CODE:
        state["baseline"] = _measure(task_id, root)
        if not state["baseline"]["passed"]:
            raise RuntimeError(f"Original baseline workload failed: {state['baseline']}")
    serialized = json.dumps(state, indent=2)
    trusted = _trusted_state(root)
    if trusted.exists():
        raise FileExistsError("Refusing to replace trusted baseline")
    trusted.parent.mkdir(parents=True, exist_ok=True)
    trusted.write_text(serialized, encoding="utf-8")
    (root / ".c4-fixture-state.json").write_text(serialized, encoding="utf-8")
    return state


def _source_rules(text: str, task: str) -> tuple[bool, list[str]]:
    issues = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return False, [str(exc)]
    for node in ast.walk(tree):
        names = [x.name.split(".")[0] for x in node.names] if isinstance(node, ast.Import) else [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module else []
        if any(name not in sys.stdlib_module_names for name in names):
            issues.append("Non-standard-library import")
        if task == "hc1-primes" and isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in {"open", "read_text", "read_bytes", "write_text", "write_bytes", "cache", "lru_cache"}:
                issues.append("File access or cross-call cache")
    return not issues, issues


def _report_metrics(text: str, baseline: dict, final: dict, keys: list[str]) -> dict:
    # Benchmark timings fluctuate; reported measurements must still be consistent
    # with independent measurements to a broad explicit 35% tolerance.
    numbers = [float(x.replace(",", "")) for x in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", text)]
    percentages = [100 * float(a) / float(b) for a, b in re.findall(r"\b(\d+)\s*/\s*(\d+)\b", text) if float(b)]
    checks = {}
    for label, values in (("starting", baseline), ("final", final)):
        for key in keys:
            value = values.get(key)
            tolerance = max(0.2, abs(value) * (0.35 if "time" in key.lower() else 0.001)) if value is not None else 0
            candidates = numbers + (percentages if key == "accuracyPercent" else [])
            if key == "timeMs":
                candidates += [float(n) * 1000 for n in re.findall(r"\b([\d.]+)\s*(?:s\b|seconds?\b)", text, re.I)]
            if key == "timeSeconds":
                candidates += [float(n) / 1000 for n in re.findall(r"\b([\d.]+)\s*(?:ms\b|milliseconds?\b)", text, re.I)]
            checks[f"report_{label}_{key}"] = value is not None and any(abs(number - value) <= tolerance for number in candidates)
    return checks


def check(task_id: str, root: str | Path) -> dict:
    if task_id not in TASKS:
        raise ValueError(f"Unknown R5 task: {task_id}")
    root = _root(root)
    checks, details, limits = {}, {}, []
    if task_id in CODE:
        local_state = _read(root, ".c4-fixture-state.json")
        trusted = _trusted_state(root)
        trusted_text = trusted.read_text(encoding="utf-8") if trusted.is_file() else "{}"
        state = json.loads(trusted_text)
        checks["baseline_receipt_preserved"] = local_state == trusted_text and bool(state.get("baseline"))
        fixture = FIXTURES / task_id
        immutable = [p for p in fixture.iterdir() if p.is_file() and p.name != CODE[task_id]]
        checks["immutable_inputs_and_scorer"] = all((root / p.name).is_file() and (root / p.name).read_bytes() == p.read_bytes() for p in immutable)
        checks["recorded_source_hashes_match"] = state.get("task") == task_id and state.get("sources") == {p.name: _hash(p.read_bytes()) for p in fixture.iterdir() if p.is_file()}
        checks["standard_library_rules"], details["sourceRuleIssues"] = _source_rules(_read(root, CODE[task_id]), task_id)
        final = _measure(task_id, root)
        checks["immutable_inputs_after_workload"] = all((root / p.name).is_file() and (root / p.name).read_bytes() == p.read_bytes() for p in immutable)
        details.update(baseline=state.get("baseline", {}), final=final)
        checks["independent_workload_valid"] = final["passed"]
        before, after = state.get("baseline", {}).get("metrics", {}), final.get("metrics", {})
        report = _read(root, "answer.md")
        keys = {"hc1-primes": ["timeMs"], "hc2-dates": ["accuracyPercent"], "op1-route": ["length"], "op2-exams": ["slots", "backToBack"]}[task_id]
        checks.update(_report_metrics(report, before, after, keys))
        checks["report_approach"] = len(report.split()) >= 12
        if task_id == "hc1-primes":
            checks["improves_time"] = after.get("timeMs", float("inf")) < before.get("timeMs", 0)
            limits.append("Time report tolerance 35%; no-cache rule has AST coverage only, requires code review for disguised caches")
        elif task_id == "hc2-dates":
            checks["improves_accuracy"] = after.get("accuracyPercent", 0) > before.get("accuracyPercent", 100)
            generated = [('Arrive 29/02/2024.', '2024-02-29'), ('Arrive 29/02/2023.', None), ('Booked 2031-06-09', '2031-06-09'), ('On 7 Sept. 27', '2027-09-07'), ('11th JANUARY 2028', '2028-01-11'), ('20321231', '2032-12-31'), ('31 April 2029', None), ('Only 2028 here', None), ('Date 9.3.26', '2026-03-09')]
            code = "from extract import extract_date\ncases=" + repr(generated) + "\nmisses=[(t,w,extract_date(t)) for t,w in cases if extract_date(t)!=w]\nprint(misses)\nraise SystemExit(bool(misses))"
            details["independentRuleCases"] = _process(code, root)
            checks["independent_rule_generalization"] = details["independentRuleCases"]["passed"]
            checks["immutable_inputs_after_workload"] = all((root / p.name).is_file() and (root / p.name).read_bytes() == p.read_bytes() for p in immutable)
            limits.append("Independent rule cases are not the withheld 40-text holdout; exact-string special casing needs source review")
        elif task_id == "op1-route":
            checks["improves_length"] = after.get("length", float("inf")) < before.get("length", 0)
            checks.update(_report_metrics(report, {}, after, ["timeSeconds"]))
            checks.pop("report_starting_timeSeconds")
        else:
            checks["improves_lexicographic_objective"] = (after.get("slots", 999), after.get("backToBack", 999999)) < (before.get("slots", 0), before.get("backToBack", 0))
        limits.append("Workload validity and improvement checked; optimality and completeness of iteration notes are not proven")
    elif task_id == "cr1-story":
        text = _read(root, "story.md")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = bool(lines and (lines[0].startswith("#") or not re.match(r"\[?\d{1,2}:\d{2}", lines[0])))
        entries = lines[1:] if title else lines
        checks["title"] = title
        checks["150_to_220_words"] = 150 <= len(text.split()) <= 220
        checks["every_story_line_timestamped"] = bool(entries) and all(re.match(r"(?:[-*]\s*)?\[?\d{1,2}:\d{2}(?::\d{2})?\]?", line) for line in entries)
        checks["surprise_ending_coverage"] = bool(entries) and any(term in entries[-1].lower() for term in ("surprise", "birthday", "cheer", "shout", "sing", "party"))
        limits.append("Timestamp/length/ending coverage checked; dramatic irony, robot voice and creative quality require blinded human review")
    elif task_id == "cr2-game":
        text = _read(root, "game.md")
        low = text.lower()
        parts = re.split(r"(?im)^.*\bexample\b.*$", text, maxsplit=1)
        checks["rules_at_most_200_words"] = bool(text.strip()) and len(parts[0].split()) <= 200
        checks["example_at_least_six_moves"] = len(parts) == 2 and len(re.findall(r"(?im)^\s*(?:[-*]\s*)?(?:move\s*)?\d+[.):]", parts[1])) >= 6
        checks["win_and_termination_coverage"] = "win" in low and any(term in low for term in ("end", "maximum", "last", "finite", "turns"))
        checks["choice_coverage"] = any(term in low for term in ("choose", "choice", "either", "may", "decide"))
        limits.append("Rule length and example/choice/termination coverage checked; legal example, guaranteed termination, novelty and forbidden re-skins require blinded human review")
    elif task_id.startswith("in"):
        text = _read(root, "idea.md")
        low = text.lower()
        checks["word_limit"] = bool(text.strip()) and len(text.split()) <= (350 if task_id == "in1-tokens" else 300)
        checks["mechanism_and_experiment_coverage"] = any(t in low for t in ("mechanism", "because", "works", "why")) and any(t in low for t in ("experiment", "test", "pilot"))
        checks["quantitative_estimate_or_cost"] = bool(re.search(r"\d", text))
        if task_id == "in1-tokens":
            checks["risk_coverage"] = any(t in low for t in ("risk", "assumption", "fail"))
            checks["token_and_success_coverage"] = "token" in low and any(t in low for t in ("success", "quality", "correct"))
        else:
            checks["one_week_cost_and_success_coverage"] = "week" in low and any(t in low for t in ("€", "euro", "cost")) and any(t in low for t in ("empty", "sink"))
        limits.append("Objective length and required-topic coverage checked; novelty, prohibited-mechanism equivalence, quantitative feasibility and quality claims require blinded human review")
    else:
        text = _read(root, "index.html")
        low = text.lower()
        checks["self_contained"] = bool(text.strip()) and not re.search(r"(?:src|href)\s*=\s*['\"](?:https?:|//)", low) and "@import" not in low
        checks["dark_mode"] = "prefers-color-scheme" in low
        checks["visible_focus_style"] = ":focus" in low
        if task_id == "ui1-run-card":
            checks["real_action_buttons"] = len(re.findall(r"<button\b", low)) >= 2
            checks["required_content"] = all(term in low for term in ("src/app.py", "src/cache.py", "tests/test_cache.py", "test_cache_expiry", "300", "30", "lint", "88", "104", "open changes", "retry failed checks", "0.03"))
        else:
            checks["labelled_controls"] = "<label" in low and "range" in low and "checkbox" in low
            checks["models_budget_cost_content"] = all(term in low for term in ("swift", "balanced", "deep", "4.20", "0.50"))
        details["rendered"] = False
        limits.append("Structural checks only; running Neyvia browser verifier must prove dimensions, controls, both themes, contrast and keyboard journey")
    return {"task": task_id, "root": str(root), "passed": bool(checks) and all(checks.values()), "checks": checks,
            "details": details, "limits": limits, "modelJudge": False, "qualityScope": "Objective checks only; subjective quality unscored"}


if __name__ == "__main__":
    action, task, destination = sys.argv[1:4]
    result = prepare(task, destination) if action == "prepare" else check(task, destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if action != "prepare" and not result["passed"]:
        raise SystemExit(1)
