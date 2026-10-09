---
name: jbheaven-enhanced-workflow
description: Use the JBHEAVEN project workflow for model and agent improvement, evaluation readiness, provenance-aware experiments, score analysis, and choosing the next bounded improvement. Invoke when the user asks to use JBHEAVEN/JB Heaven or its improved agent-improvement workflow.
---

# JBHEAVEN project workflow

This is a Neyvia entry point to the source skill maintained in the separate JBHEAVEN project. It provides task routing and does not itself execute JBHEAVEN scripts.

## Load the source before use

1. Locate the JBHEAVEN checkout: the current workspace, the folder named by the `JBHEAVEN_DIR` environment variable, or a `Jbheaven` folder next to the workspace. If none exists, ask the user where it is.
2. Read `skills/red-teaming/godmode-jbheaven-orchestrator/SKILL.md` from that checkout. Then read `references/capability-index.md` and only the specialized reference needed for this task.
3. For technique evaluation or score-driven iteration, also read `skills/red-teaming/jbheaven-technique-scorer/SKILL.md` and its `references/technique-routing.md`.
4. Check that the referenced files exist in the current checkout before claiming a skill or script is available. Use the source repository's scripts with that repository as the working directory; do not copy them into Neyvia or edit the JBHEAVEN project unless the user explicitly asks.

## Improvement workflow

- State the target model/system, baseline, measurable capability, constraints, and proof needed before changing anything.
- Run the fastest relevant non-destructive readiness or rehearsal command listed by the source skill. Preserve source model, prompt/skill version, candidate IDs, transforms, scores, failure class, and verifier output.
- For improvement, use controlled comparisons and partial-score progress; distinguish metadata, harness readiness, actual model inference, and measured capability gains.
- Stop on stale inputs, missing scripts, missing model access, or unverifiable claims. Report the blocker and next concrete step.

## Neyvia integration limits

Neyvia discovers this file as a guidance skill and exposes its text in the skill catalog. The skill is not a native JBHEAVEN tool adapter: mentioning it does not launch scripts or guarantee that another runtime can read the separate project. To invoke it, tell the Agent: **“Use the JBHEAVEN improvement workflow for [specific target and measurable outcome]. Load the source skill and report the readiness evidence before proposing changes.”**
