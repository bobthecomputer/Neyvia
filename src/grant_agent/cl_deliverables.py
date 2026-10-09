"""Deliverable observers shared by the CL-Skill CLI and host completion gate.

The reference is proof/c9-deliverables/prototype.py. These are finish checks,
not a replacement for the calibrated pairwise taste judge.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .neyvia_language import TEXT_SUFFIXES, TextOutput, task_artifacts

REPO = Path(__file__).resolve().parents[2]
DELIVERABLE_SUFFIXES = TEXT_SUFFIXES | {".py", ".js", ".ts", ".css", ".scss", ".json", ".csv", ".cl", ".rs", ".cs", ".sql", ".sh", ".ps1", ".yaml", ".yml"}


def document(path: Path, text: str) -> dict[str, Any]:
    kind = "html" if path.suffix.lower() in {".html", ".htm"} else "md" if path.suffix.lower() in {".md", ".txt", ".markdown", ".rst"} else "code"
    lines = text.splitlines()
    result = {"file": str(path), "kind": kind, "words": len(re.findall(r"\w[\w'.%$-]*", text))}
    if kind == "html":
        styles = text
        for tag in re.findall(r'<link\b[^>]*>', text, re.I):
            if not re.search(r'rel\s*=\s*[\"\x27]stylesheet[\"\x27]', tag, re.I): continue
            href = re.search(r'href\s*=\s*[\"\x27]([^\"\x27]+)[\"\x27]', tag, re.I)
            if not href or ':' in href.group(1): continue
            stylesheet = (path.parent / href.group(1).split('?', 1)[0]).resolve()
            if stylesheet.is_relative_to(path.parent.resolve()) and stylesheet.suffix == '.css' and stylesheet.is_file():
                styles += '\n' + stylesheet.read_text(encoding='utf-8')
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
        result.update(title=title.group(1).strip() if title else None,
                      heading=re.sub("<[^>]+>", "", h1.group(1)).strip() if h1 else None,
                      dark=bool(re.search(r"prefers-color-scheme\s*:\s*dark", styles, re.I)),
                      focus=":focus-visible" in styles, motion="prefers-reduced-motion" in styles)
    elif kind == "md":
        # Markdown skills and other authored documents can begin with YAML
        # front matter. Judge their visible title, rather than the delimiter.
        if lines and lines[0].strip() == '---':
            closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == '---'), None)
            if closing is not None:
                metadata = lines[1:closing]
                lines = lines[closing + 1:]
                if not any(re.match(r'^#{1,2}\s+', line) for line in lines if line.strip()):
                    name = next((line.split(':', 1)[1].strip() for line in metadata if line.startswith('name:')), '')
                    if name: lines.insert(0, '# ' + name)
        body = [line for line in lines if line.strip()]
        first = body[0].strip() if body else ""
        title = re.match(r"^#{1,2}\s+(.*)$", first) or re.match(r"^\*\*(.+?)\*\*\s*$", first)
        headings = [re.sub(r"^#+\s+", "", line).strip() for line in lines if re.match(r"^#{1,6}\s+", line)]
        headings += [match.group(1) for line in lines[1:] if (match := re.match(r"^\*\*([^*]{2,60}?)[.:]?\*\*\s*\S", line.strip()))]
        tables = sum(bool(re.fullmatch(r"\s*\|?\s*:?-{3,}.*", line)) for line in lines)
        items = [line for line in lines if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line)]
        numeric = [line for line in items if re.search(r"\d", line)]
        labels = [line for line in lines if re.match(r"^\s*(?:[-*+]\s+)?\**[A-Z][\w /()-]{1,40}\**\s*:\s*\S", line) and re.search(r"\d", line)]
        prose = [line.strip() for line in lines if line.strip() and not line.strip().startswith(("#", "|", "```", ">"))]
        lead = next((line for line in prose if not (title and line == first)), "")
        result.update(title=title.group(1).strip() if title else None, headings=headings, tables=tables,
                      comparableFacts=max(len(numeric), len(labels)), lead=lead, lists=len(items))
    return result


class DeliverableOutput(TextOutput):
    def __init__(self, files=None, summary: str = "", task_text: str | None = None):
        files = list(files or [])
        super().__init__([path for path in files if path.suffix.lower() in TEXT_SUFFIXES],
                         {"done summary": summary} if summary.strip() else {})
        self.files = files
        self.summary, self.task_text = summary, task_text
        self.raw = {path: path.read_text(encoding="utf-8") for path in self.files}
        self.documents = [document(path, text) for path, text in self.raw.items()]

    def docs(self):
        return [dict(row) for row in self.documents]

    def _reports(self):
        return [row for row in self.documents if row["kind"] == "md"]

    def _doc_hit(self, row, match, text=None):
        path = Path(row["file"])
        raw = self.raw.get(path, "")
        snippet = text or row.get("title") or row.get("lead") or next((line.strip() for line in raw.splitlines() if line.strip()), "")
        index = raw.find(snippet) if snippet else 0
        return {"file": row["file"], "line": raw.count("\n", 0, max(index, 0)) + 1,
                "text": snippet[:160], "match": str(match)[:160]}

    def chatdump(self, max=150):
        count = len(self.summary.split())
        return [{"file": "done summary", "line": 1, "text": self.summary[:160], "match": f"{count} words; no deliverable file"}] if count > int(max) and not self.files else []

    def untitled(self, generic):
        regex = re.compile(generic)
        hits = []
        for row in self.documents:
            if row["kind"] == "code":
                continue
            title = row.get("title") or (row.get("heading") if row["kind"] == "html" else None)
            if not title or regex.search(title):
                hits.append(self._doc_hit(row, "missing or generic title"))
        return hits

    def tableless(self, min=3):
        return [self._doc_hit(row, f"{row['comparableFacts']} comparable facts without a table") for row in self._reports() if row["comparableFacts"] >= int(min) and not row["tables"]]

    def buried(self, verdict):
        hits = []
        for row in self._reports():
            first = re.split(r"(?<=[.!?])\s+(?=[A-Z])", row["lead"], maxsplit=1)[0]
            if not (re.search(r"\d|`|\b[\w-]+\.(?:md|txt|html|py|js|jsx|tsx|json|csv)\b", first) or re.search(verdict, first)):
                hits.append(self._doc_hit(row, "answer is not in the lead", first))
        return hits

    def flat(self, words=120):
        return [self._doc_hit(row, "fewer than two sections") for row in self._reports() if row["words"] >= int(words) and len(row["headings"]) < 2]

    def unstructured(self, words=40):
        return [self._doc_hit(row, "no heading, table or list") for row in self._reports() if row["words"] >= int(words) and not (row["headings"] or row["tables"] or row["lists"])]

    def silent(self, words, pattern):
        return [self._doc_hit(row, "missing limitations or assumptions") for row in self._reports() if row["words"] >= int(words) and not re.search(pattern, self.raw[Path(row["file"])])]

    def unfinished(self, need):
        hits = []
        for row in self.documents:
            if row["kind"] == "html":
                missing = [name for name in need if not row.get(name)]
                if missing:
                    hits.append(self._doc_hit(row, "missing " + ", ".join(missing)))
        return hits

    def oversized(self, ratio, floor):
        if self.task_text is None or not self.task_text.strip():
            from .cl_skill import _Undecided
            raise _Undecided("task text unavailable; proportion cannot be decided")
        words = len(self.task_text.split())
        multiple = len(re.findall(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", self.task_text)) > 1 or self.task_text.count("?") > 1
        multiple = multiple or bool(re.search(r"(?i)\band\s+(?:then\s+)?(?:build|create|write|fix|compare|show|explain|test|implement)\b", self.task_text))
        if words >= 60 or multiple:
            return []
        limit = max(int(floor), int(ratio) * words)
        return [self._doc_hit(row, f"{row['words']} words exceeds {limit}") for row in self._reports() if row["words"] > limit]

    def calls(self):
        return {**super().calls(), **{"deliverable." + name: getattr(self, name) for name in
                ("docs", "chatdump", "untitled", "tableless", "buried", "flat", "unstructured", "silent", "unfinished", "oversized")}}


def lesson_service(root):
    if root is None:
        return None
    try:
        from .lesson_evolver import service_for
    except ModuleNotFoundError as exc:
        if exc.name != __package__ + ".lesson_evolver":
            raise
        return None
    return service_for(root)


def merge_promoted(skill, rows, output):
    """Use the target skill grammar; never execute Python from a lesson."""
    from .cl_skill import _parse_skill, _tokens
    bindings = []
    for row in rows:
        line = row.get("line", "")
        if not isinstance(line, str) or "\n" in line or len(line) > 4000:
            raise ValueError("promoted lesson must contain one bounded CL line")
        if row.get("kind") not in {"check", "judge", "pitfall"}:
            continue
        parsed = _parse_skill(skill.path, f"CL 1\nL {skill.layer} {skill.version}\n{line}\n")
        if row["kind"] == "check":
            if len(parsed.checks) != 1:
                raise ValueError("promoted check is not a C line")
            check = parsed.checks[0]
            if check.params or check.name in {item.name for item in skill.checks}:
                raise ValueError("promoted check cannot override the base skill")
            _tokens(check.expr)
            calls = re.findall(r"(?<![\w.])([A-Za-z_][\w.-]*)\s*\(", check.expr)
            if not calls or not any(name in output.calls() for name in calls) or any(name != "len" and name not in output.calls() for name in calls):
                raise ValueError("promoted check must use a registered finish observer")
            skill.checks.append(check)
            bindings.append((row["id"], "check", check.name))
        elif row["kind"] == "pitfall":
            skill.pitfalls.update(parsed.pitfalls)
            bindings.extend((row["id"], "pitfall", name) for name in parsed.pitfalls)
        else:
            skill.judges.update(parsed.judges)
    return bindings


APP_DATA_DIRS = {"notes", ".neyvia", ".agent_control"}


def _app_data(path, root) -> bool:
    try:
        parts = Path(path).resolve().relative_to(Path(root).resolve()).parts
    except (ValueError, OSError):
        return False
    return bool(parts) and parts[0].lower() in APP_DATA_DIRS


def configured_gate(root: Path | None, since: float, summary: str = "", task_text: str | None = None, *, lesson_provider=None, task_id=None, lesson_root=None, trial_lessons=()):
    from copy import deepcopy
    from .cl_skill import _parse_skill, _Expr, run_checks
    files, scan_complete = task_artifacts(root, since, suffixes=DELIVERABLE_SUFFIXES) if root else ([], True)
    output = DeliverableOutput(files, summary, task_text)
    # Deliverable rules (a title that names the thing, structure, proportion) judge what the task produces,
    # not app data the agent edited on the way (a note body, Neyvia state). Language rules still read every file.
    deliverable_output = DeliverableOutput([f for f in files if not _app_data(f, root)], summary, task_text)
    paths = json.loads((REPO / "config/cl_done_skills.json").read_text(encoding="utf-8"))["skills"]
    reports, signature, lines, lesson_fires = {}, [], [], set()
    blocking = warnings = 0
    service = lesson_service(lesson_root if lesson_root is not None else root)
    for entry in paths:
        path = (REPO / entry).resolve()
        if not any(path.is_relative_to(REPO / folder) for folder in ("manuals/skills", "config/cl_skills")):
            raise ValueError("done skill must be under manuals/skills or config/cl_skills")
        skill = deepcopy(_parse_skill(path))
        active = service.active_lines(manual="skill:" + skill.layer, task_id=task_id) if service else []
        active += [row for row in trial_lessons if row.get("manual") == "skill:" + skill.layer]
        lesson_bindings = merge_promoted(skill, active, output)
        if lesson_provider:
            lesson_provider(skill)
        report = run_checks(skill, deliverable_output if skill.layer == "deliverables" else output)
        skill_blocks = skill_warns = 0
        for row in report["results"]:
            if row["status"] == "undecided":
                lines.append(f"Q {skill.layer} {row['name']} {json.dumps(row['detail'])}")
            if row["status"] != "fail":
                continue
            definition = next(check for check in skill.checks if check.name == row["name"])
            match = re.search(r"len\(((?:text|ui|deliverable)\.\w+\(.*\))\)\s*(==|<=)\s*0", definition.expr)
            if match:
                observed_output = deliverable_output if skill.layer == "deliverables" else output
                row["evidence"] = _Expr(match.group(1), {}, observed_output.calls()).run()
            if row["severity"] == "block":
                hits = row["evidence"] or [{"file": "done summary", "line": 1, "text": row["rule"], "match": row["name"]}]
                skill_blocks += len(hits)
                for hit in hits:
                    signature.append(json.dumps([skill.layer, row["name"], hit], sort_keys=True))
                    lines.append(f"X {skill.layer} {row['name']} {hit['file']}:{hit['line']} {json.dumps(hit['text'][:120], ensure_ascii=False)} -> {row['fix'] or row['rule']}")
            elif row["severity"] == "warn":
                skill_warns += max(1, len(row["evidence"]))
        report.update(blockingHits=skill_blocks, warningHits=skill_warns)
        if service and (files or summary.strip()):
            fired = [lesson_id for lesson_id, kind, name in lesson_bindings if any(result["name"] == name and
                     (result["status"] != "undecided" if kind == "check" else result["status"] == "fail") for result in report["results"])]
            if fired:
                lesson_fires.update(fired)
        reports[skill.layer] = report
        blocking += skill_blocks
        warnings += skill_warns
        if skill_warns:
            lines.append(f"Q {skill.layer} warn:{skill_warns}")
    if not scan_complete:
        lines.append("Q language artifact scan incomplete: too many entries under the task root -> narrow the output folder")
    return {"files": [str(path) for path in files], "reports": reports, "blocking": blocking,
            "warnings": warnings, "signature": sorted(signature), "lessonFires": sorted(lesson_fires),
            "cl": "\n".join(lines) + ("\n" if lines else "")}
