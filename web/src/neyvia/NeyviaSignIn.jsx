import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Eye, EyeOff, Flame, MoonStar, NotebookPen, RotateCw, SquareTerminal, Sun, TreePine, UserRound } from "lucide-react";

import { THEME_REGISTRY } from "./next/nxThemeRegistry.js";
import "./next/nxTokens.css";
import "./next/nxThemes.css";
import "./neyviaSignIn.css";
import { NxAvatar } from "./next/NxAvatar.jsx";

// The sign-in page in the control UI's own themes. It reads the theme the
// shell saved (the startup splash reads the same keys), so the page, the
// splash and the workspace never flash different colours.

/** A half sun resting on the horizon: the Sunset theme (lucide's sunset glyph reads as a download arrow). */
function HorizonSun({ size = 14, strokeWidth = 1.9 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 16a6 6 0 0 1 12 0" />
      <path d="M2 16h20M5 20h14M12 5v2.5M4.9 8.9l1.7 1.7M19.1 8.9l-1.7 1.7" />
    </svg>
  );
}

const THEME_GLYPH = { dark: TreePine, light: Sun, sunset: HorizonSun, night: MoonStar, terminal: SquareTerminal, paper: NotebookPen, ember: Flame };
const THEMES = THEME_REGISTRY.map(({ id, label }) => ({ id, label, icon: THEME_GLYPH[id] }));
const LAST_ACCOUNT = "neyvia.signin.last";
// The first account's default name; a greeting with it would read "Welcome back, Account".
const GENERIC_NAMES = new Set(["account", "admin"]);

function read(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; }
}
function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* the page works without it */ }
}

