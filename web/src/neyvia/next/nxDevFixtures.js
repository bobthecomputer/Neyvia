// Development-only design states for the control UI (`?fixtures=1` under
// `vite dev`). Never bundled into a production build: nxApi imports this
// module only behind `import.meta.env.DEV`.

const now = Date.now();
const iso = minutesAgo => new Date(now - minutesAgo * 60000).toISOString();
const host = { deviceId: "dev", deviceName: "ASUSPSDLB" };

const cap = (overrides = {}) => ({
  continue_session: true, new_session: true, stop: true, approvals: true, questions: true, images: true,
  goal: false, compact: true, steer: false, model_choice: true, effort_choice: true, permission_choice: true,
  billing: null, reason: null, ...overrides,
});

const sessions = [
  { id: "s-claude-live", app: "claude-code", category: "connected", title: "Build two-tier EXL3 offload for the 3090", project: "rtx-3090", cwd: "C:\\Users\\dev\\Projects\\rtx-3090", git_branch: "exl3-offload", model: "claude-opus-5-5", status: "working", status_since: iso(13), updated_at: iso(0.2), capabilities: cap({ billing: "agent-sdk-credits", steer: true }) },
  { id: "s-codex-approve", app: "codex", category: "connected", title: "Improve step-5 quantization quality", project: "sero", cwd: "C:\\Users\\dev\\Projects\\sero", git_branch: "main", model: "gpt-5.6", status: "waiting_approval", status_since: iso(2), updated_at: iso(2), unread: true, capabilities: cap({ goal: true, steer: true }) },
  { id: "s-neyvia-native", app: "neyvia", category: "native", runtime: "neyvia-agent", title: "Find a Corsair 9000D on Amazon", project: "sero", updated_at: iso(21), status: "idle", capabilities: cap({ permission_choice: false }) },
  { id: "s-hybrid", app: "neyvia", category: "hybrid", runtime: "codex", title: "Automate project completion checklist", project: "sero", updated_at: iso(19), status: "idle", unread: true, capabilities: cap() },
  { id: "s-claude-question", app: "claude-code", category: "connected", title: "Center and constrain the session column", project: "litter", cwd: "C:\\Users\\dev\\Projects\\litter", git_branch: "ios/center-session-column", status: "waiting_input", updated_at: iso(14), capabilities: cap({ billing: "agent-sdk-credits" }) },
  { id: "s-codex-failed", app: "codex", category: "connected", title: "Intel Arc B70 compatibility sweep", project: "sero", cwd: "C:\\Users\\dev\\Projects\\sero", git_branch: "arc-b70", status: "failed", updated_at: iso(120), capabilities: cap({ goal: true }) },
  { id: "s-claude-old", app: "claude-code", category: "connected", title: "UI polish and performance optimization", project: "Neyvia", cwd: "C:\\Users\\dev\\Projects\\Neyvia", git_branch: "main", status: "idle", updated_at: iso(60 * 26), capabilities: cap({ billing: "agent-sdk-credits" }) },
  { id: "s-claude-trust", app: "claude-code", category: "connected", title: "Set up the plotter project", project: "plotter", cwd: "C:\\Users\\dev\\Projects\\plotter", status: "waiting_approval", updated_at: iso(1), unread: true, capabilities: cap({ billing: "agent-sdk-credits" }) },
  { id: "s-opencode", app: "opencode", category: "connected", title: "Draft release notes", project: "Neyvia", cwd: "C:\\Users\\dev\\Projects\\Neyvia", status: "idle", updated_at: iso(60 * 50), capabilities: cap({ continue_session: false, reason: "OpenCode chats are read-only from Neyvia for now." }) },
  // "No folder" (07 §4): Codex's dated scratch folders, generated images, temp dirs; some stale.
  { id: "s-nf-logo", app: "codex", category: "connected", title: "Generate a komorebi logo sketch", project: "komorebi-logo", cwd: "C:\\Users\\dev\\Documents\\Codex\\2026-09-29\\komorebi-logo", status: "idle", created_at: iso(60 * 30), updated_at: iso(60 * 29), capabilities: cap() },
  { id: "s-nf-img", app: "codex", category: "connected", title: "Tree canopy wallpaper variations", project: "7f3a9c", cwd: "C:\\Users\\dev\\.codex\\generated_images\\7f3a9c", status: "idle", created_at: iso(60 * 24 * 9), updated_at: iso(60 * 24 * 9), capabilities: cap() },
  { id: "s-nf-quick", app: "claude-code", category: "connected", title: "What does EXL3 stand for?", project: "Temp", cwd: "C:\\Users\\dev\\AppData\\Local\\Temp\\q1", status: "idle", created_at: iso(62), updated_at: iso(60), capabilities: cap() },
  { id: "s-nf-quick-old", app: "codex", category: "connected", title: "Convert 3.2 GiB to GB", project: "unit-convert", cwd: "C:\\Users\\dev\\Documents\\Codex\\2026-09-12\\unit-convert", status: "idle", created_at: iso(60 * 24 * 18 + 3), updated_at: iso(60 * 24 * 18), capabilities: cap() },
  { id: "s-nf-other", app: "codex", category: "connected", title: "Compare three NAS backup plans", project: "nas-backup", cwd: "C:\\Users\\dev\\Documents\\Codex\\2026-09-20\\nas-backup", status: "idle", created_at: iso(60 * 24 * 11), updated_at: iso(60 * 24 * 10), capabilities: cap() },
  { id: "s-old-project", app: "claude-code", category: "connected", title: "Sketch the Chronos release beat", project: "litter", cwd: "C:\\Users\\dev\\Projects\\litter", git_branch: "main", status: "idle", updated_at: iso(60 * 24 * 41), capabilities: cap({ billing: "agent-sdk-credits" }) },
];

let seq = 0;
const item = (kind, data, extra = {}) => ({ id: `i${++seq}`, seq, kind, at: iso(10 - seq * 0.1), data, ...extra });

