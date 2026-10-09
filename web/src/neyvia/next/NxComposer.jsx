import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowUp, Square, Star, X } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, Segmented, Spinner, compactTokens, elapsed, local, useTick } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { compactSession, isFixtureId, isRunActive, loadList, sendMessage, startSession, steerRun, stopRun, useNx } from "./nxStore.js";
import { ModelPicker } from "./NxModelPicker.jsx";
import { RoutePicker, billingNote, preferredTransport } from "./NxRoutePicker.jsx";
import { PermissionPicker } from "./NxPermissionPicker.jsx";
import { SignInCard } from "./NxSignIn.jsx";
import { NxChecklist } from "./NxChecklist.jsx";
import {
  AttachButton, AttachmentTray, CompactButton, FileTray, PlusMenu, ToolRunner, attachAny, fileDrafts, imageDrafts, useFileDraft, useImageDraft,
} from "./NxComposerPlus.jsx";
import { imageBlocker } from "./nxComposerModel.js";
import { DictationGhost, DictationStrip, MicButton, useTextareaDictation } from "./NxDictation.jsx";
import { useRunAnnouncer } from "./nxAnnounce.js";
import { AutopilotPanel, AutopilotScope, AutopilotToggle, startAutopilot, useAutopilotMode, useAutopilotRuns } from "./NxAutopilot.jsx";
import { NxAmplifyCard, useAmplifier, useAmplifyMode } from "./NxAmplifyCard.jsx";
import { learningLine, sendOptions, shouldAmplify } from "./nxAmplifyModel.js";

export { ModelPicker, PermissionPicker };

const optionsCache = new Map();
export function forgetProviderOptions(app) {
  for (const key of [...optionsCache.keys()]) if (key.startsWith(`${app}:`)) optionsCache.delete(key);
}

export function useProviderOptions(app, sessionId, version = 0) {
  const key = `${app}:${sessionId || ""}`;
  const [options, setOptions] = useState(() => optionsCache.get(key) || null);
  useEffect(() => {
    if (!app) return undefined;
    let alive = true;
    setOptions(optionsCache.get(key) || null);
    // The tour's example chats ("tour:" ids) ask for the app's options, not a chat's.
    callNx("connected_provider_options_command", { app, id: isFixtureId(sessionId) ? undefined : sessionId })
      .then(result => { optionsCache.set(key, result); if (alive) setOptions(result); })
      .catch(() => { if (alive && !optionsCache.get(key)) setOptions({ models: [], permissionModes: [], unavailable: true }); });
    return () => { alive = false; };
  }, [app, sessionId, version]);
  return options;
}


function ContextRing({ context }) {
  const used = context?.used_tokens ?? context?.usedTokens;
  const windowSize = context?.window_tokens ?? context?.windowTokens;
  const threshold = context?.auto_compact_tokens ?? context?.autoCompactTokens;
  if (used == null) return null;
  const known = windowSize > 0;
  const ratio = known ? Math.min(1, used / windowSize) : 0;
  const percent = known ? Math.max(1, Math.round(ratio * 100)) : null;
  const circumference = 2 * Math.PI * 7;
  const title = known
    ? `${used.toLocaleString()} of ${windowSize.toLocaleString()} tokens${threshold ? ` · compacts at ${threshold.toLocaleString()}` : ""}`
    : `${used.toLocaleString()} tokens in context · window not reported`;
  return (
    <span className="nx-context" title={title} aria-label={title} role="img">
      {known ? <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
        <circle cx="9" cy="9" r="7" className="nx-ring-track" />
        {known && ratio >= 0.02 ? <circle cx="9" cy="9" r="7" className={`nx-ring-fill${ratio > 0.85 ? " is-high" : ""}`}
          strokeDasharray={`${circumference * ratio} ${circumference}`} transform="rotate(-90 9 9)" /> : null}
      </svg> : null}
      <span>{known ? `${percent}%` : `${compactTokens(used)} tokens`}</span>
    </span>
  );
}

