import { useCallback, useEffect, useRef, useState } from "react";
import { callNx } from "./nxApi.js";
import { local } from "./nxPrimitives.jsx";
import { newRequestId, isDone } from "./nxGameDevModel.js";
const LOG_KEY = "gamedev.log";
const CLEARED_KEY = "gamedev.log.cleared";
/** Every action from this screen and its receipt, newest first, per session. */
export function useReceipts() {
  const [log, setLog] = useState(() => local.get(LOG_KEY, {}));
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const put = useCallback((receipt) => {
    const created = receipt.createdEpoch || Date.parse(receipt.createdAt) / 1000;
    if (created <= (local.get(CLEARED_KEY, {})[receipt.sessionId] || 0)) return;
    setLog(current => {
      const rows = current[receipt.sessionId] || [];
      const index = rows.findIndex(row => row.requestId === receipt.requestId);
      const nextRows = index >= 0 ? rows.map((row, at) => (at === index ? { ...row, ...receipt } : row)) : [receipt, ...rows].slice(0, 40);
      const next = { ...current, [receipt.sessionId]: nextRows };
      local.set(LOG_KEY, next);
      return next;
    });
  }, []);

  /** Queue an action and follow its receipt until the editor answers. Resolves with the final receipt. */
  const send = useCallback(async (session, action, args = {}) => {
    const requestId = newRequestId();
    const draft = { requestId, sessionId: session.sessionId, action, args, status: "sending", createdAt: new Date().toISOString() };
    put(draft);
    let receipt;
    try {
      receipt = await callNx("gamedev_action_command", { sessionId: session.sessionId, action, args, requestId });
    } catch (error) {
      const failed = { ...draft, status: "failed", error: error?.message || "The PC didn't answer", refused: true };
      put(failed);
      return failed;
    }
    put(receipt);
    while (alive.current && !isDone(receipt.status)) {
      await new Promise(resolve => setTimeout(resolve, 450));
      try { receipt = await callNx("gamedev_receipt_command", { requestId }); } catch { continue; }
      put(receipt);
    }
    return receipt;
  }, [put]);

  // Receipts still open when the screen was last closed: follow them again (an unsent one is marked unknown).
  useEffect(() => {
    for (const rows of Object.values(local.get(LOG_KEY, {}))) {
      for (const row of rows) {
        if (isDone(row.status)) continue;
        if (row.status === "sending") { put({ ...row, status: "failed", error: "The screen closed before the PC answered. Check the editor before sending it again." }); continue; }
        void (async () => {
          let receipt = row;
          while (alive.current && !isDone(receipt.status)) {
            try { receipt = await callNx("gamedev_receipt_command", { requestId: row.requestId }); } catch { return; }
            put(receipt);
            if (!isDone(receipt.status)) await new Promise(resolve => setTimeout(resolve, 900));
          }
        })();
      }
    }
  }, [put]);

  useEffect(() => {
    const refresh = async () => {
      try {
        const value = await callNx("gamedev_receipts_command", { limit: 200 });
        if (alive.current) for (const row of [...value.receipts].reverse()) put(row);
      } catch { /* The next poll retries when the backend is available. */ }
    };
    void refresh();
    const timer = setInterval(refresh, 2500);
    return () => clearInterval(timer);
  }, [put]);

  const clear = useCallback(sessionId => setLog(current => {
    local.set(CLEARED_KEY, { ...local.get(CLEARED_KEY, {}), [sessionId]: Date.now() / 1000 });
    const next = { ...current };
    delete next[sessionId];
    local.set(LOG_KEY, next);
    return next;
  }), []);

  return { log, send, clear };
}