const liveItems = [
  item("user", { text: "Can we offload the cold experts to system RAM and keep hot ones on the 3090? Check the J240 plan first." }),
  item("reasoning", { summary: "**Reading the plan**\n\nThe J240 evaluation mixes native, 2-bit and 3-bit experts in one layer; I should confirm the loader supports mixed formats before touching the offload path.", hidden: false }),
  item("tool", { name: "Read", category: "read", title: "PREREGISTRATION-NIGHT2.md", files: ["C:\\Users\\dev\\Projects\\rtx-3090\\PREREGISTRATION-NIGHT2.md"], status: "ok", output: "# Night 2 preregistration\n…" }),
  item("tool", { name: "Grep", category: "search", title: "expert_offload", status: "ok", output: "src/loader.py:88: def expert_offload(...)" }),
  item("tool", { name: "Bash", category: "command", title: "python -m pytest tests/test_loader.py -q", status: "error", exitCode: 1, output: "F..\nFAILED tests/test_loader.py::test_mixed_formats - AssertionError: 2-bit expert loaded as 3-bit" }),
  item("reasoning", { summary: "", hidden: true }),
  item("assistant", { text: "The loader test fails on mixed formats: a **2-bit expert is read as 3-bit** when it sits next to native experts in the same layer.\n\nI'll fix the format lookup in `expert_offload` first, then run the offload benchmark.\n\n```python\nfmt = layer.expert_format(index)  # was layer.format\n```" }),
  item("tool", { name: "Edit", category: "edit", title: "loader.py", files: ["C:\\Users\\dev\\Projects\\rtx-3090\\loader.py"], status: "ok", output: "" }),
  item("tool", { name: "Bash", category: "command", title: "python -m pytest tests/test_loader.py -q", status: "running", output: "" }),
];

const threads = {
  "s-claude-live": { items: liveItems, context: { used_tokens: 183369, window_tokens: 1000000, auto_compact_tokens: null } },
  "s-codex-approve": {
    items: [
      item("user", { text: "Quantize step 5 again with the new calibration set and compare perplexity." }),
      item("assistant", { text: "I'll rebuild the calibration windows, then run the quantizer. This needs to write to `D:\\models`." }),
      item("compaction", { state: "completed", beforeTokens: 241000, afterTokens: 38000 }),
      item("diff", { files: [{ path: "quant/step5.py", additions: 42, deletions: 9 }, { path: "quant/calib.py", additions: 7, deletions: 2 }] }),
    ],
    context: { used_tokens: 38200, window_tokens: 258400 },
    run: { runId: "r1", state: "waiting_approval", startedAt: iso(3), canStop: true, pendingRequest: { requestId: "q1", kind: "approval", title: "Codex wants to run a command", detail: "Writes the quantized weights outside the workspace.", command: "python quant/run.py --step 5 --out D:\\models\\sero-q5", cwd: "C:\\Users\\dev\\Projects\\sero", choices: ["approve", "deny"] } },
  },
  "s-claude-question": {
    items: [
      item("user", { text: "Center the session column and cap its width on iPad." }),
      item("assistant", { text: "Two layouts would work here. Which one should I build?" }),
    ],
    context: { used_tokens: 52000 },
    run: { runId: "r2", state: "waiting_input", startedAt: iso(1), canStop: true, pendingRequest: { requestId: "q2", kind: "question", questions: [{ id: "layout", header: "Layout", question: "How should the column behave on wide screens?", options: [{ label: "Fixed 720px", description: "Centered, same width as iPhone landscape" }, { label: "Fluid to 900px", description: "Grows with the window, then stops" }] }] } },
  },
  "s-claude-trust": {
    items: [item("user", { text: "Start the plotter project here." })],
    run: { runId: "r4", state: "waiting_approval", startedAt: iso(1), canStop: true, pendingRequest: {
      requestId: "trust-1", kind: "approval", category: "folder_trust", title: "Trust this folder in Claude Code?", choices: ["approve", "deny"],
      cwd: "C:\\Users\\dev\\Projects\\plotter",
      detail: "Do you trust the files in this folder?\n\nC:\\Users\\dev\\Projects\\plotter\n\nClaude Code may read, write, or execute files contained in this directory. This can pose security risks, so only use files from trusted sources.",
    } },
  },
  "s-codex-failed": {
    items: [item("user", { text: "Sweep every kernel for Arc B70 support." }), item("tool", { name: "shell", category: "command", title: "python sweep.py --device xpu", status: "error", exitCode: 3, output: "RuntimeError: XPU device not found" })],
    context: { used_tokens: 12000, window_tokens: 258400 },
    run: { runId: "r3", state: "failed", error: "Codex stopped: the XPU device was not found on this PC." },
  },
  "s-claude-old": {
    items: [
      item("user", { text: "Tighten the sidebar spacing and measure first paint before and after." }),
      item("tool", { name: "Edit", category: "edit", title: "nxSidebar.css", files: ["C:\\Users\\dev\\Projects\\Neyvia\\web\\src\\nxSidebar.css"], status: "ok", output: "" }),
      item("assistant", { text: "# Sidebar spacing: first paint 412 ms to 268 ms\n\n| Measure | Before | After |\n|---|---|---|\n| First paint | 412 ms | 268 ms |\n| Row height | 34 px | 30 px |\n\nNot measured: the phone layout." }),
    ],
    context: { used_tokens: 52000, window_tokens: 1000000 },
    run: { runId: "r5", state: "completed", startedAt: iso(70), updatedAt: iso(62) },
  },
};
const fixtureFeedback = {}; // runId -> Feedback (plans/15-handoff.md ## C9)

