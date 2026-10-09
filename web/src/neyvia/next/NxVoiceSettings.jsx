import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "./nxPrimitives.jsx";
import { engineStatus, saveDictationSettings } from "./nxDictation.js";
import { providerChoices, providerSummary } from "./nxDictationProviders.js";

// Settings > Voice: where dictation turns speech into words. Local is the default and works offline; OpenAI (API key)
// and the Codex sign-in route are offered when this PC can use them; the browser's speech input is the last resort.
// An unavailable choice says why, and a choice that fails while talking falls back to the local engine with a note.

export function VoiceCard() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const refresh = useCallback(async probe => {
    try { setStatus(await engineStatus({ probe })); setError(""); }
    catch (failure) { setError(failure?.message || "Dictation status couldn't be read."); }
  }, []);
  useEffect(() => { void refresh(false); }, [refresh]);
  const choose = async id => {
    setBusy(id);
    try {
      const saved = await saveDictationSettings({ provider: id });
      setStatus(saved?.status || status);
      setError("");
    } catch (failure) { setError(failure?.message || "That choice couldn't be saved."); }
    finally { setBusy(""); }
  };
  const rows = providerChoices(status);
  const summary = providerSummary(status);
  const codexChecked = status?.providers?.find(row => row.id === "codex")?.checked;
  return (
    <section id="nx-set-sec-voice" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-voice" aria-busy={Boolean(busy)}>
      <header className="nx-ac-head"><div><h3 id="nx-set-voice">Voice dictation</h3>
        <p>Choose how your speech becomes words. Words appear as you speak with every choice.</p></div></header>
      {!status && !error ? <p className="nx-set-hint">Reading…</p> : null}
      <div role="radiogroup" aria-label="Dictation engine" className="nx-set-providers">
        {rows.map(row => (
          <label key={row.id} className={`nx-set-provider${row.selected ? " is-selected" : ""}${row.available ? "" : " is-unavailable"}`}>
            <input type="radio" name="nx-dictation-provider" checked={row.selected} disabled={Boolean(busy) || (!row.available && !row.selected)}
              onChange={() => void choose(row.id)} />
            <span><strong>{row.label}{row.badge ? <em className="nx-set-badge">{row.badge}</em> : null}</strong>
              <small>{row.hint}</small>
              {row.reason ? <small className="nx-set-why">{row.reason}</small> : null}</span>
          </label>
        ))}
      </div>
      {summary ? <p className="nx-notice is-warn" role="status">{summary}</p> : null}
      {error ? <p className="nx-notice is-error" role="alert">{error}</p> : null}
      <div className="nx-set-row is-actions">
        <Button size="sm" variant="outline" icon={RefreshCw} onClick={() => void refresh(true)}>{codexChecked ? "Check again" : "Check Codex sign-in"}</Button>
      </div>
    </section>
  );
}
