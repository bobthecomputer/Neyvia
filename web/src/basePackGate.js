/** First launch runs through native IPC, without Python or a PC service. */
export async function ensureBasePack() {
  if (!import.meta.env.VITE_NEYVIA_SLIM_INSTALLER || !window.__TAURI_INTERNALS__) return;
  const { invoke } = await import("@tauri-apps/api/core");
  return runBasePackGate(command => invoke(command));
}

export async function runBasePackGate(call) {
  window.__neyviaBoot?.mounted(600000);
  const first = await call("onboarding_base_pack_status_command").catch(error => ({ state: "failed", error: String(error) }));
  if (["done", "completed"].includes(first.state)) return;
  const root = document.getElementById("root");
  root.innerHTML = `<main class="nbp" aria-labelledby="nbp-title"><div class="nbp-body"><p class="nbp-brand">Neyvia</p><h1 id="nbp-title">Preparing your workspace</h1><p>One download brings the tools Neyvia needs. You can pause and return later.</p><progress aria-label="Base pack download" max="1" value="0"></progress><p class="nbp-status" role="status" aria-live="polite"></p><p class="nbp-error" role="alert" hidden></p><div class="nbp-actions"><button class="nbp-primary" type="button">Start download</button><button class="nbp-pause" type="button" hidden>Pause</button></div></div></main>`;
  const style = document.createElement("style");
  style.textContent = `.nbp{min-height:100vh;display:grid;place-items:center;background:#0a0f0c;color:#f1ede3;font:16px/1.6 "Segoe UI",system-ui,sans-serif;padding:24px;box-sizing:border-box}.nbp-body{width:min(100%,440px)}.nbp-brand{color:#6fbf8a;letter-spacing:.04em}.nbp h1{font-size:30px;line-height:1.25;font-weight:600;margin:12px 0 20px}.nbp p{color:#c2c8c2}.nbp progress{width:100%;height:10px;accent-color:#6fbf8a;margin-top:20px}.nbp-status{font-size:14px;font-variant-numeric:tabular-nums}.nbp .nbp-error{color:#ffbaab;overflow-wrap:anywhere}.nbp-actions{display:flex;gap:12px;margin-top:24px}.nbp button{font:inherit;padding:10px 20px;border:0;border-radius:24px;background:#f1ede3;color:#0a0f0c;cursor:pointer}.nbp button:focus-visible{outline:3px solid #6fbf8a;outline-offset:4px}.nbp button:disabled{opacity:.5;cursor:default}.nbp .nbp-pause{background:#223329;color:#f1ede3}@media(prefers-color-scheme:light){.nbp{background:#f7f2e8;color:#1b211c}.nbp p{color:#435547}.nbp .nbp-brand{color:#2f7d4f}.nbp button{background:#1b211c;color:#f7f2e8}.nbp .nbp-error{color:#992b20}}`;
  document.head.appendChild(style);
  window.__neyviaBoot?.ready();
  const button = root.querySelector(".nbp-primary"), pause = root.querySelector(".nbp-pause"), progress = root.querySelector("progress"), status = root.querySelector(".nbp-status"), error = root.querySelector(".nbp-error");
  let busy = false, stopped = false, resolve;
  const complete = new Promise(done => { resolve = done; });
  function render(state) {
    busy = state.state === "running";
    const total = Number(state.totalBytes || 0), done = Number(state.doneBytes || 0);
    progress.max = Math.max(1, total); progress.value = done;
    status.textContent = state.phase === "verifyRuntime" ? "Checking the tools are ready…" : total ? `${(done / 1048576).toFixed(1)} of ${(total / 1048576).toFixed(1)} MB · ${state.state === "paused" ? "Paused" : "Verified as it arrives"}` : busy ? "Checking the signed download list…" : "Ready when you are.";
    error.hidden = !state.error; error.textContent = state.error || "";
    button.hidden = busy; button.disabled = busy;
    button.textContent = state.state === "failed" ? "Try again" : state.state === "paused" ? "Resume download" : "Start download";
    pause.hidden = !busy; pause.disabled = Boolean(state.pauseRequested);
    if (["done", "completed"].includes(state.state)) { stopped = true; root.replaceChildren(); style.remove(); resolve(); }
  }
  async function act(command) {
    button.disabled = true;
    try { render(await call(command)); } catch (failure) { render({ state: "failed", error: String(failure) }); }
  }
  button.onclick = () => act("onboarding_base_pack_start_command");
  pause.onclick = () => act("onboarding_base_pack_pause_command");
  render(first);
  const poll = async () => {
    if (stopped) return;
    try { render(await call("onboarding_base_pack_status_command")); }
    catch (failure) { render({ state: "failed", error: String(failure) }); }
    if (!stopped) setTimeout(poll, 500);
  };
  if (first.state === "idle") await act("onboarding_base_pack_start_command");
  void poll();
  return complete;
}