const options = {
  "claude-code": {
    models: [
      { id: "claude-opus-5-5", label: "Opus 5.5", description: "Most capable · 1M context", efforts: ["low", "medium", "high", "max"], defaultEffort: "high", default: true },
      { id: "claude-sonnet-5-5", label: "Sonnet 5.5", description: "Fast and strong for everyday tasks", efforts: ["low", "medium", "high"], defaultEffort: "medium" },
      { id: "claude-haiku-4-5", label: "Haiku 4.5", description: "Quickest, lightest", efforts: [] },
    ],
    permissionModes: [
      { id: "default", label: "Ask first", description: "Asks before edits and commands", default: true },
      { id: "acceptEdits", label: "Auto-edit", description: "Edits files, asks before commands" },
      { id: "plan", label: "Plan only", description: "Reads and plans, changes nothing" },
      { id: "bypassPermissions", label: "Full access", description: "Runs everything without asking" },
    ],
    auth: { kind: "signed-out", label: "no sign-in" },
    transports: [
      { id: "print", label: "Agent SDK credit", default: true, available: true, risk: null, note: null,
        description: "Claude Code's print mode (claude -p). Anthropic bills it to your monthly Agent SDK credit, separate from your plan's limits." },
      { id: "terminal", label: "Plan limits", default: false, available: true, note: null,
        description: "Claude Code's normal interactive mode, run in a hidden terminal on this PC with your message as its prompt.",
        risk: "Anthropic's terms restrict automated access to Claude, and here a program starts Claude Code for you. This could put your Claude account at risk.",
        limits: ["Images are saved on the PC and opened by Claude", "Replies arrive step by step, not word by word"] },
    ],
  },
  codex: {
    models: [
      { id: "gpt-5.6", label: "GPT-5.6", description: "Default for Codex", efforts: ["low", "medium", "high", "xhigh"], defaultEffort: "medium", default: true },
      { id: "gpt-5.6-mini", label: "GPT-5.6 mini", description: "Faster, cheaper", efforts: ["low", "medium", "high"], defaultEffort: "medium" },
    ],
    permissionModes: [
      { id: "on-request", label: "Ask for approval", description: "Asks before leaving the workspace", default: true },
      { id: "workspace", label: "Auto in workspace", description: "Edits and runs inside the project" },
      { id: "full", label: "Full access", description: "No sandbox, no prompts" },
    ],
    auth: { kind: "signed-out", label: "no sign-in" },
  },
};

// Signing in finishes a few seconds after it starts, so the waiting state is visible.
const signIns = {};

// ---- Workspace panel: git and GitHub state, diffs and actions ----------------
// A few scenarios keyed by chat, plus `?ws=` overrides for the odd states
// (offline, error, slow, detached, merged, draft, passing, pending, many, truncated, gh-missing, actionfail).

const wsParam = new URLSearchParams(globalThis.location?.search || "").get("ws") || "";
// `&idle=1`: nothing is running (the working chat reads as idle), to see the still shell (15 · T2).
const idleParam = new URLSearchParams(globalThis.location?.search || "").get("idle") === "1";

/** A unified diff from hunks written as " context", "-removed" and "+added" lines; counts are computed. */
function makePatch(path, hunks, { head = [], oldPath = "" } = {}) {
  const out = [`diff --git a/${oldPath || path} b/${path}`, ...head];
  const created = head.some(line => line.startsWith("new file"));
  const removed = head.some(line => line.startsWith("deleted file"));
  if (!head.some(line => line.startsWith("index") || line.startsWith("similarity"))) out.push("index 3fa2c1d..b8e91a7 100644");
  out.push(`--- ${created ? "/dev/null" : `a/${oldPath || path}`}`, `+++ ${removed ? "/dev/null" : `b/${path}`}`);
  let shift = 0;
  for (const hunk of hunks) {
    const lines = hunk.lines;
    const before = lines.filter(line => line[0] !== "+" && line[0] !== "\\").length;
    const after = lines.filter(line => line[0] !== "-" && line[0] !== "\\").length;
    const start = hunk.at ?? 1;
    out.push(`@@ -${before ? start : 0}${before === 1 ? "" : `,${before}`} +${after ? start + shift : 0}${after === 1 ? "" : `,${after}`} @@${hunk.section ? ` ${hunk.section}` : ""}`, ...lines);
    shift += after - before;
  }
  return `${out.join("\n")}\n`;
}
const tally = patch => ({
  additions: patch.split("\n").filter(line => line.startsWith("+") && !line.startsWith("+++")).length,
  deletions: patch.split("\n").filter(line => line.startsWith("-") && !line.startsWith("---")).length,
});
const file = (path, status, patch, extra = {}) => ({ path, status, ...(patch ? tally(patch) : { additions: null, deletions: null }), staged: status === "added", ...extra });

