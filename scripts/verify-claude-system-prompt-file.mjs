import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const scratch = mkdtempSync(join(tmpdir(), "neyvia-claude-system-prompt-"));
const file = join(scratch, "instructions.txt");
writeFileSync(file, "SYSTEM_ONLY_DISPOSABLE_FIXTURE", "utf8");
const source = String.raw`
import json, sys
from grant_agent.external_cli_bridge import build_cli_args
path, prompt = sys.argv[1], "USER_QUERY_DISPOSABLE_FIXTURE"
args = build_cli_args(runtime="claude-code", command="claude", prompt=prompt, model="sonnet", mode="chat", system_prompt_file=path)
assert args[0] == "claude"
assert args[args.index("--system-prompt-file") + 1] == path
assert any(prompt in arg for arg in args)
assert "SYSTEM_ONLY_DISPOSABLE_FIXTURE" not in args
assert args[args.index("--permission-mode") + 1] == "plan"
assert args[args.index("--allowedTools") + 1:args.index("--allowedTools") + 4] == ["Read", "Glob", "Grep"]
try:
    build_cli_args(runtime="codex", command="codex", prompt=prompt, system_prompt_file=path)
except ValueError:
    rejected = True
else:
    rejected = False
assert rejected
print(json.dumps({"claudeSystemPromptFilePassed": True, "promptContentsAbsentFromArgv": True, "readonlyPolicyPreserved": True, "nonClaudeUseRejected": True}))
`;
try {
  const result = spawnSync("python", ["-c", source, file, "USER_QUERY_DISPOSABLE_FIXTURE"], {
    cwd: resolve("."), encoding: "utf8", env: { ...process.env, PYTHONPATH: `${resolve("src")};${process.env.PYTHONPATH || ""}` },
  });
  assert.equal(result.status, 0, result.stderr || "Claude prompt argv verification failed");
  const proof = JSON.parse(result.stdout.trim());
  for (const [gate, passed] of Object.entries(proof)) assert.equal(passed, true, `${gate} failed`);
  console.log(JSON.stringify(proof));
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
