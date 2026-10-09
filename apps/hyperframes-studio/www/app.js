import { createNeyviaClient } from "/api/sdk/neyvia-sdk.js";

const sdk = createNeyviaClient({ appId: "hyperframes-studio" });
const $ = (id) => document.getElementById(id);
const form = $("form");
let current = { project: "", port: 49165, studio: "stopped", url: "", clips: 0, findings: null, render: null, contractsPassed: null, error: "" };

function say(text) { $("status").textContent = text; }
function settings() {
  const data = new FormData(form);
  return { project: String(data.get("project") || "").trim(), port: Number(data.get("port") || 49165) };
}
function list(rows) {
  const ul = document.createElement("ul");
  for (const row of rows) { const li = document.createElement("li"); li.textContent = row.text; if (row.warn) li.className = "finding"; ul.append(li); }
  return ul;
}

async function open() {
  const { project, port } = settings();
  say("Starting Studio…");
  const result = await sdk.tool("neyvia.video.studio", { project, port });
  if (!result.ok) throw new Error(result.reason || "Studio did not start");
  current = { ...current, project, port, studio: "running", url: result.studio || result.url, error: "" };
  const frame = document.createElement("iframe");
  frame.title = "HyperFrames Studio"; frame.src = current.url;
  $("stage").className = ""; $("stage").replaceChildren(frame);
  say("Studio is running on port " + port + ".");
  return current;
}

async function timeline() {
  const { project } = settings();
  say("Reading the timeline…");
  const { scene, verdict } = await sdk.tool("neyvia.video.timeline", { project });
  const clips = scene.nodes.filter((n) => n.kind.startsWith("clip-"));
  current = { ...current, project, clips: clips.length, findings: verdict.findings.length };
  $("clips").replaceChildren(list(clips.map((n) => ({ text: `${n.measurements.start.toFixed(2)}s · ${n.kind.slice(5)} · ${n.attributes.text || n.attributes.src || n.id}` }))));
  $("checks").replaceChildren(verdict.findings.length ? list(verdict.findings.map((f) => ({ text: `${f.predicate} → ${f.fix.action}`, warn: true })))
    : Object.assign(document.createElement("p"), { textContent: "No findings before render." }));
  say(`${clips.length} clips, ${verdict.findings.length} findings.`);
  return current;
}

async function render() {
  const { project } = settings();
  say("Rendering a draft (about a minute per 20 s of video)…");
  const out = await sdk.tool("neyvia.video.render", { project, quality: "draft" });
  if (!out.ok) throw new Error("Render failed: " + (out.summary || []).join(" "));
  const checks = await sdk.tool("neyvia.video.contracts", { video: out.output, project });
  current = { ...current, render: out.output, contractsPassed: checks.passed };
  $("checks").replaceChildren(list(Object.entries(checks.contracts).map(([name, c]) => ({ text: `${c.passed ? "✓" : "✗"} ${name}`, warn: !c.passed }))));
  say(checks.passed ? "Rendered; every outcome contract passes." : "Rendered; some contracts need attention.");
  return current;
}

async function stop() {
  const { project, port } = settings();
  await sdk.tool("neyvia.video.studio", { project, port, stop: true });
  current = { ...current, studio: "stopped", url: "" };
  $("stage").className = "empty"; $("stage").textContent = "Studio stopped.";
  say("Stopped.");
  return current;
}

const actions = { open, timeline, render, stop };
const guard = (fn) => () => fn().catch((error) => { current.error = error.message; say(error.message); });
form.addEventListener("submit", (event) => { event.preventDefault(); guard(open)(); });
$("timeline").onclick = guard(timeline);
$("render").onclick = guard(render);
$("stop").onclick = guard(stop);

window.neyviaApp = Object.freeze({
  state: () => ({ ...current }),
  describe: () => ({ instance: "hyperframes-studio", actions: Object.keys(actions) }),
  async act(name, args = {}) {
    if (!actions[name]) throw Error("Unknown app action");
    if (args.project) form.elements.project.value = args.project;
    if (args.port) form.elements.port.value = args.port;
    return actions[name]();
  },
});
