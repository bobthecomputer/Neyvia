import React from "react";

import { NeyviaSignIn } from "./NeyviaSignIn.jsx";
import { NeyviaWelcome } from "./NeyviaWelcome.jsx";
import { neyviaBootMounted, neyviaBootReady } from "./neyviaBoot.js";
import "./neyviaRecovery.css";

// The workspace shell is the only thing a console or desktop visit shows, so
// its download starts with this module instead of after the session check.
// One shell for every console and desktop visit, including old saved URLs.
const NeyviaNextShell = React.lazy(() =>
  import("./next/NxShell.jsx").then(module => ({ default: module.NxShell })),
);

/** Screens with no conversation list to wait for reveal themselves at once. */
function BootReady({ children }: { children: React.ReactNode }) {
  React.useEffect(() => neyviaBootReady(), []);
  return <>{children}</>;
}

const PRODUCT_NAME = "Neyvia";
function hasTauriBackend() {
  return Boolean((globalThis as any).window?.__TAURI__ || (globalThis as any).window?.__TAURI_INTERNALS__);
}

function webBackendBaseUrl(): string {
  const configured =
    (import.meta as any).env?.VITE_FLUXIO_BACKEND_URL ||
    (globalThis as any).window?.__FLUXIO_BACKEND_URL__ ||
    "";
  return String(configured || "").trim().replace(/\/$/, "");
}

function isLocalBrowserOrigin(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const hostname = String(window.location.hostname || "").trim().toLowerCase();
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1";
}

function isConsolePath(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.location.pathname.startsWith("/control") || window.location.pathname.startsWith("/console");
}

function isDevControlPreview(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return Boolean(
    (import.meta as any).env?.DEV &&
      isConsolePath() &&
      new URLSearchParams(window.location.search).get("preview-control") === "1",
  );
}

// A phone reaching the PC through a relayed tailnet path needs several round
// trips before the first byte; 1.8 s reported a running backend as offline.
async function fetchWithTimeout(url: string, init: RequestInit = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

function SidebarProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

type BoundaryProps = {
  children: React.ReactNode;
  getLastAction: () => string;
  getBootDiagnostics: () => string[];
  onRecover: () => void;
};

type BoundaryState = {
  error: Error | null;
  capturedAt: string;
};

function hardReloadControl(reason: string) {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set("_neyvia_reload", `${Date.now()}`);
    url.searchParams.set("_neyvia_reason", reason);
    window.location.replace(url.toString());
  } catch {
    window.location.reload();
  }
}

class NeyviaErrorBoundary extends React.Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = {
    error: null,
    capturedAt: "",
  };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return {
      error,
      capturedAt: new Date().toISOString(),
    };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`${PRODUCT_NAME} UI crashed`, {
      error,
      info,
      lastAction: this.props.getLastAction(),
      capturedAt: new Date().toISOString(),
    });
  }

  handleRecover = () => {
    hardReloadControl("recover");
  };

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    neyviaBootReady();
    return (
      <main className="neyvia-recovery-screen">
        <section className="neyvia-recovery-panel">
          <p className="eyebrow">Recoverable UI error</p>
          <h1>{PRODUCT_NAME} hit a render failure.</h1>
          <p>
            <strong>Failing action:</strong> {this.props.getLastAction() || "Unknown action"}
          </p>
          <p>
            <strong>Error:</strong> {this.state.error.message || String(this.state.error)}
          </p>
          <p>
            <strong>Captured:</strong> {this.state.capturedAt || "Unknown"}
          </p>
          <details>
            <summary>Boot diagnostics</summary>
            <ul>
              {this.props.getBootDiagnostics().map(line => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
          <div className="neyvia-recovery-actions">
            <button className="action-btn primary" onClick={this.handleRecover} type="button">
              Recover UI
            </button>
            <button className="action-btn" onClick={() => hardReloadControl("reload")} type="button">
              Reload app
            </button>
          </div>
        </section>
      </main>
    );
  }
}

function makeBootDiagnostics(): string[] {
  return [
    `Boot timestamp: ${new Date().toISOString()}`,
    `Location: ${window.location.href}`,
    `User agent: ${window.navigator.userAgent}`,
  ];
}

type AuthState = {
  checked: boolean;
  authenticated: boolean;
  backendAvailable: boolean;
  productName: string;
  user: { username?: string; displayName?: string; role?: string } | null;
  accountHints: { username?: string; displayName?: string }[];
  error: string;
};