function savedTheme() {
  const theme = read("nx.os.theme");
  if (THEMES.some(item => item.id === theme)) return theme;
  return globalThis.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function ThemeSwitch({ theme, onChange }) {
  return (
    <div className="ny-si-themes" role="radiogroup" aria-label="Theme">
      {THEMES.map(({ id, label, icon: Glyph }) => (
        <button key={id} type="button" role="radio" aria-checked={theme === id} title={label} aria-label={label}
          className={theme === id ? "is-on" : ""} onClick={() => onChange(id)}>
          <Glyph size={14} strokeWidth={1.9} />
        </button>
      ))}
    </div>
  );
}

function greeting(account) {
  const name = account?.displayName || account?.username || "";
  return name && !GENERIC_NAMES.has(name.toLowerCase()) ? `Welcome back, ${name}` : "Welcome back";
}

/**
 * Sign in to Neyvia with a local account. With several accounts it starts on
 * a chooser; the account used last on this device is ready straight away.
 */
export function NeyviaSignIn({ accountHints = [], offline = "", onSignIn }) {
  const accounts = useMemo(() => accountHints
    .map(item => ({ username: String(item?.username || "").trim(), displayName: String(item?.displayName || "").trim() }))
    .filter(item => item.username), [accountHints]);
  const [theme, setTheme] = useState(savedTheme);
  const [username, setUsername] = useState(() => {
    const last = read(LAST_ACCOUNT);
    if (accounts.some(item => item.username === last)) return last;
    return accounts.length === 1 ? accounts[0].username : "";
  });
  const [typing, setTyping] = useState(accounts.length === 0);
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [caps, setCaps] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [shake, setShake] = useState(0);
  const passwordRef = useRef(null);
  const userRef = useRef(null);

  const chosen = accounts.find(item => item.username === username);
  const step = typing ? "other" : chosen ? "password" : "choose";

  useEffect(() => {
    if (step === "password") passwordRef.current?.focus();
    if (step === "other") userRef.current?.focus();
  }, [step]);

  const pickTheme = next => { setTheme(next); write("nx.os.theme", next); };
  const choose = name => { setUsername(name); setTyping(false); setPassword(""); setError(""); };
  const back = () => { setUsername(""); setTyping(false); setPassword(""); setError(""); };
  const other = () => { setUsername(""); setTyping(true); setPassword(""); setError(""); };

  const submit = async event => {
    event.preventDefault();
    if (busy || !username.trim() || !password) return;
    setBusy(true);
    setError("");
    try {
      await onSignIn(username.trim(), password);
      write(LAST_ACCOUNT, username.trim());
    } catch (failure) {
      setError(failure?.message || "That didn't work. Try again.");
      setPassword("");
      setShake(count => count + 1);
      passwordRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };
  const onKey = event => setCaps(Boolean(event.getModifierState?.("CapsLock")));

  return (
    <main className="nx ny-si" data-nx-theme={theme}>
      <div className="ny-si-sky" aria-hidden="true" />
      <header className="ny-si-top">
        <span className="ny-si-brand"><img src="/icons/neyvia-mark.svg" alt="" width="22" height="22" />Neyvia</span>
        <ThemeSwitch theme={theme} onChange={pickTheme} />
      </header>

      <section className="ny-si-center">
        <div className="ny-si-mark" aria-hidden="true"><img src="/icons/neyvia-mark.svg" alt="" width="76" height="76" /></div>
        <h1 className="ny-si-title">{greeting(chosen)}</h1>
        <p className="ny-si-sub">
          {step === "choose" ? "Who's signing in?" : "Your agents and chats are waiting on your PC."}
        </p>

        <div key={shake} className={`ny-si-card${shake ? " is-shake" : ""}`}>
          {offline ? (
            <div className="ny-si-offline" role="alert">
              <strong>Neyvia's PC service isn't answering.</strong>
              <span>{offline}</span>
              <button type="button" className="ny-si-primary" onClick={() => window.location.reload()}>
                <RotateCw size={15} /> Try again
              </button>
            </div>
          ) : step === "choose" ? (
            <div className="ny-si-accounts" role="list">
              {accounts.map(account => (
                <button key={account.username} type="button" role="listitem" className="ny-si-account" onClick={() => choose(account.username)}>
                  <NxAvatar username={account.username} name={account.displayName} />
                  <span className="ny-si-account-text">
                    <strong>{account.displayName || account.username}</strong>
                    <span>{account.username}</span>
                  </span>
                  <ArrowRight size={16} className="ny-si-account-go" />
                </button>
              ))}
              <button type="button" className="ny-si-account is-other" onClick={other}>
                <span className="ny-avatar is-blank" aria-hidden="true"><UserRound size={18} /></span>
                <span className="ny-si-account-text"><strong>Another account</strong><span>Type a username</span></span>
              </button>
            </div>
          ) : (
            <form onSubmit={submit} noValidate>
              {step === "password" ? (
                <div className="ny-si-who">
                  <NxAvatar username={chosen.username} name={chosen.displayName} size={44} />
                  <span className="ny-si-account-text">
                    <strong>{chosen.displayName || chosen.username}</strong>
                    <span>{chosen.username}</span>
                  </span>
                  {accounts.length > 1 ? (
                    <button type="button" className="ny-si-link" onClick={back}><ArrowLeft size={14} /> Switch</button>
                  ) : null}
                </div>
              ) : (
                <label className="ny-si-field">
                  <span>Username</span>
                  <input ref={userRef} autoComplete="username" autoCapitalize="none" spellCheck={false}
                    value={username} onChange={event => setUsername(event.target.value)} />
                </label>
              )}
              {step === "password" ? <input type="hidden" autoComplete="username" value={username} readOnly /> : null}
              <label className="ny-si-field">
                <span>Password</span>
                <span className="ny-si-password">
                  <input ref={passwordRef} type={reveal ? "text" : "password"} autoComplete="current-password"
                    value={password} onChange={event => setPassword(event.target.value)} onKeyDown={onKey} onKeyUp={onKey}
                    aria-invalid={Boolean(error)} aria-describedby={error ? "ny-si-error" : undefined} />
                  <button type="button" className="ny-si-reveal" onClick={() => setReveal(!reveal)}
                    aria-label={reveal ? "Hide password" : "Show password"} aria-pressed={reveal}>
                    {reveal ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>
              {caps ? <p className="ny-si-hint">Caps Lock is on.</p> : null}
              {error ? <p className="ny-si-error" id="ny-si-error" role="alert">{error}</p> : null}
              <button type="submit" className="ny-si-primary" disabled={busy || !username.trim() || !password}>
                {busy ? <span className="ny-si-spin" aria-hidden="true" /> : null}
                {busy ? "Signing in…" : "Sign in"}
              </button>
              {step === "other" && accounts.length ? (
                <button type="button" className="ny-si-link is-center" onClick={back}><ArrowLeft size={14} /> Back to accounts</button>
              ) : null}
            </form>
          )}
        </div>

        <details className="ny-si-help">
          <summary>Can't sign in?</summary>
          <p>Ask the PC owner: they can give you a new password in <strong>Accounts</strong>. If you are the owner, open Neyvia on the PC itself; it signs you in there without a password.</p>
        </details>
      </section>

      <footer className="ny-si-foot">Private to this PC. Only accounts created on it can sign in.</footer>
    </main>
  );
}
