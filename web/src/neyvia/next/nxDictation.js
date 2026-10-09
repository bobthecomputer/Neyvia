import { backendBase, callNx, isDesktopApp } from "./nxApi.js";
import { createDictation } from "../neyviaDictation.js";
import { normalizeAnswer } from "./nxDictationEdit.js";

// Prompt dictation with the local Phonon-2 engine (French and mixed speech go to Qwen, chosen by the backend).
// The microphone is resampled to 16 kHz mono 16-bit here and sent in 250 ms pieces while Paul speaks; each answer
// carries the stable words and the grey provisional ones. On release only the last piece is left to decode.
// Browser/phone: /api/ui/dictation/stream. Desktop app: dictation_stream_command through the bridge.

export const RATE = 16000;
const PIECE_MS = 250;
const KEEP_MIC_MS = 20000; // the mic stays open this long after a dictation, so the next one starts at once

// ---------------------------------------------------------------- audio worklet (inline, no extra file)

const WORKLET = `
class NxPcm extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.ratio = sampleRate / ${RATE};
    this.acc = 0; this.sum = 0; this.n = 0;
    this.out = new Int16Array(320); this.len = 0; this.level = 0;  /* 20 ms per message: little is left to flush on release */
    this.port.onmessage = event => { if (event.data === "flush") this.flush(true); };
  }
  push(value) {
    const clipped = Math.max(-1, Math.min(1, value));
    this.out[this.len++] = clipped < 0 ? clipped * 32768 : clipped * 32767;
    this.level = Math.max(this.level, Math.abs(clipped));
    if (this.len === this.out.length) this.flush(false);
  }
  flush(final) {
    const pcm = this.out.slice(0, this.len);
    this.port.postMessage({ pcm, level: this.level, final }, [pcm.buffer]);
    this.len = 0; this.level = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    if (this.ratio === 1) { for (let i = 0; i < channel.length; i++) this.push(channel[i]); return true; }
    // Box-filter decimation: average each output period (good enough for speech at 48 -> 16 kHz).
    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i]; this.n += 1; this.acc += 1;
      if (this.acc >= this.ratio) { this.acc -= this.ratio; this.push(this.sum / this.n); this.sum = 0; this.n = 0; }
    }
    return true;
  }
}
registerProcessor("nx-pcm", NxPcm);
`;

let shared = null; // { context, stream, source, releaseTimer }
let prepared = null; // Promise<AudioContext> with the worklet loaded, made ahead of the first press

async function makeContext(rate) {
  const context = rate ? new AudioContext({ sampleRate: rate, latencyHint: "interactive" }) : new AudioContext({ latencyHint: "interactive" });
  const url = URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" }));
  try { await context.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
  return context;
}

/** Create the 16 kHz audio context and load the worklet before the press (hover, focus): ~100-200 ms saved. */
export function prepareAudio() {
  if (!prepared && typeof AudioContext !== "undefined") {
    prepared = makeContext(RATE).catch(() => makeContext(0));
    prepared.catch(() => { prepared = null; });
  }
  return prepared;
}

async function openMic() {
  if (shared?.stream?.active) {
    clearTimeout(shared.releaseTimer);
    if (shared.context.state !== "running") await shared.context.resume();
    return shared;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw Object.assign(new Error(window.isSecureContext ? "This browser has no microphone access." : "The microphone needs a secure page: open Neyvia with its https address."), { code: "no_mic" });
  }
  // The mic and the audio graph start together.
  const [stream, ready] = await Promise.all([
    navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } }),
    prepareAudio(),
  ]);
  let context = ready;
  let source;
  try { source = context.createMediaStreamSource(stream); } catch {
    // Firefox refuses a 16 kHz context with a 48 kHz mic: use the device rate and decimate in the worklet.
    void context.close();
    context = await makeContext(0);
    prepared = Promise.resolve(context);
    source = context.createMediaStreamSource(stream);
  }
  if (context.state !== "running") {
    // Audio only runs after a click or key press on the page; never wait forever for it.
    await Promise.race([context.resume(), new Promise(resolve => setTimeout(resolve, 3000))]);
    if (context.state !== "running") {
      stream.getTracks().forEach(track => track.stop());
      throw Object.assign(new Error("The browser kept audio paused. Click the mic to start."), { code: "audio_paused" });
    }
  }
  shared = { context, stream, source, releaseTimer: 0 };
  return shared;
}