const seroPatches = {
  "quant/step5.py": makePatch("quant/step5.py", [
    { at: 38, section: "LOGGER = logging.getLogger(__name__)", lines: [
      " def build_calibration_windows(shards, tokenizer, seq_len, count, rng):",
      '     """Cut the calibration corpus into fixed-length token windows."""',
      "     windows = []",
      "     for shard in shards:",
      "-        tokens = tokenizer.encode(shard.text)",
      "-        windows.append(tokens[:seq_len])",
      "+        tokens = tokenizer.encode(shard.text, add_special_tokens=False)",
      "+        # Slide with 50% overlap so rare tokens near a window edge are still seen.",
      "+        stride = max(1, seq_len // 2)",
      "+        for start in range(0, max(1, len(tokens) - seq_len + 1), stride):",
      "+            windows.append(tokens[start:start + seq_len])",
      "     rng.shuffle(windows)",
      "     return windows[:count]",
    ] },
    { at: 97, section: "def collect_hessians(model, group, windows):", lines: [
      " def quantize_layer_group(model, group, windows, config):",
      "     hessians = collect_hessians(model, group, windows)",
      "-    for name, module in group.linear_modules():",
      "-        h = hessians[name]",
      "-        module.weight.data = gptq_quantize(module.weight.data, h, bits=config.bits)",
      "+    damp = config.hessian_damp",
      "+    for name, module in group.linear_modules():",
      "+        h = hessians[name]",
      "+        # Retry with heavier damping when the Cholesky factor is not positive definite.",
      "+        for attempt in range(3):",
      "+            try:",
      "+                module.weight.data = gptq_quantize(module.weight.data, h, bits=config.bits, damp=damp * 4**attempt)",
      "+                break",
      "+            except NotPositiveDefiniteError:",
      '+                LOGGER.warning("step5 %s: Hessian not positive definite at damp=%.4f, retrying", name, damp * 4**attempt)',
      "+        else:",
      '+            raise QuantizationError(f"{name}: no damping level produced a positive definite Hessian (last damp={damp * 4**2:.4f})")',
      '+    LOGGER.info("step5 layer_group=%s bits=%s calib_windows=%d calib_seed=%d hessian_damp=%.4f group_size=%d act_order=%s sym=%s target=%s", group.name, config.bits, len(windows), config.seed, damp, config.group_size, config.act_order, config.sym, config.target_device)',
      "     return group",
    ] },
  ]),
  "quant/calib.py": makePatch("quant/calib.py", [
    { at: 3, lines: [" import json", "+import hashlib", " from pathlib import Path", " "] },
    { at: 12, section: "from .tokens import load_shards", lines: [
      " ",
      "-DEFAULT_SEED = 1234",
      "+DEFAULT_SEED = 20260729",
      "+",
      "+",
      "+def stable_seed(name: str) -> int:",
      '+    """A per-shard seed that does not change when the shard list is reordered."""',
      "+    return int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)",
      " ",
    ] },
  ]),
  "tests/test_step5_calibration.py": makePatch("tests/test_step5_calibration.py", [
    { at: 1, lines: [
      "+import random",
      "+",
      "+import pytest",
      "+",
      "+from quant.step5 import build_calibration_windows",
      "+",
      "+",
      "+class FakeTokenizer:",
      "+    def encode(self, text, add_special_tokens=True):",
      "+        return list(range(len(text)))",
      "+",
      "+",
      "+class Shard:",
      "+    def __init__(self, text):",
      "+        self.text = text",
      "+",
      "+",
      '+@pytest.mark.parametrize("seq_len", [8, 16])',
      "+def test_windows_overlap_by_half(seq_len):",
      '+    shards = [Shard("x" * 64)]',
      "+    windows = build_calibration_windows(shards, FakeTokenizer(), seq_len, 100, random.Random(0))",
      "+    starts = sorted(window[0] for window in windows)",
      "+    assert starts[1] - starts[0] == seq_len // 2",
      "+",
      "+",
      "+def test_short_shard_still_yields_one_window():",
      '+    windows = build_calibration_windows([Shard("abc")], FakeTokenizer(), 8, 10, random.Random(0))',
      "+    assert len(windows) == 1",
    ] },
  ], { head: ["new file mode 100644", "index 0000000..7c1d9e2"] }),
  "scripts/tmp_ppl_check.py": makePatch("scripts/tmp_ppl_check.py", [
    { at: 1, lines: [
      "-# scratch: compare perplexity before/after step 5 (delete when the harness covers this)",
      "-import sys",
      "-from quant.eval import perplexity",
      "-",
      "-baseline = perplexity(sys.argv[1])",
      "-candidate = perplexity(sys.argv[2])",
      '-print(f"baseline={baseline:.3f} candidate={candidate:.3f} delta={candidate - baseline:+.3f}")',
    ] },
  ], { head: ["deleted file mode 100644", "index 5d0a3f8..0000000"] }),
  "notes/step5-perplexity.md": makePatch("notes/step5-perplexity.md", [
    { at: 1, lines: [
      "+# Step 5 perplexity, per layer group",
      "+",
      "+| group | baseline | candidate |",
      "+| --- | --- | --- |",
      "+| attn | 6.412 | 6.398 |",
      "+| mlp | 6.412 | 6.471 |",
      "+",
      "+The mlp group regressed by 0.059. Hessian damping retries are the suspect.",
      "\\ No newline at end of file",
    ] },
  ], { head: ["new file mode 100644", "index 0000000..e69de29"] }),
};
const seroChanges = [
  file("quant/step5.py", "modified", seroPatches["quant/step5.py"]),
  file("quant/calib.py", "modified", seroPatches["quant/calib.py"]),
  file("tests/test_step5_calibration.py", "added", seroPatches["tests/test_step5_calibration.py"]),
  file("scripts/tmp_ppl_check.py", "deleted", seroPatches["scripts/tmp_ppl_check.py"]),
  file("notes/step5-perplexity.md", "untracked", seroPatches["notes/step5-perplexity.md"]),
];

const longDoc = "docs/experiments/J240-mixed-format-evaluation-notes-night2-preregistration-followup.md";
const rtxPatches = {
  "src/rtx3090/offload/expert_offload.py": makePatch("src/rtx3090/offload/expert_offload.py", [
    { at: 84, section: "class ExpertCache:", lines: [
      " def expert_offload(layer, hot_ids, budget_bytes):",
      "-    fmt = layer.format",
      "+    fmt = layer.expert_format(index)",
      "     resident = {i: layer.experts[i] for i in hot_ids}",
      "     cold = [i for i in range(len(layer.experts)) if i not in resident]",
      "+    # Pin cold experts in page-locked RAM so a miss costs one DMA, not a copy.",
      "+    for i in cold:",
      "+        layer.experts[i] = layer.experts[i].pin_memory()",
      "     return ExpertCache(resident, cold, budget_bytes)",
    ] },
  ]),
  "src/rtx3090/loader.py": makePatch("src/rtx3090/loader.py", [
    { at: 20, section: "def read_header(fp):", lines: [
      "     def load_layer(self, index):",
      "-        return self._read(index, self.default_format)",
      "+        return self._read(index, self.layer_formats.get(index, self.default_format))",
    ] },
  ], { oldPath: "src/rtx3090/loader_v1.py", head: ["similarity index 91%", "rename from src/rtx3090/loader_v1.py", "rename to src/rtx3090/loader.py", "index a41c0de..0e5b7f2 100644"] }),
  "tests/test_loader.py": makePatch("tests/test_loader.py", [
    { at: 52, section: "def test_native_layer_roundtrip():", lines: [
      " def test_mixed_formats():",
      "     layer = build_layer(formats=[\"native\", \"exl3-2bit\", \"exl3-3bit\"])",
      "-    assert layer.expert_format(1) == \"exl3-3bit\"",
      "+    assert layer.expert_format(1) == \"exl3-2bit\"",
      "+    assert layer.expert_format(2) == \"exl3-3bit\"",
    ] },
  ]),
  [longDoc]: makePatch(longDoc, [
    { at: 1, lines: ["+# J240 mixed-format follow-up", "+", "+Preregistered check: mixed native, 2-bit and 3-bit experts in one layer must load without format drift."] },
  ], { head: ["new file mode 100644", "index 0000000..1b6a2c4"] }),
  "assets/offload-diagram.png": "diff --git a/assets/offload-diagram.png b/assets/offload-diagram.png\nindex 91a2b3c..4d5e6f7 100644\nBinary files a/assets/offload-diagram.png and b/assets/offload-diagram.png differ\n",
};
const rtxChanges = [
  file("src/rtx3090/offload/expert_offload.py", "modified", rtxPatches["src/rtx3090/offload/expert_offload.py"]),
  file("src/rtx3090/loader.py", "renamed", rtxPatches["src/rtx3090/loader.py"], { oldPath: "src/rtx3090/loader_v1.py", staged: true }),
  file("tests/test_loader.py", "modified", rtxPatches["tests/test_loader.py"]),
  file(longDoc, "untracked", rtxPatches[longDoc]),
  file("assets/offload-diagram.png", "modified", null),
];

