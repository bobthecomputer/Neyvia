import { Suspense, lazy } from "react";

import { isDesktopApp } from "./nxApi.js";
import { usePip } from "./nxBrowserApi.js";

// Picture in picture for a browser tab, shell-wide (desktop app only: the page
// is a native view). The frame and the browser code load only once a tab floats.
const Frame = lazy(() => import("./NxBrowser.jsx").then(module => ({ default: module.PipFrame })));

export function NxBrowserPip() {
  const pip = usePip();
  if (!isDesktopApp() || !pip) return null;
  return <Suspense fallback={null}><Frame pip={pip} /></Suspense>;
}
