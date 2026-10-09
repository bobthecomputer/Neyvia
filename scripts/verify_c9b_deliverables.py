"""Small real file/CL-host journeys for C9.1; no network, services or test suite."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.host import HostContext
from grant_agent.cl_deliverables import DeliverableOutput, configured_gate, merge_promoted
from grant_agent.cl_skill import Output, _parse_skill, run_checks


def main():
    for name in ("cl_skill.py", "cl_deliverables.py", "cl/host.py"):
        ast.parse((REPO / "src/grant_agent" / name).read_text(encoding="utf-8"))
    evidence = REPO / "scripts/evidence"
    evidence.mkdir(exist_ok=True)
    proof = {"schema": "neyvia.c9b-deliverables-proof.v1", "checks": {}}
    with tempfile.TemporaryDirectory(prefix="c9b-deliverables-", dir=evidence) as folder:
        root = Path(folder)
        report = root / "coil.md"
        report.write_text("Report\nTODO\n- A: 12 ms\n- B: 15 ms\n- C: 20 ms\n", encoding="utf-8")
        skill = _parse_skill(REPO / "manuals/skills/deliverables.cl")
        initial = run_checks(skill, Output([report], task_text="Compare the three coil timings."))
        statuses = {row["name"]: row["status"] for row in initial["results"]}
        assert statuses["titled"] == statuses["no-placeholder"] == "fail", statuses
        assert statuses["summary-table"] == "fail", statuses
        assert next(row for row in initial["results"] if row["name"] == "titled")["evidence"][0]["line"] == 1
        proof["checks"]["bad_file"] = statuses
        tools = [{"name": "files.stat", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, "annotations": {"readOnlyHint": True}}]
        def dispatch(name, args, action_id=""):
            path = root / args["path"]
            return {"exists": path.is_file(), "bytes": path.stat().st_size if path.exists() else 0}
        def host():
            return HostContext(tools, dispatch, root=root, task_text="Compare the three coil timings.", goals="files.stat(path='coil.md').exists == True")
        context = host()
        tries = [context.execute('done("coil.md contains the timings.")')["results"][0] for _ in range(3)]
        assert [row["status"] for row in tries] == ["refused", "refused", "ok"], tries
        assert set(tries[0]["skillReceipts"]) == {"no-slop", "deliverables"}
        assert "X deliverables titled" in tries[0]["cl"] and "Q deliverables warn:" in tries[0]["cl"]
        proof["checks"]["anti_trap"] = [row["status"] for row in tries]
        proof["checks"]["refusal_receipt"] = tries[0]["cl"]
        report.write_text("# Coil timings: 12 to 20 ms\n\nA passed in 12 ms.\n\n| Coil | Time |\n| --- | --- |\n| A | 12 ms |\n| B | 15 ms |\n| C | 20 ms |\n", encoding="utf-8")
        fixed = host().execute('done("coil.md contains the three timings.")')["results"][0]
        assert fixed["status"] == "ok", fixed
        assert fixed["skillReceipts"]["deliverables"]["checksPassed"] == 11
        proof["checks"]["fixed_file"] = {key: fixed["skillReceipts"]["deliverables"][key] for key in ("status", "checksRun", "checksPassed")}
        unknown = configured_gate(root, 0, "Written coil.md")
        proportion = next(row for row in unknown["reports"]["deliverables"]["results"] if row["name"] == "proportion")
        assert proportion["status"] == "undecided", proportion
        proof["checks"]["unknown_task"] = proportion["status"]
        # The visible JSX extractor must not recurse through the added output adapter.
        jsx = root / "coil.jsx"
        jsx.write_text('export const Coil = () => <button aria-label="Read coil timings">Read timings</button>;', encoding="utf-8")
        assert Output([jsx]).calls()["text.match"](pattern="Read timings")
        proof["checks"]["jsx_visible_text"] = True
        page = root / "coil.html"
        page.write_text("<title>Coil timings</title><h1>Coil timings</h1><style>@media (prefers-color-scheme: dark){body{color:white}} button:focus-visible{outline:solid} @media (prefers-reduced-motion){button{animation:none}}</style>", encoding="utf-8")
        ui = DeliverableOutput([page], task_text="Show coil timings")
        assert ui.unfinished(["dark", "focus", "title", "motion"]) == []
        assert ui.untitled("(?i)^report$") == []
        proof["checks"]["html_finished"] = True
        text = DeliverableOutput([], summary="word " * 151, task_text="Explain coils")
        assert text.chatdump(max=150)
        proof["checks"]["chatdump"] = True
        report.write_text("# Coil winding\n\n" + "word " * 260, encoding="utf-8")
        output = DeliverableOutput([report], task_text="Describe a coil")
        assert output.oversized(ratio=12, floor=250) and output.flat(words=120)
        assert output.silent(words=250, pattern="(?i)missing|assumed|unproven")
        proof["checks"]["proportion_and_long_report"] = True
        report.write_text("No title. " + "word " * 45, encoding="utf-8")
        assert DeliverableOutput([report]).unstructured(words=40)
        proof["checks"]["unstructured"] = True
        bindings = merge_promoted(skill, [{"id": "observer-proof", "kind": "check", "line": 'C deliverables.finish coil-number: len(text.match(pattern:"word" in:all)) == 0 -- warn proof: use the measured number'}], DeliverableOutput([report]))
        promoted = run_checks(skill, DeliverableOutput([report], task_text="Describe coils"))
        assert bindings == [("observer-proof", "check", "coil-number")]
        assert next(row for row in promoted["results"] if row["name"] == "coil-number")["status"] == "fail"
        proof["checks"]["promoted_observer_grammar"] = True
        trial_row = {"id": "quarantined-proof", "manual": "skill:deliverables", "kind": "check", "line": 'C deliverables.finish trial-coil: len(text.match(pattern:"word" in:all)) == 0 -- warn proof: use the measured number'}
        trial_gate = configured_gate(root, 0, "Read coil.md", "Describe coils", trial_lessons=[trial_row])
        assert next(row for row in trial_gate["reports"]["deliverables"]["results"] if row["name"] == "trial-coil")["status"] == "fail"
        clean_gate = configured_gate(root, 0, "Read coil.md", "Describe coils")
        assert not any(row["name"] == "trial-coil" for row in clean_gate["reports"]["deliverables"]["results"])
        proof["checks"]["candidate_trial_observer_isolation"] = True
        report.unlink()
        page.unlink()
        jsx.unlink()
        code = root / "coil.py"
        code.write_text("# TODO is a code comment, not unfinished visible copy.\nprint(12)\n", encoding="utf-8")
        code_gate = configured_gate(root, 0, "word " * 151, "Print the coil number")
        assert str(code) in code_gate["files"]
        assert not code_gate["reports"]["deliverables"]["blockingHits"]
        proof["checks"]["code_counts_as_deliverable"] = True
        from grant_agent.neyvia_manuals import get_manual, records
        from grant_agent.lesson_evolver import service_for
        workspace, control = root / "outputs", root / "control"
        workspace.mkdir(); control.mkdir()
        identity = records()[0]["id"]
        assert get_manual(identity, workspace / ".neyvia") == get_manual(identity, workspace / ".neyvia", lesson_root=control)
        assert service_for(control).path.parent == control / ".neyvia/lessons"
        proof["checks"]["separate_manual_and_lesson_roots"] = True
    (evidence / "C9b-deliverables.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "checks": list(proof["checks"]), "receipt": "scripts/evidence/C9b-deliverables.json"}))


if __name__ == "__main__":
    main()