const oldPatches = {
  "README.md": makePatch("README.md", [{ at: 8, lines: [" ## Install", " ", "-Run `pip install neyvia`.", "+Run `uv tool install neyvia`.", " "] }]),
  "scratch/ideas.txt": makePatch("scratch/ideas.txt", [{ at: 1, lines: ["+try a per-project default model"] }], { head: ["new file mode 100644"] }),
};

const diffTable = { "s-codex-approve": seroPatches, "s-claude-live": rtxPatches, "s-claude-old": oldPatches };

const noGh = { installed: true, authenticated: false, reason: "The GitHub CLI is not signed in. Run `gh auth login` on this PC." };
const ghOk = { installed: true, authenticated: true, reason: null };
const repoOf = (root, name, github = true) => ({
  root, name, remoteUrl: github ? `https://github.com/bobthecomputer/${name}.git` : "git@gitlab.com:paul/neyvia.git",
  github: github ? { owner: "bobthecomputer", name, url: `https://github.com/bobthecomputer/${name}` } : null,
});
const emptyWorkspace = { cwd: null, exists: false, repo: null, branch: null, detached: false, upstream: null, ahead: null, behind: null, worktrees: [], changes: [], changesTruncated: false, pullRequest: null, gh: ghOk };

const scenarios = {
  "s-codex-approve": () => ({
    cwd: "C:\\Users\\dev\\Projects\\sero", exists: true, repo: repoOf("C:\\Users\\dev\\Projects\\sero", "sero"),
    branch: "quant/step5-recalibrate", detached: false, upstream: "origin/quant/step5-recalibrate", ahead: 2, behind: 0,
    worktrees: [
      { path: "C:\\Users\\dev\\Projects\\sero", branch: "quant/step5-recalibrate", current: true },
      { path: "C:\\Users\\dev\\Projects\\sero-arc-b70", branch: "arc-b70", current: false },
    ],
    changes: seroChanges, changesTruncated: false,
    pullRequest: { number: 482, title: "Recalibrate step-5 quantization windows and report perplexity per layer group", url: "https://github.com/bobthecomputer/sero/pull/482", state: "open", checks: "failing" },
    gh: ghOk,
  }),
  "s-claude-live": () => ({
    cwd: "C:\\Users\\dev\\Projects\\rtx-3090", exists: true, repo: repoOf("C:\\Users\\dev\\Projects\\rtx-3090", "rtx-3090"),
    branch: "exl3-offload", detached: false, upstream: "origin/exl3-offload", ahead: 3, behind: 0,
    worktrees: [
      { path: "C:\\Users\\dev\\Projects\\rtx-3090-main", branch: "main", current: false },
      { path: "C:\\Users\\dev\\Projects\\rtx-3090", branch: "exl3-offload", current: true },
    ],
    changes: rtxChanges, changesTruncated: false, pullRequest: null, gh: ghOk,
  }),
  "s-claude-question": () => ({
    cwd: "C:\\Users\\dev\\Projects\\litter", exists: true, repo: repoOf("C:\\Users\\dev\\Projects\\litter", "litter"),
    branch: "ios/center-session-column", detached: false, upstream: "origin/ios/center-session-column", ahead: 0, behind: 0,
    worktrees: [{ path: "C:\\Users\\dev\\Projects\\litter", branch: "ios/center-session-column", current: true }],
    changes: [], changesTruncated: false, pullRequest: null, gh: noGh,
  }),
  "s-claude-old": () => ({
    cwd: "C:\\Users\\dev\\Projects\\Neyvia", exists: true, repo: repoOf("C:\\Users\\dev\\Projects\\Neyvia", "Neyvia", false),
    branch: "main", detached: false, upstream: "origin/main", ahead: 1, behind: 3, worktrees: [{ path: "C:\\Users\\dev\\Projects\\Neyvia", branch: "main", current: true }],
    changes: [file("README.md", "modified", oldPatches["README.md"]), file("scratch/ideas.txt", "untracked", oldPatches["scratch/ideas.txt"])], changesTruncated: false,
    pullRequest: null, gh: ghOk,
  }),
  "s-opencode": () => ({ ...emptyWorkspace, cwd: "C:\\Users\\dev\\Projects\\Neyvia", exists: true }),
  "s-codex-failed": () => ({ ...emptyWorkspace, cwd: "C:\\Users\\dev\\Projects\\sero-arc-b70" }),
};

// The state of each folder lives for the page's lifetime, so commit, push and
// pull request visibly change what the next refresh returns.
const live = {};
function workspaceState(id) {
  if (!live[id]) {
    live[id] = JSON.parse(JSON.stringify(scenarios[id]?.() || emptyWorkspace));
    const state = live[id];
    if (state.pullRequest && ["passing", "pending"].includes(wsParam)) state.pullRequest.checks = wsParam;
    if (state.pullRequest && ["merged", "draft"].includes(wsParam)) state.pullRequest.state = wsParam;
    if (wsParam === "detached" && state.repo) Object.assign(state, { branch: null, detached: true, upstream: null, ahead: null, behind: null });
    if (wsParam === "gh-missing") state.gh = { installed: false, authenticated: false, reason: "The GitHub CLI (gh) is not installed on this PC." };
    if (wsParam === "many" && state.repo) {
      state.changes = Array.from({ length: 60 }, (_, index) => file(`src/generated/module_${String(index).padStart(2, "0")}.py`, index % 7 === 0 ? "added" : "modified", makePatch(`src/generated/module_${index}.py`, [{ at: 4, lines: [" value = 1", "-old = True", "+old = False"] }])));
      state.changesTruncated = true;
    }
  }
  return live[id];
}

const fail = (message, code) => Object.assign(new Error(message), { code });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

