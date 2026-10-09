"""Run production manual observers/procedures in a new, confined scratch root."""
from __future__ import annotations

import importlib
import json
import subprocess
import time
import uuid
import os
import secrets
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from .proof_contracts import REPO, catalog, manifest_files, source_bindings, source_binding_digest

# Code imports are host-owned, never supplied by a manual or tool argument.
ADAPTERS = {"release-outcomes": "grant_agent.proofs_release_outcomes", "fast-contracts": "grant_agent.proofs_fast_contracts", "dictation": "grant_agent.proofs_dictation", "notes-files": "grant_agent.proofs_notes_files",
            "connections": "grant_agent.proofs_connections", "usage": "grant_agent.proofs_usage",
            "rel29-outcomes": "grant_agent.proofs_rel29_outcomes",
            "parallel-outcomes": "grant_agent.proofs_parallel_outcomes",
            "scene-outcomes": "grant_agent.proofs_scene_outcomes", "laya-floor": "grant_agent.proofs_laya_floor",
            "apple-outcomes": "grant_agent.proofs_apple_outcomes",
            "cl-completion": "grant_agent.proofs_cl_completion", "plan-history": "grant_agent.proofs_plan_history",
            "semantic-outcomes": "grant_agent.proofs_semantic_outcomes",
            "browser-journey": "grant_agent.proofs_browser_journey", "chat-journey": "grant_agent.proofs_chat_journey",
            "cl-effect-outcomes": "grant_agent.proofs_cl_effect_outcomes", "creative-journey": "grant_agent.proofs_creative_journey",
            "mission-journey": "grant_agent.proofs_mission_journey", "runtime-journey": "grant_agent.proofs_runtime_journey",
            "settings-journey": "grant_agent.proofs_settings_journey",
            "transcript-journey": "grant_agent.proofs_transcript_journey",
            "onboarding-external-journey": "grant_agent.proofs_onboarding_external_journey",
            "measured-coverage":"grant_agent.proofs_measured_coverage",
            "coverage-ratchet":"grant_agent.proofs_ratchet",
            "static-web-reach":"grant_agent.proofs_web_reach",
            "build-cache":"grant_agent.proofs_build_cache",
            "resource-outcomes":"grant_agent.proofs_resource_outcomes",
            "python-sdk-journey":"grant_agent.proofs_python_sdk_journey",
            "installed-preflight-journey":"grant_agent.proofs_installed_preflight_journey",
            "surface-games-extra":"grant_agent.proofs_surface_games_extra",
            "scroll-export-journey":"grant_agent.proofs_scroll_export_journey",
            "codex-transcript-journey":"grant_agent.proofs_codex_transcript_journey",
            "installer-extra":"grant_agent.proofs_installer_extra",
            "capability-config-journey":"grant_agent.proofs_capability_config_journey",
            "context-config-journey":"grant_agent.proofs_context_config_journey",
            "manual-registry-journey":"grant_agent.proofs_manual_registry_journey",
            "path-policy-outcomes":"grant_agent.proofs_path_policy_outcomes",
            "generator-outcomes":"grant_agent.proofs_generator_outcomes",
            "pack-generator-outcomes":"grant_agent.proofs_pack_generator",
            "event-recovery-journey":"grant_agent.proofs_event_recovery_journey",
            "working-memory-journey":"grant_agent.proofs_working_memory_journey",
            "project-files-journey":"grant_agent.proofs_project_files_journey",
            "p22-pdf-backend-journey":"grant_agent.proofs_pdf_backend_journey",
            "session-events-journey":"grant_agent.proofs_session_events_journey",
            **{area+'-journey': 'grant_agent.proofs_'+module+'_journey' for area,module in
               [('applications','applications'),('games','games'),('image-studio','image_studio'),
                ('research','research'),('workspace','workspace'),('ui-planning','ui_planning'),
                ('local-host','local_host'),('installer','installer')]},
            "browser-scripts": "grant_agent.proofs_browser_scripts",
            "documents": "grant_agent.proofs_documents",
            "awareness": "grant_agent.proofs_awareness", "settings": "grant_agent.proofs_settings",
            "a-sessions": "grant_agent.proofs_a_sessions", "a-capabilities": "grant_agent.proofs_a_capabilities",
            "a-cli": "grant_agent.proofs_a_cli", "a-control": "grant_agent.proofs_a_control",
            "a-livecontrol": "grant_agent.proofs_a_livecontrol", "a-providers": "grant_agent.proofs_a_providers",
            "a-native-sessions": "grant_agent.proofs_a_native_sessions",
            "proofs-b-desktop": "grant_agent.proofs_b_desktop",
            "proofs-b-engine": "grant_agent.proofs_b_engine",
            "proofs-b-adapters": "grant_agent.proofs_b_adapters",
            "proofs-b-harness": "grant_agent.proofs_b_harness",
            **{f"proofs-c-{area}": f"grant_agent.proofs_c_{area}"
               for area in ("intent", "mobile", "runtime", "models", "missions", "control")},
            **{f"d-{area}": f"grant_agent.proofs_d_{area.replace(chr(45), chr(95))}"
               for area in ("host", "native", "neyvia", "runtime", "ui-planning", "onboarding", "nearby")},
            **{f"proofs-e-{area}": f"grant_agent.proofs_e_{area}" for area in ("sv", "wz", "host")}}