function RunStrip({ run, appName, onStop }) {
  const active = isRunActive(run);
  useTick(active, 1000);
  if (!active) return null;
  const waiting = run.state === "waiting_approval" || run.state === "waiting_input";
  return (
    <div className={`nx-runstrip${waiting ? " is-gold" : ""}`} role="status">
      {waiting ? <Icon as={Star} size={13} /> : <Spinner size={11} />}
      <span>{waiting ? (run.state === "waiting_approval" ? "Waiting for your approval" : "Waiting for your answer") : "Working"}</span>
      {run.startedAt ? <span className="nx-runstrip-time">{elapsed(run.startedAt)}</span> : null}
      {run.canStop !== false ? (
        <button type="button" className="nx-runstrip-stop" onClick={onStop}><Icon as={Square} size={11} /> Stop</button>
      ) : null}
    </div>
  );
}

// `placeholder` and `contextBlock` are the pop-out chat's (NxPopout): its own hint, and a compact text block about the app it floats over
// that goes in front of each message. Neither changes the chat's own composer.
export function NxComposer({ sessionId, session, appName, onOpenChat, placeholder = null, contextBlock = null, className = "" }) {
  const run = useNx(state => state.runs[sessionId]);
  useRunAnnouncer(sessionId, run, appName);
  const context = useNx(state => state.threads[sessionId]?.context);
  const capabilities = session?.capabilities || {};
  const app = session?.app;
  const [authVersion, setAuthVersion] = useState(0);
  const providerOptions = useProviderOptions(app, sessionId, authVersion);
  const [draft, setDraft] = useState(() => local.get(`draft.${sessionId}`, ""));
  const [choice, setChoice] = useState(() => local.get(`choice.${sessionId}`, {}));
  const [error, setError] = useState(null);
  const [sendingFor, setSendingFor] = useState(null);
  const sending = sendingFor === sessionId;
  const [images, setImages] = useImageDraft(sessionId);
  const [files, setFiles] = useFileDraft(sessionId);
  const [compacting, setCompacting] = useState(false);
  const [branchNext, setBranchNext] = useState(false);
  const [imageNotice, setImageNotice] = useState("");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);
  const attachRef = useRef(null);
  const formRef = useRef(null);
  // "Send it" sends after a short preview, with the text as it is then.
  const dictation = useTextareaDictation({ inputRef: input, setText: setDraft, containerRef: formRef, kind: "composer", onSend: () => void submitRef.current?.() });
  const submitRef = useRef(null);
  // The chat on screen and its text right now, for work that finishes after a switch.
  const shown = useRef({ sessionId, draft });
  shown.current = { sessionId, draft };
  const active = isRunActive(run);
  // A branch only when asked for (+ menu); otherwise a chat open in the Claude app continues in place.
  const branching = branchNext && Boolean(capabilities.fork);
  const canSend = active || capabilities.continue_session !== false || branching;
  const alsoOpen = !active && !branching && capabilities.continue_session !== false && ["app", "cli"].includes(session?.live_owner);
  const canSteer = active && (run?.canSteer ?? capabilities.steer);
  // Autopilot (plan 15 T17) is Neyvia's own: it works in Neyvia's workspace, so it is offered on Neyvia chats.
  const autopilotAllowed = app === "neyvia" && Boolean(sessionId) && !isFixtureId(sessionId);
  const [autopilotMode, setAutopilotMode] = useAutopilotMode(sessionId);
  const autopilot = useAutopilotRuns(autopilotAllowed ? sessionId : null);
  const autopilotOn = autopilotAllowed && autopilotMode.on;
  const autopilotBusy = ["planning", "running"].includes(autopilot.latest?.status);
  // Rough prompt in, good prompt out (plan 20 C14): the card under the composer.
  const items = useNx(state => state.threads[sessionId]?.items);
  const [amplifyMode, setAmplifyMode] = useAmplifyMode();
  const [amplifyNote, setAmplifyNote] = useState(null); // {id, learning} of the last edited prompt sent
  const noteLearning = useNx(state => (amplifyNote ? state.amplifyLearning[amplifyNote.id] : null));
  const noteText = amplifyNote ? learningLine(noteLearning || amplifyNote.learning) : "";
  const amplifyAllowed = Boolean(sessionId) && !isFixtureId(sessionId) && canSend && !autopilotOn && !canSteer && !branching && amplifyMode !== "off";
  const amplifier = useAmplifier({ sessionId, draft, enabled: amplifyAllowed, items, project: session?.cwd, mode: amplifyMode });

  useEffect(() => {
    setDraft(local.get(`draft.${sessionId}`, ""));
    setChoice(local.get(`choice.${sessionId}`, {}));
    setError(null);
    setImageNotice("");
    setToolsOpen(false);
    setBranchNext(false);
    setAmplifyNote(null);
  }, [sessionId]);

  // An app (Notes: Send to chat) put text in this chat's saved draft.
  useEffect(() => {
    const onCompose = event => {
      if (event.detail?.sessionId !== sessionId) return;
      setDraft(local.get(`draft.${sessionId}`, ""));
      requestAnimationFrame(() => { const element = input.current; if (element) { element.focus(); element.setSelectionRange(element.value.length, element.value.length); } });
    };
    window.addEventListener("nx:compose", onCompose);
    return () => window.removeEventListener("nx:compose", onCompose);
  }, [sessionId]);

  useEffect(() => {
    const timer = setTimeout(() => local.set(`draft.${sessionId}`, draft || null), 250);
    return () => clearTimeout(timer);
  }, [draft, sessionId]);

  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(element.scrollHeight, 280)}px`;
  }, [draft]);

  const updateChoice = useCallback(patch => {
    setChoice(current => {
      const next = { ...current, ...patch };
      local.set(`choice.${sessionId}`, next);
      return next;
    });
  }, [sessionId]);

  const models = providerOptions?.models || [];
  const modes = providerOptions?.permissionModes || [];
  const transports = providerOptions?.transports?.length ? providerOptions.transports : null;
  const transport = transports ? (choice.transport || preferredTransport(transports)) : null;
  const modelValue = choice.model || session?.model || null;
  const blocker = imageBlocker({ app, appName, capabilities, transport, transports, model: models.find(model => model.id === modelValue) });
  const imagesBlocked = images.length > 0 && Boolean(blocker);
  const message = draft.trim();
  const ready = autopilotOn
    ? Boolean(message) && !images.length && !files.length && !sending && !autopilotBusy
    : Boolean(message || images.length || files.length) && !imagesBlocked && !sending && canSend && !(active && !canSteer);
  const canCompact = Boolean(capabilities.compact) && !active && !compacting;
  // The button and a typed /compact take this one path, with the model and billing mode a message would use.
  const compact = async (instructions = null) => {
    setCompacting(true); setError(null);
    try {
      await compactSession(sessionId, { model: choice.model || null, effort: choice.effort || null, transport: transports ? transport : null }, instructions);
    }
    catch (failure) { setError({ code: failure?.code || "", message: failure?.message || "The chat couldn't be compacted." }); }
    finally { setCompacting(false); }
  };

  const addFiles = picked => {
    const origin = sessionId;
    void attachAny(picked, origin).then(notice => { if (shown.current.sessionId === origin) setImageNotice(notice); });
  };

  useEffect(() => {
    if (!noteText) return undefined;
    const timer = setTimeout(() => setAmplifyNote(null), 12000);
    return () => clearTimeout(timer);
  }, [noteText]);

  // `via`: the amplification the card sends (its id and revision go with the original words);
  // `raw`: send as typed, without the card.
  const submit = async ({ via = null, raw = false } = {}) => {
    const typedCompact = /^\/compact(\s|$)/i.test(message) && !images.length && !files.length && capabilities.compact && !branching;
    if (typedCompact) {
      if (!canCompact || sending) { if (active) setError({ code: "busy", message: "Wait until the current turn finishes, then compact." }); return; }
      const origin = sessionId;
      await compact(message.slice("/compact".length).trim() || null);
      if (shown.current.sessionId === origin) setDraft("");
      local.set(`draft.${origin}`, null);
      return;
    }
    if (!ready) {
      // The card waits on this answer; an unsent prompt must not look sent.
      if (via) throw new Error(active ? "Wait until the current turn finishes, then send." : "This message can't be sent from here right now.");
      return;
    }
    const origin = sessionId;
    if (!via && !raw && amplifyAllowed && shouldAmplify({ mode: amplifyMode, message, attachmentsOnly: !message })) {
      amplifier.stage();
      return;
    }
    if (autopilotOn) {
      // The message becomes an Autopilot run for this chat; the chat's own agent is not asked.
      setSendingFor(origin); setError(null);
      try {
        autopilot.put(await startAutopilot({ sessionId: origin, text: message, scope: autopilotMode.scope }));
        local.set(`draft.${origin}`, null);
        if (shown.current.sessionId === origin && shown.current.draft.trim() === message) setDraft("");
      } catch (failure) {
        if (shown.current.sessionId === origin) setError({ code: failure?.code || "", message: failure?.message || "Autopilot didn't start." });
      } finally {
        setSendingFor(current => (current === origin ? null : current));
      }
      return;
    }
    const block = contextBlock ? contextBlock() : "";
    const outgoing = block ? `${block}\n\n${message}` : message;
    const sent = new Set(images.map(image => image.id));
    const sentFiles = new Set(files.map(file => file.id));
    setSendingFor(origin); setError(null);
    try {
      // Sent exactly as chosen; images go only when attached, without a data-URL prefix.
      const options = {
        model: choice.model || null, effort: choice.effort || null, permission_mode: choice.permission || null,
        transport: transports ? transport : null,
        ...(via ? sendOptions(via) : {}),
        ...(images.length ? { images: images.map(({ mime, data, name }) => ({ mime, data, name })) } : {}),
        ...(files.length ? { files: files.map(({ name, data }) => ({ name, data })) } : {}),
      };
      if (canSteer) {
        // Into the turn that is working now; the app takes it in at its next step.
        await steerRun(origin, outgoing, { ...(images.length ? { images: options.images } : {}), ...(files.length ? { files: options.files } : {}) });
      } else if (branching) {
        const started = await startSession(app, session.cwd, outgoing, { ...options, forkFrom: origin });
        if (started?.sessionId) {
          local.set(`choice.${started.sessionId}`, choice);
          await loadList();
          onOpenChat?.(started.sessionId);
        }
        setBranchNext(false);
      } else {
        await sendMessage(origin, outgoing, options);
      }
      // Clear what was sent from the chat it was sent in, even if another chat is on screen now.
      imageDrafts.update(origin, current => current.filter(image => !sent.has(image.id)));
      fileDrafts.update(origin, current => current.filter(file => !sentFiles.has(file.id)));
      local.set(`draft.${origin}`, null);
      if (shown.current.sessionId === origin) {
        if (shown.current.draft.trim() === message) setDraft("");
        else local.set(`draft.${origin}`, shown.current.draft);  // typed on while it sent: keep that
        setImageNotice("");
        if (via) { amplifier.reset(); setAmplifyNote(via.learning ? { id: via.id, learning: via.learning } : null); }
      }
    } catch (failure) {
      if (shown.current.sessionId !== origin) return;
      // The draft and images stay, so the person can retry or change something.
      const imageOnly = !message && images.length && failure?.code === "invalid_message";
      if (via) throw failure;  // the card shows it next to the prompt it tried to send
      setError({
        code: failure?.code || "",
        message: imageOnly ? "This PC's Neyvia service doesn't take image-only messages yet. Add a few words and send again." : failure?.message || "The message didn't reach the app.",
      });
    } finally {
      setSendingFor(current => (current === origin ? null : current));
    }
  };

  const onPaste = event => {
    const pastedFiles = [...(event.clipboardData?.files || [])];
    if (!pastedFiles.length) return;
    // A copied picture with no text replaces the paste; mixed content keeps its text too.
    if (!event.clipboardData.getData("text/plain")) event.preventDefault();
    addFiles(pastedFiles);
  };
  const hasFiles = event => [...(event.dataTransfer?.types || [])].includes("Files");

  const onKeyDown = event => {
    if (event.key === "Escape" && amplifier.open) {
      event.preventDefault();
      amplifier.close();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  submitRef.current = submit;
  return (
    <div className={`nx-composer-wrap${className ? ` ${className}` : ""}`}>
      <SignInCard app={app} auth={error?.code === "auth_failed" ? { kind: "signed-out" } : providerOptions?.auth}
        onSignedIn={() => { forgetProviderOptions(app); setError(null); setAuthVersion(value => value + 1); }} />
      <NxChecklist sessionId={sessionId} working={active || ["working", "waiting_approval", "waiting_input"].includes(session?.status)} />
      {autopilotAllowed ? <AutopilotPanel sessionId={sessionId} runs={autopilot.runs} latest={autopilot.latest} readError={autopilot.error} onChanged={autopilot.put} /> : null}
      {autopilotOn && !autopilot.latest ? (
        <p className="nx-ap-hint">Autopilot turns your message into a checklist and finishes it without asking. Steps the manuals cover run with no model; GPT-6 Luna makes only the choices they leave open.</p>
      ) : null}
      <RunStrip run={run} appName={appName} onStop={() => void stopRun(sessionId).catch(failure => setError({ message: failure?.message || "Stop didn't reach the app." }))} />
      {branching ? (
        <p className="nx-composer-branch">
          Your next message starts a branch: a new chat with this whole history. This chat stays as it is.
          <button type="button" onClick={() => setBranchNext(false)}>Cancel</button>
        </p>
      ) : !canSend && capabilities.reason ? (
        <p className="nx-composer-branch is-quiet">{capabilities.reason}</p>
      ) : alsoOpen ? (
        <p className="nx-composer-branch is-quiet">
          Also open in {app === "codex" ? "Codex" : session?.live_owner === "cli" ? "a Claude Code terminal" : "the Claude app"}: what you send here is added to this
          chat. Reopen it there to see these messages.
        </p>
      ) : null}
      {error ? (
        <div className="nx-composer-error" role="alert">
          <span>{error.message}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setError(null)}><Icon as={X} size={13} /></button>
        </div>
      ) : null}
      {toolsOpen ? <ToolRunner session={session} appName={appName} onClose={() => setToolsOpen(false)} /> : null}
      {imageNotice ? (
        <div className="nx-composer-error" role="alert">
          <span>{imageNotice}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setImageNotice("")}><Icon as={X} size={13} /></button>
        </div>
      ) : null}
      {imagesBlocked ? (
        <div className="nx-composer-error is-warn" role="alert">
          <span>{blocker.reason}</span>
          {blocker.switchTo ? (
            <button type="button" className="nx-composer-switch" onClick={() => updateChoice({ transport: blocker.switchTo.id })}>Use {blocker.switchTo.label}</button>
          ) : null}
        </div>
      ) : null}
      <form ref={formRef} className={`nx-composer${!canSend ? " is-disabled" : ""}${dragging ? " is-drop" : ""}`} onSubmit={event => { event.preventDefault(); void submit(); }}
        onDragOver={event => { if (canSend && hasFiles(event)) { event.preventDefault(); setDragging(true); } }}
        onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }}
        onDrop={event => { if (!hasFiles(event)) return; event.preventDefault(); setDragging(false); if (canSend) addFiles(event.dataTransfer.files); }}>
        <AttachmentTray images={images} disabled={sending} onRemove={id => setImages(current => current.filter(image => image.id !== id))} />
        <FileTray files={files} disabled={sending} onRemove={id => setFiles(current => current.filter(file => file.id !== id))} />
        <DictationStrip dictation={dictation} />
        <textarea ref={input} rows={1} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={onKeyDown} onPaste={onPaste}
          disabled={!canSend} aria-label={`Message ${appName}`}
          placeholder={autopilotOn ? (autopilotBusy ? "Autopilot is working on this chat's last list…" : "Give Autopilot a few things to get done") : !canSend ? (capabilities.reason || `${appName} can't be continued from this device.`) : branching ? "Continue as a branch: your message starts a new chat with the whole history" : canSteer ? `Steer ${appName} while it works…` : active ? "Write your next message…" : placeholder || `Message ${appName}`} />
        <DictationGhost dictation={dictation} />
        <div className="nx-composer-bar">
          <div className="nx-composer-left">
            <PlusMenu appName={appName} disabled={!canSend} imagesUnavailable={session && !capabilities.images ? blocker?.reason : ""}
              onFiles={addFiles} onOpenTools={() => setToolsOpen(true)} onAttach={() => attachRef.current?.click()}
              compact={session ? { available: canCompact, reason: active ? "Wait until the current turn finishes." : capabilities.reason, onCompact: () => void compact() } : null}
              branch={capabilities.fork ? { on: branchNext, onToggle: () => setBranchNext(on => !on) } : null}
              amplify={{ on: amplifyMode !== "off", onToggle: () => setAmplifyMode(amplifyMode === "off" ? "auto" : "off") }} />
            <AttachButton disabled={!canSend} onFiles={addFiles} inputRef={attachRef} />
            {session ? <CompactButton available={canCompact} busy={compacting} reason={active ? "Wait until the current turn finishes." : capabilities.reason} onCompact={() => void compact()} /> : null}
            {autopilotAllowed ? <AutopilotToggle on={autopilotOn} onChange={on => setAutopilotMode({ on })} /> : null}
            {autopilotOn ? <AutopilotScope value={autopilotMode.scope} onChange={scope => setAutopilotMode({ scope })} /> : null}
            {!autopilotOn && capabilities.model_choice !== false ? (
              <ModelPicker app={app} models={models} value={modelValue} effort={choice.effort || null}
                billing={capabilities.billing} note={billingNote(providerOptions, transport)} onChange={patch => updateChoice(patch)} />
            ) : null}
            {!autopilotOn && capabilities.permission_choice ? <PermissionPicker modes={modes} value={choice.permission} onChange={permission => updateChoice({ permission })} /> : null}
            {!autopilotOn ? <RoutePicker transports={transports} value={transport} onChange={next => updateChoice({ transport: next })} /> : null}
          </div>
          <div className="nx-composer-right">
            <ContextRing context={context} />
            <MicButton dictation={dictation} disabled={!canSend} />
            <button type="submit" className="nx-send" aria-label={autopilotOn ? "Start Autopilot" : canSteer ? "Steer" : "Send"} title={autopilotOn ? "Start Autopilot (Enter)" : active && !canSteer ? "Send once it finishes" : "Send (Enter)"}
              disabled={!ready}>
              {sending ? <Spinner size={13} /> : <Icon as={ArrowUp} size={16} />}
            </button>
          </div>
        </div>
      </form>
      {amplifyAllowed ? (
        <NxAmplifyCard amplifier={amplifier} appName={appName} mode={amplifyMode} onModeChange={setAmplifyMode} sending={sending}
          onSend={amplification => submitRef.current?.({ via: amplification })}
          onSendOriginal={() => void submitRef.current?.({ raw: true })} />
      ) : null}
      {noteText ? <p className="nx-amp-note" role="status">{noteText}</p> : null}
    </div>
  );
}