async function workspaceCall(command, payload) {
  const id = payload?.id;
  if (wsParam === "offline") throw fail("The PC service can't be reached.", "network");
  if (command === "connected_session_workspace_command") {
    if (wsParam === "error") throw fail("git could not read this folder: fatal: detected dubious ownership in repository", "workspace_failed");
    if (wsParam === "slow") await wait(6000);
    return JSON.parse(JSON.stringify(workspaceState(id)));
  }
  if (command === "connected_session_file_diff_command") {
    await wait(200);
    const patch = diffTable[id]?.[payload.path] ?? makePatch(payload.path, [{ at: 4, lines: [" value = 1", "-old = True", "+old = False"] }]);
    return { path: payload.path, patch, truncated: wsParam === "truncated" };
  }
  // connected_session_git_action_command
  if (payload?.confirm !== true) throw fail("This action changes your repository. Confirm it to continue.", "confirmation_required");
  await wait(900);
  const state = workspaceState(id);
  if (wsParam === "actionfail") {
    return { ok: false, output: payload.action === "push"
      ? "To https://github.com/bobthecomputer/sero.git\n ! [rejected]        quant/step5-recalibrate -> quant/step5-recalibrate (fetch first)\nerror: failed to push some refs to 'https://github.com/bobthecomputer/sero.git'\nhint: Updates were rejected because the remote contains work that you do not have locally."
      : "error: gpg failed to sign the data\nfatal: failed to write commit object" };
  }
  if (payload.action === "commit") {
    const committed = state.changes.filter(change => change.status !== "untracked");
    state.changes = state.changes.filter(change => change.status === "untracked");
    if (state.upstream) state.ahead += 1;
    const totals = committed.reduce((sum, change) => ({ added: sum.added + (change.additions || 0), removed: sum.removed + (change.deletions || 0) }), { added: 0, removed: 0 });
    return { ok: true, output: `[${state.branch} 9c41e0b] ${String(payload.message).split("\n")[0]}\n ${committed.length} files changed, ${totals.added} insertions(+), ${totals.removed} deletions(-)` };
  }
  if (payload.action === "push") {
    const count = state.ahead || 1;
    state.ahead = 0;
    state.upstream ||= `origin/${state.branch}`;
    return { ok: true, output: `Enumerating objects: 17, done.\nCounting objects: 100% (17/17), done.\nWriting objects: 100% (${count * 4 + 1}/${count * 4 + 1}), 3.42 KiB | 3.42 MiB/s, done.\nTo ${state.repo.remoteUrl}\n   4be2a1c..9c41e0b  ${state.branch} -> ${state.branch}` };
  }
  const url = `${state.repo.github.url}/pull/483`;
  state.pullRequest = { number: 483, title: payload.title, url, state: "open", checks: "pending" };
  return { ok: true, output: `Creating pull request for ${state.branch} into main in ${state.repo.github.owner}/${state.repo.github.name}\n\n${url}`, url };
}

// A few rows in the real NativeToolRegistry.snapshot() shape (checked on 1 Oct).
const tools = [
  { name: "workspace.read", description: "Read one UTF-8 text file inside the active workspace.", category: "files", aliases: ["read file"], risk_level: "low", requires_approval: false, mutability_class: "read", available: true, availabilityDetail: "Ready",
    inputSchema: { type: "object", properties: { path: { type: "string" }, maxChars: { type: "integer", minimum: 1 } }, required: ["path"] } },
  { name: "workspace.write", description: "Atomically save a bounded UTF-8 text artifact.", category: "files", aliases: [], risk_level: "medium", requires_approval: false, mutability_class: "file_write", available: true, availabilityDetail: "Ready",
    inputSchema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } }, required: ["path", "content"] } },
  { name: "neyvia.project.create", description: "Create a project in Neyvia's sidebar.", category: "neyvia", aliases: [], risk_level: "low", requires_approval: false, mutability_class: "none", available: true, availabilityDetail: "Ready",
    inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } },
  { name: "nas.transfer", description: "Copy a file to the NAS.", category: "nas", aliases: [], risk_level: "high", requires_approval: true, mutability_class: "external_write", available: false, availabilityDetail: "No NAS is configured on this PC." },
];

// Accounts screen: the owner, a member, and devices.
let fixtureAccounts = {
  isOwner: true,
  managed: "local",
  passwordMin: 8,
  you: {
    username: "paul", displayName: "Paul", role: "owner", isYou: true, devices: 2, lastSeenAt: iso(0), createdAt: iso(60 * 24 * 40),
    sessions: [
      { id: "s-here", device: "Chrome on Windows", current: true, address: "192.0.2.10", lastSeenAt: iso(0) },
      { id: "s-phone", device: "Safari on iPhone", current: false, address: "192.0.2.10", lastSeenAt: iso(95) },
    ],
  },
  people: [
    { username: "paul", displayName: "Paul", role: "owner", isYou: true, devices: 2, lastSeenAt: iso(0) },
    { username: "maya", displayName: "Maya Rivera", role: "member", isYou: false, devices: 1, lastSeenAt: iso(60 * 26) },
  ],
};

function updateFixtureAccounts({ op, ...body }) {
  const next = structuredClone(fixtureAccounts);
  if (op === "create") {
    if (next.people.some(person => person.username.toLowerCase() === String(body.username).toLowerCase())) throw new Error(`There is already an account called ${body.username}.`);
    next.people.push({ username: body.username, displayName: body.displayName || body.username, role: "member", isYou: false, devices: 0, lastSeenAt: null });
  } else if (op === "remove") next.people = next.people.filter(person => person.username !== body.username);
  else if (op === "profile") { next.you.displayName = body.displayName; next.people[0].displayName = body.displayName; }
  else if (op === "password" && body.currentPassword !== "fixture-pass") throw new Error("Your current password isn't right.");
  else if (op === "signOut") next.you.sessions = next.you.sessions.filter(row => row.id !== body.sessionId);
  else if (op === "signOutOthers") next.you.sessions = next.you.sessions.filter(row => row.current);
  next.you.devices = next.you.sessions.length;
  fixtureAccounts = next;
  return { ...next, ended: 1 };
}

