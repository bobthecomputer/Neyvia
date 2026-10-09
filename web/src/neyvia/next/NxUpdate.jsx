import { useState } from "react";
import { Button } from "./nxPrimitives.jsx";

export function UpdateCard() {
  const desktop = Boolean(window.__TAURI_INTERNALS__);
  const [update, setUpdate] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const run = async install => {
    setBusy(true); setMessage("");
    try {
      if (install) {
        await update.downloadAndInstall(event => {
          if (event.event === "Started") setMessage("Downloading the signed update…");
          if (event.event === "Finished") setMessage("Installing…");
        });
        const { relaunch } = await import("@tauri-apps/plugin-process");
        await relaunch();
      } else {
        const { check } = await import("@tauri-apps/plugin-updater");
        const next = await check();
        setUpdate(next);
        setMessage(next ? `Neyvia ${next.version} is available.` : "Neyvia is up to date.");
      }
    } catch (error) { setMessage(error?.message || "The update could not complete. Try again."); }
    finally { setBusy(false); }
  };
  return <section id="nx-set-sec-updates" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-updates" aria-busy={busy}>
    <header className="nx-ac-head"><div><h3 id="nx-set-updates">Neyvia updates</h3><p>Updates come from Neyvia’s GitHub releases and must match the embedded signing key.</p></div></header>
    {desktop ? <div className="nx-set-row is-actions">
      <Button variant="outline" disabled={busy} onClick={() => void run(false)}>Check for updates</Button>
      {update ? <Button disabled={busy} onClick={() => void run(true)}>Download and install Neyvia {update.version}</Button> : null}
    </div> : <p className="nx-set-hint">Open the Neyvia desktop app to check for and install updates.</p>}
    {message ? <p className="nx-set-hint" role="status">{message}</p> : null}
  </section>;
}
