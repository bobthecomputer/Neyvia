import React from "react";
import { createRoot } from "react-dom/client";
import { neyviaStorage } from "./neyvia/neyviaStorage.js";

import "./neyvia/neyviaFonts.css";
import { NeyviaApp } from "./neyvia/NeyviaApp";
import { registerNeyviaPwa } from "./pwa";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Neyvia web root element is missing.");
}

void neyviaStorage.initialize().then(storage => createRoot(rootElement).render(
  <React.StrictMode>
    {!storage.available ? <aside className="neyvia-storage-warning" role="alert">Large local saves are unavailable. Saved data has been kept. Keep this window open until server sync completes, then reload to retry.</aside> : null}
    <NeyviaApp />
  </React.StrictMode>,
));

void registerNeyviaPwa();