// Night Shift (plan 15 T10): one night's board, shaped like nightshift_summary_command. Fixture only.
const fixtureNight = () => {
  const tasks = [
    { id: "A1", title: "Neyvia catalog truth", status: "done", harness: "codex", model: "gpt-6-luna", needs: [], evidence: { type: "commit", hash: "a1b2c3d4e5f6" } },
    { id: "A2", title: "Release notes draft", status: "done", harness: "claude-code", model: "claude-sonnet-5", needs: [], evidence: { type: "file", path: "C:\\Users\\dev\\Projects\\Neyvia\\docs\\release-notes.md" } },
    { id: "B1", title: "Command bus + neyvia.* tools", status: "running", harness: "codex", model: "gpt-6.1-sol", needs: ["A1"] },
    { id: "B2", title: "Offload benchmark on the 3090", status: "blocked", harness: "claude-code", needs: ["A1"], reason: "GPU busy with a training run" },
    { id: "C1", title: "Sign the installer", status: "waiting", owner: "paul", needs: ["B1"] },
    { id: "C2", title: "Film re-shoot in Forest", status: "waiting", harness: "neyvia", needs: ["B1", "A2"] },
  ];
  const counts = { waiting: 2, running: 1, blocked: 1, done: 2 };
  return {
    tasks, counts, evidenceLinks: [],
    blocked: tasks.filter(task => task.status === "blocked"),
    waitingOnPaul: tasks.filter(task => task.owner === "paul"),
    usage: { reportedTokens: 1840000, complete: true, attempts: 4 },
    perHarness: { codex: { knownRuns: 2, running: 1 }, "claude-code": { knownRuns: 1 } },
    elapsedSeconds: 5 * 3600 + 12 * 60,
    night: { startedAt: iso(60 * 7), elapsedSeconds: 7 * 3600 },
  };
};

const FIXTURE_PLAN = { source: "claude-todos", throughSeq: 0, items: [
  { id: "1", text: "Read the plan", status: "completed" },
  { id: "2", text: "Build the dashboard", active: "Building the dashboard", status: "in_progress" },
  { id: "3", text: "Prove it in the browser", status: "pending" },
] };

// Prompt amplification (plans/15-handoff.md ## C14), shaped like the backend's record. Fixture only.
const fixtureAmplifications = {};
function fixtureAmplify(payload) {
  const text = String(payload.text || "").trim();
  if (!text) throw Object.assign(new Error("Write a prompt first."), { code: "invalid_text", status: 400 });
  const vague = /(that|the thing|from before|it)/i.test(text);
  const record = {
    schema: "neyvia.prompt-amplification.v1", id: `amp-${Object.keys(fixtureAmplifications).length + 1}`, revision: 1, requestId: payload.requestId,
    sessionId: payload.sessionId || null, mode: payload.mode || "auto", status: vague ? "needs_input" : "ready", original: text,
    goal: "Make the chat sidebar narrower on desktop without changing the phone layout",
    deliverable: { form: "CSS change", path: "web/src/neyvia/next/nxSidebar.css" },
    checks: ["Sidebar is 248 px wide or less at 1440 px", "Phone layout at 390 px is unchanged", "Light and dark screenshots attached"],
    constraints: ["Theme tokens only", "No new dependencies"],
    contextPointers: [{ kind: "file", target: "web/src/neyvia/next/nxSidebar.css" }, { kind: "plan", target: "plans/20-revolutionise-computer-and-browser-use.md" }],
    assumptions: ["\"side bar\" means the chat list, not the settings rail", "Current width is the 280 px token"],
    questions: vague ? ["Which width do you want: 248 px or 232 px?"] : [],
    checklist: { items: [], dropped: [], questions: [] }, cl: "CL 1.1", agentPrompt: "", route: "script", elapsedMs: 180, tokens: 0, receiptPath: "C:\fixture\amp.json",
  };
  fixtureAmplifications[record.id] = record;
  return { amplification: record };
}

