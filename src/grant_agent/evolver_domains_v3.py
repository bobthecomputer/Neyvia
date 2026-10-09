"""Fresh authority-domain review; reuse only discovery-qualified candidate text."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .evolver_domains import CONFIG, REPO
from .evolver_domains_v2 import domain_spec_v2, ReviewedEvaluator
from . import evolver_transport_v3


def domain_spec_v3(domain_id):
    if domain_id != "cl_skill_v3":
        raise ValueError("Unknown v3 frozen domain")
    spec = domain_spec_v2("cl_skill_v2")
    spec["panels"] = json.loads((CONFIG / "cl_skill_v3.panels.json").read_text(encoding="utf-8"))
    spec["baseline"] = (CONFIG / "cl_skill_v3.incumbent.txt").read_text(encoding="utf-8")
    spec["promotion"] = {**spec["promotion"], "max_trials": 1, "max_evaluations": 64}
    spec["judges"] += [str(Path(__file__).resolve()), str(Path(evolver_transport_v3.__file__).resolve()),
                        str(CONFIG / "cl_skill_v3.panels.json"), str(CONFIG / "cl_skill_v3.review.json"),
                        str(CONFIG / "cl_skill_v3.seed.txt"), str(CONFIG / "cl_skill_v3.flags-proof.json")]
    return spec


def selected_candidate_v3():
    review = json.loads((CONFIG / "cl_skill_v3.review.json").read_text(encoding="utf-8"))
    text = (CONFIG / "cl_skill_v3.seed.txt").read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest() != review["selectedTextSha256"]:
        raise ValueError("Discovery-qualified selected document was altered")
    return text, {"selection": review, "discoveryOnly": True, "noNewProposal": True}
