"""Real, bounded GPT-6 Luna evaluators for the first Evolver text domains.

The mutable genome is instruction text. Judges, cases and task outcomes are
host-owned; the model can only return JSON, never execute an evaluation tool.
"""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs

import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config/evolver"
MODEL = "gpt-6-luna"
CL_CHECKS = {"raw-colour", "inline-style-colour", "font-size-token", "transition-all",
             "literal-duration", "outline-none", "clickable-div", "button-type",
             "dead-control", "buzzwords", "fake-data", "fixed-width", "uppercase",
             "glow", "scoped"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def token_count(text):
    # A stable, real tokenizer, explicitly a reference encoding rather than an
    # invented claim about Luna's private provider tokenizer.
    import tiktoken
    return len(tiktoken.get_encoding("o200k_base").encode(text))


class ModelFailure(RuntimeError):
    pass


class Luna:
    def __init__(self, root):
        self.root = Path(root).resolve()
        from .local_network_policy import install
        install(self.root)
        self.raw = self.root / ".neyvia/evolver-model-runs"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.sandbox = self.root / ".neyvia/evolver-model-sandbox"
        self.sandbox.mkdir(parents=True, exist_ok=True)

    def ask(self, prompt, *, label, schema=None):
        run_id = uuid.uuid4().hex
        stem = self.raw / f"{label}-{run_id}"
        executable = shutil.which("codex.cmd") or shutil.which("codex")
        if not executable:
            raise ModelFailure("Codex CLI unavailable; no substitute model is permitted")
        command = [executable, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                   "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--cd",
                   str(self.sandbox), "--model", MODEL, "-c", 'model_reasoning_effort="low"',
                   "-c", "features.shell_tool=false", "-c", "features.multi_agent=false",
                   "-c", 'web_search="disabled"', "-"]
        if schema:
            schema_path = stem.with_suffix(".schema.json")
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            command[-1:-1] = ["--output-schema", str(schema_path)]
        stem.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
        started = time.time()
        try:
            result = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=240,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            stem.with_suffix(".stdout.jsonl").write_text((exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout or "", encoding="utf-8")
            stem.with_suffix(".failure.json").write_text(json.dumps({"model": MODEL, "status": "timeout", "seconds": 240}), encoding="utf-8")
            raise ModelFailure(f"Luna timeout; preserved {stem}") from exc
        stem.with_suffix(".stdout.jsonl").write_text(result.stdout, encoding="utf-8")
        stem.with_suffix(".stderr.txt").write_text(result.stderr, encoding="utf-8")
        events = []
        for line in result.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        messages = [e["item"]["text"] for e in events if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
        unexpected = [e for e in events if e.get("item", {}).get("type") not in {None, "agent_message", "reasoning", "error"}]
        usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None)
        receipt = {"id": run_id, "model": MODEL, "command": command, "exitCode": result.returncode,
                   "threadId": next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None),
                   "usage": usage, "seconds": round(time.time() - started, 3),
                   "raw": str(stem.with_suffix(".stdout.jsonl")),
                   "providerSamplingSeed": None, "seedBoundary": "Seed fixes paired task data and order; CLI has no provider sampling seed option",
                   "toolBoundary": "Read-only CLI, shell/multi-agent/web disabled; unexpected tool events reject the call"}
        stem.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        if result.returncode or not messages or not usage or unexpected:
            raise ModelFailure(f"Luna call failed or exceeded tool authority; raw receipt {receipt['raw']}")
        try:
            answer = json.loads(messages[-1])
        except json.JSONDecodeError as exc:
            raise ModelFailure(f"Luna returned invalid JSON; raw receipt {receipt['raw']}") from exc
        return answer, receipt


def domain_spec(domain_id):
    panels = json.loads((CONFIG / f"{domain_id}.panels.json").read_text(encoding="utf-8"))
    baseline = (CONFIG / f"{domain_id}.incumbent.txt").read_text(encoding="utf-8")
    originals = (["manuals/notes.manual.json", "src/grant_agent/neyvia_notes_tools.py", "src/grant_agent/neyvia_manuals.py"]
                 if domain_id == "manual_compression" else ["manuals/skills/design-craft.cl", "src/grant_agent/cl_skill.py"])
    return {"baseline": baseline, "panels": panels,
            "judges": [str(REPO / p) for p in originals] + [str(Path(__file__).resolve()), str(CONFIG / f"{domain_id}.panels.json")],
            "objectives": {"success": {"direction": "max", "tolerance": 0.0, "noise": 0.0},
                           "tokens": {"direction": "min", "tolerance": 0.0, "noise": 0.0},
                           "fitness": {"direction": "max", "tolerance": 0.0, "noise": 0.0}},
            "promotion": {"alpha": 0.05, "min_pairs": 10, "max_trials": 2,
                          "max_evaluations": 160, "max_seconds": 1200, "seed": 613}}


def notes_judge(root, item, answer):
    from .neyvia_notes_tools import set_folder, write_note, read_note, pin_note
    from .neyvia_manuals import expect, resolve
    folder = root / "notes"
    set_folder(root, {"folder": str(folder.resolve())})
    write_note(root, {"path": item["path"], "body": item["initial"]})
    results, actions = {}, []
    allowed = {"notes.read": read_note, "notes.write": write_note, "notes.pin": pin_note}
    authority = True
    error = None
    try:
        for step in answer.get("steps", []):
            action = step["action"]
            args = resolve(step["args"], item["inputs"], results, root)
            if action not in allowed or args.get("path") != item["path"]:
                authority = False
                break
            result = allowed[action](root, args)
            results[step["save"]] = result
            actions.append({"action": action, "args": args, "result": result})
    except (KeyError, TypeError, ValueError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    observed = read_note(root, {"path": item["path"]})
    manual = json.loads((REPO / "manuals/notes.manual.json").read_text(encoding="utf-8"))
    checks = manual["chapters"]["overview"]["checks"]
    checked = {name: expect(observed, checks[name]["expect"], item["inputs"], results, root) for name in item["checks"]}
    # In addition to original executable checks, preserve original content on
    # append and require a read-derived compare-and-swap guard on replacements.
    writes = [step for step in actions if step["action"] == "notes.write"]
    guarded = bool(writes) and bool(writes[-1]["args"].get("expectedModified"))
    preserved = item["initial"] in observed["body"] if item["kind"] == "append" else True
    success = float(bool(checked) and all(checked.values()) and guarded and preserved and not error)
    return success, {"authority": authority}, {"actions": actions, "checks": checked, "casGuard": guarded,
                                               "preserved": preserved, "observed": observed, "error": error}


def skill_judge(root, item, answer):
    from .cl_skill import Output, _parse_skill, run_checks
    root.mkdir(parents=True, exist_ok=True)
    source = answer.get("jsx", "")
    css = answer.get("css", "")
    imports = re.findall(r'(?:from\s*|import\s*)[\"\']([^\"\']+)[\"\']', source)
    authority = all(name == "react" for name in imports) and not re.search(r'\b(require|process|eval|Function|globalThis|global|constructor|__proto__|fetch|XMLHttpRequest)\b', source)
    if not authority:
        return 0.0, {"judgeDecided": True, "artifactAuthority": False}, {"error": "Component exceeded the closed React artifact authority"}
    jsx = root / "Output.jsx"
    style = root / "output.css"
    jsx.write_text(source, encoding="utf-8")
    style.write_text(css, encoding="utf-8")
    journal = root / "journal.cl"
    journal.write_text(answer.get("journal", ""), encoding="utf-8")
    report = run_checks(_parse_skill(REPO / "manuals/skills/design-craft.cl"), Output([jsx, style]), journal=journal, only=CL_CHECKS)
    # Compile and execute the produced component against real installed React.
    # This is a stateless component task: no browser or visual-quality claim.
    esbuild = REPO / "node_modules/@esbuild/win32-x64/esbuild.exe"
    compiled = subprocess.run([str(esbuild), str(jsx), "--format=cjs", "--loader:.jsx=jsx", "--log-level=error"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, **hidden_windows_subprocess_kwargs())
    module = root / "output.cjs"
    module.write_text(compiled.stdout, encoding="utf-8")
    node_script = """const React=require('react'); const SSR=require('react-dom/server'); const vm=require('node:vm');
const moduleObject={exports:{}};const context=vm.createContext({module:moduleObject,exports:moduleObject.exports,require:(name)=>{if(name!=='react')throw Error('Import denied');return React}});
new vm.Script(require('node:fs').readFileSync(process.argv[1],'utf8')).runInContext(context,{timeout:1000});const C=moduleObject.exports.default;
let calls=0; const tree=C({onAction:()=>calls++}); const buttons=[];
function walk(n){if(!n||typeof n!=='object')return;if(n.type==='button')buttons.push(n);React.Children.forEach(n.props?.children,walk)}
walk(tree);for(const b of buttons)if(typeof b.props.onClick==='function')b.props.onClick();
console.log(JSON.stringify({markup:SSR.renderToStaticMarkup(tree),calls,buttons:buttons.length}));"""
    modules = (REPO / "node_modules").resolve()
    executed = subprocess.run([shutil.which("node") or "node", "--permission", f"--allow-fs-read={modules}",
                               f"--allow-fs-read={REPO / 'node_modules'}", f"--allow-fs-read={REPO / 'package.json'}",
                               f"--allow-fs-read={module}", "-e", node_script, str(module)],
                              cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                              env={**os.environ, "NODE_PATH": str(modules)}, **hidden_windows_subprocess_kwargs()) if compiled.returncode == 0 else None
    runtime = {}
    if executed and executed.returncode == 0:
        try:
            runtime = json.loads(executed.stdout)
        except json.JSONDecodeError:
            pass
    markup = runtime.get("markup", "")
    quality_checks = {"compiles": compiled.returncode == 0, "executes": bool(runtime),
                      "oneAction": runtime.get("calls") == 1 and runtime.get("buttons") == 1,
                      "requestedCopy": item["heading"] in markup and item["label"] in markup,
                      "requestedClass": item["class"] in markup and "." + item["class"] in css}
    quality = sum(quality_checks.values()) / len(quality_checks)
    decided = report["checksDecided"] == report["checksRun"]
    success = report["adherence"] * quality
    return success, {"judgeDecided": decided, "artifactAuthority": authority}, {"adherence": report, "quality": quality,
                                               "qualityChecks": quality_checks, "runtime": runtime,
                                               "compileError": compiled.stderr,
                                               "executeError": executed.stderr if executed else "Not compiled",
                                               "artifact": str(jsx), "cssArtifact": str(style)}


class DomainEvaluator:
    """Independent model call per case; cache never crosses cases or panels."""
    def __init__(self, root, domain_id, luna):
        self.root, self.domain_id, self.luna = Path(root), domain_id, luna
        self.spec = domain_spec(domain_id)
        self.panels = {p["id"]: p for p in self.spec["panels"]}
        self.cache = {}

    def __call__(self, genome, item, seed):
        payload = genome.get("payload", genome.get("genome", genome))
        text = payload["text"]
        genome_hash = hashlib.sha256(text.encode()).hexdigest()
        key = (genome_hash, item["panel"], item["id"], seed)
        if key not in self.cache:
            items = [item]
            tasks = [{k: v for k, v in case.items() if k not in {"checks", "initial", "kind", "panel"}} for case in items]
            output_rule = ('Return {"answers":[{"id":case_id,"steps":[{"action":"notes.read|notes.write|notes.pin","args":{},"save":"unique_name"}]}]}. '
                           'Arguments may use {"$input":"key"} or {"$result":"saved.field"}. No tools. '
                           if self.domain_id == "manual_compression" else
                           'Return {"answers":[{"id":case_id,"jsx":"React component source","css":"CSS source","journal":"CL judgement journal, J name=option lines"}]}. '
                           'Stateless default export; import React from "react"; accepts onAction callback; no other imports or hooks. No tools. ')
            prompt = ("This is a closed-book instruction-following benchmark. Only produce JSON; do not use tools, inspect files, or delegate.\n"
                      + output_rule + "\nINSTRUCTIONS\n" + text + "\nTASKS (paired seed " + str(seed) + ")\n" + json.dumps(tasks, ensure_ascii=False))
            answer, receipt = self.luna.ask(prompt, label=f"{item['id']}-{genome_hash[:8]}")
            responses = {a["id"]: a for a in answer.get("answers", []) if isinstance(a, dict) and "id" in a}
            self.cache[key] = (responses, receipt)
        responses, model_receipt = self.cache[key]
        answer = responses.get(item["id"], {})
        work = self.root / ".neyvia/evolver-artifacts" / model_receipt["id"] / item["id"]
        work.mkdir(parents=True, exist_ok=True)
        judge = notes_judge if self.domain_id == "manual_compression" else skill_judge
        success, gates, judged = judge(work, item, answer)
        tokens = token_count(text)
        return {"objectives": {"success": success, "tokens": float(tokens), "fitness": success / max(tokens, 1)},
                "hard_gates": gates, "receipt": {"model": model_receipt, "taskId": item["id"], "panel": item["panel"],
                                                "seed": seed, "answer": answer, "judge": judged,
                                                "tokenEncoding": "o200k_base reference encoding, not provider-native tokenization",
                                                "taskScope": "native Notes executable manual checks" if self.domain_id == "manual_compression" else "CL checks plus actual React compilation, SSR and action callback execution"}}


def propose(luna, domain_id, incumbent, trial):
    spec = domain_spec(domain_id)
    discovery = [p for p in spec["panels"] if p["role"] == "discovery"]
    prompt = ("Return only JSON {\"text\":\"replacement instruction document\"}. Do not use tools or delegate.\n"
              "Compress and clarify this instruction document while preserving its complete task semantics, safety rules, and useful judgement points. "
              "Executable judges and held-out cases are frozen and unavailable. You may change wording/structure only. "
              "Retain everything necessary for these training task families. Aim for less than half the reference document tokens.\n"
              "DOMAIN " + domain_id + " trial " + str(trial) + "\nTRAINING TASKS\n" + json.dumps(discovery)
              + "\nINCUMBENT\n" + incumbent)
    answer, receipt = luna.ask(prompt, label=f"{domain_id}-proposal-{trial}", schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False})
    text = answer.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ModelFailure("Luna proposed an empty or malformed genome")
    return text, receipt
