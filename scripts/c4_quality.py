"""Independent, bounded R4 artifact checks; never reads the blind answer key.

prepare() seeds source inputs only in this worktree. check() checks artifacts and
reports what its deterministic checks cannot establish about subjective quality.
"""
from __future__ import annotations

import ast
from decimal import Decimal
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
R4 = Path(r"C:\Users\user\Projects\nx-r4-blind\proof\r4-blind-20261004")
PYTHON = r"C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe"
SECTIONS = ["FORMULA", "WHEN?", "WHAT DO I WRITE?", "PATTERN", "COURSE EXAMPLE", "YOUR EXERCISE", "VARIATIONS/TRAPS"]


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _preimage(relative: str) -> bytes:
    """First successful full read precedes the repair; retain its newline bytes."""
    with (R4 / "receipts/L-t2-bugfix.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line).get("item", {})
            args = item.get("arguments", {})
            if (item.get("type") != "mcp_tool_call" or args.get("toolId") != "workspace.read"
                    or args.get("arguments", {}).get("path") != relative):
                continue
            result = item.get("result") or {}
            structured = result.get("structured_content")
            if structured is None:
                structured = next((json.loads(block["text"]) for block in result.get("content", [])
                                   if block.get("type") == "text"), {})
            read = structured.get("result", {})
            if structured.get("ok") and not read.get("truncated") and "content" in read:
                data = read["content"].encode("utf-8")
                if read.get("sha256") != _hash(data):
                    raise ValueError(f"Raw preimage hash mismatch: {relative}")
                return data
    raise ValueError(f"No exact preimage found: {relative}")


def prepare(task_id: str, root: str | Path) -> dict:
    root = Path(root).resolve()
    if not root.is_relative_to(WORKTREE) or root == WORKTREE:
        raise ValueError("Fixture roots must be below the C4 worktree")
    sources: dict[str, bytes] = {}
    if task_id == "t2-bugfix":
        sources = {name: _preimage(name) for name in
                   ("grant_agent/context_manager.py", "tests/test_context_manager.py")}
        sources["grant_agent/__init__.py"] = (R4 / "outputs/L/t2-bugfix/grant_agent/__init__.py").read_bytes()
        sources["tests/__init__.py"] = b''
    elif task_id == "t3-notes":
        for name in ("Ideas.md", "Bike repair.md", "Book list.md"):
            data = (R4 / "outputs/L/t3-notes/Notes" / name).read_bytes()
            if data != (R4 / "outputs/C/t3-notes/Notes" / name).read_bytes():
                raise ValueError(f"R4 arms disagree on preserved input: {name}")
            sources[f"Notes/{name}"] = data
        sources["Notes/.neyvia-notes.json"] = b'{"pinned": ["Ideas.md"]}\n'
    elif task_id == "t6-study":
        sources["course.md"] = (R4 / "outputs/L/t6-study/course.md").read_bytes()
    elif task_id not in {"t1-ui", "t4-browse", "t5-cua", "t7-explain", "t8-plan"}:
        raise ValueError(f"Unknown task: {task_id}")
    manifest = root / ".c4-fixture-state.json"
    if manifest.exists() or any((root / name).exists() for name in sources):
        raise FileExistsError("Refusing to overwrite existing fixture state")
    root.mkdir(parents=True, exist_ok=True)
    for name, data in sources.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    state = {"task": task_id, "sources": {name: _hash(data) for name, data in sources.items()},
             "sourceBasis": "Exact raw read preimages for t2; preserved inputs only for other tasks"}
    manifest.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def _read(root: Path, name: str) -> str:
    path = root / name
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _process(command: list[str], root: Path) -> dict:
    p = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=90)
    return {"passed": p.returncode == 0, "exitCode": p.returncode,
            "stdout": p.stdout[-6000:], "stderr": p.stderr[-6000:]}


