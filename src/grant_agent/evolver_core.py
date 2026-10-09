"""Durable paired text evolution; genomes never carry evaluation authority.

The text grammar deliberately exposes only a rendered document. Newline encoding
is its sole equivalence rewrite. Frozen Python evaluators own measurements; this
module owns trial accounting and promotion. A promotion changes this local
domain's incumbent, never a public release or an installed skill.
"""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs

import hashlib
import inspect
import json
import math
import os
import platform
import sqlite3
import statistics
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

SCHEMA = "neyvia.evolver/v1"


class EvolutionError(ValueError):
    pass


class FrozenJudgeError(EvolutionError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def canonical_genome(genome: dict) -> dict:
    if not isinstance(genome, dict) or set(genome) != {"kind", "text"} or genome["kind"] != "text":
        raise EvolutionError("Genome permits only kind='text' and text; judges, paths and promotion rules are frozen")
    text = genome["text"]
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 256_000 or "\0" in text:
        raise EvolutionError("Text must be nonempty UTF-8, <=256000 bytes, without NUL")
    return {"kind": "text", "text": text.replace("\r\n", "\n").replace("\r", "\n")}


class EvolverEngine:
    def __init__(self, store_path: str | Path):
        self.store_path = Path(store_path).resolve()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.symbolic_binary = Path(__file__).resolve().parents[2] / "rust" / "evolver-core" / "target" / "debug" / ("evolver-text-core.exe" if os.name == "nt" else "evolver-text-core")
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS domains(id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_hash TEXT NOT NULL,
                    incumbent TEXT, trials INTEGER NOT NULL DEFAULT 0, evaluations INTEGER NOT NULL DEFAULT 0,
                    active_trial TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS genomes(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lineage(domain TEXT NOT NULL, genome TEXT NOT NULL, parent TEXT,
                    operator TEXT NOT NULL, provenance TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(domain,genome));
                CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY, domain TEXT NOT NULL, candidate TEXT NOT NULL,
                    incumbent TEXT NOT NULL, number INTEGER NOT NULL, state TEXT NOT NULL, receipt TEXT NOT NULL,
                    UNIQUE(domain,candidate));
                CREATE TABLE IF NOT EXISTS observations(cache_key TEXT PRIMARY KEY, domain TEXT NOT NULL,
                    genome TEXT NOT NULL, panel TEXT NOT NULL, item TEXT NOT NULL, seed INTEGER NOT NULL,
                    result TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS panel_use(domain TEXT NOT NULL, panel TEXT NOT NULL, trial TEXT NOT NULL,
                    PRIMARY KEY(domain,panel));
                CREATE TABLE IF NOT EXISTS pareto(domain TEXT NOT NULL, genome TEXT NOT NULL, scores TEXT NOT NULL,
                    trial TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(domain,genome));
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.store_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def establish_domain(self, domain_id: str, *, judges: list[str | Path], panels: list[dict],
                         objectives: dict[str, dict], promotion: dict | None = None,
                         hard_gates: list[str] | None = None) -> dict:
        if not domain_id or not objectives or not judges or len(panels) < 4:
            raise EvolutionError("Domain needs judges, objectives and at least four disjoint panels")
        files = {}
        if not self.symbolic_binary.is_file():
            raise EvolutionError("Build the Rust L0 core with cargo build --offline --manifest-path rust/evolver-core/Cargo.toml")
        rust_root = self.symbolic_binary.parents[2]
        for raw in [*judges, Path(__file__), self.symbolic_binary, rust_root / "src" / "main.rs", rust_root / "Cargo.toml", rust_root / "Cargo.lock"]:
            path = Path(raw).resolve()
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        policy = {"alpha": .05, "min_pairs": 8, "max_trials": 20, "max_evaluations": 2000,
                  "seed": 7301, "max_seconds": 7200}
        if promotion:
            if set(promotion) - set(policy):
                raise EvolutionError("Unknown promotion policy field")
            policy.update(promotion)
        if not 0 < policy["alpha"] < .5 or policy["min_pairs"] < 4:
            raise EvolutionError("Invalid alpha/minimum paired sample count")
        for name in ["max_trials", "max_evaluations", "seed", "min_pairs", "max_seconds"]:
            if not isinstance(policy[name], int) or policy[name] < (0 if name == "seed" else 1):
                raise EvolutionError(f"Invalid promotion {name}")
        for name, objective in objectives.items():
            if set(objective) - {"direction", "tolerance", "noise"} or objective.get("direction") not in {"min", "max"}:
                raise EvolutionError(f"Invalid objective {name}")
            for field in ["tolerance", "noise"]:
                value = objective.get(field, 0)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise EvolutionError(f"Invalid objective {name}.{field}")
        seen_ids, seen_panels, normalized = set(), set(), []
        for index, raw in enumerate(panels):
            panel = json.loads(_json(raw))
            panel.setdefault("role", "discovery" if index < len(panels) // 2 else "held_out")
            if set(panel) - {"id", "role", "items"} or panel["role"] not in {"discovery", "held_out"}:
                raise EvolutionError("Invalid panel grammar")
            if panel["id"] in seen_panels or len(panel["items"]) < policy["min_pairs"]:
                raise EvolutionError("Panels need unique IDs and enough independent paired cases")
            seen_panels.add(panel["id"])
            for item in panel["items"]:
                case_id = item.get("id")
                if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
                    raise EvolutionError("Cases must have globally unique IDs; held-out overlap is forbidden")
                seen_ids.add(case_id)
            normalized.append(panel)
        if not all(any(p["role"] == role for p in normalized) for role in ["discovery", "held_out"]):
            raise EvolutionError("Separate discovery and held_out panels are required")
        if hard_gates is None or not hard_gates or any(not isinstance(g, str) or not g for g in hard_gates) or len(set(hard_gates)) != len(hard_gates):
            raise EvolutionError("Hard gate names must be nonempty and unique")
        spec = {"schema": SCHEMA, "domain": domain_id, "judges": files, "panels": normalized,
                "objectives": objectives, "promotion": policy, "genome_schema": "text/newline-equivalence/v1"}
        if hard_gates is not None:
            spec["hard_gates"] = hard_gates
        with self._db() as db:
            row = db.execute("SELECT spec_hash FROM domains WHERE id=?", (domain_id,)).fetchone()
            if row and row["spec_hash"] != _hash(spec):
                raise FrozenJudgeError("Established domain is hash locked; create a human-reviewed new domain version")
            db.execute("INSERT OR IGNORE INTO domains(id,spec,spec_hash,created) VALUES(?,?,?,?)",
                       (domain_id, _json(spec), _hash(spec), time.time()))
        return self.status(domain_id)

    def _domain(self, domain_id: str) -> tuple[dict, dict]:
        with self._db() as db:
            row = db.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
        if row is None:
            raise EvolutionError("Unknown domain")
        spec = json.loads(row["spec"])
        if _hash(spec) != row["spec_hash"]:
            raise FrozenJudgeError("Frozen domain manifest was altered")
        return dict(row), spec

    def _verify_frozen(self, domain_id: str, expected_hash: str | None = None) -> dict:
        row, spec = self._domain(domain_id)
        if expected_hash and row["spec_hash"] != expected_hash:
            raise FrozenJudgeError("Frozen manifest changed during evaluation")
        for path, expected in spec["judges"].items():
            if not Path(path).is_file() or hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise FrozenJudgeError(f"Frozen judge changed: {Path(path).name}")
        return spec

    def register_genome(self, domain_id: str, genome: dict, parent_id: str | None = None,
                        operator: str = "seed", provenance: dict | None = None) -> dict:
        self._verify_frozen(domain_id)
        payload = canonical_genome(genome)
        genome_id = _hash(payload)
        process = subprocess.run([str(self.symbolic_binary)], input=_json(payload) + "\n", capture_output=True, text=True, encoding="utf-8", timeout=10, **hidden_windows_subprocess_kwargs())
        if process.returncode:
            raise EvolutionError("Rust symbolic validation failed")
        symbolic = json.loads(process.stdout)
        if symbolic.get("id") != genome_id or symbolic.get("canonical") != payload:
            raise EvolutionError("Rust/Python canonical identities disagree")
        if not isinstance(operator, str) or not operator:
            raise EvolutionError("Mutation operator must be named")
        with self._db() as db:
            if parent_id and not db.execute("SELECT 1 FROM lineage WHERE domain=? AND genome=?", (domain_id, parent_id)).fetchone():
                raise EvolutionError("Parent must belong to this domain")
            duplicate = bool(db.execute("SELECT 1 FROM lineage WHERE domain=? AND genome=?", (domain_id, genome_id)).fetchone())
            db.execute("INSERT OR IGNORE INTO genomes VALUES(?,?)", (genome_id, _json(payload)))
            db.execute("INSERT OR IGNORE INTO lineage VALUES(?,?,?,?,?,?)",
                       (domain_id, genome_id, parent_id, operator, _json(provenance or {}), time.time()))
        return {"id": genome_id, "eclass_id": genome_id, "duplicate": duplicate,
                "canonical_bytes": len(payload["text"].encode("utf-8"))}

    def _genome(self, domain_id: str, genome_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT payload FROM genomes JOIN lineage ON genomes.id=lineage.genome WHERE domain=? AND genomes.id=?",
                             (domain_id, genome_id)).fetchone()
        if not row:
            raise EvolutionError("Genome not registered for this domain")
        payload = json.loads(row["payload"])
        if _hash(canonical_genome(payload)) != genome_id:
            raise EvolutionError("Content-addressed genome was altered")
        return payload

    def set_incumbent(self, domain_id: str, genome_id: str) -> dict:
        self._verify_frozen(domain_id)
        self._genome(domain_id, genome_id)
        with self._db() as db:
            row = db.execute("SELECT incumbent,trials FROM domains WHERE id=?", (domain_id,)).fetchone()
            if row["incumbent"] and row["incumbent"] != genome_id:
                raise EvolutionError("Incumbent changes only through paired promotion")
            db.execute("UPDATE domains SET incumbent=? WHERE id=?", (genome_id, domain_id))
        return self.status(domain_id)

    def _measure(self, domain_id: str, genome_id: str, panel: dict, item: dict, seed: int,
                 evaluator: Callable, spec: dict, manifest_hash: str, started: float) -> dict:
        self._verify_frozen(domain_id, manifest_hash)
        key = _hash([manifest_hash, genome_id, panel["id"], item, seed])
        with self._db() as db:
            cached = db.execute("SELECT result FROM observations WHERE cache_key=?", (key,)).fetchone()
            if cached:
                return {**json.loads(cached["result"]), "cache_hit": True}
            if time.monotonic() - started > spec["promotion"]["max_seconds"]:
                raise EvolutionError("Trial wall-time budget exhausted")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT evaluations FROM domains WHERE id=?", (domain_id,)).fetchone()
            if row["evaluations"] >= spec["promotion"]["max_evaluations"]:
                raise EvolutionError("Domain real-evaluation budget exhausted")
            db.execute("UPDATE domains SET evaluations=evaluations+1 WHERE id=?", (domain_id,))
        result = evaluator(self._genome(domain_id, genome_id), json.loads(_json(item)), seed)
        self._verify_frozen(domain_id, manifest_hash)
        if not isinstance(result, dict) or set(result.get("objectives", {})) != set(spec["objectives"]):
            raise EvolutionError("Evaluator must measure every frozen objective")
        for value in result["objectives"].values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EvolutionError("Objective measurements must be finite numbers")
        gates = result.get("hard_gates")
        if not isinstance(gates, dict) or not gates or any(type(value) is not bool for value in gates.values()):
            raise EvolutionError("Executable hard gates must be nonempty boolean measurements")
        if "hard_gates" in spec and set(gates) != set(spec["hard_gates"]):
            raise EvolutionError("Evaluator cannot add/remove frozen hard gates")
        result = json.loads(_json(result))
        with self._db() as db:
            db.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)",
                       (key, domain_id, genome_id, panel["id"], item["id"], seed, _json(result), time.time()))
        return {**result, "cache_hit": False}

    def _paired(self, domain_id: str, incumbent: str, candidate: str, panel: dict, evaluator: Callable,
                spec: dict, manifest_hash: str, trial_number: int, started: float) -> dict:
        def measure_pair(item):
            seed = int(hashlib.sha256(f"{spec['promotion']['seed']}:{panel['id']}:{item['id']}".encode()).hexdigest()[:8], 16)
            order = [incumbent, candidate] if seed % 2 else [candidate, incumbent]
            results = {genome_id: self._measure(domain_id, genome_id, panel, item, seed, evaluator, spec, manifest_hash, started)
                       for genome_id in order}
            return {"item": item["id"], "seed": seed, "order": order,
                    "incumbent": results[incumbent], "candidate": results[candidate]}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="evolver-pair") as workers:
            pairs = list(workers.map(measure_pair, panel["items"]))
        alpha = spec["promotion"]["alpha"] / (2 * trial_number * (trial_number + 1) * len(spec["objectives"]))
        z = statistics.NormalDist().inv_cdf(1 - alpha)
        statistics_by_objective = {}
        for name, objective in spec["objectives"].items():
            direction = 1 if objective["direction"] == "max" else -1
            deltas = [direction * (p["candidate"]["objectives"][name] - p["incumbent"]["objectives"][name]) for p in pairs]
            noise, tolerance = objective.get("noise", 0), objective.get("tolerance", 0)
            mean = statistics.mean(deltas)
            error = statistics.stdev(deltas) / math.sqrt(len(deltas)) if len(deltas) > 1 else 0
            lower = mean - z * error
            wins = sum(d > noise for d in deltas)
            losses = sum(d < -noise for d in deltas)
            effective = wins + losses
            p_value = sum(math.comb(effective, k) for k in range(wins, effective + 1)) / 2 ** effective if effective else 1
            statistics_by_objective[name] = {
                "incumbent_mean": statistics.mean(p["incumbent"]["objectives"][name] for p in pairs),
                "candidate_mean": statistics.mean(p["candidate"]["objectives"][name] for p in pairs),
                "paired_gain": mean, "standard_error": error, "lower_confidence_gain": lower,
                "wins": wins, "losses": losses, "sign_p": p_value, "alpha": alpha,
                "noninferior": lower >= -tolerance - noise,
                "improved": lower > noise and effective >= spec["promotion"]["min_pairs"] and p_value <= alpha,
            }
        hard_ok = all(all(p[side]["hard_gates"].values()) for p in pairs for side in ["incumbent", "candidate"])
        eligible = hard_ok and all(s["noninferior"] for s in statistics_by_objective.values()) and any(s["improved"] for s in statistics_by_objective.values())
        return {"panel": panel["id"], "role": panel["role"], "panel_hash": _hash(panel),
                "pairs": pairs, "statistics": statistics_by_objective, "hard_gates_passed": hard_ok,
                "eligible": eligible, "sample_count": len(pairs), "level": "L4"}

    def evaluate_candidate(self, domain_id: str, genome_id: str, evaluator: Callable) -> dict:
        domain, spec = self._domain(domain_id)
        self._verify_frozen(domain_id)
        source = inspect.getsourcefile(evaluator if inspect.isfunction(evaluator) or inspect.ismethod(evaluator) else evaluator.__call__)
        if source is None or str(Path(source).resolve()) not in spec["judges"]:
            raise FrozenJudgeError("Evaluator source must be explicitly hash-locked in the judge manifest")
        self._genome(domain_id, genome_id)
        if not domain["incumbent"]:
            raise EvolutionError("Set a seed incumbent before evolution")
        started = time.monotonic()
        trial_id = uuid.uuid4().hex
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT receipt FROM trials WHERE domain=? AND candidate=?", (domain_id, genome_id)).fetchone()
            if prior:
                return {**json.loads(prior["receipt"]), "deduplicated": True}
            if domain["incumbent"] == genome_id:
                raise EvolutionError("Candidate is canonically equivalent to the incumbent")
            fresh = db.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
            if fresh["active_trial"]:
                raise EvolutionError("Another domain trial is active; interrupted trials require explicit recovery")
            if fresh["trials"] >= spec["promotion"]["max_trials"]:
                raise EvolutionError("Domain candidate trial budget exhausted")
            number, incumbent = fresh["trials"] + 1, fresh["incumbent"]
            receipt = {"schema": SCHEMA, "id": trial_id, "domain": domain_id, "candidate": genome_id,
                       "incumbent": incumbent, "trial_number": number, "manifest_hash": domain["spec_hash"],
                       "state": "running", "promoted": False, "stages": [], "started": time.time(),
                       "code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "hardware": {"platform": platform.platform(), "machine": platform.machine()},
                       "authority": "local_domain_incumbent_only", "levels_reached": ["L0", "L1"]}
            db.execute("INSERT INTO trials VALUES(?,?,?,?,?,?,?)",
                       (trial_id, domain_id, genome_id, incumbent, number, "running", _json(receipt)))
            db.execute("UPDATE domains SET trials=?,active_trial=? WHERE id=?", (number, trial_id, domain_id))
        try:
            discovery = [p for p in spec["panels"] if p["role"] == "discovery"]
            panel = discovery[(number - 1) % len(discovery)]
            receipt["stages"].append(self._paired(domain_id, incumbent, genome_id, panel, evaluator, spec, domain["spec_hash"], number, started))
            receipt["levels_reached"].append("L4")
            if receipt["stages"][-1]["eligible"]:
                with self._db() as db:
                    used = {row["panel"] for row in db.execute("SELECT panel FROM panel_use WHERE domain=?", (domain_id,))}
                    fresh_panels = [p for p in spec["panels"] if p["role"] == "held_out" and p["id"] not in used]
                    if len(fresh_panels) < 2:
                        raise EvolutionError("Fresh held-out panels exhausted; human-reviewed new domain version required")
                    fresh_panel = fresh_panels[(number - 1) % len(fresh_panels)]
                    reconfirm_panel = next(p for p in fresh_panels if p["id"] != fresh_panel["id"])
                    # Reserve both before revealing outputs, including a failed screening.
                    for reserved in [fresh_panel, reconfirm_panel]:
                        db.execute("INSERT INTO panel_use VALUES(?,?,?)", (domain_id, reserved["id"], trial_id))
                receipt["stages"].append(self._paired(domain_id, incumbent, genome_id, fresh_panel, evaluator, spec, domain["spec_hash"], number, started))
                receipt["stages"][-1]["purpose"] = "rotating_held_out"
                if receipt["stages"][-1]["eligible"]:
                    receipt["stages"].append(self._paired(domain_id, incumbent, genome_id, reconfirm_panel, evaluator, spec, domain["spec_hash"], number, started))
                    receipt["stages"][-1]["purpose"] = "fresh_reconfirmation"
            promoted = len(receipt["stages"]) == 3 and all(stage["eligible"] for stage in receipt["stages"])
            self._verify_frozen(domain_id, domain["spec_hash"])
            receipt.update(state="accepted" if promoted else "rejected", promoted=promoted)
        except Exception as error:
            receipt.update(state="blocked", error_type=type(error).__name__, error=str(error), promoted=False)
        receipt.update(finished=time.time(), elapsed_seconds=time.monotonic() - started)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if receipt["state"] != "blocked":
                self._verify_frozen(domain_id, domain["spec_hash"])
                self._update_front(db, domain_id, genome_id, incumbent, receipt, spec)
            db.execute("UPDATE trials SET state=?,receipt=? WHERE id=?", (receipt["state"], _json(receipt), trial_id))
            db.execute("UPDATE domains SET active_trial=NULL WHERE id=? AND active_trial=?", (domain_id, trial_id))
        return receipt

    def _update_front(self, db, domain_id: str, candidate: str, incumbent: str, receipt: dict, spec: dict):
        if not receipt["stages"][-1]["hard_gates_passed"]:
            return
        scores = {name: row["candidate_mean"] for name, row in receipt["stages"][-1]["statistics"].items()}
        baseline = {name: row["incumbent_mean"] for name, row in receipt["stages"][-1]["statistics"].items()}
        evidence = {"panel": receipt["stages"][-1]["panel"], "confirmed": receipt["promoted"], "level": "L4"}
        current = db.execute("SELECT incumbent FROM domains WHERE id=?", (domain_id,)).fetchone()
        if current["incumbent"] != incumbent:
            raise EvolutionError("Incumbent changed; paired comparison is stale")
        db.execute("INSERT OR IGNORE INTO pareto VALUES(?,?,?,?,?)", (domain_id, incumbent, _json(baseline), receipt["id"], _json({**evidence, "confirmed": True})))
        # Compare only paired observations on the same panel. Across panels the
        # archive conservatively retains members with explicit evidence labels.
        gains = [(1 if o["direction"] == "max" else -1) * (scores[n] - baseline[n]) for n, o in spec["objectives"].items()]
        candidate_dominates = all(d >= 0 for d in gains) and any(d > 0 for d in gains)
        incumbent_dominates = all(d <= 0 for d in gains) and any(d < 0 for d in gains)
        if candidate_dominates and receipt["promoted"]:
            db.execute("DELETE FROM pareto WHERE domain=? AND genome=?", (domain_id, incumbent))
        if not incumbent_dominates:
            db.execute("INSERT OR REPLACE INTO pareto VALUES(?,?,?,?,?)", (domain_id, candidate, _json(scores), receipt["id"], _json(evidence)))
        if receipt["promoted"]:
            db.execute("UPDATE domains SET incumbent=? WHERE id=?", (candidate, domain_id))

    def recover_interrupted(self, domain_id: str) -> dict:
        """Explicit operator recovery never reruns/erases a counted trial."""
        self._verify_frozen(domain_id)
        with self._db() as db:
            row = db.execute("SELECT active_trial FROM domains WHERE id=?", (domain_id,)).fetchone()
            if row["active_trial"]:
                trial = db.execute("SELECT receipt FROM trials WHERE id=?", (row["active_trial"],)).fetchone()
                receipt = json.loads(trial["receipt"])
                receipt.update(state="blocked", error="Interrupted evaluator; trial and spent budget retained", promoted=False, finished=time.time())
                db.execute("UPDATE trials SET state='blocked',receipt=? WHERE id=?", (_json(receipt), row["active_trial"]))
                db.execute("UPDATE domains SET active_trial=NULL WHERE id=?", (domain_id,))
        return self.status(domain_id)

    def status(self, domain_id: str | None = None) -> dict:
        with self._db() as db:
            domains = db.execute("SELECT * FROM domains" + (" WHERE id=?" if domain_id else ""), (domain_id,) if domain_id else ()).fetchall()
            output = []
            for domain in domains:
                spec = json.loads(domain["spec"])
                trials = [json.loads(row["receipt"]) for row in db.execute("SELECT receipt FROM trials WHERE domain=? ORDER BY number", (domain["id"],))]
                lineages = [{**dict(row), "provenance": json.loads(row["provenance"])} for row in db.execute("SELECT * FROM lineage WHERE domain=? ORDER BY created", (domain["id"],))]
                front = [{"genome": row["genome"], "scores": json.loads(row["scores"]), "trial": row["trial"], **json.loads(row["evidence"])} for row in db.execute("SELECT * FROM pareto WHERE domain=?", (domain["id"],))]
                try:
                    self._verify_frozen(domain["id"])
                    lock = {"ok": True}
                except FrozenJudgeError as error:
                    lock = {"ok": False, "error": str(error)}
                output.append({"id": domain["id"], "incumbent": domain["incumbent"], "trials": domain["trials"],
                               "evaluations": domain["evaluations"], "active_trial": domain["active_trial"],
                               "manifest_hash": domain["spec_hash"], "objectives": spec["objectives"], "budget": spec["promotion"],
                               "panels": [{"id": p["id"], "role": p["role"], "count": len(p["items"])} for p in spec["panels"]],
                               "held_out_used": [row["panel"] for row in db.execute("SELECT panel FROM panel_use WHERE domain=?", (domain["id"],))],
                               "receipts": trials, "lineage": lineages, "pareto_front": front,
                               "frozen_lock": lock, "judge_hashes": {Path(path).name: digest for path, digest in spec["judges"].items()}})
        return {"schema": SCHEMA, "domains": output, "store": str(self.store_path),
                "frontier": ["Text domains only", "No L5 field promotion", "No surrogate or unrestricted e-graph"]}