RUNNERS = {"frontend": "scripts/proofs-frontend.mjs", "frontend-models": "scripts/proofs-frontend-models.mjs",
           "p22-frontend-outcomes": "scripts/p22_frontend_outcomes.mjs",
           "agents-journey":"scripts/p22_agents_journey.mjs",
           "nightshift-journey":"scripts/p22_nightshift_journey.mjs",
           "p22-outputs-journey":"scripts/p22_outputs_journey.mjs",
           "proofs-b-browser": "scripts/proofs-b-browser.mjs",
           "proofs-c-frontend": "scripts/proofs-c-frontend.mjs",
           **{f"proofs-e-{area}": f"scripts/proofs-e-{area}.mjs"
              for area in ("frontend", "models", "shell", "chat", "release")}}
LOCAL_TOOLS = {
    "neyvia.manual.index", "neyvia.manual.patches", "neyvia.manual.versions", "neyvia.manual.compiled",
    "neyvia.state", "neyvia.folder.list", "neyvia.work.list", "neyvia.notes.list", "neyvia.notes.read",
    "neyvia.notes.search", "neyvia.notes.write", "neyvia.notes.pin", "neyvia.files.stat", "neyvia.files.list",
    "neyvia.files.move", "neyvia.files.mkdir", "neyvia.files.undo", "neyvia.dictation.names",
    "neyvia.artifact.list", "neyvia.artifact.get",
    "neyvia.verify.status",
    "neyvia.native.runtime.observe", "neyvia.native.runtime.self-check",
    "workspace.read", "neyvia.time.now", "neyvia.settings.get",
    "neyvia.voice.commands", "neyvia.view.transparency.state",
    "workspace.write", "neyvia.efficiency.metrics", "neyvia.efficiency.transitions",
    "neyvia.efficiency.extract",
}


# Authored evidence a manual reads by a constant workspace.read path. Only these
# committed evidence directories qualify, as regular in-repository files under a
# size bound; the scratch workspace receives their exact bytes plus a sha256
# binding instead of a wider read boundary. Generated or run-local paths
# (.agent_control, c8e-effects, ...) are never copied: they must be produced in
# the scratch workspace by the procedure itself.
AUTHORED_EVIDENCE_DIRS = ("docs/evidence/", "scripts/evidence/")
AUTHORED_EVIDENCE_MAX_BYTES = 4 * 1024 * 1024

# Startup self-check scope. These procedures assert the outcome of this very
# self-check (or of the release gate that itself requires it to pass), so
# inside it they could only fail circularly or pass on a stale earlier receipt.
# They are reported as status "skipped" with the reason below, never counted as
# passed. `complete` describes the in-scope rows; the report counts skipped rows
# separately and lists each with its reason. They are verified after the
# self-check by their own owners (neyvia.verify.status, the INTN release gate).
# Keep this list explicit and tiny; an entry naming no live procedure fails.
SELF_REFERENTIAL_PROCEDURES = {
    ("proofs", "overview", "procedure", "require-complete-self-check"):
        "Depends on this self-check's own outcome: it requires the completed startup self-check receipt",
    ("proofs", "release-integration", "procedure", "inspect-integrated-release"):
        "Depends on this self-check's own outcome: releaseGate requires a passing startup self-check",
}


def _constant_read_paths(chapter):
    """Constant workspace.read paths per observer and procedure (including bound checks)."""
    def literal(arguments):
        path = arguments.get("path") if isinstance(arguments, dict) else None
        return [path] if isinstance(path, str) else []
    reads = {}
    for identity, row in chapter["state"].items():
        reads[("observer", identity)] = literal(row["args"]) if row["tool"] == "workspace.read" else []
    for identity, procedure in chapter["procedures"].items():
        paths = []
        for step in procedure["steps"]:
            if "action" in step and chapter["actions"][step["action"]]["tool"] == "workspace.read":
                paths += literal(step["args"])
            if step.get("check") and chapter["checks"][step["check"]]["tool"] == "workspace.read":
                paths += literal(chapter["checks"][step["check"]]["args"])
        reads[("procedure", identity)] = paths
    return reads


def _authored_evidence(path):
    """Return the repository file for an admitted authored evidence path, else None."""
    if not path.startswith(AUTHORED_EVIDENCE_DIRS) or "\\" in path or ".." in Path(path).parts:
        return None
    source = REPO / path
    try:
        if (source.is_symlink() or not source.is_file()
                or not source.resolve().is_relative_to(REPO.resolve())
                or source.stat().st_size > AUTHORED_EVIDENCE_MAX_BYTES):
            return None
    except OSError:
        return None
    return source