function closeMic(mic) {
  mic.stream.getTracks().forEach(track => track.stop());
  try { mic.source.disconnect(); } catch { /* already */ }
  void mic.context.suspend();  // kept (with its worklet) for the next dictation
  if (shared === mic) shared = null;
}

function releaseMicLater() {
  if (!shared) return;
  clearTimeout(shared.releaseTimer);
  const mic = shared;
  mic.releaseTimer = setTimeout(() => closeMic(mic), KEEP_MIC_MS);
}

export function releaseMicNow() {
  if (!shared) return;
  clearTimeout(shared.releaseTimer);
  closeMic(shared);
}

// ---------------------------------------------------------------- transport

function concat(chunks, total) {
  const out = new Int16Array(total);
  let at = 0;
  for (const chunk of chunks) { out.set(chunk, at); at += chunk.length; }
  return out;
}

function base64(int16) {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

async function postAudio(url, body, { signal } = {}) {
  let response;
  try {
    response = await fetch(url, { method: "POST", body, signal, credentials: isDesktopApp() ? "omit" : "include", headers: { "Content-Type": "application/octet-stream" } });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw Object.assign(new Error("The speech engine can't be reached."), { code: "engine_off" });
  }
  const answer = await response.json().catch(() => ({}));
  if (!response.ok || answer.ok === false) {
    const message = answer.error || (response.status >= 500 ? "Neyvia didn't answer (it may be restarting)." : `Dictation failed (HTTP ${response.status}).`);
    throw Object.assign(new Error(message), { code: answer.code || (response.status === 503 ? "engine_busy" : ""), httpStatus: response.status });
  }
  return answer.data ?? answer;
}

/** Engine state; start=true starts it when it is off. Desktop answers include the engine URL. */
export async function engineStatus({ start = false, probe = false } = {}) {
  if (isDesktopApp()) return callNx("dictation_status_command", { start, probe });
  const query = [start && "start=1", probe && "probe=1"].filter(Boolean).join("&");
  const response = await fetch(`${backendBase()}/api/ui/dictation/status${query ? `?${query}` : ""}`, { credentials: "include" });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok || answer.ok === false) {
    const message = answer.loginRequired ? "You're signed out of Neyvia. Sign in again to dictate." : answer.error || "Dictation status failed";
    throw Object.assign(new Error(message), { code: answer.loginRequired ? "login_required" : answer.code || "", httpStatus: response.status });
  }
  return answer.data;
}

// Every client streams through the backend, so the prompt policy (stable words, commands, language, names)
// is the same everywhere and the backend keeps the audio for a French re-decode.
async function postStream(sid, op, seq, body, signal) {
  if (isDesktopApp()) return callNx("dictation_stream_command", { sid, op, seq, pcm: body.length ? base64(body) : "" }, { signal });
  return postAudio(`${backendBase()}/api/ui/dictation/stream/${sid}/${op}?seq=${seq}`, body, { signal });
}

/** One-shot decode of a whole recording (the engine cuts long audio at pauses). Same finish-shaped answer, no sid. */
async function postWhole(pcm, signal) {
  if (isDesktopApp()) return callNx("dictation_transcribe_command", { pcm: base64(pcm) }, { signal });
  return postAudio(`${backendBase()}/api/ui/dictation/transcribe`, pcm, { signal });
}

/** Decode a finished dictation again with the engine the backend chose (French / mixed → Qwen). */
export function redecodeDictation(sid) {
  return callNx("dictation_redecode_command", { sid });
}

/** Choose where speech is turned into words (local | openai | codex | browser). Returns {settings, status}. */
export async function saveDictationSettings(settings) {
  if (isDesktopApp()) return callNx("dictation_settings_command", { settings });
  const response = await fetch(`${backendBase()}/api/ui/dictation/settings`, {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ settings }),
  });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok || answer.ok === false) throw Object.assign(new Error(answer.error || "Dictation settings couldn't be saved."), { httpStatus: response.status });
  return answer.data;
}