export async function devFixtureCall(command, payload) {
  await new Promise(resolve => setTimeout(resolve, 120));
  switch (command) {
    case "connected_sessions_list_command": {
      const query = String(payload?.query || "").toLowerCase();
      const rows = sessions.filter(session => !query || `${session.title} ${session.project} ${session.git_branch || ""}`.toLowerCase().includes(query))
        .map(session => (idleParam && session.status === "working" ? { ...session, status: "idle" } : session));
      return { sessions: rows, host, total: rows.length, cursor: 0, sources: [{ app: "claude-code", available: true }, { app: "codex", available: true }, { app: "opencode", available: true }] };
    }
    case "task_feedback_submit_command": {
      const at = new Date().toISOString();
      const feedback = { schema: "neyvia.task-feedback.v1", id: `fb-${payload.runId}`, runId: payload.runId, sessionId: payload.sessionId, verdict: payload.verdict, reason: payload.reason || "", reasonSource: payload.reasonSource || null, at };
      fixtureFeedback[payload.runId] = feedback;
      const lessons = payload.reason ? [{ id: `ls-${payload.runId}`, title: "Put 3+ measured facts in a table", state: "quarantined", manual: "skill:deliverables", kind: "check" }] : [];
      return { feedback, lessons };
    }
    case "task_feedback_get_command":
      return { feedback: fixtureFeedback[payload.runId] || null };
    case "lesson_list_command":
      return { lessons: [] };
    case "connected_session_read_command": {
      const thread = threads[payload.id] || { items: [item("user", { text: "Earlier conversation…" }), item("assistant", { text: "Done. The checklist is in `CHECKLIST.md`." })], context: null };
      return { session: sessions.find(session => session.id === payload.id), items: thread.items, context: thread.context, has_earlier: payload.id === "s-claude-live", run: thread.run || (payload.id === "s-claude-live" ? { runId: "r0", state: "running", startedAt: iso(13), canStop: true } : null),
        plan: payload.id === "s-claude-live" ? FIXTURE_PLAN : null };
    }
    case "connected_agents_dashboard_command": {
      const working = sessions.filter(session => ["working", "waiting_approval", "waiting_input"].includes(session.status));
      return {
        at: new Date().toISOString(), board: null, sources: [],
        limits: [
          { app: "claude-code", window: "five_hour", label: "5-hour", usedPercent: 62, status: "allowed", resetsAt: new Date(Date.now() + 2 * 3600e3).toISOString() },
          { app: "claude-code", window: "seven_day", label: "Weekly", usedPercent: 81, status: "allowed_warning", resetsAt: new Date(Date.now() + 3 * 86400e3).toISOString() },
          { app: "codex", window: "weekly", label: "Weekly", usedPercent: 48, status: null, resetsAt: new Date(Date.now() + 2 * 86400e3).toISOString() },
        ],
        sessions: working.map(session => ({
          id: session.id, app: session.app, category: session.category, runtime: session.runtime, title: session.title, status: session.status,
          since: iso(13), now: session.id === "s-claude-live" ? { kind: "plan", text: "Building the dashboard" } : { kind: "tool", text: "npm test" },
          plan: session.id === "s-claude-live" ? { done: 1, total: 3, current: "Building the dashboard", next: null } : null, tokens: 48200,
          subagents: session.id === "s-claude-live" ? [{ id: "a1", title: "Check the transcript parser", type: "Explore", status: "running", startedAt: iso(4), tokens: 12900, now: "Grep · TodoWrite" }] : [],
        })),
      };
    }
    case "connected_provider_options_command":
      return options[payload.app] || { models: [], permissionModes: [] };
    case "accounts_list_command":
      return fixtureAccounts;
    case "accounts_update_command":
      return updateFixtureAccounts(payload);
    case "connected_session_mark_seen_command":
      return { ok: true };
    case "connected_app_sign_in_command":
      signIns[payload.app] = Date.now();
      return payload.app === "codex"
        ? { state: "code", verificationUrl: "https://auth.openai.com/codex/device", userCode: "QK7M-4TZP" }
        : { state: "paste", verificationUrl: "https://claude.com/cai/oauth/authorize?code=true&client_id=fixture" };
    case "connected_app_sign_in_code_command":
      if (payload.code !== "good-code#state") throw new Error("Claude Code didn't accept that code. Start the sign-in again and copy the whole code.");
      options[payload.app].auth = { kind: "subscription", label: "your Claude Max plan" };
      return { state: "signed-in", auth: options[payload.app].auth };
    case "connected_app_auth_command":
      if (signIns[payload.app] && Date.now() - signIns[payload.app] > 6000) {
        if (options[payload.app]) options[payload.app].auth = { kind: "subscription", label: payload.app === "codex" ? "your ChatGPT Plus plan" : "your Claude Max plan" };
        return options[payload.app]?.auth;
      }
      return { kind: "signed-out", label: "no sign-in" };
    case "connected_session_steer_command":
      globalThis.__nxFixtureSteers = [...(globalThis.__nxFixtureSteers || []), payload];
      return { runId: payload.runId, state: "running", canStop: true, canSteer: true, startedAt: iso(13) };
    case "prompt_amplify_command":
      await new Promise(resolve => setTimeout(resolve, 500));
      return fixtureAmplify(payload);
    case "prompt_amplification_get_command":
      if (!fixtureAmplifications[payload.id]) throw Object.assign(new Error("No such amplification."), { code: "not_found", status: 404 });
      return { amplification: fixtureAmplifications[payload.id] };
    case "prompt_amplification_edit_command": {
      const record = fixtureAmplifications[payload.id];
      if (!record) throw Object.assign(new Error("No such amplification."), { code: "not_found", status: 404 });
      if (record.revision !== payload.revision) throw Object.assign(new Error("Revision conflict."), { code: "conflict", status: 409 });
      const learning = { state: "pending_gate", reason: "C9 lesson gate not installed", lessonIds: [] };
      fixtureAmplifications[payload.id] = { ...record, revision: record.revision + 1, status: "edited", agentPrompt: payload.text, learning };
      return { amplification: fixtureAmplifications[payload.id], learning };
    }
    case "connected_session_send_command": {
      globalThis.__nxFixtureSends = [...(globalThis.__nxFixtureSends || []), { ...payload, options: { ...payload.options, images: payload.options?.images?.map(image => ({ ...image, data: `${image.data.length} chars` })) } }];
      // Mirrors the broker: text, images, or both.
      if (!String(payload.message || "").trim() && !payload.options?.images?.length) throw Object.assign(new Error("Send text or attach an image. Text may contain up to 100,000 characters."), { code: "invalid_message" });
      return { runId: `fx-${payload.requestId}`, state: "completed" };
    }
    case "get_native_tool_catalog_command": {
      if (payload.describe) {
        const tool = tools.find(entry => entry.name === payload.describe);
        if (!tool) throw new Error(`Unknown Neyvia native tool: ${payload.describe}`);
        return { ...tool, inputSchema: tool.inputSchema || { type: "object", properties: {} } };
      }
      return { schema: "fluxio.native_tool_catalog.v1", label: "Neyvia Native Tools", ready: 3, total: tools.length, tools: tools.map(({ inputSchema, ...row }) => row) };
    }
    case "call_native_tool_command":
      globalThis.__nxFixtureToolCalls = [...(globalThis.__nxFixtureToolCalls || []), payload];
      if (payload.tool === "workspace.read") return { tool: payload.tool, ok: true, status: "completed", duration_ms: 4, result: { path: payload.arguments.path, content: "# plotter\n", truncated: false }, receipt_path: "C:\\fixture\\receipt.json" };
      return { tool: payload.tool, ok: false, status: "failed", duration_ms: 2, error: `${payload.arguments.path || "That path"} is outside the workspace.` };
    case "connected_session_workspace_command":
    case "connected_session_file_diff_command":
    case "connected_session_git_action_command":
      return workspaceCall(command, payload);
    case "voice_command_command":
    case "voice_commands_command": {
      const { fixtureVoice } = await import("./nxDevVoiceFixture.js");
      return fixtureVoice(command, payload, { threads, sessions });
    }
    case "parallel_state_command": {
      // Parallel branches (nxParallelApi reads the same fixture over HTTP): ?parallel=working|conflict|settled picks the state.
      const { fixtureParallelAction, fixtureParallelRead } = await import("./nxParallelFixture.js");
      return payload?.operation ? fixtureParallelAction(payload) : fixtureParallelRead();
    }
    case "nightshift_summary_command":
    case "nightshift_tasks_command":
      return fixtureNight();
    case "nightshift_resources_command":
      return { paused: false, maxConcurrent: 2, maxNightSeconds: 8 * 3600, holdAtPlanPercent: 70 };
    default:
      throw Object.assign(new Error(`${command} is not in the design fixtures`), { code: "fixture" });
  }
}