def _scratch(workspace, *, compact=False):
    base = Path(workspace).resolve() / '.agent_control/proofs'
    compact = compact or os.environ.get('NEYVIA_PROOF_COMPACT_ROOT') == '1'
    root = base / ('x-' + uuid.uuid4().hex[:12]) if compact else base / 'scratch' / uuid.uuid4().hex
    root.mkdir(parents=True)
    return root


def _local_arguments(arguments, root):
    for key, value in arguments.items():
        if key in {"path", "folder", "from", "to", "output", "source", "target"} and isinstance(value, str):
            path = Path(value)
            path = (path if path.is_absolute() else root / path).resolve()
            path.relative_to(root)
        if isinstance(value, dict):
            _local_arguments(value, root)


def manual_self_checks(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Each manual host owns its explicit empty broker, like supervised areas.
    # Never let a local inspection fall back to repository account settings.
    from .proof_credential_guard import prepare_broker_fixture
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    from .neyvia_manuals import records, document, resolve, unwrap, run, validate
    from .neyvia_workspace_tools import workspace_for
    from .native_tools import NativeToolRegistry
    from .ui_command_bus import bus_for
    bus_for(root).put("notes:folder", str(root / "notes"))
    (root / "notes").mkdir(exist_ok=True)
    (root / "proof.txt").write_text("Scratch proof\n", encoding="utf-8")
    (root / "exact.json").write_text('{"record":{"id":"000739","name":"Élodie"}}\n', encoding="utf-8")
    # Only explicitly reviewed local entries receive inputs. The files are real
    # scratch artifacts; no provider result or judgement decision is substituted.
    reviewed_inputs = {
        ("workspace", "files", "observer", "current"): {"path": "proof.txt"},
        ("workspace", "files", "procedure", "create-and-confirm"): {
            "path": "confirmed.txt", "content": "Exact scratch write: Élodie 000739\n"},
        ("workspace", "files", "procedure", "read-and-confirm"): {
            "path": "proof.txt", "phrase": "Scratch proof"},
        ("tools-depth", "tools", "observer", "file"): {"path": "proof.txt"},
        ("efficiency", "cascade", "procedure", "extract-and-confirm"): {
            "path": "exact.json", "field": "/record", "expectedJson": '{"id":"000739","name":"Élodie"}'},
        # A real scratch move, then undo, then a fresh stat of the original path.
        ("files", "overview", "procedure", "verify-effect-files-undo"): {
            "from": "undo-proof.txt", "to": "undo-proof-moved.txt", "originalName": "undo-proof.txt"},
    }
    (root / "undo-proof.txt").write_text("Scratch undo proof\n", encoding="utf-8")
    loaded = []
    for record in records():
        try:
            loaded.append((record, document(record)[1], None))
        except Exception as exc:
            loaded.append((record, None, exc))  # reported as a structure failure below
    constant_reads = {(record["id"], chapter_id) + key: paths
                      for record, manual, _ in loaded if manual
                      for chapter_id, chapter in manual["chapters"].items()
                      for key, paths in _constant_read_paths(chapter).items()}
    # Authored design reads use these exact sources, and authored evidence is
    # derived from the manuals' constant reads. Copy current bytes into the
    # confined workspace rather than widening its read boundary. Procedures
    # requiring a design judgement still stop at that explicit frontier.
    evidence = sorted({path for paths in constant_reads.values() for path in paths if _authored_evidence(path)})
    fixture_bindings = {}
    for relative in ("web/src/neyvia/next/nxThemes.css", "web/src/neyvia/next/nxTokens.css",
                     "web/src/neyvia/next/details/details.manifest.json",
                     "docs/evidence/placement-shots/receipt.json", *evidence):
        if relative in fixture_bindings:
            continue
        source_bytes = (REPO / relative).read_bytes()
        fixture_file = root / relative
        fixture_file.parent.mkdir(parents=True, exist_ok=True)
        fixture_file.write_bytes(source_bytes)
        fixture_bindings[relative] = {"source": relative,
                                      "sha256": hashlib.sha256(source_bytes).hexdigest()}
    service = workspace_for(root)
    registry = NativeToolRegistry(root)

    def dispatch(tool, arguments, action_id=""):
        if tool not in LOCAL_TOOLS:
            raise PermissionError("Self-check requires an explicit local fixture/authority for " + tool)
        _local_arguments(arguments, root)
        return registry.call(tool, arguments)

    rows = []
    visited = set()
    for record, manual, load_error in loaded:
        try:
            if load_error is not None:
                raise load_error
            validate(manual, registry)
            rows.append({"manual": record["id"], "kind": "grounding", "status": "passed"})
        except Exception as exc:
            rows.append({"manual": record["id"], "kind": "structure", "status": "failed", "error": str(exc)})
            continue
        for chapter_id, chapter in manual["chapters"].items():
            for kind, entries in (("observer", chapter["state"]), ("procedure", chapter["procedures"])):
                for identity, entry in entries.items():
                    row = {"manual": record["id"], "chapter": chapter_id, "kind": kind, "id": identity}
                    key = (record["id"], chapter_id, kind, identity)
                    visited.add(key)
                    bound = [fixture_bindings[path] for path in dict.fromkeys(constant_reads.get(key, []))
                             if path in fixture_bindings]
                    if kind == "procedure" and bound:
                        row["fixtureSources"] = bound
                    if key in SELF_REFERENTIAL_PROCEDURES:
                        row.update(status="skipped", reason=SELF_REFERENTIAL_PROCEDURES[key])
                        rows.append(row)
                        continue
                    try:
                        inputs = reviewed_inputs.get((record["id"], chapter_id, kind, identity), {})
                        if entry["inputs"].get("required") and not inputs:
                            raise PermissionError("Missing reviewed scratch inputs: " + ", ".join(entry["inputs"]["required"]))
                        if inputs:
                            from jsonschema import Draft202012Validator
                            Draft202012Validator(entry["inputs"]).validate(inputs)
                            row["fixtureInputs"] = inputs
                        if kind == "observer":
                            from jsonschema import Draft202012Validator
                            arguments = resolve(entry["args"], inputs, {}, root)
                            output = unwrap(dispatch(entry["tool"], arguments))
                            Draft202012Validator(entry["shape"]).validate(output)
                            if entry["tool"] == "workspace.read" and arguments.get("path") in fixture_bindings:
                                row["fixtureSource"] = fixture_bindings[arguments["path"]]
                        else:
                            tools = {chapter["actions"][step["action"]]["tool"] for step in entry["steps"] if "action" in step}
                            tools |= {chapter["checks"][step["check"]]["tool"] for step in entry["steps"] if step.get("check")}
                            if not tools <= LOCAL_TOOLS:
                                raise PermissionError("Missing scratch fixture/authority: " + ", ".join(sorted(tools - LOCAL_TOOLS)))
                            output = run(service, {"id": record["id"], "chapter": chapter_id, "procedure": identity,
                                                   "inputs": inputs}, registry, dispatch)
                            if output.get("status") == "judge":
                                raise PermissionError("Procedure requires an explicit judgement fixture")
                            if output.get("ok") is False:
                                raise RuntimeError(output.get("error") or output.get("reason") or "Procedure failed")
                        row["status"] = "passed"
                    except PermissionError as exc:
                        row.update(status="blocked", reason=str(exc))
                    except Exception as exc:
                        row.update(status="failed", error=str(exc)[:600])
                    rows.append(row)
    loaded_ids = {record["id"] for record, manual, _ in loaded if manual}
    for key in sorted(set(SELF_REFERENTIAL_PROCEDURES) - visited):
        if key[0] in loaded_ids:
            rows.append({"manual": key[0], "chapter": key[1], "kind": key[2], "id": key[3], "status": "failed",
                         "error": "Stale self-check scope exclusion: no such procedure"})
    return rows


def _selected_adapter_chapters(areas, chapters):
    if chapters is None:
        return None
    allowed = {'git', 'handoff', 'html', 'ocr', 'publication', 'sync', 'release'}
    if (not isinstance(chapters, (list, tuple)) or not chapters
            or any(not isinstance(chapter, str) or chapter not in allowed for chapter in chapters)
            or len(set(chapters)) != len(chapters)
            or set(areas or []) != {'proofs-b-adapters'}):
        raise ValueError('Adapter chapters require unique known chapters and only proofs-b-adapters')
    return list(chapters)


def run_verification(workspace, *, areas=None, include_manuals=True, adapter_chapters=None, timeout_seconds=1800, low_priority=False):
    """An embedded backend must never redirect scratch actions to its live UI bus.

    Use a fresh interpreter: UI bus/network policy/broker caches and environment
    overrides are process-scoped. No temporary mutation of host globals.
    """
    command = [sys.executable, str(REPO / "scripts/verify_proofs.py"), "--worker", "--root", str(Path(workspace).resolve())]
    adapter_chapters = _selected_adapter_chapters(areas, adapter_chapters)
    for area in areas or []:
        command += ["--area", area]
    if not include_manuals:
        command += ["--skip-manuals"]
    for chapter in adapter_chapters or []:
        command += ['--adapter-chapter', chapter]
    env = dict(os.environ)
    # Isolate home/account state without losing the interpreter's installed
    # dependencies. In particular, a Windows user-site follows APPDATA.
    dependency_paths = [path for path in sys.path if path and Path(path).is_dir()
                        and Path(path).name.lower() in {"site-packages", "dist-packages"}]
    configured = env.get("PYTHONPATH", "").split(os.pathsep)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(path for path in [*configured, *dependency_paths] if path))
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT"):
        env.pop(key, None)
    # Runtime discovery inside a proof must not consult the operator's saved
    # credentials. Keep the child's home state within the selected workspace.
    worker_home = Path(workspace).resolve() / ".agent_control/proofs/worker-home" / uuid.uuid4().hex
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR",
                "APPDATA", "LOCALAPPDATA", "NEYVIA_MANAGED_RUNTIME_ROOT", "TEMP", "TMP"):
        directory = worker_home / key.lower()
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    # Fixture services bind reviewed loopback ports. A startup check has no caller
    # to assign them, so default to the reviewed set unless a map is supplied.
    from .proof_ports import ALLOWED_ENV, PORT_ENV, INT3_PORT_MAP
    if PORT_ENV not in env:
        slots = sorted(set(INT3_PORT_MAP.values()))
        env[ALLOWED_ENV] = json.dumps(slots)
        env[PORT_ENV] = json.dumps({str(original): target for original, target in INT3_PORT_MAP.items()})
    if low_priority:
        env["NEYVIA_PROOF_LOW_PRIORITY"] = "1"
    env.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0")
    if timeout_seconds <= 0:
        raise ValueError("Verification timeout must be positive")
    # The expanded local journeys include real process-tree shutdown and lock
    # contention. Keep a hard deadline with enough room for those OS operations.
    scratch_password = secrets.token_urlsafe(24)
    env.update(GRAND_AGENT_ADMIN_PASSWORD=scratch_password, SYNTELOS_ACCOUNT_PASSWORD=scratch_password)
    from .subprocess_utils import capture_bounded_process
    completed = capture_bounded_process(command, cwd=REPO, env=env, input_text=None, timeout=timeout_seconds)
    (worker_home / "diagnostics.log").write_text(completed["stderr"].replace(scratch_password, "[redacted]"), encoding="utf-8")
    if completed["timedOut"]:
        raise RuntimeError("Proof worker exceeded its deadline; owned process tree stopped: "
                           + str(completed["processTreeStopped"]))
    if not completed["stdout"].strip():
        raise RuntimeError(worker_failure_message(completed, worker_home))
    try:
        return json.loads(completed["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(worker_failure_message(completed, worker_home, "wrote an unreadable receipt (" + str(exc) + ")")) from exc


def worker_failure_message(completed, worker_home, what="failed before writing a receipt"):
    """Name the exit status and retained diagnostics; empty stderr must never be the whole message."""
    code = completed["returncode"]
    if isinstance(code, int) and code > 0x7FFFFFFF:
        code -= 1 << 32
    detail = (completed["stderr"].strip() or "no stderr")[-1000:]
    hint = (" (Windows status 0x%08X: the worker was terminated or crashed before Python reported anything)"
            % (code & 0xFFFFFFFF)) if os.name == "nt" and isinstance(code, int) and code < 0 else ""
    return (f"Proof worker {what}: exit code {code}{hint}; stdout {len(completed['stdout'])} bytes; "
            f"stderr: {detail}; diagnostics kept in {worker_home}")


def _run_area(area, area_root, *, adapter_chapters=None):
    """Run one host-owned adapter in its own interpreter and disposable state."""
    if area in ADAPTERS:
        if adapter_chapters is not None:
            chapters = _selected_adapter_chapters([area], adapter_chapters)
            return {'area': area, **importlib.import_module(ADAPTERS[area]).self_check_chapters(area_root, chapters)}
        return {"area": area, **importlib.import_module(ADAPTERS[area]).self_check(area_root)}
    if area not in RUNNERS:
        raise ValueError("Unknown proof area: " + area)
    from .subprocess_utils import capture_bounded_process
    command = ["node", str(REPO / RUNNERS[area]), "--root", str(area_root), "--json"]
    env = dict(os.environ)
    # A source checkout and its disposable proof state may live on different
    # volumes. The supervising host owns and validates this exact area root.
    env["NEYVIA_PROOF_STATE_ROOT"] = str(Path(area_root).resolve())
    captured = capture_bounded_process(command, cwd=REPO, env=env, input_text=None,
                                       timeout=240 if area == "proofs-b-browser" else 60)
    if captured["timedOut"]:
        raise RuntimeError("Browser proof exceeded its deadline; owned process tree stopped: "
                           + str(captured["processTreeStopped"]))
    try:
        result = json.loads(captured["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Proof runner {area} returned no JSON (exit {captured['returncode']}): "
                           + captured["stderr"][-1000:]) from exc
    return {"area": area, **result, **({"ok": False, "exitCode": captured["returncode"]} if captured["returncode"] else {})}


def _supervised_area(workspace, area, area_root, *, adapter_chapters=None):
    from .subprocess_utils import capture_bounded_process
    env = dict(os.environ)
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR",
                "APPDATA", "LOCALAPPDATA", "NEYVIA_MANAGED_RUNTIME_ROOT", "TEMP", "TMP"):
        directory = area_root / "worker-home" / key.lower()
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    command = [sys.executable, str(REPO / "scripts/verify_proofs.py"), "--root", str(Path(workspace).resolve()),
               "--area-worker", area, "--area-root", str(area_root)]
    for chapter in adapter_chapters or []:
        command += ['--adapter-chapter', chapter]
    captured = capture_bounded_process(command, cwd=REPO, env=env, input_text=None, timeout=300)
    (area_root / "diagnostics.log").write_text(captured["stderr"], encoding="utf-8")
    (area_root / "executor-stdout.log").write_text(captured["stdout"], encoding="utf-8")
    (area_root / "process-result.json").write_text(json.dumps({
        "returncode": captured["returncode"], "timedOut": captured["timedOut"],
        "processTreeStopped": captured["processTreeStopped"],
        "stdoutBytes": len(captured["stdout"].encode("utf-8")),
        "stderrBytes": len(captured["stderr"].encode("utf-8")),
    }, indent=2) + "\n", encoding="utf-8")
    if captured["timedOut"]:
        raise RuntimeError("Proof area exceeded its 300-second deadline; owned process tree stopped: "
                           + str(captured["processTreeStopped"]))
    try:
        result = json.loads(captured["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Proof area failed before writing JSON (exit {captured['returncode']}): "
                           + captured["stderr"][-1500:]) from exc
    if result.get("area") != area:
        raise ValueError("Proof child returned another area's receipt")
    if captured["returncode"] and result.get("ok"):
        raise ValueError("Proof child claimed success after a failed process exit")
    return result


def _run_verification(workspace, *, areas=None, include_manuals=True, adapter_chapters=None):
    started = time.perf_counter()
    adapter_chapters = _selected_adapter_chapters(areas, adapter_chapters)
    from .proof_credential_guard import install as install_authority_guard
    install_authority_guard(workspace)
    initial_sources = source_bindings()
    from .neyvia_inception import _declared_run_root
    c8_base = _declared_run_root() or REPO / '.agent_control/proofs/C8'
    c8_host = (os.environ.get('NEYVIA_C8_SOURCE') and set(areas or []) <= {'proofs-b-engine', 'proofs-b-harness'}
               and Path(workspace).resolve().is_relative_to(c8_base))
    root = _scratch(workspace, compact=adapter_chapters is not None or bool(c8_host))
    trace_stream = None
    if os.environ.get("NEYVIA_PROOF_PROGRESS") == "1":
        import faulthandler
        trace_stream = (root / "worker-stacks.log").open("w", encoding="utf-8")
        faulthandler.dump_traceback_later(120, repeat=True, file=trace_stream)
    from .proof_credential_guard import self_check as authority_self_check
    authority_proof = authority_self_check(root / "authority")
    results = []
    files = manifest_files()
    manifests = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    wanted = set(areas or ADAPTERS.keys() | RUNNERS.keys())
    for area in sorted(wanted):
        area_started = time.perf_counter()
        if os.environ.get("NEYVIA_PROOF_PROGRESS") == "1":
            print("proof area started: " + area, file=sys.stderr, flush=True)
        area_root = root / area
        area_root.mkdir()
        try:
            results.append(_supervised_area(workspace, area, area_root, adapter_chapters=adapter_chapters))
        except ModuleNotFoundError as exc:
            results.append({"area": area, "ok": False, "status": "blocked", "reason": str(exc)})
        except Exception as exc:
            import traceback
            frames = [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                      for frame in traceback.extract_tb(exc.__traceback__)]
            results.append({"area": area, "ok": False, "status": "failed", "error": str(exc)[-1000:],
                            "exceptionType": type(exc).__name__, "frames": frames})
        from .durability import atomic_write_json
        atomic_write_json(area_root / "contract-receipt.json", results[-1])
        if os.environ.get("NEYVIA_PROOF_PROGRESS") == "1":
            print(f"proof area finished: {area} {time.perf_counter()-area_started:.1f}s ok={results[-1].get('ok')}", file=sys.stderr, flush=True)
    if os.environ.get("NEYVIA_PROOF_PROGRESS") == "1":
        print("proof manual checks started", file=sys.stderr, flush=True)
    manual_rows = manual_self_checks(root / "manuals") if include_manuals else []
    if os.environ.get("NEYVIA_PROOF_PROGRESS") == "1":
        print("proof manual checks finished", file=sys.stderr, flush=True)
    # Reviewed domain fixtures run the actual manual runner, including required
    # inputs and judgement resumes. Reuse that evidence rather than reclassify
    # the same procedures as blocked merely because a generic fixture is absent.
    for result in results:
        for receipt in result.get("manualReceipts", []):
            if not receipt.get("ok"):
                continue
            for row in manual_rows:
                kind = "procedure" if "procedure" in receipt else "observer"
                if (row["manual"] == receipt["id"] and row.get("chapter") == receipt.get("chapter")
                        and row["kind"] == kind and row.get("id") == receipt[kind]):
                    row.update(status="passed", fixtureArea=result["area"])
                    if kind == "procedure":
                        row.update(runId=receipt["runId"], checks=receipt["checks"])
                    row.pop("reason", None)
    failures = [r for r in results if not r.get("ok")] + [r for r in manual_rows if r["status"] == "failed"]
    blocked = [r for r in manual_rows if r["status"] == "blocked"]
    # Skipped rows are out of this self-check's scope (see
    # SELF_REFERENTIAL_PROCEDURES): never passed, reported with their reason.
    skipped = [r for r in manual_rows if r["status"] == "skipped"]
    # Area contracts whose separately prepared prerequisite (pinned Syncthing,
    # admitted headless Obscura) is absent are listed by the area as skipped
    # with the reason. They are in scope but unexercised: never passed, and
    # they keep `complete` false.
    skipped_contracts = [{"area": result.get("area"), **row} for result in results
                         for row in result.get("skipped") or [] if isinstance(row, dict)]
    final_sources = source_bindings()
    source_stable = initial_sources == final_sources
    # Recheck existing mappings against this real run without rewriting another
    # track's coverage rows. Original manifest/receipt integrity is still required.
    coverage = coverage_report(revalidation={"sourceBindings": final_sources,
        "sourceStable": source_stable, "areas": results})
    source_stable = source_stable and final_sources == source_bindings()
    contracts_ok = not failures
    contracts_ok = contracts_ok and not coverage["uncoveredDeletedFiles"] and not coverage["invalidMappings"]
    contracts_ok = contracts_ok and source_stable
    complete = (contracts_ok and not blocked and not skipped_contracts and coverage["coveragePercent"] == 100
        and coverage["remainingScopedFiles"] == 0 and not coverage["newScopedFiles"]
        and not coverage["inventoryError"] and not coverage["unboundMappings"] and include_manuals
        and adapter_chapters is None and wanted == set(ADAPTERS) | set(RUNNERS))
    report = {"schema": "neyvia.proofs.v1", "at": datetime.now(timezone.utc).isoformat(), "ok": complete,
        "contractsOk": contracts_ok, "complete": complete, "scratchRoot": str(root), "areas": results,
        "manualSelfChecks": manual_rows, "coverage": coverage, "failures": len(failures), "blocked": len(blocked),
        "skipped": len(skipped), "skippedContracts": skipped_contracts,
        "durationMs": round((time.perf_counter() - started) * 1000), "oldSuiteReferenceMs": 55 * 60 * 1000,
        "sourceBindings": final_sources, "sourceStable": source_stable, "sourceDigestAlgorithm": "utf8-LF-sha256",
        "timingScope": "Partial contract coverage; not an equivalent full-suite speed comparison"}
    report["authorityProof"] = authority_proof
    if adapter_chapters is not None:
        report.update(selectedAdapterChapters=adapter_chapters, partial=True)
    from .durability import atomic_write_json
    atomic_write_json(root / "receipt.json", report)
    atomic_write_json(Path(workspace) / ".agent_control/proofs/latest.json", report)
    if os.environ.get("NEYVIA_PROOF_PROGRESS") == "1":
        faulthandler.cancel_dump_traceback_later()
        trace_stream.close()
    return report


def coverage_report(*, revalidation=None, current_runs=(), verified_sources=None):
    from .proof_contracts import file_digest
    from .proof_coverage import revalidated_cases, evidence_revalidated
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    path = REPO / "config/proofs/test-inventory.json"
    baseline = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"files": []}
    files = baseline["files"]
    total = sum(len(row["cases"]) for row in files)
    known = catalog()[1]
    digests, documents, claims, invalid, unbound, mapped = {}, {}, {}, [], [], 0
    manifest_revalidated_cases = []
    current_sources = source_bindings()
    current_binding_digest = source_binding_digest(current_sources)
    if revalidation is None and current_runs:
        revalidation = {"areas": current_runs, "sourceBindings": verified_sources,
                        "sourceStable": verified_sources == current_sources}
    if revalidation is None:
        try:
            revalidation = json.loads((REPO / ".agent_control/proofs/latest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            revalidation = {}
    # E renewal attests immutable coverage using a hash-bound current-source run.
    if not revalidation.get("sourceBindings") == current_sources:
        renewal_path = REPO / "config/proof-coverage-revalidation.json"
        if renewal_path.is_file():
            try:
                renewal = json.loads(renewal_path.read_text(encoding="utf-8"))
                renewal_receipt = (REPO / renewal["receipt"]).resolve()
                renewal_receipt.relative_to(REPO)
                if file_digest(renewal_receipt) == renewal["sha256"]:
                    renewed = json.loads(renewal_receipt.read_text(encoding="utf-8"))
                    if renewed.get("sourceStable") is True and renewed.get("sourceBindings") == current_sources:
                        revalidation = renewed
            except (KeyError, ValueError, OSError):
                pass
    fresh = {}
    if revalidation.get("sourceStable") is True and revalidation.get("sourceBindings") == current_sources:
        for area in revalidation.get("areas", []):
            if area.get("ok") is True:
                fresh[area["area"]] = {item if isinstance(item, str) else item["id"]
                    for item in area.get("contracts", [])
                    if isinstance(item, str) or item.get("status", "passed") == "passed"}
    revalidated_contracts = set().union(*fresh.values()) if fresh else set()
    revalidated = []
    refreshed = revalidated_cases(current_sources)
    def digest(path):
        if path not in digests:
            digests[path] = file_digest(path)
        return digests[path]
    def document(path):
        if path not in documents:
            documents[path] = json.loads(path.read_text(encoding="utf-8"))
        return documents[path]
    def contract_spec(value):
        spec = {key: value[key] for key in ("id", "phase", "claim", "checkedAt", "impact") if key in value}
        try:
            spec["claim"] = spec["claim"].encode("cp1252").decode("utf-8")
        except (UnicodeError, KeyError):
            pass
        return spec
    for row in files:
        for case in row["cases"]:
            if not (case.get("contract_ids") and case.get("checked_at") and case.get("self_checks")):
                continue
            try:
                receipt = (REPO / case["self_checks"][0].partition("#")[0]).resolve()
                manifest = (REPO / case["manifest"]).resolve()
                receipt.relative_to(REPO)
                manifest.relative_to(REPO)
                if (not set(case["contract_ids"]) <= known.keys() or digest(receipt) != case["receipt_sha256"]):
                    raise ValueError("Contract or evidence changed; run and record fresh coverage")
                if digest(manifest) != case["manifest_sha256"]:
                    # Appending a batch may change the manifest bytes while an
                    # earlier case's mapping remains exactly the same. Accept
                    # that mapping only after its contracts pass in this run.
                    # Retirement still requires recording the new hashes.
                    current_manifest = document(manifest)
                    matches = [entry for entry in current_manifest.get("coverage", [])
                               if entry.get("case_id") == case["id"]
                               or (not entry.get("case_id")
                                   and entry.get("test") == row["path"]
                                   and entry.get("case") == case["name"])]
                    area, _, procedure = case["self_checks"][0].partition("#areas/")[2].partition("/")
                    if (len(matches) != 1 or current_manifest.get("area") != area
                        or matches[0].get("test") != row["path"]
                        or matches[0].get("case") != case["name"]
                        or matches[0].get("contracts") != case["contract_ids"]
                        or matches[0].get("checkedAt") != case["checked_at"]
                        or matches[0].get("procedure", "self_check") != procedure
                        or not set(case["contract_ids"]) <= revalidated_contracts):
                        raise ValueError("Manifest mapping changed; run and record fresh coverage")
                    manifest_revalidated_cases.append(case["id"])
                binding = case.get("source_binding_sha256")
                if not binding and case.get("source_bindings"):
                    binding = source_binding_digest(case["source_bindings"])
                if not binding:
                    unbound.append(case["id"])
                elif binding != current_binding_digest:
                    original = document(receipt)
                    declared = document(manifest)
                    area = declared["area"]
                    if manifest not in claims:
                        claims[manifest] = {row["id"]: contract_spec(row) for row in declared.get("contracts", [])}
                    original_claims = claims[manifest]
                    if (original.get("sourceStable") is not True
                        or binding != source_binding_digest(original.get("sourceBindings", {}))
                        or (not set(case["contract_ids"]) <= fresh.get(area, set())
                            and not evidence_revalidated(case, refreshed))
                        or any(original_claims.get(identity) != contract_spec(known[identity])
                               for identity in case["contract_ids"])):
                        raise ValueError("Proof source changed; run and record fresh coverage")
                    revalidated.append(case["id"])
                mapped += 1
            except (KeyError, ValueError, OSError) as exc:
                invalid.append({"case": case["id"], "reason": str(exc)})
    deleted = [row["path"] for row in files if not (REPO / row["path"]).exists()]
    uncovered_deleted = [row["path"] for row in files if not (REPO / row["path"]).exists() and
        row.get("disposition") not in {"obsolete", "dead-code"} and (not row["cases"] or any(not (c.get("contract_ids") and c.get("checked_at") and c.get("self_checks")) for c in row["cases"]))]
    inventory_error, new_files = None, []
    try:
        current = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO, capture_output=True, text=True, timeout=10, check=True, **hidden_windows_subprocess_kwargs())
        scoped = {p for p in current.stdout.split("\0") if p and (p.startswith("tests/") or p.endswith((".test.js", ".test.mjs"))) and (REPO / p).is_file()}
        new_files = sorted(scoped - {row["path"] for row in files})
    except (OSError, subprocess.SubprocessError) as exc:
        inventory_error = type(exc).__name__
    return {"baselineFiles": len(files), "baselineCases": total, "mappedCases": mapped,
        "coveragePercent": round(100 * mapped / total, 3) if total else 0,
        "deletedFiles": len(deleted), "uncoveredDeletedFiles": uncovered_deleted,
        "manualContracts": len(known), "pendingFiles": sum(row.get("disposition") == "pending" for row in files),
        "remainingScopedFiles": len(files) - len(deleted), "newScopedFiles": new_files,
        "invalidMappings": invalid, "unboundMappings": unbound, "inventoryError": inventory_error,
        "revalidatedMappings": revalidated, "revalidatedCases": revalidated, "manifestRevalidatedCases": manifest_revalidated_cases}