/** The same prompt policy for text that didn't come from the engine (the browser's speech input). */
export function processSpoken(text, engine = "browser") {
  return callNx("dictation_process_command", { text, final: true, engine });
}

/** Paul's names list (sound-alike fixes). action: list | add | remove. */
export function dictationNames(payload = { action: "list" }) {
  return callNx("dictation_names_command", payload);
}

// ---------------------------------------------------------------- one dictation

const WHOLE_MAX_S = 28;  // a recording held while the engine loaded: up to this, one finish call; longer, the one-shot path
const COLD_MESSAGE = "The speech model is starting. Keep talking: your words are kept and written when it's ready.";
const LOST_CODES = new Set(["engine_off", "engine_busy"]);
const newSid = () => (crypto.randomUUID?.() || `${Date.now()}${Math.random()}`).replace(/[^A-Za-z0-9]/g, "").slice(0, 24);

/**
 * Start one dictation. The mic opens at once; `status` (an engine status or a promise of one) decides how the audio
 * travels: "ready" streams it live (grey words while talking); "starting" / "loading" / "off" keeps every sample
 * and decodes it once the engine is up (waitReady); anything else calls onUnavailable(status) and stops quietly.
 * If the engine goes away mid-dictation (it idled out, or restarted), the audio is kept the same way.
 * Callbacks: onState({status, message, cold?, waiting?}), onLevel(0..1), onPartial(answer), onFinal(answer, info).
 * answer is normalised (nxDictationEdit.normalizeAnswer): {stable, provisional, revision, segments, text, language, route,
 * redecode, route_note, fixes}. Returns { sid, stop(), cancel() }. status: starting | listening | finishing | idle | error.
 */
