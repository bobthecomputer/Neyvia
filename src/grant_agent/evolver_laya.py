"""CPU LAYA architecture binding for the existing frozen text Evolver.

Architectures are canonical JSON documents in the core's text grammar. Paired
selection uses independent train-side case correctness; the complete public
JevBench score is a diagnostic frontier, never a replicated paired observation.
The caller owns materialization and CPU measurement; this module starts no jobs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .evolver_core import EvolverEngine, EvolutionError

DOMAIN = "laya_cpu_r4"
OPERATORS = frozenset({"lexical_mutation", "conditional_mutation", "teacher_typed_distillation", "crossover"})
HARD_GATES = ["cpu_only", "cpu_p95_le_50_ms", "peak_memory_le_100_mib", "train_only_fit", "typed_valid"]
EXTRA_GENES = {"lexical_mix": [0, .25, .5, .75, 1],
               "early_exit_margin": [0, .1, .2, .3, .5, 1],
               "chunk_cap": [64, 128, 256], "teacher_weight": [0, .5, 1]}


def store_path(root: str | Path) -> Path:
    return Path(root).resolve() / "evidence" / "r4" / "evolver.sqlite3"


def architecture_genome(architecture: dict) -> dict:
    """Validate the executable genes without granting genome-owned judge paths."""
    if not isinstance(architecture, dict) or architecture.get("schema") != "laya.architecture_genome.v1":
        raise EvolutionError("LAYA requires the r3 architecture genome schema")
    graph = architecture.get("graph", [])
    if not isinstance(graph, list) or not {"lexical", "shared_state", "head"}.issubset(
            {node.get("id") for node in graph if isinstance(node, dict)}):
        raise EvolutionError("LAYA architecture must retain shared lexical state and typed heads")
    genes = architecture.get("genes")
    if not isinstance(genes, dict) or not genes:
        raise EvolutionError("LAYA architecture requires executable genes")
    for name, gene in genes.items():
        if isinstance(gene, dict):
            if "value" not in gene or "allowed" not in gene or gene["value"] not in gene["allowed"]:
                raise EvolutionError(f"Invalid executable gene {name}")
            value = gene["value"]
        else:
            value = gene
        if name in EXTRA_GENES and value not in EXTRA_GENES[name]:
            raise EvolutionError(f"Invalid executable gene {name}")
    execution = architecture.get("execution_genes", {})
    if not isinstance(execution, dict) or set(execution) - set(EXTRA_GENES):
        raise EvolutionError("Unknown LAYA execution gene")
    for name, value in execution.items():
        if isinstance(value, bool) or value not in EXTRA_GENES[name]:
            raise EvolutionError(f"Invalid LAYA execution gene {name}")
    return {"kind": "text", "text": json.dumps(architecture, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":"), allow_nan=False)}


def decode_architecture(genome: dict) -> dict:
    if set(genome) != {"kind", "text"} or genome.get("kind") != "text":
        raise EvolutionError("LAYA uses canonical JSON in the Evolver text grammar")
    architecture = json.loads(genome["text"])
    architecture_genome(architecture)
    return architecture


def establish(root: str | Path, panels: list[dict], judge_paths: list[str | Path],
              base_genome: dict | None = None, *, max_trials: int = 6,
              min_pairs: int = 8, seed: int = 4404, max_seconds: int = 3600) -> dict:
    """Freeze judges/panels and register the retained r3 seed in the real core."""
    root = Path(root).resolve()
    base_path = root / "architecture" / "r3-genome.json"
    architecture = base_genome if base_genome is not None else json.loads(base_path.read_text(encoding="utf-8"))
    if not 1 <= max_trials <= 6:
        raise EvolutionError("LAYA r4 permits at most six children across three generations")
    discoveries = [p for p in panels if p.get("role") == "discovery"]
    held_out = [p for p in panels if p.get("role") == "held_out"]
    if len(discoveries) < max_trials or len(held_out) < 2 * max_trials:
        raise EvolutionError("Each bounded trial needs discovery and two fresh reconfirmation panels")
    engine = EvolverEngine(store_path(root))
    judges = list(dict.fromkeys([Path(__file__).resolve(), base_path, *(Path(p).resolve() for p in judge_paths)]))
    engine.establish_domain(DOMAIN, judges=judges, panels=panels,
                            objectives={"train_correct": {"direction": "max", "tolerance": 0., "noise": 0.}},
                            promotion={"max_trials": max_trials, "max_evaluations": max_trials * min_pairs * 6,
                                       "min_pairs": min_pairs, "seed": seed, "max_seconds": max_seconds},
                            hard_gates=HARD_GATES)
    registration = engine.register_genome(DOMAIN, architecture_genome(architecture), operator="seed",
                                           provenance={"round": 4, "source": str(base_path),
                                                       "selection": "paired train correctness",
                                                       "public_fitness": "diagnostic full public split only"})
    status = engine.status(DOMAIN)
    if status["domains"][0]["incumbent"] is None:
        status = engine.set_incumbent(DOMAIN, registration["id"])
    return {"engine": engine, "registration": registration, "status": status}


def register(engine: EvolverEngine, architecture: dict, parent_id: str, operator: str,
             provenance: dict) -> dict:
    if operator not in OPERATORS:
        raise EvolutionError("LAYA operator is not allowed by this domain")
    if not isinstance(provenance, dict) or provenance.get("generation") not in {1, 2, 3}:
        raise EvolutionError("LAYA lineage requires a generation in the frozen three-generation budget")
    if operator == "teacher_typed_distillation" and provenance.get("fit_split") != "original_train":
        raise EvolutionError("Teacher typed answers may fit only on the original train split")
    return engine.register_genome(DOMAIN, architecture_genome(architecture), parent_id=parent_id,
                                  operator=operator, provenance=provenance)


def trial(engine: EvolverEngine, genome_id: str, evaluator: Callable) -> dict:
    """Callback returns per-case train correctness and all frozen hard gates."""
    return engine.evaluate_candidate(DOMAIN, genome_id, evaluator)


def public_frontier(measurements: list[dict]) -> list[dict]:
    """Constrained public Pareto archive; no authority to change the incumbent."""
    feasible = [row for row in measurements
                if row["cpu_p95_ms"] <= 50 and row["peak_memory_mib"] <= 100
                and row.get("cpu_only") is True and row.get("train_only_fit") is True
                and row.get("failures", 0) == 0]
    def dominates(a, b):
        gains = [a["public_correct"] - b["public_correct"],
                 b["cpu_p95_ms"] - a["cpu_p95_ms"], b["peak_memory_mib"] - a["peak_memory_mib"]]
        return all(g >= 0 for g in gains) and any(g > 0 for g in gains)
    return sorted([row for row in feasible if not any(dominates(other, row) for other in feasible)],
                  key=lambda row: (-row["public_correct"], row["cpu_p95_ms"], row["peak_memory_mib"]))
