"""Freeze future workflow task data from local source, maths and render artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .workflow_manuals import REPO, STAGES


def frozen_panels(identity):
    sources = sorted((REPO / "manuals/cl").glob("*.cl"))[:16]
    images = sorted(p for p in (REPO / "docs/evidence").rglob("*.png")
                    if p.name not in {"classic-notebook-dark.png", "classic-notebook-light.png",
                                      "voice-live-spoken-open-notes.png"})[:16]
    if identity == "design" and len(images) < 16:
        raise ValueError("Sixteen separate historical rendered artifacts required")
    items = []
    for index in range(16):
        path = sources[index]
        relative = path.relative_to(REPO).as_posix()
        content = path.read_bytes()
        check_hash = hashlib.sha256(content).hexdigest()
        item = {"id": f"{identity}-future-source-{index}", "manual": identity}
        if identity == "hill-climb":
            from .cl.manuals import cl_to_manual
            from .neyvia_manuals import _compiled_manual_source
            source = content.decode()
            start = time.perf_counter()
            baseline = cl_to_manual(source)
            baseline_ms = max(.000001, time.perf_counter() - start)
            _compiled_manual_source(source)
            start = time.perf_counter()
            candidate = _compiled_manual_source(source)
            candidate_ms = max(.000001, time.perf_counter() - start)
            adverse = index % 2 == 0
            measured = 0 if adverse else 1 / candidate_ms
            if candidate != baseline:
                measured = 0
            noise = .1 / baseline_ms
            expected = measured > 1 / baseline_ms + noise
            evidence = {"before": {"checkHash": check_hash, "value": 1 / baseline_ms, "noise": noise},
                        "after": {"checkHash": check_hash, "value": measured, "success": not adverse,
                                  "boundary": "Controlled dropped-result adverse projection" if adverse else "Actual cached source equality"},
                        "ledger": {"kind": "research-ledger", "measurement": "after"}}
            task = f"Keep a single compilation-cache change for {relative}? Value is equality-valid compilations/second; zero is an adverse equality failure. Use frozen baseline noise; candidate noise is not needed. Log the after measurement."
        elif identity == "efficiency":
            start = time.perf_counter()
            digest = hashlib.sha256(content).hexdigest()
            elapsed = (time.perf_counter() - start) * 1000
            evidence = {"exact-read": {"path": "script", "success": True, "sha256": digest, "cheaperFailures": []},
                        "measured-cost": {"path": "script", "tokens": 0, "latencyMs": elapsed},
                        "cost-ledger": {"kind": "research-ledger", "measurement": "measured-cost"}}
            task = f"Choose the cheapest valid path to compute exact SHA256 for {relative}. Host script succeeded; memory, small-model and big-model are also available. Measure and log the provided actual cost."
            expected = "script"
        elif identity == "critique-review":
            from .cl.manuals import cl_to_manual
            parsed = cl_to_manual(content.decode())
            mechanism = "all authored chapters remain in the delivered projection"
            adverse = index % 2 == 0
            delivered = len(parsed["chapters"]) - int(adverse)
            evidence = {"source-comparison": {"success": not adverse, "source": relative,
                        "sourceSha256": check_hash, "authoredChapters": len(parsed["chapters"]),
                        "deliveredChapters": delivered, "boundary": "Controlled chapter-count projection"}}
            task = f"Review {relative} for its defining mechanism: {mechanism}. Attack missing wiring and unjustified completion. Decide done only if actual source-comparison supports all chapters."
            expected = not adverse
        elif identity == "research":
            exponent, x = index + 2, 1 + index / 10
            step = 1e-5
            function = lambda at: (3 * at * at + 1) ** (-exponent)
            analytic = -exponent * (3 * x * x + 1) ** (-exponent - 1) * 6 * x
            numeric = (function(x + step) - function(x - step)) / (2 * step)
            proposed = analytic if index % 2 else -analytic
            success = math.isclose(proposed, numeric, rel_tol=1e-5, abs_tol=1e-12)
            evidence = {"derivative-test": {"success": success, "x": x, "exponent": exponent,
                        "proposed": proposed, "finiteDifference": numeric, "step": step}}
            task = f"Does the proposed derivative of (3*x*x+1)^(-{exponent}) agree at x={x}? Prior art: the local course note explains chain rule; source CL exactness cannot establish learning retention. State falsifier, smallest actual test and limitation-bound result."
            expected = success
        elif identity == "creativity":
            options = [{"id": f"script-{index}", "family": "deterministic extraction", "mechanism": "parse exact source", "feasible": True, "cost": index + 1},
                       {"id": f"retrieval-{index}", "family": "indexed retrieval", "mechanism": "retrieve prior receipt", "feasible": False, "cost": 0},
                       {"id": f"model-{index}", "family": "model reconstruction", "mechanism": "infer a new structure", "feasible": True, "cost": index + 4}]
            evidence = {"design-constraints": {"source": relative, "sourceSha256": check_hash, "options": options,
                         "costBoundary": "Supplied operator-step estimate; not provider-token measurement"}}
            task = f"Propose three mechanism-distinct ways to inspect {relative}. Reframe, borrow another field and flip one constraint. Keep supplied option IDs. Choose least cost among feasible options under the exact-source constraint; record novelty/usefulness/cost criteria before choice."
            expected = f"script-{index}"
        else:
            image = images[index]
            image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
            evidence = {"archived-render": {"rendered": True, "historical": True,
                         "path": image.relative_to(REPO).as_posix(), "sha256": image_hash}}
            item.update(image=image.relative_to(REPO).as_posix(), imageSha256=image_hash)
            task = f"Review this archived artifact for {'readability' if index % 2 else 'full-screen hierarchy'}. Explain purposeful details and observed defects. Decide whether it proves the current product design complete. Archived evidence cannot establish current interactive behavior."
            expected = False
        item.update(task=task, evidence=evidence, expected=expected)
        items.append(item)
    return [{"id": f"{identity}-future-{panel}", "role": "discovery" if panel < 2 else "held_out",
             "items": items[panel * 4:panel * 4 + 4]} for panel in range(4)]
