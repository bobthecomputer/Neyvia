import { useCallback, useEffect, useRef, useState } from "react";
import { NeyviaClaudeSubscription } from "./NeyviaClaudeSubscription.jsx";
import {
  ArrowRight,
  Check,
  CircleDashed,
  ExternalLink,
  KeyRound,
  Link2,
  ShieldAlert,
  X,
} from "lucide-react";

const PROVIDERS = Object.freeze([
  { id: "openai-codex", label: "OpenAI / Codex", checked: true },
  { id: "openrouter", label: "OpenRouter", checked: true },
  { id: "minimax-portal", label: "MiniMax", checked: true },
  { id: "anthropic", label: "Anthropic / Claude", checked: true },
  { id: "hermes-anthropic", label: "Hermes / Claude extra credits", checked: false },
]);

function list(value) {
  return Array.isArray(value) ? value : [];
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error || "Unknown connection error");
}

function flowUrl(state) {
  const flow = state?.nextAction?.flow || {};
  return String(flow.authUrl || flow.verificationUrl || "").trim();
}

function stateIcon(state) {
  if (state === "connected") return Check;
  if (state === "skipped" || state === "cancelled") return X;
  return CircleDashed;
}

export function NeyviaProviderAuthQueue({ callBackend }) {
  const [selected, setSelected] = useState(() =>
    Object.fromEntries(PROVIDERS.map(provider => [provider.id, provider.checked])),
  );
  const [queue, setQueue] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const authWindowRef = useRef(null);
  const activeProviderRef = useRef("");

  const routeAuthWindow = useCallback(state => {
    const url = flowUrl(state);
    if (!url) return false;
    try {
      const popup = authWindowRef.current && !authWindowRef.current.closed
        ? authWindowRef.current
        : window.open("about:blank", "neyvia-provider-auth", "popup,width=980,height=760");
      if (!popup) {
        setNotice("Your browser blocked the connection window. Use “Open connection” below.");
        return false;
      }
      authWindowRef.current = popup;
      if (popup.location.href !== url) popup.location.replace(url);
      popup.focus();
      return true;
    } catch {
      setNotice("Use “Open connection” below to continue in the provider tab.");
      return false;
    }
  }, []);

  const refresh = useCallback(async () => {
    if (typeof callBackend !== "function") return;
    try {
      const state = await callBackend("advance_provider_auth_queue_command", {
        callbackBaseUrl: window.location.origin,
      });
      setQueue(state || null);
      const active = String(state?.activeProviderId || "");
      if (active && active !== activeProviderRef.current) {
        activeProviderRef.current = active;
        routeAuthWindow(state);
      }
      if (!active) activeProviderRef.current = "";
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }, [callBackend, routeAuthWindow]);

  useEffect(() => {
    if (typeof callBackend !== "function") return undefined;
    void callBackend("get_provider_auth_queue_command", {
      callbackBaseUrl: window.location.origin,
    })
      .then(value => {
        setQueue(value || null);
        activeProviderRef.current = String(value?.activeProviderId || "");
      })
      .catch(() => {});
    return undefined;
  }, [callBackend]);

  useEffect(() => {
    if (queue?.status !== "running") return undefined;
    const timer = window.setInterval(() => void refresh(), 1600);
    return () => window.clearInterval(timer);
  }, [queue?.status, refresh]);

  async function startQueue() {
    const providerIds = PROVIDERS.filter(provider => selected[provider.id]).map(
      provider => provider.id,
    );
    if (!providerIds.length || busy) return;
    setBusy(true);
    setNotice("");
    try {
      authWindowRef.current = window.open(
        "about:blank",
        "neyvia-provider-auth",
        "popup,width=980,height=760",
      );
      const state = await callBackend("start_provider_auth_queue_command", {
        providerIds,
        callbackBaseUrl: window.location.origin,
      });
      setQueue(state);
      activeProviderRef.current = String(state?.activeProviderId || "");
      if (!routeAuthWindow(state) && authWindowRef.current && !authWindowRef.current.closed) {
        authWindowRef.current.close();
      }
      setNotice(
        state?.status === "completed"
          ? "Those providers were already connected."
          : "The first provider is ready. Neyvia will detect completion and move to the next.",
      );
    } catch (error) {
      setNotice(errorMessage(error));
      if (authWindowRef.current && !authWindowRef.current.closed) authWindowRef.current.close();
    } finally {
      setBusy(false);
    }
  }

  async function skipActive() {
    const providerId = String(queue?.activeProviderId || "");
    if (!providerId) return;
    try {
      const state = await callBackend("skip_provider_auth_queue_item_command", {
        providerId,
        callbackBaseUrl: window.location.origin,
      });
      setQueue(state);
      activeProviderRef.current = String(state?.activeProviderId || "");
      routeAuthWindow(state);
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }

  async function cancelQueue() {
    try {
      const state = await callBackend("cancel_provider_auth_queue_command", {});
      setQueue(state);
      activeProviderRef.current = "";
      if (authWindowRef.current && !authWindowRef.current.closed) authWindowRef.current.close();
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }

  const activeFlow = queue?.nextAction?.flow || {};

  return (
    <><NeyviaClaudeSubscription callBackend={callBackend} /><section className="neyvia-provider-auth" data-provider-auth-queue={queue?.status || "idle"}>
      <header>
        <div>
          <span><KeyRound size={14} /> Provider connection</span>
          <strong>Connect once, in order</strong>
        </div>
        <em>{queue?.status || "idle"}</em>
      </header>

      <p>
        Neyvia opens one provider at a time, detects the completed connection, and
        continues in the same window. API keys stay a separate setup path.
      </p>

      <div className="neyvia-provider-auth__choices">
        {PROVIDERS.map(provider => (
          <label key={provider.id}>
            <input
              checked={Boolean(selected[provider.id])}
              disabled={queue?.status === "running"}
              onChange={event =>
                setSelected(current => ({ ...current, [provider.id]: event.target.checked }))
              }
              type="checkbox"
            />
            <span>{provider.label}</span>
          </label>
        ))}
      </div>

      <p>Hermes / Claude Max uses purchased extra-usage credits, not the included Max allowance. Claude Pro is not supported by this Hermes route. Sign-in opens on the Neyvia host.</p>

      {list(queue?.items).length ? (
        <ol className="neyvia-provider-auth__steps">
          {list(queue.items).map(item => {
            const Icon = stateIcon(item.state);
            return (
              <li data-state={item.state} key={item.providerId}>
                <Icon size={15} />
                <div>
                  <strong>{item.label}</strong>
                  <small>{item.message}</small>
                  {item.state === "active" && list(item.consumers).length ? (
                    <span>
                      <Link2 size={12} />
                      {list(item.consumers).map(consumer => consumer.id).join(" · ")}
                    </span>
                  ) : null}
                  {item.warning ? (
                    <span className="warning"><ShieldAlert size={12} />{item.warning}</span>
                  ) : null}
                  {item.state === "active" && item.flow?.command ? (
                    <code>{item.flow.command}</code>
                  ) : null}
                </div>
                {item.state === "active" ? <ArrowRight size={15} /> : null}
              </li>
            );
          })}
        </ol>
      ) : null}

      {queue?.activeProviderId ? (
        <div className="neyvia-provider-auth__active">
          <strong>{queue.nextAction?.label}</strong>
          <p>{activeFlow.message || "Complete this provider before Neyvia starts the next one."}</p>
          {activeFlow.userCode ? <code>{activeFlow.userCode}</code> : null}
          <div>
            {flowUrl(queue) ? (
              <button onClick={() => routeAuthWindow(queue)} type="button">
                <ExternalLink size={14} /> Open connection
              </button>
            ) : null}
            <button className="secondary" onClick={() => void skipActive()} type="button">
              Skip
            </button>
          </div>
        </div>
      ) : null}

      <div className="neyvia-provider-auth__actions">
        <button
          className="primary"
          disabled={busy || queue?.status === "running"}
          onClick={() => void startQueue()}
          type="button"
        >
          <KeyRound size={14} /> {busy ? "Preparing…" : "Connect selected providers"}
        </button>
        {queue?.status === "running" ? (
          <button className="secondary" onClick={() => void cancelQueue()} type="button">
            Cancel queue
          </button>
        ) : null}
      </div>
      {notice ? <small className="neyvia-provider-auth__notice">{notice}</small> : null}
    </section></>
  );
}

export default NeyviaProviderAuthQueue;
