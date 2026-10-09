import { WifiOff } from "lucide-react";

import { Button, Icon } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";
import { PaneRefused } from "./NxPaneObserver.jsx";
import { blockedByLocalOnly, useLocalOnly } from "./nxSettingsApi.js";

// Local-only (T11) in the interface: a page on the internet is not loaded
// while it is on, so this screen never reaches out on its own either.

export function LocalOnlyGate({ url, children }) {
  const localOnly = useLocalOnly();
  if (!blockedByLocalOnly(url, localOnly)) return children;
  return (
    <div className="nx-pane-honest" role="status">
      <PaneRefused reason="Local-only is on, so this internet page is not opened" />
      <Icon as={WifiOff} size={22} />
      <strong>Local-only is on</strong>
      <p>This page is on the internet, so Neyvia doesn't open it. Turn local-only off in Settings to see it.</p>
      <Button size="sm" variant="outline" onClick={() => os.showPane("settings", "privacy")}>Open Settings</Button>
    </div>
  );
}
