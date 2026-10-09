"""Identity-bound browser confidence calibration; never changes model choices."""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import digest


def temperature_probabilities(probabilities, temperature):
    if not probabilities or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("Calibration needs finite probabilities and positive temperature")
    values = {}
    for key, value in probabilities.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Model probabilities must be finite and inside [0,1]")
        values[key] = math.log(max(value, 1e-12)) / temperature
    if abs(sum(probabilities.values()) - 1) > .001:
        raise ValueError("Model probabilities must sum to one")
    largest = max(values.values())
    weights = {key: math.exp(value - largest) for key, value in values.items()}
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


class BrowserCalibration:
    def __init__(self, path):
        self.path = Path(path)
        self.spec = json.loads(self.path.read_text(encoding="utf-8"))
        if self.spec.get("schema") not in {"neyvia.browser-confidence@1", "neyvia.browser-confidence@2"} or self.spec.get("family") not in {"browser_factual", "grounded_action"}:
            raise ValueError("Unsupported browser calibration artifact")
        self.temperature = float(self.spec["temperature"])
        if not math.isfinite(self.temperature) or self.temperature < 1:
            raise ValueError("Conservative browser calibration temperature must be at least one")
        if not self.spec.get("calibration_count") or not self.spec.get("heldout_count"):
            raise ValueError("Browser calibration requires separate fitting and held-out observations")
        self.threshold = self.spec.get("acceptance_threshold", .8)
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (float, int)) or not math.isfinite(self.threshold) or self.threshold < 0:
            raise ValueError("Calibration threshold must be a finite nonnegative number")

    def confidence(self, response, answer, *, decision_profile=None, url=None):
        # Factual two-way page questions do not calibrate arbitrary controls.
        # Retain their measured statistics, but never transfer that confidence
        # into an action grant without a separately evaluated action corpus.
        if self.spec.get("family") != "grounded_action" or self.spec.get("decision_scope") != "grounded_action":
            return None
        if self.spec.get("schema") == "neyvia.browser-confidence@2" and self.spec.get("validated") is not True:
            return None
        if self.spec.get("schema") == "neyvia.browser-confidence@2":
            if decision_profile not in self.spec.get("supported_decision_profiles", []) or urlsplit(url or "").hostname not in self.spec.get("evaluated_hosts", []):
                return None
            if list(answer.get("p", {})) not in self.spec.get("supported_option_id_sequences", []):
                return None
            if hashlib.sha256(Path(__file__).with_name("browser_client.py").read_bytes()).hexdigest() != self.spec.get("browser_client_sha256"):
                return None
        if digest(response.get("identity")) != self.spec["identity_digest"]:
            return None
        # Corrections' distributions do not inherit frozen-model calibration.
        if answer.get("source") != "laya":
            return None
        if len(answer.get("p", {})) not in self.spec.get("supported_option_counts", []):
            return None
        probabilities = temperature_probabilities(answer.get("p", {}), self.temperature)
        confidence = probabilities.get(answer.get("answer"))
        raw = answer.get("top_probability")
        if confidence is None or isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            return None
        return min(confidence, raw)

    def advisory_confidence(self, response, answer, question, *, field, url):
        if self.spec.get("schema") != "neyvia.browser-confidence@2" or self.spec.get("advisory_validated") is not True:
            return None
        if digest(response.get("identity")) != self.spec["identity_digest"] or answer.get("source") != "laya":
            return None
        if urlsplit(url or "").hostname not in self.spec.get("advisory_evaluated_hosts", []):
            return None
        if {"field": field, "instructions": question.get("instructions")} not in self.spec.get("supported_advisory_questions", []):
            return None
        if list(answer.get("p", {})) not in self.spec.get("advisory_option_id_sequences", []):
            return None
        if hashlib.sha256(Path(__file__).with_name("browser_client.py").read_bytes()).hexdigest() != self.spec.get("advisory_browser_client_sha256"):
            return None
        p = temperature_probabilities(answer.get("p", {}), self.temperature)
        return p.get(answer.get("answer"))
