"""Write the Claude Code plugin's skills (plugins/neyvia/skills) from Neyvia's manuals.

    python scripts/build_claude_plugin_skills.py           # rewrite the skills
    python scripts/build_claude_plugin_skills.py --check   # exit 1 when a skill is out of date

The manual text is kept as is; a short header says how its ``neyvia.*`` names map to the plugin's MCP tools.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "plugins" / "neyvia" / "skills"
# skill name -> (manual, when Claude should load it). The workspace manual is left out: Claude Code has its own
# file and terminal tools, so Neyvia's are not offered there.
MANUALS = {
    "neyvia": ("docs/manuals/neyvia.md", "Use when working with the Neyvia app on this PC: its chats, projects, panes, "
               "follow-ups, timers, missions, approvals or the work board. Explains every Neyvia tool."),
    "neyvia-pdf": ("docs/manuals/pdf.md", "Use when the person has a PDF open in Neyvia or asks to open, search, "
                   "highlight or read one there."),
    "neyvia-image-studio": ("docs/manuals/image-studio.md", "Use when editing or exporting images in Neyvia's "
                            "Image Studio (crop, resize, composite, export)."),
    "neyvia-lab": ("docs/manuals/hill-climb.md", "Use when asked about Neyvia's Improvement Lab: saved measurements, "
                   "competitions and Pareto sets."),
}
HEADER = """Use `cl(lines=\"...\")` for CL 1.1 calls. Start with the layer index below;
`help(\"layer\")` loads signatures on demand. Prefer `run layer.procedure(...)`.
The host fills stamps and handles, checks effects, and preserves existing approvals.
Finish with `done(\"summary\")`; it succeeds only after the observed task goal passes.
The existing PORTED.md scope remains discoverable.
"""


def render(name: str, manual: str, description: str) -> str:
    sys.path.insert(0, str(REPO / "src"))
    from grant_agent.neyvia_manuals import records
    from grant_agent.cl.integration import index_lines
    identity = Path(manual).stem
    source = next(row for row in records() if row["id"] == identity).get("clSource", manual)
    body = "\n".join(index_lines())
    intent = ""
    if name == "neyvia":
        intent = ("\nFor a multi-ask message, first call `intent_checklist` with the entire message, fill its returned schema yourself, and apply later corrections only to what they name before acting. Publish each ask with `plan_update(plan=[{step,status}])` or Claude Code's TaskCreate/TaskUpdate (load them with ToolSearch if deferred; TodoWrite on older versions), then keep statuses updated after verified progress. Blocked asks stay pending with an explanation. The `working-with-paul` manual's `overview` chapter gives the procedure; no hidden model is called.\n")
    return f"---\nname: {name}\ndescription: {json.dumps(description)}\n---\n\n{HEADER}{intent}\n<!-- Generated from {source} by scripts/build_claude_plugin_skills.py; edit the CL source. -->\n\n{body}\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    # --out <dir>: write the skills somewhere else (the installer's staged copy) and leave the repo alone.
    target = Path(argv[argv.index("--out") + 1]) if "--out" in argv else SKILLS
    stale = []
    for name, (manual, description) in MANUALS.items():
        path = target / name / "SKILL.md"
        text = render(name, manual, description)
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(name)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    if check and stale:
        print("Out of date: " + ", ".join(stale) + ". Run python scripts/build_claude_plugin_skills.py")
        return 1
    sys.path.insert(0, str(REPO / "src"))
    from grant_agent.proofs_a_cli import check_plugin_skills
    check_plugin_skills(MANUALS, target, render)
    print(("Up to date" if check else "Wrote " + (", ".join(stale) or "nothing")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
