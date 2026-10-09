"""Content audit for authored manuals and their compiled CL projections."""
from __future__ import annotations

def audit_content(data):
    for name, chapter in data["chapters"].items():
        for key, procedure in chapter["procedures"].items():
            if key == "inspect":
                goal = str(procedure.get("goal", "")).strip()
                steps = procedure.get("steps", [])
                # The callable name is an API. Judge its actual domain goal and
                # executable actions instead of deleting a meaningful API key.
                if (len(goal.split()) < 4 or goal.lower() in {
                    "inspect the current state", "inspect the selected app"
                } or not steps or not all(
                    step.get("action") in chapter["actions"] for step in steps
                )):
                    raise ValueError(f"{data['id']}/{name}: inspect needs a real goal and executable actions")
        for action in chapter["actions"].values():
            if action["pre"] == "Use the selected workspace and existing approval scope":
                raise ValueError(f"{data['id']}/{name}: action needs its actual guard")
        if "next" in chapter["judge"] and chapter["judge"]["next"]["options"] == ["mapped", "frontier"]:
            raise ValueError(f"{data['id']}/{name}: replace generic judgement with a domain decision")
        for guidance in chapter["guidance"]:
            if guidance.startswith("<!-- Generated from"):
                raise ValueError(f"{data['id']}/{name}: generated views cannot become source")
