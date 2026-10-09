import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
function buildPresentationCapturePayloadUnchecked(form = {}) {
  const destinationKind = String(form.destinationKind || "project").trim();
  const destinationId = String(form.destinationId || "").trim();
  return {
    source: String(form.source || "").trim(),
    direction: "chatgpt-to-neyvia",
    content: { selectedText: String(form.content || "").trim() },
    userInitiated: form.userInitiated === true,
    projectId: destinationKind === "project" ? destinationId : "",
    conversationId: destinationKind === "conversation" ? destinationId : "",
    missionId: destinationKind === "mission" ? destinationId : "",
  };
}

function buildBenchmarkResultPayloadUnchecked(form = {}) {
  return {
    subjectId: String(form.subjectId || "").trim(),
    success: String(form.success || "not-reported") === "true"
      ? true
      : String(form.success || "") === "false"
        ? false
        : "not-reported",
    comparableContext: form.comparableContext === true,
    budgetExceeded: form.budgetExceeded === true,
    measuredFacts: String(form.measuredFacts || "").trim() || "not-reported",
  };
}

function canSubmitBenchmarkResultUnchecked(run, form = {}) {
  const subjects = Array.isArray(run?.subjects) ? run.subjects : [];
  const subjectId = String(form.subjectId || "").trim();
  return Boolean(
    run?.runId &&
      subjectId &&
      subjects.some(subject =>
        String(typeof subject === "object" ? subject.subjectId : subject) === subjectId,
      ),
  );
}

function canConcludeExperimentUnchecked(experiment, verdict) {
  return Boolean(
    experiment?.experimentId &&
      experiment?.state !== "concluded" &&
      String(verdict || "").trim(),
  );
}

export function buildPresentationCapturePayload(...args) {
  const before = frontendContractBefore("ecosystem.capture", args);
  return checkedFrontendAction("ecosystem.capture", args, buildPresentationCapturePayloadUnchecked(...args), before);
}

export function buildBenchmarkResultPayload(...args) {
  const before = frontendContractBefore("ecosystem.benchmark", args);
  return checkedFrontendAction("ecosystem.benchmark", args, buildBenchmarkResultPayloadUnchecked(...args), before);
}

export function canSubmitBenchmarkResult(...args) {
  const before = frontendContractBefore("ecosystem.submit", args);
  return checkedFrontendAction("ecosystem.submit", args, canSubmitBenchmarkResultUnchecked(...args), before);
}

export function canConcludeExperiment(...args) {
  const before = frontendContractBefore("ecosystem.conclude", args);
  return checkedFrontendAction("ecosystem.conclude", args, canConcludeExperimentUnchecked(...args), before);
}
