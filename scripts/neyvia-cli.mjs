#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
if (process.argv[2] === "app") {
  const python = process.env.NEYVIA_APP_PYTHON || (process.platform === "win32" ? "C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe" : "python3");
  const result = spawnSync(python, [path.join(scriptDir, "app_sdk.py"), ...process.argv.slice(3)], { stdio: "inherit", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  if (result.error) console.error(result.error.message);
  process.exit(result.status ?? 1);
}
const launcher = path.join(scriptDir, "launch_neyvia.py");
const python = process.platform === "win32" ? "python" : "python3";
const result = spawnSync(python, [launcher, ...process.argv.slice(2)], { stdio: "inherit" });
process.exit(result.status ?? 1);
