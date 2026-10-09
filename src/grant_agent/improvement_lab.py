"""Executable comparisons and bounded, evidence-linked improvement decisions.

Local artifact measurements are observations, not independent endorsements of
model quality. Definitions are frozen by the existing quality store.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .experimental_quality import ExperimentalQuality
from .experiment_studio import ExperimentStudio
from .installed_programs import InstalledPrograms


class ImprovementLab:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.quality = ExperimentalQuality(self.root, "improvement-lab")
        self.base = self.quality.base

    def artifact(self, raw):
        path = (self.root / str(raw)).resolve(strict=True)
        path.relative_to(self.root)
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Choose a workspace file smaller than 16 MB")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def document(self, raw):
        path, digest = self.artifact(raw)
        return json.loads(path.read_text(encoding="utf-8")), {"path": str(path.relative_to(self.root)), "sha256": digest}

    @staticmethod
    def number(value, low=0, high=1e12):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("A finite number within the supported range is required")
        return value

    def competition(self, identity, source, candidates, instruments):
        self.quality._safe(identity)
        if not isinstance(candidates, list) or not 2 <= len(candidates) <= 8 or len(set(candidates)) != len(candidates):
            raise ValueError("Choose two to eight distinct candidate identifiers")
        if not isinstance(instruments, list) or not 1 <= len(instruments) <= 12 or len(set(instruments)) != len(instruments):
            raise ValueError("Choose distinct frozen measurement instruments")
        for instrument in instruments:
            self.quality._definition("instrument", instrument)
        for candidate in candidates:
            self.quality._safe(candidate)
        studio = ExperimentStudio(self.root)
        spec = {"source": str((self.root / source).resolve()), "candidates": candidates, "instruments": instruments}
        # Freeze the shared contract before producing any candidate. Interrupted
        # creation resumes with the same contract and matching source baseline.
        path = self.base / f"competition-{identity}.json"
        if path.exists():
            if self.quality._definition("competition", identity)["spec"] != spec:
                raise ValueError("Competition definition is already frozen")
        else:
            self.quality._seal("competition", identity, spec)
        snapshots = []
        baseline = None
        for candidate in candidates:
            experiment_id = hashlib.sha256(f"{identity}:{candidate}".encode()).hexdigest()[:32]
            manifest = studio.inspect(experiment_id)
            if manifest.get("status") == "not_found":
                manifest = studio.create(experiment_id, source=spec["source"])["manifest"]
            hashes = manifest["sourceSha256"]
            if baseline is not None and hashes != baseline:
                raise ValueError("Source changed between candidate snapshots; preserve and inspect this competition")
            baseline = hashes
            snapshots.append({"candidate": candidate, "experimentId": experiment_id, "path": manifest["snapshot"]})
        return {"competitionId": identity, "candidates": snapshots, "sharedBaseline": baseline, "promoted": False}

    def compare(self, identity, targets):
        definition = self.quality._definition("competition", identity)
        spec = definition["spec"]
        if set(targets) != set(spec["candidates"]):
            raise ValueError("Every frozen candidate must be included, including failed candidates")
        measurements = []
        studio = ExperimentStudio(self.root)
        for candidate in spec["candidates"]:
            snapshot = Path(studio.inspect(hashlib.sha256(f"{identity}:{candidate}".encode()).hexdigest()[:32])["snapshot"]).resolve()
            path = (snapshot / targets[candidate]).resolve(strict=True)
            path.relative_to(snapshot)
            row = {"candidate": candidate, "measurements": []}
            for instrument in spec["instruments"]:
                row["measurements"].append(self.quality.measure(instrument, path))
            row["eligible"] = all(m["withinLimit"] for m in row["measurements"])
            measurements.append(row)
        return self.quality._receipt({"kind": "competition", "competitionId": identity, "definitionHash": definition["hash"],
                                      "candidates": measurements, "promoted": False, "boundary": "frozen artifact measurements; not independent user-journey proof"})

    def rehearse(self, experiment_id, script, arguments=None, _actor="agent"):
        studio = ExperimentStudio(self.root)
        manifest = studio.inspect(experiment_id)
        if manifest.get("status") == "not_found":
            raise ValueError("Experiment snapshot does not exist")
        snapshot = Path(manifest["snapshot"]).resolve()
        path = (snapshot / script).resolve(strict=True)
        path.relative_to(snapshot)
        result = InstalledPrograms(self.root).launch_file(str(path), arguments or [], _actor=_actor)
        return {"session": result, "experimentId": experiment_id,
                "boundary": "separate source and working folders; process retains host permissions", "promotion": "not_performed"}

    def uncertainty(self, identity, assumptions):
        if not isinstance(assumptions, list) or not 1 <= len(assumptions) <= 100:
            raise ValueError("Choose one to 100 assumptions")
        rows = []
        for row in assumptions:
            name = str(row.get("claim", "")).strip()
            experiment = str(row.get("experiment", "")).strip()
            if not name or not experiment:
                raise ValueError("Every assumption requires a claim and resolving experiment")
            probability = self.number(row.get("probabilityWrong"), 0, 1)
            impact = self.number(row.get("impact"))
            cost = self.number(row.get("cost"), .001)
            rows.append({"claim": name, "experiment": experiment, "probabilityWrong": probability, "impact": impact,
                         "cost": cost, "priority": probability * impact / cost, "estimateSource": "caller_estimate"})
        self.quality._seal("uncertainty", identity, {"assumptions": rows})
        return {"identity": identity, "ranked": sorted(rows, key=lambda r: -r["priority"]), "estimatesVerified": False}

    def causal(self, baseline, variant, factor):
        first, a = self.document(baseline)
        second, b = self.document(variant)
        for row in (first, second):
            if not isinstance(row, dict) or not isinstance(row.get("conditions"), dict) or not isinstance(row.get("outcomes"), list) or not row["outcomes"]:
                raise ValueError("Trials require conditions and nonempty numeric outcomes")
            for outcome in row["outcomes"]:
                self.number(outcome, -1e12)
        changed = [key for key in first["conditions"].keys() | second["conditions"].keys()
                   if first["conditions"].get(key) != second["conditions"].get(key)]
        matched = changed == [factor] and len(first["outcomes"]) == len(second["outcomes"])
        return self.quality._receipt({"kind": "causal_comparison", "inputs": [a, b], "changedFactors": sorted(changed),
            "status": "matched_reported_trial" if matched else "confounded", "causalityProven": False,
            "pairedDeltas": [right-left for left, right in zip(first["outcomes"], second["outcomes"])] if matched else [],
            "limitation": "Artifact contents are reported trials; repetitions, assignment and confounders require independent evaluation"})

    def resolve_uncertainty(self, identity, assumption, instrument, target):
        definition = self.quality._definition("uncertainty", identity)
        rows = definition["spec"]["assumptions"]
        if type(assumption) is not int or not 0 <= assumption < len(rows):
            raise ValueError("Unknown assumption index")
        measurement = self.quality.measure(instrument, target)
        return self.quality._receipt({"kind": "uncertainty_observation", "identity": identity, "assumption": assumption,
            "definitionHash": definition["hash"], "measurement": measurement, "claimProven": False})

    def next_experiment(self, identity):
        definition = self.quality._definition("uncertainty", identity)
        observed = {}
        files = sorted(self.base.glob("receipt-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:500]:
            if path.stat().st_size > 262144:
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("kind") != "uncertainty_observation" or value.get("identity") != identity or value.get("definitionHash") != definition["hash"]:
                continue
            index = value["assumption"]
            if index in observed:
                continue
            try:
                _, digest = self.artifact(value["measurement"]["path"])
                current = digest == value["measurement"]["sha256"]
            except (OSError, ValueError):
                current = False
            observed[index] = {"measurementCurrent": current, "withinLimit": value["measurement"]["withinLimit"], "receipt": str(path.relative_to(self.root))}
        ranked = [{**row, "index": i, "observation": observed.get(i)} for i,row in enumerate(definition["spec"]["assumptions"])]
        ranked.sort(key=lambda r: (bool(r["observation"] and r["observation"]["measurementCurrent"]), -r["priority"]))
        return {"identity": identity, "ranked": ranked, "next": ranked[0] if ranked else None,
                "omittedReceipts": max(0, len(files)-500), "claimVerification": "measurements_do_not_prove_the_assumption"}

    def journey(self, path):
        rows, evidence = self.document(path)
        if not isinstance(rows, list) or not 2 <= len(rows) <= 10000:
            raise ValueError("A journey needs two to 10000 timestamped events")
        previous = -1
        transitions, pending, delays, errors = [], {}, [], []
        disconnected, checkpoints, continuity_mismatches = False, {}, []
        for row in rows:
            stamp = self.number(row.get("atMs"))
            if stamp < previous:
                raise ValueError("Journey timestamps are not monotonic")
            previous = stamp
            kind = row.get("kind")
            if kind == "input":
                identity = str(row.get("id", ""))
                if not identity or identity in pending:
                    raise ValueError("Input identity missing or duplicated")
                pending[identity] = stamp
            elif kind == "response":
                identity = str(row.get("inputId", ""))
                if identity not in pending:
                    raise ValueError("Response has no outstanding input")
                delays.append(stamp-pending.pop(identity))
            elif kind == "error":
                errors.append(row)
            elif kind in {"disconnect", "reconnect", "checkpoint", "resume"}:
                if kind == "disconnect":
                    disconnected = True
                elif kind == "reconnect":
                    if not disconnected:
                        raise ValueError("Reconnect has no preceding disconnect")
                    disconnected = False
                else:
                    identity, digest = row.get("checkpointId"), row.get("stateHash")
                    if not isinstance(identity, str) or not identity or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                        raise ValueError("Continuity event needs a checkpoint identity and SHA-256 state hash")
                    if kind == "checkpoint":
                        if identity in checkpoints:
                            raise ValueError("Checkpoint identities cannot be overwritten")
                        checkpoints[identity] = digest
                    elif checkpoints.get(identity) != digest:
                        continuity_mismatches.append(identity)
                transitions.append(row)
            else:
                raise ValueError("Unsupported journey event")
        return self.quality._receipt({"kind": "journey", "input": evidence, "durationMs": rows[-1]["atMs"]-rows[0]["atMs"],
            "responseDelaysMs": delays, "unansweredInputs": list(pending), "errors": errors, "transitions": transitions,
            "continuityMismatches": continuity_mismatches, "disconnectedAtEnd": disconnected,
            "journeySuccessful": bool(delays) and not errors and not pending and not disconnected and not continuity_mismatches,
            "boundary": "reported trace analysis; recording provenance unverified"})

    def curriculum(self, identity, examples):
        if not isinstance(examples, list) or not 2 <= len(examples) <= 200:
            raise ValueError("Curriculum needs two to 200 examples")
        rows, seen = [], {}
        for item in examples:
            split = item.get("split")
            if split not in {"train", "holdout"}:
                raise ValueError("Explicit train or holdout split required")
            path, digest = self.artifact(item["path"])
            family = str(item.get("family", "")).strip()
            if not family:
                raise ValueError("Declare a task family to detect cross-split leakage")
            for key in ("hash:"+digest, "family:"+family):
                if key in seen and seen[key] != split:
                    raise ValueError("Training and holdout overlap")
                seen[key] = split
            rows.append({"path": str(path.relative_to(self.root)), "sha256": digest, "family": family, "split": split})
        if {r["split"] for r in rows} != {"train", "holdout"}:
            raise ValueError("Both training and holdout examples are required")
        self.quality._seal("curriculum", identity, {"examples": rows})
        return {"curriculumId": identity, "trainingCount": sum(r["split"] == "train" for r in rows),
                "holdoutCount": sum(r["split"] == "holdout" for r in rows), "modelImprovementVerified": False}

    def lesson_packet(self, identity):
        spec = self.quality._definition("curriculum", identity)["spec"]
        selected = []
        for row in spec["examples"]:
            path, digest = self.artifact(row["path"])
            if digest != row["sha256"]:
                raise ValueError("Curriculum evidence changed")
            if row["split"] == "train":
                text = path.read_text(encoding="utf-8")
                if sum(len(r["text"]) for r in selected) + len(text) > 16000:
                    raise ValueError("Training packet exceeds context allowance; use a smaller curriculum")
                selected.append({"text": text, "sha256": digest, "family": row["family"]})
        return {"curriculumId": identity, "examples": selected, "holdoutDisclosed": False}

    def taste_packet(self, work_id, context):
        from .contextual_learning import ContextualLearningStore
        self.quality._safe(work_id)
        store = ContextualLearningStore(self.root / ".agent_control" / "contextual_learning" / f"{work_id}.json", scope_root=self.root)
        history = store.history(context)
        preferences, rejected = [], []
        for row in history["rows"]:
            if row.get("trustedOperator") is not True or row.get("status") != "accepted":
                continue
            intact = True
            for key in ("before", "after"):
                try:
                    _, digest = self.artifact(row[key]["path"])
                    intact = intact and digest == row[key]["sha256"]
                except (OSError, ValueError):
                    intact = False
            if intact:
                preferences.append({"correctionId": row["correctionId"], "guidance": row["correction"], "context": context})
            else:
                rejected.append(row["correctionId"])
        return {"context": context, "preferences": preferences, "staleComparisons": rejected,
                "transferVerified": False, "scope": "operator-confirmed comparisons in this context only"}

    def visual_guard(self, baseline, candidate, regions):
        from PIL import Image, ImageChops
        first, ah = self.artifact(baseline)
        second, bh = self.artifact(candidate)
        if not isinstance(regions, list) or not 1 <= len(regions) <= 100:
            raise ValueError("Declare one to 100 protected rectangles")
        with Image.open(first) as a, Image.open(second) as b:
            if a.size != b.size or a.width*a.height > 16777216:
                raise ValueError("Images must have identical dimensions and at most 16 megapixels")
            aa, bb = a.convert("RGBA"), b.convert("RGBA")
            checks = []
            for region in regions:
                values = [region.get(k) for k in ("x", "y", "width", "height")]
                if any(type(n) is not int for n in values):
                    raise ValueError("Rectangle coordinates must be integers")
                x, y, w, h = values
                if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > a.width or y+h > a.height:
                    raise ValueError("Protected rectangle outside image")
                diff = ImageChops.difference(aa.crop((x,y,x+w,y+h)), bb.crop((x,y,x+w,y+h)))
                unchanged = all(channel.getbbox() is None for channel in diff.split())
                checks.append({"region": region, "unchanged": unchanged})
        return self.quality._receipt({"kind": "visual_guard", "baselineSha256": ah, "candidateSha256": bh,
            "checks": checks, "protectedPixelsUnchanged": all(r["unchanged"] for r in checks),
            "semanticQualityVerified": False})

    def status(self):
        paths = sorted(self.base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        rows = []
        for path in paths[:50]:
            if path.stat().st_size > 262144:
                rows.append({"path": path.name, "status": "oversized"}); continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                rows.append({"path": path.name, "kind": value.get("kind") or value.get("schema"),
                             "identity": value.get("id") or value.get("receiptId"), "status": "recorded"})
            except (ValueError, OSError, AttributeError):
                rows.append({"path": path.name, "status": "unreadable"})
        return {"records": rows, "omittedCount": max(0, len(paths)-50), "automaticPromotion": False}

    def complexity(self):
        from .native_tools import NativeToolRegistry
        from .runtime_diagnostics import summarize_receipts
        catalog = NativeToolRegistry(self.root).list_tools(include_schemas=True)
        receipts = summarize_receipts(self.root, limit=500)
        calls = {r["tool"]: r["calls"] for r in receipts["tools"]}
        groups = {}
        for row in catalog:
            signature = json.dumps({"description": row["description"], "schema": row["inputSchema"], "mutation": row["mutability_class"]}, sort_keys=True)
            groups.setdefault(signature, []).append(row["name"])
        return {"duplicateContracts": [names for names in groups.values() if len(names)>1],
                "unobservedTools": [r["name"] for r in catalog if not calls.get(r["name"])],
                "window": "latest 500 native receipts", "retirementPerformed": False,
                "limitation": "Absent observations do not establish that a tool is unused or safe to remove"}
