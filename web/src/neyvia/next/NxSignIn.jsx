import { useEffect, useRef, useState } from "react";
import { Check, Copy, ExternalLink, KeyRound } from "lucide-react";

import { appLabel } from "./NxSidebar.jsx";
import { callNx } from "./nxApi.js";
import { Icon, Spinner } from "./nxPrimitives.jsx";

// Only the app's own sign-in pages are shown as links.
const OWN_PAGES = /^https:\/\/([a-z0-9-]+\.)*(openai\.com|chatgpt\.com|claude\.ai|claude\.com|anthropic\.com)\//i;

export function needsSignIn(auth) {
  return auth?.kind === "signed-out";
}

/**
 * Sign in to an app with the app's own sign-in: Codex shows a one-time code that works from any device,
 * Claude Code opens its sign-in in the browser on the PC. Neyvia never sees a password or token.
 */
export function SignInCard({ app, auth, onSignedIn }) {
  const [state, setState] = useState({ phase: "idle" });
  const [copied, setCopied] = useState(false);
  const [code, setCode] = useState("");
  const timer = useRef(null);
  useEffect(() => () => clearInterval(timer.current), []);
  useEffect(() => { clearInterval(timer.current); setState({ phase: "idle" }); }, [app]);
  if (!needsSignIn(auth) && state.phase !== "done") return null;
  const name = appLabel(app);

  const finish = next => {
    clearInterval(timer.current);
    setState({ phase: "done", auth: next });
    onSignedIn?.(next);
  };
  const waitForIt = () => {
    clearInterval(timer.current);
    const started = Date.now();
    timer.current = setInterval(async () => {
      if (Date.now() - started > 15 * 60 * 1000) { clearInterval(timer.current); setState(current => ({ ...current, expired: true })); return; }
      try {
        const next = await callNx("connected_app_auth_command", { app });
        if (next?.kind && !["signed-out", "unknown"].includes(next.kind)) finish(next);
      } catch { /* still waiting */ }
    }, 3000);
  };
  const start = async () => {
    setState({ phase: "starting" });
    try {
      const result = await callNx("connected_app_sign_in_command", { app });
      if (result?.state === "signed-in") { finish(result.auth); return; }
      if (result?.state === "paste" && OWN_PAGES.test(result.verificationUrl || "")) {
        // Claude Code's sign-in: the page shows a code to bring back here, so it works from any device.
        setCode("");
        setState({ phase: "paste", url: result.verificationUrl });
      } else if (result?.state === "code" && OWN_PAGES.test(result.verificationUrl || "")) {
        setState({ phase: "code", url: result.verificationUrl, code: result.userCode });
      } else {
        setState({ phase: "host", message: result?.message || `${name}'s sign-in opened on your PC. Finish it there.` });
      }
      waitForIt();
    } catch (failure) {
      setState({ phase: "error", message: failure?.message || "The sign-in couldn't start." });
    }
  };
  const sendCode = async event => {
    event.preventDefault();
    if (!code.trim()) return;
    setState(current => ({ ...current, sending: true, error: "" }));
    try {
      const result = await callNx("connected_app_sign_in_code_command", { app, code: code.trim() });
      setCode("");
      finish(result?.auth);
    } catch (failure) {
      clearInterval(timer.current);
      setCode("");
      setState({ phase: "error", message: failure?.message || "That code didn't work. Start the sign-in again." });
    }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(state.code); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* the code stays visible */ }
  };

  if (state.phase === "done") {
    return (
      <div className="nx-signin is-done" role="status">
        <Icon as={Check} size={15} />
        <span>{name} is signed in with {state.auth?.label || "your account"}.</span>
      </div>
    );
  }
  return (
    <div className="nx-signin" role="status">
      <div className="nx-signin-row">
        <Icon as={KeyRound} size={15} className="nx-signin-icon" />
        <span className="nx-signin-text">
          {app === "codex" ? (
            <><strong>{name} isn't signed in on this PC.</strong> Sign in with your ChatGPT account from any device.</>
          ) : (
            // The Claude app keeps its own sign-in; Neyvia runs the command-line Claude Code, which has a separate one.
            <><strong>Claude Code's command line is signed out on this PC.</strong> The Claude app has its own sign-in, so it
              still works there, and you can read these chats here. To send or start Claude chats from Neyvia, sign the
              command line in once with your Claude account.</>
          )}
        </span>
        {state.phase === "idle" || state.phase === "error" || state.expired ? (
          <button type="button" className="nx-btn nx-btn-sm nx-btn-primary" onClick={() => void start()}>Sign in</button>
        ) : null}
        {state.phase === "starting" ? <Spinner size={13} /> : null}
      </div>
      {state.phase === "code" ? (
        <div className="nx-signin-step">
          <span>Open</span>
          <a href={state.url} target="_blank" rel="noopener noreferrer" className="nx-signin-link">
            {state.url.replace(/^https:\/\//, "")} <Icon as={ExternalLink} size={12} />
          </a>
          <span>and enter</span>
          <button type="button" className="nx-signin-code" onClick={() => void copy()} title="Copy the code">
            {state.code} <Icon as={copied ? Check : Copy} size={12} />
          </button>
        </div>
      ) : null}
      {state.phase === "paste" ? (
        <form className="nx-signin-paste" onSubmit={event => void sendCode(event)}>
          <p className="nx-signin-step">
            <span>1.</span>
            <a href={state.url} target="_blank" rel="noopener noreferrer" className="nx-signin-link">
              Open Claude's sign-in page <Icon as={ExternalLink} size={12} />
            </a>
            <span>on this device and sign in.</span>
          </p>
          <p className="nx-signin-step"><span>2. Paste the code the page shows:</span></p>
          <div className="nx-signin-step">
            <input className="nx-signin-input" value={code} onChange={event => setCode(event.target.value)} autoComplete="off"
              spellCheck={false} autoCapitalize="none" placeholder="Code from Claude's page" aria-label="Code from Claude's page" />
            <button type="submit" className="nx-btn nx-btn-sm nx-btn-primary" disabled={!code.trim() || state.sending}>
              {state.sending ? <Spinner size={11} /> : null} Finish sign-in
            </button>
          </div>
        </form>
      ) : null}
      {state.phase === "host" ? <p className="nx-signin-note">{state.message}</p> : null}
      {state.phase === "code" || state.phase === "host" || state.phase === "paste" ? (
        <p className="nx-signin-note">
          {state.expired ? "The sign-in timed out. Start it again when you're ready." : <><Spinner size={11} /> Waiting for you to finish. Neyvia never sees your password.</>}
        </p>
      ) : null}
      {state.phase === "error" ? <p className="nx-signin-note is-error">{state.message}</p> : null}
    </div>
  );
}