function NeyviaLogin({
  auth,
  onAuthenticated,
}: {
  auth: AuthState;
  onAuthenticated: (next: AuthState) => void;
}) {
  const signIn = React.useCallback(async (username: string, password: string) => {
    let response: Response;
    try {
      response = await fetch(`${webBackendBaseUrl()}/api/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
    } catch {
      throw new Error("Neyvia's PC service can't be reached. Check the PC is on and try again.");
    }
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) throw new Error("That username and password don't match.");
    if (!response.ok || payload?.ok === false) throw new Error(payload?.error || "Signing in failed. Try again.");
    onAuthenticated({
      checked: true,
      authenticated: true,
      backendAvailable: true,
      productName: payload?.data?.productName || PRODUCT_NAME,
      user: payload?.data?.user || { username, role: "account" },
      accountHints: auth.accountHints,
      error: "",
    });
  }, [auth.accountHints, onAuthenticated]);
  return (
    <NeyviaSignIn
      accountHints={auth.accountHints}
      offline={auth.backendAvailable ? "" : auth.error}
      onSignIn={signIn}
    />
  );
}

export function NeyviaApp() {
  const devControlPreview = isDevControlPreview();
  const consolePath = isConsolePath();
  const [instanceKey, setInstanceKey] = React.useState(0);
  const [auth, setAuth] = React.useState<AuthState>({
    checked: hasTauriBackend() || devControlPreview || !consolePath,
    authenticated: hasTauriBackend() || devControlPreview,
    backendAvailable: hasTauriBackend() || devControlPreview,
    productName: PRODUCT_NAME,
    user: devControlPreview ? { username: "preview", displayName: "Preview", role: "account" } : null,
    accountHints: devControlPreview ? [{ username: "preview", displayName: "Preview" }] : [],
    error: "",
  });
  const lastActionRef = React.useRef("boot:initialize");
  const bootDiagnosticsRef = React.useRef<string[]>(makeBootDiagnostics());


  React.useEffect(() => {
    const handleWindowError = (event: ErrorEvent) => {
      lastActionRef.current = `window:error:${event.message || "unknown"}`;
    };
    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      const reason =
        event.reason instanceof Error ? event.reason.message : String(event.reason || "unknown");
      lastActionRef.current = `window:unhandled_rejection:${reason}`;
    };

    window.addEventListener("error", handleWindowError);
    window.addEventListener("unhandledrejection", handleUnhandledRejection);
    return () => {
      window.removeEventListener("error", handleWindowError);
      window.removeEventListener("unhandledrejection", handleUnhandledRejection);
    };
  }, []);

  React.useEffect(() => {
    if (hasTauriBackend() || devControlPreview || !consolePath) {
      return;
    }
    let cancelled = false;
    const checkAuth = async () => {
      try {
        const response = await fetchWithTimeout(`${webBackendBaseUrl()}/api/auth/status`, {
          credentials: "include",
        });
        let payload = await response.json().catch(() => ({}));
        let backendAvailable = response.ok;
        if (
          response.ok &&
          !payload?.data?.authenticated &&
          isLocalBrowserOrigin()
        ) {
          const localSessionResponse = await fetchWithTimeout(
            `${webBackendBaseUrl()}/api/auth/local-session`,
            {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: "{}",
            },
          );
          const localSessionPayload = await localSessionResponse.json().catch(() => ({}));
          backendAvailable = backendAvailable || localSessionResponse.ok;
          if (localSessionResponse.ok && localSessionPayload?.data?.authenticated) {
            payload = localSessionPayload;
          }
        }
        if (cancelled) {
          return;
        }
        setAuth({
          checked: true,
          authenticated: Boolean(payload?.data?.authenticated),
          backendAvailable,
          productName: payload?.data?.productName || PRODUCT_NAME,
          user: payload?.data?.user || null,
          accountHints: Array.isArray(payload?.data?.accountHints) ? payload.data.accountHints : [],
          error: "",
        });
      } catch {
        if (cancelled) {
          return;
        }
        setAuth({
          checked: true,
          authenticated: false,
          backendAvailable: false,
          productName: PRODUCT_NAME,
          user: null,
          accountHints: [],
          error: "Local backend is offline. Start `npm run web:backend` on the NAS or workstation.",
        });
      }
    };
    void checkAuth();
    return () => {
      cancelled = true;
    };
  }, [consolePath, devControlPreview]);

  const recoverShell = React.useCallback(() => {
    lastActionRef.current = "recover:manual";
    setInstanceKey(current => current + 1);
  }, []);

  React.useEffect(() => {
    neyviaBootMounted();
  }, []);

  if (!consolePath && !hasTauriBackend()) {
    return <BootReady><NeyviaWelcome /></BootReady>;
  }

  // The startup splash stays over the page while the session is checked.
  if (!auth.checked) {
    return null;
  }

  if (!auth.backendAvailable && !isConsolePath()) {
    return <BootReady><NeyviaWelcome /></BootReady>;
  }

  if (!auth.authenticated) {
    return <BootReady><NeyviaLogin auth={auth} onAuthenticated={setAuth} /></BootReady>;
  }

  return (
    <SidebarProvider>
      <NeyviaErrorBoundary
        getBootDiagnostics={() => bootDiagnosticsRef.current}
        getLastAction={() => lastActionRef.current}
        onRecover={recoverShell}
      >
        {/* The startup splash covers the shell download. */}
        <React.Suspense fallback={null}>
          <BootReady><NeyviaNextShell key={instanceKey} /></BootReady>
        </React.Suspense>
      </NeyviaErrorBoundary>
    </SidebarProvider>
  );
}
