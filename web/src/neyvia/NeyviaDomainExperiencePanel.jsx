import { useState } from "react";
import { ArrowRight, Compass, Sparkles } from "lucide-react";

import {
  NEYVIA_DOMAIN_EXPERIENCES,
  domainExperienceById,
  domainStarterPrompt,
} from "./neyviaDomainExperiences.js";

async function callNeyvia(command, payload = {}) {
  const response = await fetch("/api/backend", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, payload }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `${command} failed`);
  return result?.data || {};
}

export function NeyviaDomainExperiencePanel({
  onApplyExperience,
  onRequestAction,
  onSelectPrompt,
  onSetSurface,
}) {
  const [selectedId, setSelectedId] = useState("student");
  const [specificIntent, setSpecificIntent] = useState("");
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");
  const selected = domainExperienceById(selectedId);

  const prepareInChat = async () => {
    setState("loading");
    setError("");
    try {
      const prompt = domainStarterPrompt(selected, specificIntent);
      const contract = await callNeyvia("build_neyvia_ecosystem_context_pack_command", {
        prompt,
        taskProfile: selected.profile,
        silentRewrite: true,
        taskContext: {
          scope: selected.intent,
          constraints: selected.approvals,
          success: `Return one or more of: ${selected.artifacts.join(", ")}`,
          currentState: selected.reality,
        },
      });
      const prepared = String(contract?.rewrite?.prompt || prompt);
      if (typeof onSelectPrompt !== "function") {
        throw new Error("Chat draft surface is unavailable");
      }
      await onApplyExperience?.({
        domainId: selected.id,
        label: selected.label,
        profile: selected.profile,
        ...selected.adaptive,
        source: "explicit-domain-launch",
      });
      onSetSurface?.("agent");
      onSelectPrompt(prepared);
      onRequestAction?.("neyvia:domain:start", {
        domainId: selected.id,
        profile: selected.profile,
        adaptive: selected.adaptive,
      });
      setState("ready");
    } catch (nextError) {
      setState("error");
      setError(nextError instanceof Error ? nextError.message : "Domain brief could not be prepared");
    }
  };

  return (
    <section className="neyvia-domain-experiences" data-neyvia-domain-experiences="true">
      <header>
        <div>
          <span className="neyvia-surface-eyebrow"><Compass aria-hidden="true" size={14} /> Experiences</span>
          <h3>Choose a starting point</h3>
          <p>Pick the kind of work you want to do. Neyvia will prepare the right tools and keep unavailable actions clearly marked.</p>
        </div>
      </header>
      <div className="neyvia-domain-layout">
        <div className="neyvia-domain-list" role="list">
          {NEYVIA_DOMAIN_EXPERIENCES.map(experience => (
            <button
              aria-current={selectedId === experience.id ? "true" : undefined}
              className={selectedId === experience.id ? "is-selected" : undefined}
              key={experience.id}
              onClick={() => setSelectedId(experience.id)}
              role="listitem"
              type="button"
            >
              <strong>{experience.label}</strong>
              <span>{experience.intent}</span>
            </button>
          ))}
        </div>
        <article className="neyvia-domain-detail">
          <div>
            <span>{selected.profile.replaceAll("_", " ")} experience</span>
            <h4>{selected.label}</h4>
            <p>{selected.intent}</p>
          </div>
          <dl>
            <div><dt>Uses</dt><dd>{selected.composed.join(" · ")}</dd></div>
            <div><dt>Creates</dt><dd>{selected.artifacts.join(" · ")}</dd></div>
            <div><dt>Permission</dt><dd>{selected.approvals}</dd></div>
            <div><dt>Available now</dt><dd>{selected.reality}</dd></div>
          </dl>
          <label>
            Your specific goal
            <textarea
              onChange={event => setSpecificIntent(event.target.value)}
              placeholder="Add an optional detail. Neyvia keeps your wording when it prepares the task."
              rows={3}
              value={specificIntent}
            />
          </label>
          <button disabled={state === "loading"} onClick={prepareInChat} type="button">
            <Sparkles aria-hidden="true" size={14} />
            {state === "loading" ? "Preparing…" : "Prepare in Chat"}
            <ArrowRight aria-hidden="true" size={14} />
          </button>
          {error ? <p className="neyvia-ecosystem-error" role="alert">{error}</p> : null}
        </article>
      </div>
    </section>
  );
}
