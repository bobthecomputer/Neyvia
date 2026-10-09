import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
const THINKING_LABELS = new Set(["", "thinking...", "working..."]);

function isChatCancellationResultUnchecked(result) {
  return String(result?.status || result?.compartment?.state || "").trim().toLowerCase() === "cancelled"
    || result?.cancelled === true;
}

function cancelledChatTurnPatchUnchecked(current = {}, fallbackTitle = "") {
  const existingTitle = String(current.title || "").trim();
  const title = THINKING_LABELS.has(existingTitle.toLowerCase())
    ? String(fallbackTitle || "Stopped by you.")
    : existingTitle;
  return {
    title,
    detail: "Stopped by you.",
    pending: false,
    tone: "neutral",
    source: "chat-cancelled",
  };
}

export function isChatCancellationResult(...args) {
  const before = frontendContractBefore("chat.cancellation-result", args);
  return checkedFrontendAction("chat.cancellation-result", args, isChatCancellationResultUnchecked(...args), before);
}

export function cancelledChatTurnPatch(...args) {
  const before = frontendContractBefore("chat.cancelled", args);
  return checkedFrontendAction("chat.cancelled", args, cancelledChatTurnPatchUnchecked(...args), before);
}
