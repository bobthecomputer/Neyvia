"""Bounded real task replay: model writes files; host owns executable measurements.

Replay inputs and validator scripts are frozen by the caller before a trial.
No model-authored command is executed. Unsupported external tasks remain unmapped.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .autopilot_model import decide
from .durability import atomic_write_json, atomic_write_text
from .subprocess_utils import hidden_windows_subprocess_kwargs

REPO = Path(__file__).resolve().parents[2]
MAX_BYTES = 1_000_000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def relative(name):
    path = Path(name)
    if path.is_absolute() or not path.parts or any(p in {"..", ".neyvia", ".agent_control", "node_modules", ".git"} for p in path.parts):
        raise ValueError("Replay paths must stay in the disposable workspace")
    if re.search(r"credential|password|secret|token|nas.*runbook", name, re.I):
        raise ValueError("Protected files are excluded from replay")
    return path


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("task"), str) or not manifest["task"].strip():
        raise ValueError("Replay requires the original task text")
    if not isinstance(manifest.get("outputs"), list) or not manifest["outputs"]:
        raise ValueError("Replay requires named output paths")
    for name in manifest["outputs"]:
        relative(name)
    inputs = manifest.get("inputs", {})
    if not isinstance(inputs, dict) or sum(len(str(t).encode()) for t in inputs.values()) > MAX_BYTES:
        raise ValueError("Replay input budget exceeded")
    for name, text in inputs.items():
        relative(name)
        if not isinstance(text, str):
            raise ValueError("Replay inputs must be text")
    validator = manifest.get("validator")
    if validator is not None and (validator not in {"bench.py", "score.py"} or validator not in inputs):
        raise ValueError("Only a frozen bench.py or score.py recipe may execute")
    checks = manifest.get("executableChecks", [])
    if (not isinstance(checks, list) or len(checks) > 32
            or any(not isinstance(name, str) or not re.fullmatch(r"[a-z][a-zA-Z0-9_]{0,63}", name) for name in checks)
            or len(set(checks)) != len(checks)):
        raise ValueError("Executable checks require unique bounded criterion names")
    if checks and not validator:
        raise ValueError("Executable checks require a frozen validator")
    model_inputs = manifest.get("modelInputs")
    if model_inputs is not None and (not isinstance(model_inputs, list)
            or any(not isinstance(name, str) or name not in inputs for name in model_inputs)
            or len(set(model_inputs)) != len(model_inputs)):
        raise ValueError("Model inputs must name unique frozen input files")
    return manifest


def capture_task_manifest(workspace, task):
    """Freeze explicitly named text inputs before edits, or report unmapped.

    This bounded local file recipe does not claim replay coverage for browser,
    native-app, network, package-install or arbitrary shell tasks.
    """
    if not workspace or re.search(r'https?://|\b(?:browse|browser|web search|navigate|install|download|Notepad|Calculator|Notes app)\b', task, re.I):
        return None
    root = Path(workspace).resolve()
    protected = [Path(r"C:\Users\user\Projects\Neyvia").resolve(), Path(r"C:\Users\user\Projects\Neyvia-next").resolve()]
    if any(root == p or p in root.parents for p in protected):
        return None
    names = sorted(set(re.findall(r'(?<![\w:/\\])([\w./-]+\.(?:py|md|html|txt|csv|json))\b', task)))
    inputs, outputs = {}, []
    for name in names:
        try:
            path = (root / relative(name)).resolve()
            path.relative_to(root)
            if path.is_file():
                if path.stat().st_size > MAX_BYTES:
                    return None
                inputs[name] = path.read_text(encoding="utf-8")
            if Path(name).suffix in {".md", ".html", ".txt", ".py"} and Path(name).name not in {"bench.py", "score.py"}:
                outputs.append(name)
        except (ValueError, OSError, UnicodeError):
            return None
    if not outputs:
        return None
    validator = next((name for name in ("bench.py", "score.py") if name in inputs), None)
    if any(Path(n).suffix == ".py" for n in outputs) and not validator:
        return None
    manifest = {"task": task, "inputs": inputs, "outputs": outputs, "validator": validator}
    try:
        return validate_manifest(manifest)
    except ValueError:
        return None


SCHEMA = {"type": "object", "additionalProperties": False, "required": ["writes", "measure", "done", "summary"],
          "properties": {"writes": {"type": "array", "maxItems": 8, "items": {"type": "object", "additionalProperties": False,
              "required": ["path", "text"], "properties": {"path": {"type": "string"}, "text": {"type": "string"}}}},
              "measure": {"type": "boolean"}, "done": {"type": "boolean"}, "summary": {"type": "string"}}}


def replay(manifest, directory, *, lines=(), lessons=(), model="gpt-6-luna", timeout=180):
    validate_manifest(manifest)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    for name, text in manifest.get("inputs", {}).items():
        atomic_write_text(directory / relative(name), text)
    writable = set(manifest["outputs"])
    # Existing implementation files named as outputs may be changed; measurement
    # scripts and datasets never become writable just because a model requests it.
    for name in writable:
        if name == manifest.get("validator"):
            raise ValueError("The executable validator cannot be an output")
    measurements, receipts, feedback = [], [], ""
    block_retries = {}
    base = ("Complete this original task in a disposable workspace. You propose file writes; the host writes them, "
            "runs the frozen measurement recipe when measure=true, and returns actual results. You cannot run tools yourself. "
            "Never invent measurements. Read back is performed by the host from written bytes. Finish only after evidence. "
            "Return JSON file writes without markdown fences.\nTASK:\n" + manifest["task"] +
            "\nInstruction lines for this replay:\n" + "\n".join(lines) + "\nWritable outputs: " + json.dumps(sorted(writable)))
    measured_hashes = None
    for turn in range(12):
        # Host measurement oracles may be excluded explicitly from task context.
        # Every actual measurement, including failing quality criteria, is still
        # returned verbatim below; this cannot conceal an observed failure.
        visible_inputs = manifest.get("modelInputs", list(manifest.get("inputs", {})))
        current = {n: (directory / n).read_text(encoding="utf-8") for n in sorted(set(visible_inputs) | writable) if (directory / n).is_file()}
        result = decide(base + "\nCurrent files:\n" + json.dumps(current, ensure_ascii=False) + "\nActual host feedback:\n" + feedback,
                        SCHEMA, directory, model=model, timeout=timeout)
        receipts.append({k: result[k] for k in ("model", "tokens", "elapsedMs", "receiptPath")})
        answer = result["answer"]
        if not isinstance(answer, dict) or type(answer.get("done")) is not bool or type(answer.get("measure")) is not bool:
            raise ValueError("Invalid replay proposal")
        writes = answer.get("writes")
        if not isinstance(writes, list) or len(writes) > 8:
            raise ValueError("Invalid replay writes")
        for write in writes:
            name, text = write.get("path"), write.get("text")
            if name not in writable or not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
                raise ValueError("Replay proposed an unauthorized or oversized output")
            atomic_write_text(directory / relative(name), text)
        code_hashes = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in writable if Path(name).suffix == ".py" and (directory / name).is_file()}
        output_hashes = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in writable if (directory / name).is_file()}
        if answer["measure"] or answer["done"] and manifest.get("validator") and output_hashes != measured_hashes:
            validator = manifest.get("validator")
            if not validator:
                feedback = "No executable measurement recipe is mapped for this task."
            else:
                for name, text in manifest.get("inputs", {}).items():
                    if name not in writable and (directory / name).read_text(encoding="utf-8") != text:
                        raise ValueError("Frozen replay input changed")
                env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0"}
                started = time.monotonic()
                try:
                    proc = subprocess.run([sys.executable, validator], cwd=directory, env=env, capture_output=True, text=True,
                                          encoding="utf-8", errors="replace", timeout=40, **hidden_windows_subprocess_kwargs())
                    measurement = {"exitCode": proc.returncode, "output": proc.stdout[-16000:], "error": proc.stderr[-2000:]}
                except subprocess.TimeoutExpired as exc:
                    raw = exc.stdout or b""
                    measurement = {"exitCode": None, "timedOut": True, "output": raw.decode("utf-8", "replace")[-16000:] if isinstance(raw, bytes) else raw[-16000:], "error": "Frozen measurement exceeded 40 seconds"}
                measurement.update(elapsedMs=round((time.monotonic() - started) * 1000), outputCodeSha256=code_hashes, outputSha256=output_hashes)
                if manifest.get("executableChecks"):
                    try:
                        observed = json.loads(measurement["output"].splitlines()[-1])["criteria"]
                    except (ValueError, KeyError, IndexError, TypeError):
                        raise ValueError("Frozen validator omitted executable criteria")
                    if (not isinstance(observed, dict) or set(observed) != set(manifest["executableChecks"])
                            or any(type(value) is not bool for value in observed.values())):
                        raise ValueError("Frozen validator returned incomplete or invalid executable criteria")
                    measurement["criteria"] = observed
                measurements.append(measurement)
                measured_hashes = output_hashes
                feedback = json.dumps(measurement)
        if answer["done"]:
            files = {name: (directory / name).read_text(encoding="utf-8") for name in sorted(writable) if (directory / name).is_file()}
            from .cl_deliverables import configured_gate
            gate = configured_gate(directory, 0, answer.get("summary", ""), manifest["task"], trial_lessons=lessons)
            signature = digest(gate["signature"])
            block_retries[signature] = block_retries.get(signature, 0) + 1
            if gate["blocking"] and block_retries[signature] < 3:
                feedback += "\nProduction done gate refused:\n" + gate["cl"]
                continue
            if manifest.get("validator") and (not measurements or measurements[-1]["exitCode"] != 0):
                feedback += "\nThe final executable measurement has not passed; fix the implementation before done."
                continue
            valid = not gate["blocking"] and len(files) == len(writable) and (not manifest.get("validator") or bool(measurements) and measurements[-1]["exitCode"] == 0)
            record = {"valid": valid, "task": manifest["task"], "files": files, "measurements": measurements,
                      "summary": answer.get("summary", ""), "modelRuns": receipts, "manifestSha256": digest(manifest),
                      "route": "bounded-file-replay+host-owned-measurements", "turns": turn + 1}
            record.update(skillReceipts=gate["reports"], unresolvedBlocks=gate["blocking"], doneStatus="ok" if valid else "refused",
                          executableCriteria=measurements[-1].get("criteria", {}) if measurements else {})
            atomic_write_json(directory / "replay.json", record)
            return record
    failed = {"valid": False, "task": manifest["task"], "measurements": measurements, "modelRuns": receipts,
              "files": {name: (directory / name).read_text(encoding="utf-8") for name in sorted(writable) if (directory / name).is_file()},
              "executableCriteria": measurements[-1].get("criteria", {}) if measurements else {}, "doneStatus": "refused",
              "manifestSha256": digest(manifest), "feedback": feedback, "error": "Real replay exhausted twelve turns without completion"}
    atomic_write_json(directory / "replay-failed.json", failed)
    return failed
