# NEYVIA efficient agent harness

Open **Workflows** from chat to prepare Reader → Planner → Executor → Verifier.
The default route uses native GLM-5.3-Flash at low reasoning for routine stages and
native Astra at max reasoning for planning. Routes remain explicit; failures do
not select another model. Read-only is the default. Only the executor can receive
workspace-write and code-editing grants when read-only is turned off.

Edit Common, Chat, Reader, Planner, Executor, and Verifier instructions in
**Settings → Rules & Routing → Prompt library**. Save uses revision checks and
atomic replacement. Prepared workflows freeze role instructions and hashes;
prepare another workflow to adopt later edits. Runtime permission checks remain
outside editable prompts.

The graph freezes its execution workspace. Reader context becomes a bounded
evidence handoff for later stages; full results remain in the durable graph.
The SDK planner receives only the question tool, so it cannot reread the source.
Questions are stored with the runtime session, pause dependent stages, and resume
after a real answer. The panel restores the saved workflow and shows stage
results, failures, and pending questions.

Native SDK instructions use the agent instructions channel. The supervised
Codex transport uses developer instructions. Other supported runtime adapters
receive the role contract in the task prompt. SDK turn/output limits are enforced
by the SDK/provider; the Codex transport has a process timeout and a requested
turn limit in its prompt, not an SDK turn counter.

The verifier returns JSON containing verdict (pass, fail, or unverified),
summary, and an evidence array. Missing/invalid verdicts and evidence-free
passes cannot complete the graph. This validates the result contract, not the
truth of every model statement; inspect the attached evidence.

Vision tools return actual image content. Chat Completions gets the two latest
images in its supported user-content channel because its tool channel accepts
text. Images must be in the workspace or managed proof directory. Read-only
captures cannot choose arbitrary output paths. A model still needs vision
support from its provider; the tool does not manufacture it.

Key modules: agent_prompt_library.py, agent_questions.py, efficient_workflow.py,
agent_vision.py, neyvia_agent.py, and NeyviaAgentHarnessPanel.jsx.
Storage lives under .agent_control and is excluded from source archives.
No prompts or credentials are stored in Codex settings.

Provider contract: [GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash)
supports low/high/max reasoning; omitted reasoning defaults to max.
[OpenCode Go endpoints](https://opencode.ai/docs/go/#endpoints) determine the
native transport. Keep capability metadata and transport serialization aligned.

Backend accounting now includes compaction requests and format retries in the native run receipt,
with separate execution/compaction stages. Failures retain measured partial usage; absent provider
counters remain unknown. Codex app-server usage uses cumulative thread totals, and resumed totals
need a current baseline before they can become a per-run delta. Duplicate notifications are ignored.
Claude cache read/creation fields are normalized to input inclusive of cache, with cache read as a subset.

`GET /api/ui/analytics` and the Night Shift resources API expose the scoped receipts and controls;
see [the workspace manual](manuals/neyvia.md). This does not add extra model calls, change authored
prompts, lower reasoning settings or replace provider compaction. Native-to-Codex still starts an
ephemeral app-server process for each operation; pooling and fidelity comparisons need separate proof.

Run `node docs/verification/backend-resources.mjs` for deterministic broker/scheduler acceptance,
and `node docs/verification/backend-resource-http.mjs` against a disposable backend on 47891.
Also run the existing context, semantic compaction and native stream fixtures after accounting changes.
These checks validate contracts and recovery; they do not establish a universal quality winner or cash savings.