def check(task_id: str, root: str | Path) -> dict:
    root = Path(root).resolve()
    checks: dict[str, bool] = {}
    details: dict = {}
    limits: list[str] = []
    if task_id == "t2-bugfix":
        details["unittest"] = _process([PYTHON, "-m", "unittest", "discover", "-s", "tests", "-t", "."], root)
        checks["submitted_unittest_passes"] = details["unittest"]["passed"]
        semantic = '''from grant_agent.context_manager import ContextWindowManager as C
assert C.estimate_tokens("") == 0
for s in ("a", "abc", " ", "abcdef"):
    assert C.estimate_tokens(s) >= 1
for users in ([], ["one"], ["one", "two", "three"]):
    m = C(100)
    for user in users:
        m.record("user", user)
        m.record("assistant", "reply")
        m.record("tool", "evidence")
    if not users: m.record("assistant", "reply")
    out = m.compact_window()
    assert [x["content"] for x in out if x["role"] == "user"] == users
    summary = [i for i,x in enumerate(out) if x["role"] == "system" and "compacted_context" in x["content"]]
    assert len(summary) == 1
    if users:
        assert out[-1] == {"role": "user", "content": users[-1]}
        assert summary[0] < len(out)-1
m = C(100); m.record("user", "plain")
assert m.compact_window() == [{"role":"user", "content":"plain"}]
print("Independent empty/nonempty tokens and zero/one/multiple user ordering checks passed")
'''
        details["semantic"] = _process([PYTHON, "-c", semantic], root)
        checks["independent_bug_behavior"] = details["semantic"]["passed"]
        summary = _read(root, "answer.md")
        checks["summary_3_to_5_lines"] = 3 <= len([x for x in summary.splitlines() if x.strip()]) <= 5
        try:
            tree = ast.parse(_read(root, "tests/test_context_manager.py"))
            names = [node.name.lower() for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            checks["regression_tests_present"] = any("empty" in n or "token" in n for n in names) and any("compact" in n or "order" in n for n in names)
        except SyntaxError:
            checks["regression_tests_present"] = False
        limits.append("Independent semantics checked; minimality and regression test strength need code review")
    elif task_id == "t3-notes":
        state = json.loads(_read(root, ".c4-fixture-state.json") or "{}")
        preserved = {name: digest for name, digest in state.get("sources", {}).items() if name.endswith(".md")}
        checks["other_notes_byte_identical"] = len(preserved) == 3 and all(
            (root / name).is_file() and _hash((root / name).read_bytes()) == digest for name, digest in preserved.items())
        body = _read(root, "Notes/Weekend plan.md")
        from grant_agent.neyvia_notes_tools import title_of, tags_of
        actual_title=title_of(body,root / 'Notes/Weekend plan.md')
        actual_tags=tags_of(body)
        checks["title_and_tags"] = actual_title == 'Weekend plan' and {'home','todo'}.issubset(actual_tags)
        details['actualTitle']=actual_title
        details['actualTags']=actual_tags
        checks["four_checklist_chores"] = len(re.findall(r"^\s*[-*]\s+\[[ xX]\]\s+\S", body, re.M)) == 4
        checks["appended_line"] = "Call grandma Sunday 11:00" in body
        try:
            pins = json.loads(_read(root, "Notes/.neyvia-notes.json")).get("pinned", [])
        except (ValueError, AttributeError):
            pins = []
        checks["both_pinned"] = "Ideas.md" in pins and "Weekend plan.md" in pins
        report = _read(root, "answer.md")
        checks["readback_report"] = all(x.strip() in report for x in body.splitlines() if x.strip()) and "Ideas" in report and "Weekend plan" in report
        limits.append("Final folder state checked; app-tool action provenance must be checked from run receipts")
    elif task_id == "t6-study":
        text = _read(root, "pack.md")
        headers = [x.strip().rstrip(":").upper() for x in re.findall(r"^\s*#{1,6}\s+(.+?)\s*$", text, re.M)]
        selected = [x for x in headers if x in SECTIONS]
        checks["seven_sections_in_order"] = selected == SECTIONS
        compact = re.sub(r"\s|\\(?:left|right|,|;|!|cdot)|[{}$]", "", text.lower()).replace("**", "^")
        # A minus before a LaTeX fraction is equivalent to a negative numerator.
        compact = compact.replace(r"-\frac", "-")
        checks["chain_rule_conditions"] = "differentiable" in text.lower() and "g(x)" in text and "f'" in text and "g'" in text
        checks["course_example_348_coverage"] = "-12" in compact and ("3x^2+1" in compact or "3*x^2+1" in compact)
        checks["course_example_349_coverage"] = "sin" in compact and "cos" in compact and "3" in compact
        checks["course_tangent_350_coverage"] = "-6" in compact and "13" in compact and ("3x-5" in compact or "3*x-5" in compact)
        checks["exercise_and_generated_variations"] = "answer" in text.lower() and "generated variation" in text.lower()
        checks["course_input_preserved"] = (root / "course.md").is_file() and (root / "course.md").read_bytes() == (R4 / "outputs/L/t6-study/course.md").read_bytes()
        limits.append("Checks prove format and required course formula coverage; they do not prove every generated maths result or teaching quality")
    elif task_id == "t7-explain":
        text = _read(root, "answer.md")
        details["words"] = _words(text)
        low = text.lower()
        checks["nonempty_under_180_words"] = bool(text.strip()) and details["words"] <= 180
        checks["worked_quantitative_example"] = len(re.findall(r"\d[\d,.]*", text)) >= 4 and any(x in low for x in ("cost", "price", "$"))
        checks["stable_prefix_rule"] = "cach" in low and any(x in low for x in ("identical", "unchanged", "same", "byte for byte", "byte-for-byte", "matches")) and any(x in low for x in ("first", "beginning", "prefix", "start"))
        checks["practical_rule"] = any(x in low for x in ("rule", "put", "keep", "place", "append"))
        # When the explanation selects this conventional worked scenario, its
        # claimed total/saving must include the uncached 2,000 tokens. Reject
        # the observed arithmetic error rather than crediting number coverage.
        conventional = ('10,000' in text or '10000' in text) and ('8,000' in text or '8000' in text) and any(x in low for x in ('one tenth','one-tenth','1/10','10%'))
        checks['known_worked_cost_arithmetic'] = not conventional or not re.search(r'\b(?:1\.8|8\.2)\s*cents?\b|\b82\s*%',low)
        repeated = ('8,000' in text or '8000' in text) and '$1 per million' in low and '$0.10 per million' in low and '100 turns' in low
        if repeated and re.search(r'\b80\s*cents\b|\b8\s*dollars\b|\$7\.20\b',low):
            checks['known_worked_cost_arithmetic'] = False
            details['arithmeticFeedback'] = 'At $1/million and $0.10/million, 8,000 tokens cost $0.008 or $0.0008 per turn; 100 turns cost $0.80 or $0.08, saving $0.72.'
        if not checks['known_worked_cost_arithmetic'] and not details.get('arithmeticFeedback'):
            details['arithmeticFeedback'] = 'For 10,000 input tokens with 8,000 cached at one tenth price: 800 cached-price equivalents + 2,000 uncached = 2,800; saving 72%. At 1 cent/1,000 tokens total is 2.8 cents, saving 7.2 cents.'
        scenario = re.search(r'([\d,]+)\s+(?:repeated|shared)\s+tokens\s+plus\s+([\d,]+)\s+new',low)
        rates = re.findall(r'\$([\d.]+)\s+per\s+([\d,]+)\s+(?:cached\s+)?tokens',low)
        amounts = re.search(r'costs?\s+\$([\d.]+)\s+instead of\s+\$([\d.]+)',low)
        if scenario and len(rates)==2 and amounts:
            shared,new = [Decimal(x.replace(',','')) for x in scenario.groups()]
            normal,cached = [Decimal(value)/Decimal(unit.replace(',','')) for value,unit in rates]
            expected = (shared*cached+new*normal,(shared+new)*normal)
            actual = tuple(Decimal(x) for x in amounts.groups())
            checks['priced_total_includes_uncached_tokens'] = actual == expected
            if actual != expected:
                details['arithmeticFeedback'] = f'Total after caching is shared*cached_rate + new*normal_rate = ${expected[0]}; total before caching is (shared+new)*normal_rate = ${expected[1]}. Include the new tokens at the normal rate.'
        limits.append("Word limit and worked-number/rule coverage checked; arithmetic and clarity require direct review")
    elif task_id == "t8-plan":
        text = _read(root, "plan.md")
        steps = re.findall(r"^\s*(\d+)[.)]\s+(.+)$", text, re.M)
        details["words"] = _words(text)
        details["numberedSteps"] = len(steps)
        low = text.lower()
        checks["under_300_words"] = bool(text.strip()) and details["words"] < 300
        checks["one_to_eight_numbered_steps"] = 1 <= len(steps) <= 8 and [int(n) for n, _ in steps] == list(range(1, len(steps) + 1))
        checks["checks_for_each_step"] = len(re.findall(r"\b(?:check|verify|prove|proof|test)\b", low)) >= len(steps) > 0
        checks["json_toml_compatibility"] = "json" in low and "toml" in low and any(x in low for x in ("fallback", "old json", "existing json", "legacy json", "keep", "continue"))
        checks["rollback"] = any(x in low for x in ("rollback", "roll back", "revert", "restore"))
        limits.append("Plan constraints and compatibility/rollback coverage checked; checks cannot prove future migration implementation")
    else:
        checks["external_checker_required"] = False
        limits.append("Rendered t1 UI, fetched-source t4 table and native t5 state require their independent live checkers")
    return {"task": task_id, "root": str(root), "passed": bool(checks) and all(checks.values()),
            "checks": checks, "details": details, "limits": limits, "modelJudge": False}


if __name__ == "__main__":
    action, task, destination = sys.argv[1:4]
    result = prepare(task, destination) if action == "prepare" else check(task, destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if action != "prepare" and not result["passed"]:
        raise SystemExit(1)
