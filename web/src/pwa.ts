const FLUXIO_PWA_BUILD = "fluxio-pwa-v202-add-project-neutral-ui-proof-20260621";
const FLUXIO_PWA_UPDATE_INTERVAL_MS = 30 * 60 * 1000;
const FLUXIO_PWA_BUILD_KEY = "fluxio:pwa-build";

type PwaStatus = "checking" | "ready" | "updated" | "unsupported" | "failed";

function publishStatus(status: PwaStatus, detail: string) {
  document.documentElement.dataset.neyviaPwa = status;
  window.dispatchEvent(
    new CustomEvent("fluxio:pwa-status", {
      detail: { status, detail, build: FLUXIO_PWA_BUILD, checkedAt: new Date().toISOString() },
    }),
  );
}

function isTauriDesktop() {
  const desktopWindow = window as Window & { __TAURI_INTERNALS__?: unknown };
  return Boolean(
    desktopWindow.__TAURI_INTERNALS__
      || window.location.protocol === "tauri:"
      || window.location.hostname === "tauri.localhost",
  );
}

async function removeDesktopServiceWorkers() {
  if (!("serviceWorker" in navigator)) return;
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(registrations.map(registration => registration.unregister()));
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith("fluxio-pwa-")).map(key => caches.delete(key)));
  }
}

async function activateWaitingWorker(registration: ServiceWorkerRegistration) {
  if (!registration.waiting) return;
  registration.waiting.postMessage({ type: "SKIP_WAITING" });
}

export async function registerNeyviaPwa() {
  // The Tauri webview owns its app shell and native command bridge. Registering
  // the website's navigation-fallback worker there can replace a later desktop
  // launch with offline.html before the native UI has a chance to boot.
  if (isTauriDesktop()) {
    await removeDesktopServiceWorkers().catch(() => undefined);
    publishStatus("unsupported", "Website caching is disabled inside the Neyvia desktop app.");
    return null;
  }
  if (import.meta.env.DEV) {
    // An earlier production visit can leave a cache-first worker controlling
    // /src imports. Merely skipping registration keeps serving that old UI.
    await removeDesktopServiceWorkers().catch(() => undefined);
    publishStatus("unsupported", "Service worker registration is disabled in development.");
    return null;
  }
  if (!("serviceWorker" in navigator)) {
    publishStatus("unsupported", "This browser does not support installable app updates.");
    return null;
  }

  publishStatus("checking", "Checking the Neyvia app shell.");
  try {
    let hadController = Boolean(navigator.serviceWorker.controller);
    const previousBuild = window.localStorage.getItem(FLUXIO_PWA_BUILD_KEY) || "";
    const buildChanged = previousBuild !== FLUXIO_PWA_BUILD;
    const registration = await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });

    if (buildChanged && navigator.serviceWorker.controller) {
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.filter(key => key.startsWith("fluxio-pwa-")).map(key => caches.delete(key)));
      }
      navigator.serviceWorker.controller.postMessage({ type: "PURGE_FLUXIO_CACHES" });
    }
    window.localStorage.setItem(FLUXIO_PWA_BUILD_KEY, FLUXIO_PWA_BUILD);

    registration.addEventListener("updatefound", () => {
      const installing = registration.installing;
      if (!installing) return;
      installing.addEventListener("statechange", () => {
        if (installing.state === "installed" && navigator.serviceWorker.controller) {
          publishStatus("updated", "A Neyvia app update is ready.");
          void activateWaitingWorker(registration);
        }
      });
    });

    let reloading = false;
    hadController ||= Boolean(navigator.serviceWorker.controller);
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      // First installation can claim this page during a user action. It does
      // not replace the loaded build and must not reload away that action.
      if (!hadController) {
        hadController = true;
        return;
      }
      if (reloading) return;
      reloading = true;
      window.location.reload();
    });

    const checkForUpdate = () => {
      if (document.visibilityState === "visible") {
        void registration.update().catch(() => undefined);
      }
    };
    const updateTimer = window.setInterval(checkForUpdate, FLUXIO_PWA_UPDATE_INTERVAL_MS);
    document.addEventListener("visibilitychange", checkForUpdate);
    window.addEventListener("pagehide", () => {
      window.clearInterval(updateTimer);
      document.removeEventListener("visibilitychange", checkForUpdate);
    }, { once: true });

    publishStatus("ready", "Neyvia is ready for installed use.");
    return registration;
  } catch (error) {
    publishStatus("failed", String(error instanceof Error ? error.message : error));
    return null;
  }
}
