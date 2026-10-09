import fs from "node:fs";
import path from "node:path";

const catalogPath = path.resolve(process.argv[2] || "");
if (!catalogPath || !fs.existsSync(catalogPath)) {
  throw new Error("Pass the existing Codex model catalog JSON path.");
}

const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
if (!Array.isArray(catalog.models)) {
  throw new Error("The Codex model catalog does not contain a models array.");
}

let changed = 0;
for (const model of catalog.models) {
  if (typeof model.supports_parallel_tool_calls !== "boolean") {
    model.supports_parallel_tool_calls = false;
    changed += 1;
  }
}

fs.writeFileSync(catalogPath, `${JSON.stringify(catalog, null, 2)}\n`, "utf8");
process.stdout.write(JSON.stringify({ catalogPath, models: catalog.models.length, changed }));
