import { useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Clock, Search } from "lucide-react";

import { ProviderMark, resolveProviderMarkId } from "./ProviderMark.jsx";
import { Icon, Popover, Segmented, local, useRovingKeys } from "./nxPrimitives.jsx";

const EFFORT_LABELS = { minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max" };
export const effortLabel = value => EFFORT_LABELS[value] || value;

const PROVIDERS = {
  "openai-codex": { label: "OpenAI", mark: "codex" },
  openai: { label: "OpenAI", mark: "codex" },
  "opencode-go": { label: "OpenCode Go", mark: "opencode" },
  anthropic: { label: "Anthropic", mark: "claude" },
  openrouter: { label: "OpenRouter", mark: "openrouter" },
  minimax: { label: "MiniMax", mark: "minimax" },
  "kimi-code": { label: "Kimi", mark: "kimi" },
  zai: { label: "Z.ai (GLM)", mark: "glm" },
  "z-ai": { label: "Z.ai (GLM)", mark: "glm" },
  deepseek: { label: "DeepSeek", mark: "deepseek" },
  google: { label: "Google", mark: "gemini" },
  xai: { label: "xAI", mark: "grok" },
};
const RUNTIMES = { "neyvia-agent": "Neyvia", codex: "Codex", "claude-code": "Claude Code", hermes: "Hermes", opencode: "OpenCode", gptme: "gptme", "kimi-code": "Kimi Code" };

// Neyvia model ids are "<runtime>|<provider>|<model>"; other apps use plain ids.
function describe(model, app) {
  const parts = String(model.id || "").split("|");
  if (parts.length === 3) {
    const [runtime, provider] = parts;
    const vendor = PROVIDERS[provider] || { label: provider, mark: resolveProviderMarkId(provider) };
    const viaRuntime = runtime && runtime !== "neyvia-agent" ? `${RUNTIMES[runtime] || runtime} · ` : "";
    return { group: `${viaRuntime}${vendor.label}`, mark: runtime !== "neyvia-agent" ? (resolveProviderMarkId(runtime) || vendor.mark) : vendor.mark };
  }
  return { group: model.group || null, mark: app === "claude-code" ? "claude" : app };
}

// "claude-opus-5-5[1m]" -> "Opus 5.5 · 1M", for ids the app didn't label; others stay as reported.
export function prettyModel(id) {
  const raw = String(id || "").split("|").pop();
  const claude = raw.match(/^claude-([a-z]+)-(\d+)-(\d+)/i);
  if (!claude) return raw;
  const name = `${claude[1][0].toUpperCase()}${claude[1].slice(1)} ${claude[2]}.${claude[3]}`;
  return /\[1m\]$/i.test(raw) ? `${name} · 1M` : name;
}

const labelOf = model => (model.label && model.label !== model.id ? model.label : prettyModel(model.id));

function markOf(app) {
  return app === "claude-code" ? "claude" : resolveProviderMarkId(app) || app;
}

/** Ordered, searchable model chooser with effort, grouped by provider. */
export function ModelPicker({ app, models, value, effort, onChange, billing, note }) {
  const anchor = useRef(null);
  const listRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const onKeyDown = useRovingKeys(listRef);
  const current = models.find(model => model.id === value) || models.find(model => model.default) || null;
  const efforts = current?.efforts || [];
  const recentKey = `models.recent.${app}`;

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const visible = models.filter(model => !needle || `${model.label} ${model.id} ${model.description || ""}`.toLowerCase().includes(needle));
    const result = [];
    const recent = needle ? [] : local.get(recentKey, []).map(id => visible.find(model => model.id === id)).filter(Boolean).slice(0, 3);
    if (recent.length && visible.length > 6) result.push({ key: "recent", label: "Recent", icon: Clock, models: recent });
    const byGroup = new Map();
    for (const model of visible) {
      const { group, mark } = describe(model, app);
      const key = group || "Models";
      if (!byGroup.has(key)) byGroup.set(key, { key, label: group, mark, models: [] });
      byGroup.get(key).models.push(model);
    }
    return [...result, ...byGroup.values()];
  }, [models, query, app, recentKey]);

  const pick = model => {
    local.set(recentKey, [model.id, ...local.get(recentKey, []).filter(id => id !== model.id)].slice(0, 6));
    onChange({ model: model.id, effort: model.efforts?.includes(effort) ? effort : model.defaultEffort || null });
    if (!model.efforts?.length) setOpen(false);
  };

  const chipMark = current ? describe(current, app).mark || markOf(app) : markOf(app);
  return (
    <>
      <button ref={anchor} type="button" className="nx-chip" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)} title="Model and effort">
        <ProviderMark id={chipMark} size={14} />
        <span className="nx-chip-label">{current ? labelOf(current) : value ? prettyModel(value) : "Model"}</span>
        {effort ? <span className="nx-chip-sub">{effortLabel(effort)}</span> : null}
        <Icon as={ChevronDown} size={13} className="nx-chip-caret" />
      </button>
      <Popover anchor={anchor} open={open} onClose={() => { setOpen(false); setQuery(""); }} width={340} label="Choose a model">
        <div className="nx-picker is-models">
          {models.length > 8 ? (
            <label className="nx-search is-pop">
              <Icon as={Search} size={14} />
              <input data-autofocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Search models" aria-label="Search models" />
            </label>
          ) : <div className="nx-picker-head">Model</div>}
          <div role="listbox" ref={listRef} onKeyDown={onKeyDown} className="nx-picker-list nx-scroll">
            {!models.length ? <p className="nx-picker-empty">This app didn't report its models. Replies use the chat's current model.</p> : null}
            {models.length && !groups.length ? <p className="nx-picker-empty">No model matches “{query}”.</p> : null}
            {groups.map(group => (
              <div key={group.key} className="nx-picker-group">
                {group.label && (groups.length > 1 || group.key === "recent") ? (
                  <div className="nx-picker-group-head">
                    {group.icon ? <Icon as={group.icon} size={12} /> : group.mark ? <ProviderMark id={group.mark} size={12} /> : null}
                    <span>{group.label}</span>
                  </div>
                ) : null}
                {group.models.map(model => (
                  <button key={`${group.key}:${model.id}`} type="button" role="option" aria-selected={model.id === current?.id}
                    className={`nx-picker-row${model.id === current?.id ? " is-on" : ""}`} onClick={() => pick(model)}>
                    <span className="nx-picker-main">
                      <strong>{labelOf(model)}</strong>
                      {model.description ? <span>{model.description}</span> : null}
                    </span>
                    {model.default ? <span className="nx-tag">Default</span> : null}
                    {model.id === current?.id ? <Icon as={Check} size={14} className="nx-picker-check" /> : null}
                  </button>
                ))}
              </div>
            ))}
          </div>
          {efforts.length ? (
            <div className="nx-picker-effort">
              <div className="nx-picker-head">Effort</div>
              <Segmented size="sm" label="Effort" value={effort || current?.defaultEffort || efforts[0]}
                options={efforts.map(level => ({ value: level, label: effortLabel(level) }))}
                onChange={next => onChange({ model: current?.id || value, effort: next })} />
            </div>
          ) : null}
          {note ? <p className="nx-picker-foot">{note}</p> : billing === "agent-sdk-credits" ? (
            <p className="nx-picker-foot">Messages sent from Neyvia run through Claude Code's print mode and use your monthly Agent SDK credits.</p>
          ) : null}
        </div>
      </Popover>
    </>
  );
}
