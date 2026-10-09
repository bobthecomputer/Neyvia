"""Small, frozen personalized ranker; anonymous features, supervised preferences.

Leave-one-pair-out agreement bounds admission. Votes are never sent to the feature
extractor and model names, costs, paths and answer keys are removed from inputs.
"""
from __future__ import annotations

import math

from .lesson_rubric import FEATURES


def fit(examples):
    # Equal rubric weights are the prior. Eighteen identity guesses cannot
    # justify reversing a criterion or treating proxy labels as preferences.
    weights = [1.0] * len(FEATURES)
    for step in range(800):
        gradient = [0.0] * len(weights)
        for vector, target in examples:
            score = sum(a * b for a, b in zip(weights, vector))
            probability = 1 / (1 + math.exp(-max(-30, min(30, score))))
            for i, value in enumerate(vector):
                gradient[i] += (probability - target) * value
        rate = 0.3 / math.sqrt(1 + step / 40)
        weights = [max(.75, min(1.25, weight - rate * (gradient[i] / max(1, len(examples)) + .5 * (weight - 1)))) for i, weight in enumerate(weights)]
    return weights


def margin(weights, vector):
    return sum(a * b for a, b in zip(weights, vector))


def calibrate(examples):
    outcomes = []
    for i, (vector, target) in enumerate(examples):
        score = margin(fit(examples[:i] + examples[i + 1:]), vector)
        prior = margin([1.] * len(FEATURES), vector)
        outcomes.append({"index": i, "margin": score, "correct": (score > 0) == bool(target) and abs(score) > 1e-8,
                         "rubricMargin": prior, "rubricCorrect": (prior > 0) == bool(target) and abs(prior) > 1e-8})
    return {"weights": fit(examples), "leaveOneOut": outcomes,
            "agreement": sum(row["correct"] for row in outcomes) / max(1, len(outcomes)),
            "rubricAgreement": sum(row["rubricCorrect"] for row in outcomes) / max(1, len(outcomes))}