export function startDictation({ status, waitReady, wakeEngine, onUnavailable, explain, onState, onLevel, onPartial, onFinal, log }) {
  const pressed = performance.now();
  let sid = newSid();
  const chunks = [];
  let total = 0;
  let pending = [];
  let pendingLength = 0;
  let seq = 0;
  let queue = Promise.resolve();
  let failed = null;
  let done = false;
  let firstAudio = 0;
  let mic = null;
  let node = null;
  let stopping = false;
  let mode = "deciding";  // deciding | live | held (engine not up: keep everything) | unavailable
  let heldSince = 0;      // when the audio started being held, for the log
  let streamed = false;   // some audio already went to the engine under this sid
  const abort = new AbortController();
  onState({ status: "starting", message: "Listening…" });

  const listening = () => onState(mode === "held"
    ? { status: "listening", message: COLD_MESSAGE, cold: true }
    : { status: "listening", message: "Listening… release to insert, Esc to cancel." });
  const hold = () => {
    if (mode === "held") return;
    mode = "held";
    heldSince = performance.now();
    wakeEngine?.();
    if (!done && mic) listening();
  };

  const timing = { sentAt: 0 };
  const send = (op, body) => {
    const number = seq++;
    const id = sid;
    const job = queue.then(() => {
      if (op === "finish") timing.sentAt = performance.now();
      if (failed || (mode === "held" && op === "append")) return null;
      streamed = true;
      return postStream(id, op, number, body, abort.signal);
    });
    queue = job.catch(error => {
      if (error?.name === "AbortError") return;
      // The engine went away (idle exit, restart) or is loading again: keep the audio, decode it once it's back.
      if (op === "append" && LOST_CODES.has(error?.code)) hold();
      else failed = failed || error;
    });
    return job;
  };
  // One append in flight at a time: when the engine is slow (CPU, or busy decoding), the audio that arrives meanwhile
  // goes out as one bigger piece instead of a queue of small ones, so release never waits behind a backlog.
  let inFlight = false;
  const flushPiece = () => {
    if (!pendingLength || mode !== "live" || inFlight || done) return;  // deciding / held: everything stays in `chunks`
    const piece = concat(pending, pendingLength);
    pending = []; pendingLength = 0;
    inFlight = true;
    void send("append", piece)
      .then(answer => { if (!done && answer && mode === "live") onPartial(normalizeAnswer(answer)); })
      .catch(() => {})
      .finally(() => { inFlight = false; if (pendingLength >= RATE * PIECE_MS / 1000) flushPiece(); });
  };

  const teardown = () => {
    try { mic?.source.disconnect(node); } catch { /* already disconnected */ }
    if (node) node.port.onmessage = null;
    releaseMicLater();
  };

  let ready = null;
  const decided = Promise.resolve(status).then(current => current, error => ({ state: "unreachable", error: error?.message })).then(current => {
    if (mode !== "deciding") return;
    if (current?.state === "ready") {
      mode = "live";
      flushPiece();  // what was said while the status came back
    } else if (["starting", "loading", "off"].includes(current?.state)) {
      hold();
    } else {
      mode = "unavailable";
      if (done) return;
      done = true;
      abort.abort();
      void ready.then(teardown, () => {});
      onUnavailable?.(current || {});
    }
  });

  ready = (async () => {
    mic = await openMic();
    if (mode === "unavailable") return;
    node = new AudioWorkletNode(mic.context, "nx-pcm");
    node.port.onmessage = event => {
      const { pcm, level } = event.data;
      if (pcm.length) {
        if (!firstAudio) firstAudio = performance.now();
        chunks.push(pcm); total += pcm.length;
        pending.push(pcm); pendingLength += pcm.length;
        if (pendingLength >= RATE * PIECE_MS / 1000) flushPiece();
      }
      onLevel(level);
    };
    mic.source.connect(node);
    if (done) return;
    listening();
  })();

  // The engine wasn't up while Paul talked: wait for it (cancellable), then decode the whole recording.
  const replay = async () => {
    const audioMs = Math.round(total * 1000 / RATE);
    const waited = performance.now();
    const engine = await waitReady(message => onState({ status: "finishing", message, waiting: true }), { signal: abort.signal, audioMs });
    const waitMs = Math.round(performance.now() - waited);
    if (streamed) { postStream(sid, "cancel", 0, new Int16Array(0)).catch(() => {}); sid = newSid(); }
    onState({ status: "finishing", message: "Writing…" });
    timing.sentAt = performance.now();
    const audio = concat(chunks, total);
    const answer = audio.length <= RATE * WHOLE_MAX_S
      ? await postStream(sid, "finish", 0, audio, abort.signal)
      : { ...(await postWhole(audio, abort.signal)), oneShot: true };
    return { answer, waitMs, startMs: engine?.startedInMs ?? null };
  };

  const finishWith = async (released, flushed, tail) => {
    try {
      await decided;
      if (mode === "unavailable") return;
      await queue;  // an append failing right now still switches to holding the audio
      let raw;
      let held = null;
      if (mode !== "held") {
        try { raw = await send("finish", tail); } catch (error) {
          if (!LOST_CODES.has(error?.code) || abort.signal.aborted) throw error;
          failed = null;  // the engine went away right at the end: the whole recording is still here
          hold();
        }
      }
      if (mode === "held") {
        held = await replay();
        raw = held.answer;
      }
      const answered = performance.now();
      if (failed) throw failed;
      if (raw == null) throw Object.assign(new Error("The speech engine stopped."), { code: "engine_off" });
      const final = normalizeAnswer(raw, true);
      if (explain) final.route_note = explain(final);
      const entry = {
        at: new Date().toISOString(), engine: final.engine || "phonon2", audioMs: Math.round(total * 1000 / RATE),
        startMs: firstAudio ? Math.round(firstAudio - pressed) : null,
        releaseToTextMs: Math.round(performance.now() - released),
        flushMs: Math.round(flushed - released), requestMs: Math.round(answered - (held ? timing.sentAt : flushed)),
        queuedMs: timing.sentAt ? Math.round(timing.sentAt - flushed) : null,
        engineFinishMs: final.timings?.finish_ms ?? final.finish_ms, decodeMs: final.timings?.decode_ms ?? final.decode_ms,
        mode: held ? (raw.oneShot ? "held-whole" : "held") : final.mode, device: final.device, language: final.language || null,
        heldMs: held ? Math.round(released - heldSince) : null, engineWaitMs: held ? held.waitMs : null, engineStartMs: held ? held.startMs : null,
        commands: final.segments.filter(segment => segment.type === "command").map(segment => segment.op),
      };
      onFinal(final, { ...entry, sid: raw.oneShot ? null : sid });
      // Measured once the text is on screen: the frame after it was inserted.
      let logged = false;
      const record = () => { if (logged) return; logged = true; log?.({ ...entry, releaseToTextMs: Math.round(performance.now() - released), hidden: document.hidden }); };
      requestAnimationFrame(record);
      setTimeout(record, 100);  // a hidden page has no frames
      const heard = final.segments.length > 0;
      onState(final.route_note ? { status: "idle", message: final.route_note, tone: "warn" } : { status: "idle", message: heard ? "" : "Nothing was heard. Try again a little closer to the mic." });
    } catch (error) {
      if (error?.name === "AbortError" || abort.signal.aborted) return;  // cancelled while waiting
      const message = error?.code === "engine_off" ? "The speech engine stopped." : error?.message || "Dictation failed.";
      // The audio is still here: offer to decode it again rather than asking Paul to say it all again.
      onState(total ? { status: "error", message: `${message} Your ${Math.max(1, Math.round(total / RATE))} s of speech is kept.`, canRetry: true }
        : { status: "error", message });
    }
  };

  return {
    get sid() { return sid; },
    async stop() {
      if (done || stopping) return;  // a click's pointerdown and pointerup can both ask to stop
      stopping = true;
      const released = performance.now();
      try {
        await ready;
      } catch (error) {
        done = true;
        onState({ status: "error", message: micMessage(error) });
        return;
      }
      if (mode === "unavailable") return;
      done = true;
      onState({ status: "finishing", message: "Writing…" });
      // The worklet posts every 20 ms; whatever it still holds is the last few ms after release.
      node.port.postMessage("flush");
      const flushed = performance.now();
      teardown();
      const tail = concat(pending, pendingLength);
      pending = []; pendingLength = 0;
      await finishWith(released, flushed, tail);
    },
    /** After a failed decode: the recording is still in memory, decode it again (waits for the engine if needed). */
    async retry() {
      if (!done || abort.signal.aborted || !total) return;
      failed = null;
      mode = "held";
      streamed = true;  // a fresh sid: the old one may be half-finished on the backend
      onState({ status: "finishing", message: "Trying again…" });
      const now = performance.now();
      await finishWith(now, now, new Int16Array(0));
    },
    cancel() {
      if (abort.signal.aborted) return;
      done = true;
      abort.abort();
      void ready.then(teardown, () => {});
      if (streamed) postStream(sid, "cancel", 0, new Int16Array(0)).catch(() => {});
      onState({ status: "idle", message: "" });
    },
  };
}

