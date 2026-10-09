import assert from "node:assert/strict";
import test from "node:test";

import {
  operationArgumentFields,
  operationFieldLabel,
  operationInitialArguments,
  validateAndCoerceOperationArguments,
} from "./neyviaOperationForm.js";


const operation = {
  operationId: "document.convert",
  inputSchema: {
    type: "object",
    required: ["path", "outputFormat"],
    properties: {
      operation: { const: "convert" },
      path: { type: "string" },
      outputFormat: { type: "string", enum: ["docx", "pdf"] },
      timeoutSeconds: { type: "integer", minimum: 5, maximum: 600 },
      tableOfContents: { type: "boolean" },
      metadata: { type: "object" },
    },
  },
};

test("operation form labels schema keys without shell globals", () => {
  assert.equal(operationFieldLabel("outputPath"), "Output Path");
  assert.equal(operationFieldLabel("timeout_seconds"), "Timeout Seconds");
  assert.equal(operationFieldLabel(""), "Input");
});


test("operation form separates required inputs and preserves schema constants", () => {
  const fields = operationArgumentFields(operation);
  const initial = operationInitialArguments(operation);

  assert.deepEqual(fields.required.map(field => field.key), ["path", "outputFormat"]);
  assert.deepEqual(fields.optional.map(field => field.key), [
    "timeoutSeconds",
    "tableOfContents",
    "metadata",
  ]);
  assert.deepEqual(initial, { operation: "convert", outputFormat: "docx" });
});


test("operation form rejects missing or malformed values before execution", () => {
  const checked = validateAndCoerceOperationArguments(operation, {
    outputFormat: "docx",
    timeoutSeconds: "not-a-number",
    metadata: "{bad json",
  });

  assert.equal(checked.ok, false);
  assert.match(checked.errors.path, /required/i);
  assert.match(checked.errors.timeoutSeconds, /whole number/i);
  assert.match(checked.errors.metadata, /valid JSON/i);
});


test("operation form emits typed arguments for the existing executor", () => {
  const checked = validateAndCoerceOperationArguments(operation, {
    path: "report.md",
    outputFormat: "pdf",
    timeoutSeconds: "45",
    tableOfContents: "true",
    metadata: '{"title":"Report"}',
  });

  assert.equal(checked.ok, true);
  assert.deepEqual(checked.arguments, {
    operation: "convert",
    path: "report.md",
    outputFormat: "pdf",
    timeoutSeconds: 45,
    tableOfContents: true,
    metadata: { title: "Report" },
  });
});
