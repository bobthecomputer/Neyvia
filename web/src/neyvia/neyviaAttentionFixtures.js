import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
function minutesBefore(now, minutes) {
  return new Date(now - minutes * 60 * 1000).toISOString();
}

/**
 * Development-only review data for the task observer.
 *
 * The fixture uses honest conversation fields and never runs a binary. Its
 * lead orchestration describes a read-only inspection of the signed Windows
 * Notepad executable so recent activity, review, blocking, Chat, and
 * Orchestration treatments can be inspected together.
 */
function buildAttentionShowcaseConversationsUnchecked(now = Date.now()) {
  return [
    {
      conversationId: "showcase-notepad-inspection",
      kind: "orchestration",
      title: "Inspect notepad.exe safely",
      attentionState: "active",
      workspaceId: "system32-readonly",
      workspaceName: "System32 · read only",
      lastMeaningfulActivityAt: minutesBefore(now, 4),
      lastActivitySummary: "Captured size and SHA-256; PE header and import mapping is the next read-only step.",
      unreadMeaningfulChanges: 3,
    },
    {
      conversationId: "showcase-mobile-color",
      kind: "chat",
      title: "Tune Chat color on mobile",
      attentionState: "active",
      workspaceId: "neyvia-interface",
      workspaceName: "Neyvia interface",
      lastMeaningfulActivityAt: minutesBefore(now, 11),
      lastActivitySummary: "Calibrated the coral tile and checked compact-screen contrast.",
      unreadMeaningfulChanges: 1,
    },
    {
      conversationId: "showcase-motion-proof",
      kind: "orchestration",
      title: "Verify task observer motion",
      attentionState: "ready-for-review",
      workspaceId: "neyvia-interface",
      workspaceName: "Neyvia interface",
      lastMeaningfulActivityAt: minutesBefore(now, 38),
      lastActivitySummary: "Desktop, compact, and reduced-motion checks produced comparable evidence.",
      hasVerificationEvidence: true,
    },
    {
      conversationId: "showcase-approval",
      kind: "orchestration",
      title: "Approve binary analysis scope",
      attentionState: "needs-action",
      workspaceId: "system32-readonly",
      workspaceName: "System32 · read only",
      lastMeaningfulActivityAt: minutesBefore(now, 74),
      lastActivitySummary: "Waiting for confirmation that analysis remains static and read-only.",
      hasBlockingApproval: true,
    },
    {
      conversationId: "showcase-copy",
      kind: "chat",
      title: "Rewrite task descriptions",
      attentionState: "quiet",
      workspaceId: "neyvia-interface",
      workspaceName: "Neyvia interface",
      lastMeaningfulActivityAt: minutesBefore(now, 780),
      lastActivitySummary: "Replaced generic labels with the latest meaningful outcome.",
    },
  ];
}

export function isAttentionShowcaseFixture() {
  if (!import.meta.env?.DEV || typeof window === "undefined") return false;
  const search = new URLSearchParams(window.location.search);
  return search.get("preview-control") === "1" && search.get("fixture") === "attention_showcase";
}

export function buildAttentionShowcaseConversations(...args) {
  const before = frontendContractBefore("attention.showcase", args);
  return checkedFrontendAction("attention.showcase", args, buildAttentionShowcaseConversationsUnchecked(...args), before);
}