export function micMessage(error) {
  if (error?.name === "NotAllowedError") return "Microphone access was denied. Allow it in the browser's site settings, then try again.";
  if (error?.name === "NotFoundError") return "No microphone found. Connect one and try again.";
  return error?.message || "The microphone couldn't start.";
}

/** The browser's own speech input, used when the engine isn't available. Same callbacks. */
export function startBrowserDictation({ onState, onPartial, onFinal, note }) {
  let language = navigator.language || "en-US";
  try { language = localStorage.getItem("neyvia.dictation.language") || language; } catch { /* default */ }
  const words = [];
  let capture = null;
  try {
    capture = createDictation(window.SpeechRecognition || window.webkitSpeechRecognition, {
      language,
      onText: text => { words.push(text); onPartial(words.join(" ")); },
      onState: state => {
        if (state.status === "listening") onState({ status: "listening", message: `${note} Listening…` });
        else if (state.status === "idle") { onFinal(words.join(" "), { engine: "browser" }); onState({ status: "idle", message: note, tone: "warn" }); }
        else if (state.status === "error") onState({ status: "error", message: state.message });
      },
    });
    capture.start();
  } catch (error) {
    onState({ status: "error", message: error.message });
  }
  return {
    stop() { onState({ status: "finishing", message: "Writing…" }); capture?.stop(); },
    cancel() { capture?.dispose(); onState({ status: "idle", message: "" }); },
  };
}
