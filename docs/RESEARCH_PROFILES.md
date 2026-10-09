# Neyvia research profiles

Neyvia separates research workflow from reasoning effort.

- `Deep Research` is for scientific and technical synthesis. It triangulates primary sources, compares competing explanations, records contradictory evidence, and distinguishes supported claims from inference.
- `Experiment Lab` is for empirical comparisons. It runs a bounded model, architecture, and storage matrix; requires a baseline; records system and quality metrics; and retains failed or stopped trials.
- `Ultra` remains an optional reasoning effort. It can be selected with either profile, but it does not replace the profile's research contract.

## Model policy

The default orchestration routes are deliberately bounded:

- planner: GPT-5.6 Sol, low effort
- executor/controller: GPT-5.6 Sol, low effort
- verifier: GPT-5.6 Luna, xhigh effort

Experiment subject models are separate from orchestration models. The subject pool can contain any configured provider/model pair. Missing authentication or an unavailable provider blocks that row and must not be replaced with invented measurements.

## NVMe experiments

Experiment Lab treats "scale with NVMe before adding VRAM" as a hypothesis, not a promise. Every comparison records:

- quality score
- wall-clock time and throughput
- peak VRAM and system RAM
- NVMe reads, writes, and I/O wait
- failures and retries
- estimated cost

The default starter matrix compares `vram_resident` and `nvme_offload` storage modes across a baseline and a candidate architecture. It is capped at 24 cells and one concurrent run so resource contention does not invalidate the comparison. Increase either value only when the experimental plan justifies it.

## Proof gate

Deep Research cannot pass without a report, source manifest, claim/evidence matrix, readable screenshot, and accepted verifier receipt.

Experiment Lab cannot pass without a report, reproducible run manifest, machine-readable metrics dataset, failed-attempt ledger, and accepted verifier receipt. All declared files must be linked through the mission artifact manifest.

## SDK

Use `build_deep_research_contract` / `FluxioClient.deep_research_mission` for evidence synthesis and `build_experiment_lab_contract` / `FluxioClient.experiment_lab_mission` for measured comparisons. The experiment builder rejects a matrix larger than its explicit cell budget instead of silently truncating it.
