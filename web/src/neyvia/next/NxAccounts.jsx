import { useCallback, useEffect, useState } from "react";
import {
  AppWindow, Check, Copy, Eye, EyeOff, KeyRound, LogOut, Monitor, Pencil, RefreshCw, Smartphone, Tablet, Trash2, UserPlus, X,
} from "lucide-react";

import "./nxAccounts.css";
import { NxAvatar } from "./NxAvatar.jsx";
import { Button, Icon, Spinner } from "./nxPrimitives.jsx";
import { callNx, isDesktopApp, signOutHere } from "./nxApi.js";
import { os } from "./nxOsStore.js";
import { OtherPcsCard } from "./NxOtherPcs.jsx";
import {
  PASSWORD_MIN, STRENGTH_LABELS, deviceKind, generatePassword, lastSeen, newAccountProblem, passwordStrength,
} from "./nxAccountsModel.js";

// Accounts (the "accounts" stage pane): your name, password and signed-in
// devices; for the PC owner, everyone who can sign in to this PC's Neyvia.

const DEVICE_ICONS = { phone: Smartphone, tablet: Tablet, app: AppWindow, computer: Monitor };

function useAccounts() {
  const [state, setState] = useState({ status: "loading", data: null, error: "" });
  const refresh = useCallback(async () => {
    try {
      setState({ status: "ready", data: await callNx("accounts_list_command"), error: "" });
    } catch (failure) {
      setState(current => ({ ...current, status: current.data ? "ready" : "error", error: failure.message }));
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  /** Runs one change; resolves to true when it worked, and keeps the screen's data current. */
  const change = useCallback(async (op, payload = {}) => {
    const data = await callNx("accounts_update_command", { op, ...payload });
    setState({ status: "ready", data, error: "" });
    return data;
  }, []);
  return { ...state, refresh, change };
}

/** Run a change with a busy flag and an inline error. */
function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (work, done) => {
    setBusy(true);
    setError("");
    try {
      const result = await work();
      done?.(result);
      return true;
    } catch (failure) {
      setError(failure?.message || "That didn't work.");
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, run };
}

function RoleBadge({ role }) {
  return <span className={`nx-ac-role is-${role}`}>{role === "owner" ? "Owner" : "Member"}</span>;
}

function PasswordInput({ value, onChange, autoComplete = "new-password", label, autoFocus = false }) {
  const [reveal, setReveal] = useState(false);
  return (
    <label className="nx-ac-field">
      <span>{label}</span>
      <span className="nx-ac-password">
        <input type={reveal ? "text" : "password"} value={value} autoComplete={autoComplete} autoFocus={autoFocus}
          spellCheck={false} onChange={event => onChange(event.target.value)} />
        <button type="button" onClick={() => setReveal(!reveal)} aria-label={reveal ? "Hide password" : "Show password"}>
          <Icon as={reveal ? EyeOff : Eye} size={15} />
        </button>
      </span>
    </label>
  );
}

function Strength({ password }) {
  if (!password) return null;
  const level = passwordStrength(password);
  return (
    <span className={`nx-ac-strength is-${level}`}>
      <span className="nx-ac-strength-bar"><span style={{ transform: `scaleX(${(level + 1) / 4})` }} /></span>
      {STRENGTH_LABELS[level]}
    </span>
  );
}

function CopyText({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* it stays visible */ }
  };
  return (
    <button type="button" className="nx-ac-copy" onClick={() => void copy()} title="Copy">
      <code>{text}</code><Icon as={copied ? Check : Copy} size={13} />
    </button>
  );
}

function YouCard({ you, managed, change }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(you.displayName);
  const [changing, setChanging] = useState(false);
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const action = useAction();
  const local = managed === "local";
  const desktop = isDesktopApp();

  const saveName = () => action.run(() => change("profile", { displayName: name }), () => setEditing(false));
  const mismatch = form.confirm && form.next !== form.confirm;
  const savePassword = event => {
    event.preventDefault();
    if (form.next.length < PASSWORD_MIN || mismatch || !form.current) return;
    void action.run(() => change("password", { currentPassword: form.current, newPassword: form.next }), () => {
      setChanging(false);
      setForm({ current: "", next: "", confirm: "" });
      os.notify({ level: "success", message: "Password changed. Your other devices were signed out." });
    });
  };

  return (
    <section className="nx-ac-card nx-ac-you">
      <div className="nx-ac-you-head">
        <NxAvatar username={you.username} name={you.displayName} size={58} />
        <div className="nx-ac-you-name">
          {editing ? (
            <form className="nx-ac-inline" onSubmit={event => { event.preventDefault(); void saveName(); }}>
              <input value={name} maxLength={60} autoFocus onChange={event => setName(event.target.value)} aria-label="Your name" />
              <Button variant="primary" size="sm" type="submit" disabled={action.busy}>Save</Button>
              <Button size="sm" onClick={() => { setEditing(false); setName(you.displayName); action.setError(""); }}>Cancel</Button>
            </form>
          ) : (
            <h2>
              {you.displayName}
              {local ? <button type="button" className="nx-ac-edit" onClick={() => setEditing(true)} aria-label="Change your name"><Icon as={Pencil} size={13} /></button> : null}
            </h2>
          )}
          <p>{you.username} <RoleBadge role={you.role} /></p>
        </div>
        {desktop ? null : <Button variant="outline" size="sm" icon={LogOut} onClick={() => void signOutHere()}>Sign out</Button>}
      </div>

      {local ? (
        changing ? (
          <form className="nx-ac-form" onSubmit={savePassword}>
            <PasswordInput label="Current password" value={form.current} autoComplete="current-password" autoFocus
              onChange={current => setForm({ ...form, current })} />
            <PasswordInput label="New password" value={form.next} onChange={next => setForm({ ...form, next })} />
            <Strength password={form.next} />
            <PasswordInput label="New password again" value={form.confirm} onChange={confirm => setForm({ ...form, confirm })} />
            {mismatch ? <p className="nx-ac-error">The two new passwords don't match.</p> : null}
            <p className="nx-ac-note">This device stays signed in. Every other device signs in again with the new password.</p>
            <div className="nx-ac-actions">
              <Button variant="primary" type="submit" disabled={action.busy || !form.current || form.next.length < PASSWORD_MIN || form.next !== form.confirm}>
                {action.busy ? <Spinner /> : null} Change password
              </Button>
              <Button onClick={() => { setChanging(false); action.setError(""); }}>Cancel</Button>
            </div>
          </form>
        ) : (
          <div className="nx-ac-row-actions">
            <Button variant="outline" size="sm" icon={KeyRound} onClick={() => setChanging(true)}>Change password</Button>
          </div>
        )
      ) : (
        <p className="nx-ac-note">This PC's account is set by its environment, so the name and password are changed there.</p>
      )}
      {action.error ? <p className="nx-ac-error" role="alert">{action.error}</p> : null}
    </section>
  );
}

function Devices({ sessions, change }) {
  const action = useAction();
  const others = sessions.filter(row => !row.current);
  const signOut = row => action.run(() => change("signOut", { sessionId: row.id }));
  return (
    <section className="nx-ac-card">
      <header className="nx-ac-head">
        <div>
          <h3>Signed in on</h3>
          <p>Every browser and phone with your account. Sign out any you don't recognise.</p>
        </div>
        {others.length ? (
          <Button variant="outline" size="sm" disabled={action.busy}
            onClick={() => void action.run(() => change("signOutOthers"), result => os.notify({ level: "success", message: `Signed out of ${result.ended} other ${result.ended === 1 ? "device" : "devices"}.` }))}>
            Sign out everywhere else
          </Button>
        ) : null}
      </header>
      {sessions.length ? (
        <ul className="nx-ac-list">
          {sessions.map(row => (
            <li key={row.id} className="nx-ac-device">
              <span className="nx-ac-device-icon"><Icon as={DEVICE_ICONS[deviceKind(row.device)]} size={17} /></span>
              <span className="nx-ac-device-text">
                <strong>{row.device}{row.current ? <span className="nx-ac-here">This device</span> : null}</strong>
                <span>{[lastSeen(row.lastSeenAt), row.address].filter(Boolean).join(" · ")}</span>
              </span>
              {row.current ? null : (
                <Button size="sm" disabled={action.busy} onClick={() => void signOut(row)}>Sign out</Button>
              )}
            </li>
          ))}
        </ul>
      ) : <p className="nx-ac-note">Only the desktop app is using this account right now.</p>}
      {action.error ? <p className="nx-ac-error" role="alert">{action.error}</p> : null}
    </section>
  );
}

function AddPerson({ taken, change, onDone }) {
  const [form, setForm] = useState({ displayName: "", username: "", password: generatePassword() });
  const [touchedName, setTouchedName] = useState(false);
  const action = useAction();
  const problem = newAccountProblem(form, taken);
  const setDisplay = displayName => setForm(current => ({
    ...current,
    displayName,
    username: touchedName ? current.username : displayName.trim().toLowerCase().replace(/\s+/g, ".").replace(/[^a-z0-9._-]/g, "").slice(0, 32),
  }));
  const submit = event => {
    event.preventDefault();
    if (problem) { action.setError(problem); return; }
    void action.run(() => change("create", form), () => onDone(form));
  };
  return (
    <form className="nx-ac-form nx-ac-add" onSubmit={submit}>
      <div className="nx-ac-grid">
        <label className="nx-ac-field"><span>Name</span>
          <input value={form.displayName} maxLength={60} autoFocus placeholder="Maya Rivera" onChange={event => setDisplay(event.target.value)} />
        </label>
        <label className="nx-ac-field"><span>Username</span>
          <input value={form.username} maxLength={32} autoCapitalize="none" spellCheck={false} placeholder="maya"
            onChange={event => { setTouchedName(true); setForm({ ...form, username: event.target.value }); }} />
        </label>
      </div>
      <PasswordInput label="Password" value={form.password} onChange={password => setForm({ ...form, password })} />
      <div className="nx-ac-row-actions">
        <Strength password={form.password} />
        <Button size="sm" icon={RefreshCw} onClick={() => setForm({ ...form, password: generatePassword() })}>New suggestion</Button>
      </div>
      <p className="nx-ac-note">
        Members can read chats and projects from any device. Only you can run agents or change files on this PC.
      </p>
      {action.error ? <p className="nx-ac-error" role="alert">{action.error}</p> : null}
      <div className="nx-ac-actions">
        <Button variant="primary" type="submit" disabled={action.busy}>{action.busy ? <Spinner /> : null} Add account</Button>
        <Button onClick={() => onDone(null)}>Cancel</Button>
      </div>
    </form>
  );
}

function Person({ person, change }) {
  const [mode, setMode] = useState("");
  const [password, setPassword] = useState("");
  const action = useAction();
  const name = person.displayName || person.username;
  const reset = () => {
    const next = generatePassword();
    setPassword(next);
    setMode("reset");
  };
  return (
    <li className="nx-ac-person">
      <div className="nx-ac-person-row">
        <NxAvatar username={person.username} name={name} size={38} />
        <span className="nx-ac-device-text">
          <strong>{name}{person.isYou ? <span className="nx-ac-here">You</span> : null}</strong>
          <span>
            {person.username} · {person.devices ? `${person.devices} ${person.devices === 1 ? "device" : "devices"}, ${lastSeen(person.lastSeenAt)}` : "not signed in anywhere"}
          </span>
        </span>
        <RoleBadge role={person.role} />
        {person.isYou ? null : (
          <span className="nx-ac-person-tools">
            <Button size="sm" icon={KeyRound} onClick={reset} aria-label={`Reset ${name}'s password`}>Reset</Button>
            {person.devices ? (
              <Button size="sm" icon={LogOut} disabled={action.busy} aria-label={`Sign ${name} out everywhere`}
                onClick={() => void action.run(() => change("signOutAll", { username: person.username }), () => os.notify({ level: "success", message: `${name} was signed out everywhere.` }))} />
            ) : null}
            <Button size="sm" icon={Trash2} onClick={() => setMode("remove")} aria-label={`Remove ${name}`} />
          </span>
        )}
      </div>
      {mode === "reset" ? (
        <div className="nx-ac-confirm">
          <p>Give {name} this new password. They'll be signed out everywhere and sign in again with it.</p>
          <div className="nx-ac-row-actions">
            <CopyText text={password} />
            <Button size="sm" icon={RefreshCw} onClick={() => setPassword(generatePassword())}>Another</Button>
          </div>
          <div className="nx-ac-actions">
            <Button variant="primary" size="sm" disabled={action.busy}
              onClick={() => void action.run(() => change("reset", { username: person.username, newPassword: password }), () => { setMode(""); os.notify({ level: "success", message: `${name}'s password was reset.` }); })}>
              Set this password
            </Button>
            <Button size="sm" onClick={() => setMode("")}>Cancel</Button>
          </div>
        </div>
      ) : null}
      {mode === "remove" ? (
        <div className="nx-ac-confirm is-danger">
          <p>Remove {name}? They'll be signed out everywhere and can't sign in again. Their chats stay on this PC.</p>
          <div className="nx-ac-actions">
            <Button variant="warn" size="sm" icon={Trash2} disabled={action.busy}
              onClick={() => void action.run(() => change("remove", { username: person.username }), () => os.notify({ level: "info", message: `${name} was removed.` }))}>
              Remove {name}
            </Button>
            <Button size="sm" onClick={() => setMode("")}>Keep</Button>
          </div>
        </div>
      ) : null}
      {action.error ? <p className="nx-ac-error" role="alert">{action.error}</p> : null}
    </li>
  );
}

function People({ people, managed, change }) {
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(null);
  return (
    <section className="nx-ac-card">
      <header className="nx-ac-head">
        <div>
          <h3>People on this PC</h3>
          <p>Everyone who can sign in to Neyvia here, from the PC or over your private network.</p>
        </div>
        {managed === "local" && !adding ? <Button variant="primary" size="sm" icon={UserPlus} onClick={() => { setAdding(true); setAdded(null); }}>Add someone</Button> : null}
      </header>
      {added ? (
        <div className="nx-ac-confirm is-success">
          <p><strong>{added.displayName || added.username}</strong> can now sign in as <strong>{added.username}</strong> with this password:</p>
          <div className="nx-ac-row-actions"><CopyText text={added.password} />
            <Button size="sm" icon={X} onClick={() => setAdded(null)} aria-label="Hide the password" />
          </div>
        </div>
      ) : null}
      {adding ? (
        <AddPerson taken={people.map(person => person.username)} change={change}
          onDone={result => { setAdding(false); setAdded(result); }} />
      ) : null}
      <ul className="nx-ac-list">
        {people.map(person => <Person key={person.username} person={person} change={change} />)}
      </ul>
    </section>
  );
}

export function NxAccounts({ target = "" } = {}) {
  const { status, data, error, refresh, change } = useAccounts();
  if (status === "loading") return <div className="nx-ac is-center"><Spinner size={16} /></div>;
  if (status === "error" || !data) {
    return (
      <div className="nx-ac is-center">
        <p className="nx-ac-note">{error || "Accounts can't be read right now."}</p>
        <Button variant="outline" size="sm" icon={RefreshCw} onClick={() => void refresh()}>Try again</Button>
      </div>
    );
  }
  return (
    <div className="nx-ac nx-scroll">
      <div className="nx-ac-inner">
        <YouCard key={data.you.username} you={data.you} managed={data.managed} change={change} />
        <Devices sessions={data.you.sessions || []} change={change} />
        {data.isOwner ? <OtherPcsCard focus={target === "other-pcs"} /> : null}
        {data.isOwner ? <People people={data.people || []} managed={data.managed} change={change} /> : (
          <p className="nx-ac-note is-quiet">The PC owner adds people and resets passwords.</p>
        )}
      </div>
    </div>
  );
}
