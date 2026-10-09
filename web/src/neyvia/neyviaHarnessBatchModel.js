import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
function parseBatchPromptsUnchecked(text) {
  const lines = String(text || "").split(/\r?\n/).filter(line => line.trim());
  if (!lines.length || lines.length > 100) throw new Error("Provide 1 to 100 prompts.");
  return lines.map((line, index) => {
    if (!line.trimStart().startsWith("{")) return line.trim();
    let row;
    try { row = JSON.parse(line); } catch { throw new Error(`Line ${index + 1} is not valid JSON.`); }
    if (typeof row.prompt !== "string" || !row.prompt.trim()) throw new Error(`Line ${index + 1} needs a prompt.`);
    const unsupported = Object.keys(row).filter(key => key !== "prompt");
    if (unsupported.length) throw new Error(`Line ${index + 1}: ${unsupported.join(", ")} is not supported by Neyvia prompt batches. Use the harness's dataset runner for container overrides.`);
    return row.prompt;
  });
}

export function parseBatchPrompts(...args) {
  const before = frontendContractBefore("batch.prompts", args);
  return checkedFrontendAction("batch.prompts", args, parseBatchPromptsUnchecked(...args), before);
}
