import { useState } from "react";
import { Send } from "lucide-react";

import { sendRuntimeInvocationTurn } from "./neyviaRuntimeStore.js";

const TASK_PROFILES = Object.freeze([
  ["", "Auto · infer from task"],
  ["ecosystem_architecture", "Ecosystem architecture"],
  ["implementation", "Implementation"],
  ["diagnosis", "Diagnosis and repair"],
  ["optimization", "Optimization"],
  ["research", "Research and synthesis"],
  ["ui_ux", "UI and user experience"],
  ["image_generation", "Image generation"],
  ["security", "Security and red-team"],
  ["general", "General task"],
]);

/** Shared real-input path for primary and inline runtime presentations. */
export function NeyviaRuntimeComposer({ invocation, workspacePath = null }) {
  const [message, setMessage] = useState("");
  const [taskProfile, setTaskProfile] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const state = String(invocation?.state || "");
  const enabled =
    invocation?.readiness?.ready === true
    && ["ready", "returned"].includes(state)
    && !sending;

  const submit = async event => {
    event.preventDefault();
    const text = message.trim();
    if (!enabled || !text) return;
    setSending(true);
    setError("");
    try {
      await sendRuntimeInvocationTurn(invocation.invocationId, text, {
        workspacePath,
        taskProfile,
      });
      setMessage("");
    } catch (failure) {
      setError(String(failure?.message || failure));
    } finally {
      setSending(false);
    }
  };

  return (
    <form className="neyvia-runtime-composer" onSubmit={submit}>
      <label>
        <span>Continue with {invocation?.runtime || "runtime"}</span>
        <textarea
          disabled={!enabled}
          onChange={event => setMessage(event.target.value)}
          placeholder={
            state === "suspended"
              ? "Resume this invocation before sending another turn."
              : "Give this runtime the next task…"
          }
          rows={3}
          value={message}
        />
      </label>
      <label>
        <span>Prompt profile</span>
        <select
          disabled={!enabled}
          onChange={event => setTaskProfile(event.target.value)}
          value={taskProfile}
        >
          {TASK_PROFILES.map(([value, label]) => (
            <option key={value || "auto"} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <button disabled={!enabled || !message.trim()} type="submit">
        <Send aria-hidden="true" size={13} />
        {sending ? "Running…" : "Send turn"}
      </button>
      {error ? <p className="neyvia-runtime-composer-error" role="alert">{error}</p> : null}
    </form>
  );
}

export default NeyviaRuntimeComposer;
