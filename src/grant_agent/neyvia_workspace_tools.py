"""Model tools for Neyvia's own workspace; changes and commands share one bus."""
from __future__ import annotations

import json
import atexit
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .ui_command_bus import bus_for, state_root


TEXT = {"type": "string"}
BOOL = {"type": "boolean"}
PANE_KINDS = ("diff", "file", "artifact", "terminal", "browser", "mission", "replay", "builder", "accounts", "runtime", "settings", "preview", "outputs", "perception", "agentview", "sessions", "usage", "parallel", "agents")
DEFINITIONS = [
    ("folder.create", "Create a project folder; first use of each root needs user approval.", {"path": TEXT, "name": TEXT, "git": BOOL}, ["path", "name"]),
    ("folder.list", "List registered project folders.", {}, []),
    ("folder.open", "Open a registered project folder.", {"path": TEXT}, ["path"]),
    ("project.create", "Create a named project in a user-approved root.", {"name": TEXT, "path": TEXT, "template": {"type": "string", "enum": ["empty", "git"]}}, ["name"]),
    ("session.new", "Start a chat; reuse requestId for retries, choose a new ID for new intent. Write permission needs approval.", {"app": TEXT, "folder": TEXT, "prompt": TEXT, "model": TEXT, "permissionMode": TEXT, "requestId": TEXT}, ["app", "folder", "prompt", "requestId"]),
    ("session.move", "Reversibly move a chat to a project or No folder.", {"id": TEXT, "project": {"type": ["string", "null"]}}, ["id"]),
    ("session.rename", "Reversibly rename a chat.", {"id": TEXT, "title": TEXT}, ["id", "title"]),
    ("session.pin", "Pin or unpin a chat.", {"id": TEXT, "pinned": BOOL}, ["id"]),
    ("session.archive", "Archive or restore a chat without deleting provider data.", {"id": TEXT, "archived": BOOL}, ["id"]),
    ("sidebar.tidy", "Preview the cleanup summary, then pass confirmed=true after the user confirms. Fresh worktree and job checks protect every archive. undoLast=true restores everything the last tidy archived.", {"dryRun": BOOL, "confirmed": BOOL, "undoLast": BOOL}, []),
    ("sidebar.policy", "Read or save workspace-local cleanup settings; automatic archiving is off until enabled.", {"policy": {"type": "object", "properties": {"noFolderDays": {"type": "integer"}, "projectDays": {"type": "integer"}, "tidyThreshold": {"type": "integer"}, "autoArchive": BOOL}}}, []),
    ("pane.show", "Request a workspace pane through the UI bus. outputs is the shared output panel; perception uses a typed image/file/browser/window target. preview uses an owner-allowed CUA session id. A rendered UI acknowledgement proves opening.", {"kind": {"type": "string", "enum": list(PANE_KINDS)}, "target": TEXT}, ["kind", "target"]),
    ("view.layout", "Choose Calm, Workshop or Grove density.", {"level": {"type": "string", "enum": ["calm", "workshop", "grove"]}}, ["level"]),
    ("schedule.create", "Persist a follow-up; reuse requestId for retries. when is an ISO timestamp with timezone.", {"when": TEXT, "prompt": TEXT, "scope": {"type": "object", "x-empty-text-is-empty-object": True, "description": "Empty scope means notification only, including an empty text transport wrapper."}, "requestId": TEXT}, ["when", "prompt", "scope", "requestId"]),
    ("schedule.list", "List persistent follow-ups and their outcomes.", {}, []),
    ("schedule.cancel", "Cancel a pending follow-up.", {"id": TEXT}, ["id"]),
    ("notify", "Show a notification in Neyvia.", {"message": TEXT, "msg": TEXT, "level": {"type": "string", "enum": ["info", "success", "warning", "error"]}}, []),
]
from .neyvia_session_clustering import DEFINITIONS as CLUSTER_DEFINITIONS
DEFINITIONS.extend(CLUSTER_DEFINITIONS)
from .neyvia_sidebar import DEFINITIONS as SIDEBAR_DEFINITIONS
DEFINITIONS.extend(SIDEBAR_DEFINITIONS)
from .neyvia_manuals import DEFINITIONS as MANUAL_DEFINITIONS
DEFINITIONS.extend(MANUAL_DEFINITIONS)
from .neyvia_cl import DEFINITIONS as CL_DEFINITIONS
DEFINITIONS.extend(CL_DEFINITIONS)
from .neyvia_modules import DEFINITIONS as MODULE_DEFINITIONS
from .module_plugins import definitions as mod_definitions, mutability as mod_mutability
DEFINITIONS.extend(MODULE_DEFINITIONS)
DEFINITIONS.extend(mod_definitions())
from .source_marketplace import DEFINITIONS as SOURCE_MARKETPLACE_DEFINITIONS
DEFINITIONS.extend(SOURCE_MARKETPLACE_DEFINITIONS)
from .neyvia_missions import DEFINITIONS as MISSION_DEFINITIONS
DEFINITIONS.extend(MISSION_DEFINITIONS)
from .neyvia_image_tools import DEFINITIONS as IMAGE_DEFINITIONS
DEFINITIONS.extend(IMAGE_DEFINITIONS)
from .neyvia_lab_board import DEFINITIONS as LAB_DEFINITIONS
DEFINITIONS.extend(LAB_DEFINITIONS)
from .neyvia_evolver import DEFINITIONS as EVOLVER_DEFINITIONS
DEFINITIONS.extend(EVOLVER_DEFINITIONS)
from .neyvia_runtime import DEFINITIONS as RUNTIME_DEFINITIONS
DEFINITIONS.extend(RUNTIME_DEFINITIONS)
from .neyvia_view_tools import DEFINITIONS as VIEW_DEFINITIONS
DEFINITIONS.extend(VIEW_DEFINITIONS)
from .neyvia_time_tools import DEFINITIONS as TIME_DEFINITIONS
DEFINITIONS.extend(TIME_DEFINITIONS)
from .neyvia_run_watches import DEFINITIONS as WATCH_DEFINITIONS
DEFINITIONS.extend(WATCH_DEFINITIONS)
from .neyvia_attention import DEFINITIONS as ATTENTION_DEFINITIONS
DEFINITIONS.extend(ATTENTION_DEFINITIONS)
from .neyvia_awareness import DEFINITIONS as AWARENESS_DEFINITIONS
DEFINITIONS.extend(AWARENESS_DEFINITIONS)
from .prompt_amplifier import DEFINITIONS as PROMPT_DEFINITIONS
DEFINITIONS.extend(PROMPT_DEFINITIONS)
from .claude_code_mods import DEFINITIONS as CLAUDE_MOD_DEFINITIONS
DEFINITIONS.extend(CLAUDE_MOD_DEFINITIONS)
from .neyvia_mobile_studio import DEFINITIONS as MOBILE_DEFINITIONS
DEFINITIONS.extend(MOBILE_DEFINITIONS)
from .neyvia_connections import DEFINITIONS as CONNECTION_DEFINITIONS
DEFINITIONS.extend(CONNECTION_DEFINITIONS)
from .neyvia_app_sdk import DEFINITIONS as APP_SDK_DEFINITIONS
DEFINITIONS.extend(APP_SDK_DEFINITIONS)
from .neyvia_agents_tools import DEFINITIONS as AGENTS_DEFINITIONS
DEFINITIONS.extend(AGENTS_DEFINITIONS)
from .neyvia_conductor import DEFINITIONS as CONDUCTOR_DEFINITIONS
DEFINITIONS.extend(CONDUCTOR_DEFINITIONS)
from .neyvia_parallel import DEFINITIONS as PARALLEL_DEFINITIONS
DEFINITIONS.extend(PARALLEL_DEFINITIONS)
from .neyvia_comments import DEFINITIONS as COMMENTS_DEFINITIONS
DEFINITIONS.extend(COMMENTS_DEFINITIONS)
from .neyvia_dictation import DEFINITIONS as DICTATION_DEFINITIONS
DEFINITIONS.extend(DICTATION_DEFINITIONS)
from .neyvia_panes import DEFINITIONS as PANE_DEFINITIONS
DEFINITIONS.extend(PANE_DEFINITIONS)
from .neyvia_voice import DEFINITIONS as VOICE_DEFINITIONS
DEFINITIONS.extend(VOICE_DEFINITIONS)
from .neyvia_nightshift import DEFINITIONS as NIGHTSHIFT_DEFINITIONS
DEFINITIONS.extend(NIGHTSHIFT_DEFINITIONS)
from .neyvia_autopilot import DEFINITIONS as AUTOPILOT_DEFINITIONS
DEFINITIONS.extend(AUTOPILOT_DEFINITIONS)
from .neyvia_efficiency import DEFINITIONS as EFFICIENCY_DEFINITIONS
DEFINITIONS.extend(EFFICIENCY_DEFINITIONS)
from .neyvia_laya_capabilities import DEFINITIONS as LAYA_CAPABILITY_DEFINITIONS
DEFINITIONS.extend(LAYA_CAPABILITY_DEFINITIONS)
from .neyvia_scroll import DEFINITIONS as SCROLL_DEFINITIONS
DEFINITIONS.extend(SCROLL_DEFINITIONS)
from .neyvia_documents import DEFINITIONS as DOCUMENT_DEFINITIONS, READ as DOCUMENT_READS
DEFINITIONS.extend(DOCUMENT_DEFINITIONS)
from .neyvia_outputs import DEFINITIONS as OUTPUT_DEFINITIONS
DEFINITIONS.extend(OUTPUT_DEFINITIONS)
from .neyvia_perception import DEFINITIONS as PERCEPTION_DEFINITIONS
DEFINITIONS.extend(PERCEPTION_DEFINITIONS)
from .neyvia_browser import DEFINITIONS as BROWSER_DEFINITIONS
DEFINITIONS.extend(BROWSER_DEFINITIONS)
from .neyvia_video import DEFINITIONS as VIDEO_DEFINITIONS, mutability as video_mutability
DEFINITIONS.extend(VIDEO_DEFINITIONS)
from .neyvia_gamedev import DEFINITIONS as GAMEDEV_DEFINITIONS
DEFINITIONS.extend(GAMEDEV_DEFINITIONS)
from .neyvia_cua import DEFINITIONS as CUA_DEFINITIONS
DEFINITIONS.extend(CUA_DEFINITIONS)
from .neyvia_settings import DEFINITIONS as SETTINGS_DEFINITIONS
DEFINITIONS.extend(SETTINGS_DEFINITIONS)
from .neyvia_remote import DEFINITIONS as REMOTE_DEFINITIONS
DEFINITIONS.extend(REMOTE_DEFINITIONS)
from .neyvia_inception import DEFINITIONS as INCEPTION_DEFINITIONS
DEFINITIONS.extend(INCEPTION_DEFINITIONS)
from .neyvia_language import DEFINITIONS as LANGUAGE_DEFINITIONS
DEFINITIONS.extend(LANGUAGE_DEFINITIONS)
from .task_feedback import DEFINITIONS as FEEDBACK_DEFINITIONS
DEFINITIONS.extend(FEEDBACK_DEFINITIONS)
from .neyvia_memory_tools import DEFINITIONS as MEMORY_DEFINITIONS
DEFINITIONS.extend(MEMORY_DEFINITIONS)
from .neyvia_agentview import DEFINITIONS as AGENTVIEW_DEFINITIONS
DEFINITIONS.extend(AGENTVIEW_DEFINITIONS)
DEFINITIONS.extend([
    ("research.answer", "Research a public question using Search, non-stealth Obscura, LAYA and the explicit Luna cascade; save source and provider receipts in the selected workspace.",
     {"question": {"type": "string", "minLength": 1}, "obscuraPort": {"type": "integer", "minimum": 1024, "maximum": 65535},
      "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 600}, "rounds": {"type": "integer", "minimum": 1, "maximum": 5}}, ["question", "obscuraPort"]),
    ("research.journey", "Answer a public question through Neyvia's own tools: no-key web.search, web.fetch (optional non-stealth Obscura for pages refusing plain HTTP), web.dedupe, web.passages, web.cite and an extractive or explicit citation-only Sol answer whose citations are re-verified; saves a timed receipt.",
     {"question": {"type": "string", "minLength": 1, "maxLength": 2000}, "obscuraPort": {"type": "integer", "minimum": 1024, "maximum": 65535},
      "maxSources": {"type": "integer", "minimum": 1, "maximum": 8}, "vertical": {"type": "string", "enum": ["web", "scholarly", "code", "encyclopedia"]},
      "answerModel": {"type": "string", "enum": ["extractive", "gpt-6.1-sol"]}, "timeoutSeconds": {"type": "integer", "minimum": 10, "maximum": 600},
      "requestId": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,63}$"}}, ["question"]),
    ("research.receipt", "Read a saved research receipt confined to the selected workspace; inspect status and source evidence before claiming success.",
     {"path": {"type": "string", "minLength": 1}}, ["path"]),
])


def harness_mode(app: str, mode: str) -> str:
    """Translate our ceiling to the selected adapter's exact permission vocabulary."""
    if app in {"claude", "claude-code"}:
        mode = {"read-only": "plan", "workspace": "acceptEdits", "workspace-write": "acceptEdits",
                "full": "bypassPermissions", "full-access": "bypassPermissions", "default": "manual"}.get(mode, mode)
        if mode not in {"plan", "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions"}:
            raise ValueError("Unsupported Claude permission mode")
    elif app == "codex":
        from .connected_sessions.codex_items import PERMISSION_MODES
        mode = {"read-only": "ask", "workspace": "auto", "workspace-write": "auto", "full-access": "full"}.get(mode, mode)
        if mode not in PERMISSION_MODES:
            raise ValueError("Unsupported Codex permission mode")
    elif app == "neyvia":
        if mode not in {"read-only", "workspace", "full-access"}:
            raise ValueError("Unsupported Neyvia permission mode")
    elif app == "opencode":
        mode = {"plan": "read-only", "workspace-write": "workspace", "full": "full-access"}.get(mode, mode)
        if mode not in {"read-only", "workspace", "full-access"}:
            raise ValueError("Unsupported OpenCode permission mode")
    else:
        raise ValueError("Unknown harness")
    return mode


def tool_specs(spec_type, root=None):
    return [spec_type(name="neyvia." + name, description=description, category="neyvia",
                      input_schema={"type": "object", "properties": props, **({"required": required} if required or name not in {"cua.state", "cua.windows", "cua.log"} else {})},
                      mutability_class="external_action" if name in {"scene.improve", "connections.install", "connections.connect", "connections.prove"} else
                      "read" if name in {"activity", "claude.sessions", "connections.inspect", "nightshift.tasks", "nightshift.task", "nightshift.summary", "agents.overview", "agents.deliveries"} else
                      "read" if name == "comments.list" else
                      "external_action" if name == "comments.send" else
                      "artifact_write" if name.startswith("comments.") else
                      "external_action" if name.startswith("parallel.") and name != "parallel.state" else
                      "artifact_write" if name in {"scene.episode", "laya.glance_learn", "laya.glance_lesson"} else
                      "read" if name in {"scene.vocabulary", "laya.glance_contracts", "laya.glance_proof", "scene.transcribe", "laya.judge", "laya.glance"} else
                      video_mutability(name) if name.startswith("video.") else
                      "artifact_write" if name in {"browser.capture", "browser.site.manual", "view.place", "research.journey"} else
                      "external_action" if name.startswith("browser.") and name not in {"browser.state", "browser.history", "browser.downloads", "browser.decide", "browser.observe", "browser.reader", "browser.permissions", "browser.receipt", "browser.wait"} else
                      "external_action" if name in {"evolver.run", "scroll.generate", "scroll.concepts", "research.answer"} else
                      "read" if name in {"research.receipt", "gamedev.project_status"} else
                      "read" if name == "efficiency.laya_verify" else
                      "read" if name in {"scroll.state", "scroll.stats", "scroll.job", "scroll.validate", "verify.edges.status"} else
                      "artifact_write" if name.startswith("scroll.") else
                      "read" if name in DOCUMENT_READS else
                      "artifact_write" if name.startswith("documents.") else
                      "read" if name == "prompt.get" else
                      "artifact_write" if name.startswith("prompt.") else
                      "read" if name in {"evolver.lineage", "evolver.receipt", "evolver.job", "evolver.genome"} else
                      "read" if name in {"browser.state", "browser.history", "browser.downloads", "browser.decide", "browser.observe", "browser.reader", "browser.permissions", "browser.receipt", "browser.wait"} else
                      "read" if name == "perception.browser.observe" else
                      "external_action" if name in {"perception.browser.open", "perception.browser.action", "perception.browser.close"} else
                      "artifact_write" if name in {"gamedev.setup", "gamedev.action", "image.crop", "image.resize", "image.composite", "image.export"} else
                      "external_action" if name in {"image.generate", "mobile.build", "mobile.install", "cua.action", "cua.flow"} else
                      "artifact_write" if name == "cua.adapt" else
                      "artifact_write" if name in {"mobile.create", "mobile.simulate", "app_sdk.new", "app_sdk.build"} else
                      "read" if name in {"app_sdk.describe", "app_sdk.state", "app_sdk.toolchain"} else
                      "read" if name.startswith("inception.") else
                      "external_action" if name in {"app_sdk.verify", "app_sdk.action"} else
                      "artifact_write" if name in {"feedback.submit", "lessons.revert", "memory.remember", "memory.correct", "memory.forget"} else
                      "read" if name.startswith("memory.") else
                      "read" if name in {"marketplace.list", "marketplace.get", "marketplace.read"} else
                      "external_action" if name in {"marketplace.install", "marketplace.update"} else
                      "artifact_write" if name == "marketplace.set" else
                      mod_mutability(name, root) if name.startswith("mod.") else
                      "artifact_write" if name == "modules.set" else
                      "read" if name.startswith("modules.") else
                      "read" if name.startswith("time.") or name.endswith((".list", ".index", ".load", ".state", ".read")) or name in {"feedback.get", "state", "remote.windows", "remote.snapshot", "remote.log", "cua.windows", "cua.inspect", "cua.capture", "cua.log", "cua.wait", "cua.verify", "mobile.status", "mobile.verify", "dictation.status", "voice.commands", "artifact.get", "perception.observe", "perception.project", "perception.check", "settings.get", "settings.network_check", "language.check"} else "none",
                      capabilities=("neyvia." + name,), parallel_safe=False)
            for name, description, props, required in {row[0]: row for row in [*DEFINITIONS, *mod_definitions(root)]}.values()]


class WorkspaceTools:
    def __init__(self, root: Path, backend=None):
        self.bus = bus_for(root)
        from .local_network_policy import install as install_network_policy
        install_network_policy(self.bus.root, owner=self)
        self.backend = backend
        self.lock = threading.RLock()
        self.image_lock = threading.RLock()
        self.image_generation = None
        self.wake = threading.Event()
        self._timer = None
        self._usage_broker = None
        self.closed = threading.Event()
        self._watch_event_lock = threading.Lock()
        self._watch_events = {}
        self._watch_targets = set()
        atexit.register(self.close)
        with self.bus.connect() as db:
            active = db.execute("SELECT value FROM state WHERE key LIKE 'watch:%' AND json_extract(value,'$.status') IN ('armed','firing')").fetchall()
            self._watch_targets = {json.loads(row[0])["runId"] for row in active}
            self._watching = bool(active)

    def broker(self):
        from .connected_sessions.broker import broker_for
        if self.backend is None:
            raise RuntimeError("Session launches must be sent to the Neyvia web service")
        broker = broker_for(self.bus.root, self.backend)
        with self.lock:
            if self._usage_broker is not broker:
                from .neyvia_analytics import publish_indicator
                broker.add_event_listener(lambda event: publish_indicator(self.bus, event))
                broker.add_event_listener(self._watch_event)
                self._usage_broker = broker
        return broker

    def _watch_event(self, event):
        if self._watching and event.get("type") == "run.state":
            with self._watch_event_lock:
                if event.get("runId") not in self._watch_targets:
                    return
                from .ui_command_bus import now
                self._watch_events.setdefault(event["runId"], {})[event["state"]] = now()
            self.wake.set()

    def require_approval(self, key: str, description: str, details=None):
        if self.bus.get("grant:" + key, False):
            return None
        if self.bus.get("denied:" + key, False):
            return {"ok": False, "status": "denied", "error": "The owner declined this scope or exact intent"}
        with self.bus.connect() as db:
            rows = db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'").fetchall()
        for row in rows:
            saved = json.loads(row["value"])
            if saved["key"] == key:
                identity = row["key"][9:]
                if saved.get("details") is None and details is not None:
                    self.bus.put(row["key"], {**saved, "details": details})
                return {"ok": False, "status": "approval_required", "approvalId": identity, "replayed": True}
        identity = uuid.uuid4().hex
        self.bus.put("approval:" + identity, {"key": key, "description": description, "details": details})
        event = self.bus.emit("notify", {"message": description, "level": "warning", "approvalId": identity, "approvalDetail": details})
        return {"ok": False, "status": "approval_required", "approvalId": identity, "event": event}

    def approve(self, identity: str):
        request = self.bus.get("approval:" + identity)
        if not request:
            raise ValueError("Unknown approval request")
        if request["key"].startswith("settings:"):
            from .neyvia_settings import update
            digest = request["key"].split(":", 1)[1]
            saved = self.bus.get("settings.applied:" + digest)
            if saved is None:
                details = request["details"]
                saved = update(self, details["patch"], details["expectedRevision"])
                self.bus.put("settings.applied:" + digest, saved)
            self.bus.put("grant:" + request["key"], True)
            self.bus.put("denied:" + request["key"], False)
            return {"approved": True, "id": identity, "data": saved}
        self.bus.put("grant:" + request["key"], True)
        self.bus.put("denied:" + request["key"], False)
        return {"approved": True, "id": identity}

    def decline(self, identity: str):
        request = self.bus.get("approval:" + identity)
        if not request:
            raise ValueError("Unknown approval request")
        self.bus.put("denied:" + request["key"], True)
        self.bus.put("grant:" + request["key"], False)
        return self.result("notify", {"message": "Approval declined", "level": "info", "approvalId": identity, "denied": True})

    @staticmethod
    def safe_path(value) -> Path:
        path = Path(value).expanduser().resolve()
        protected = Path(r"C:\Users\user\Projects\Neyvia").resolve()
        if path == protected or protected in path.parents:
            raise ValueError("The live Neyvia tree is protected")
        return path

    def result(self, action, payload):
        return {"ok": True, **payload, "event": self.bus.emit(action, payload)}

    def create_project(self, args, folder=False):
        name = str(args["name"]).strip()
        if not name or name in {".", ".."} or any(c in name for c in '/\\:'):
            raise ValueError("Use a single folder name")
        parent = self.safe_path(args["path"]) if folder else self.safe_path(args.get("path") or self.bus.root / "projects")
        target = self.safe_path(parent / name if folder or not args.get("path") else parent)
        root = parent if folder or not args.get("path") else target.parent
        refusal = self.require_approval("folder:" + os.path.normcase(str(root)), "Approve project creation under " + str(root))
        if refusal:
            return refusal
        target.mkdir(parents=True, exist_ok=True)
        if args.get("git") or args.get("template") == "git":
            import subprocess
            from .subprocess_utils import hidden_windows_subprocess_kwargs
            subprocess.run(["git", "init", str(target)], check=True, capture_output=True,
                           **hidden_windows_subprocess_kwargs())
        self.bus.update("projects", {str(target): {"name": name, "path": str(target)}})
        return self.result("project.created", {"name": name, "path": str(target)})

    def launch(self, args):
        request_id = str(args.get("requestId") or "").strip()
        if not request_id:
            raise ValueError("requestId is required; reuse it for retries")
        folder = self.safe_path(args["folder"])
        mode = str(args.get("permissionMode") or "read-only")
        adapter_mode = harness_mode(args["app"], mode)
        if mode not in {"read-only", "plan"}:
            refusal = self.require_approval("session:" + os.path.normcase(str(folder)) + ":" + mode,
                                            f"Approve {mode} chats in {folder}", {**args, "folder": str(folder), "adapterMode": adapter_mode})
            if refusal:
                return refusal
        started = self.broker().new(args["app"], str(folder), args["prompt"], request_id,
                                    {"model": args.get("model"), "permissionMode": adapter_mode})
        if not started.get("sessionId") and started.get("state") in {"queued", "running", "waiting_approval", "waiting_input"}:
            return {"ok": True, "status": "pending", "requestId": request_id, "run": started}
        if not started.get("sessionId") or started.get("state") in {"failed", "interrupted"}:
            raise RuntimeError(started.get("error") or "The harness did not create a session; run " + str(started.get("runId")))
        identity = started["sessionId"]
        with self.lock:
            previous = self.bus.get("sessions", {}).get(identity)
            if previous:
                return {"ok": True, **previous, "run": started, "replayed": True}
            payload = {"id": identity, "app": args["app"], "folder": str(folder)}
            self.bus.update("sessions", {identity: payload})
            return {**self.result("session.created", payload), "run": started}

    def call(self, name: str, args: dict):
        from .proof_contracts import invoke
        return invoke("neyvia." + name, args, lambda: self._call_unchecked(name, args))

    def _call_unchecked(self, name: str, args: dict):
        if name.startswith("marketplace."):
            from .source_marketplace import SourceMarketplace
            return SourceMarketplace(self.bus.root).call(name.split(".")[1], args)
        if name.startswith("modules."):
            from .neyvia_modules import call
            return call(self, name, args)
        if name.startswith("mod."):
            from .module_plugins import dispatch
            return dispatch(self, name, args)
        if name in {"verify.edges", "verify.edges.status"}:
            from .edge_contracts import call
            return call(self, name, args)
        if name.startswith('memory.'):
            from .neyvia_memory_tools import call
            return call(self, name, args)
        if name == "pane.observe":
            from .cl.renderer_effects import observe
            return observe(self.bus, args.get("eventId"))
        if name.startswith("research."):
            from .research_pipeline import call
            return call(self, name, args)
        if name.startswith("app_sdk."):
            from .neyvia_app_sdk import call
            return call(self, name, args)
        if name.startswith("scroll."):
            from .neyvia_scroll import call
            return call(self, name, args)
        if name.startswith("documents."):
            from .neyvia_documents import call
            return call(self, name, args)
        if name in {"cl", "cl.describe"}:
            from .neyvia_cl import call
            return call(self, name, args)
        if name in {row[0] for row in LAYA_CAPABILITY_DEFINITIONS}:
            from .neyvia_laya_capabilities import call
            return call(name, args, self.bus.root, workspace=self)
        if name.startswith("efficiency."):
            from .neyvia_efficiency import call
            from .neyvia_agent import NeyviaToolGateway
            gateway = NeyviaToolGateway(self.bus.root, allow_mutations=False, permission_mode="read-only",
                                       managed_capabilities=False)
            return call(self, name, args, dispatcher=gateway.call_native)
        if name.startswith("evolver."):
            from .neyvia_evolver import call
            return call(self.bus.root, name, args)
        if name == "verify.status":
            from .proof_readiness import status
            readiness = status(self.bus.root)
            if readiness.get('scope') == 'impact':
                return {'ok':True,'available':True, **readiness}
            path = self.bus.root / ".agent_control/proofs/latest.json"
            if not path.exists():
                return {"ok": True, "available": False, "complete": False}
            import json
            report = json.loads(path.read_text(encoding="utf-8"))
            return {"ok": True, "available": True, "complete": report["complete"],
                    "contractsOk": report["contractsOk"], "coverage": report["coverage"],
                    "failures": report["failures"], "blocked": report["blocked"], "durationMs": report["durationMs"]}
        if name == "verify":
            if not args.get('areas'):
                from .proof_readiness import run_now
                return run_now(self.bus.root, low_priority=False)
            from .proof_verifier import run_verification
            return run_verification(self.bus.root, areas=args.get("areas"), include_manuals=args.get("includeManuals", True),
                                    adapter_chapters=args.get('adapterChapters'))
        if name.startswith("inception."):
            from .neyvia_inception import call
            return call(self, name, args)
        if name.startswith("cua."):
            from .neyvia_cua import call
            return call(self, name, args)
        # The service owns adapters; a worker must not create a second live broker.
        if self.backend is None and os.environ.get("NEYVIA_UI_BACKEND_URL"):
            from .neyvia_ui_client import call_tool
            return call_tool(name, args)
        if name.startswith("agentview."):
            from .neyvia_agentview_checks import call
            return call(self, name, args)
        if name.startswith(("feedback.", "lessons.")):
            from .task_feedback import call
            return call(self, name, args)
        if name.startswith("browser."):
            from .neyvia_browser import call
            return call(self, name, args)
        if name.startswith("video."):
            from .neyvia_video import call
            return call(self, name, args)
        if name.startswith("gamedev."):
            from .neyvia_gamedev import call
            return call(self, name, args)
        if name.startswith("settings."):
            from .neyvia_settings import call
            return call(self, name, args)
        if name.startswith("remote."):
            from .neyvia_remote import call
            return call(self, name, args)
        if name.startswith("language."):  # pure text checks; never under the workspace lock
            from .neyvia_language import call
            return call(self, name, args)
        if name == "session.new":
            return self.launch(args)
        if name.startswith("nightshift."):
            from .neyvia_nightshift import call
            return call(self, name, args)
        if name.startswith("autopilot."):
            if args.get("background"):
                raise ValueError("Background runs require the persistent owner autopilot endpoint")
            from .neyvia_autopilot import call
            if name in {"autopilot.get", "autopilot.list", "autopilot.stop"}:
                return call(self, name, args)
            from .neyvia_agent import NeyviaToolGateway
            scoped_app_goal = bool(args.get("appGoal") and "neyvia.app_sdk.verify" in args.get("scopeTools", []))
            if name == "autopilot.resume" and args.get("runId"):
                from .neyvia_autopilot import load
                previous = load(self, args["runId"])
                scoped_app_goal = bool(previous.get("appGoal") and "neyvia.app_sdk.verify" in previous.get("scopeTools", []))
            gateway = NeyviaToolGateway(self.bus.root, allow_mutations=scoped_app_goal, permission_mode="workspace" if scoped_app_goal else "read-only",
                                       allowed_mutation_tools={"neyvia.app_sdk.verify"} if scoped_app_goal else set())
            return call(self, name, args, registry=gateway.native, dispatcher=gateway.call_native)
        if name.startswith("artifact."):
            from .neyvia_outputs import call
            return call(self, name, args)
        if name.startswith("perception."):
            from .neyvia_perception import call
            return call(self, name, args)
        if name in {"sidebar.state", "sidebar.preview", "sidebar.confirm", "sidebar.undo"}:
            from .neyvia_sidebar import call
            return call(self, name, args)
        if name.startswith("voice.") or name == "app.open":
            from .neyvia_voice import call
            return call(self, name, args)
        if name.startswith("conductor."):
            from .neyvia_conductor import call
            return call(self, name, args)
        if name.startswith("parallel."):
            from .neyvia_parallel import call
            return call(self, name, args)
        if name.startswith("comments."):
            from .neyvia_comments import call
            return call(self, name, args)
        if name in {"agents.state", "agents.limits", "agents.overview", "agents.deliveries"}:  # reads several chats; never under the workspace lock
            from .neyvia_agents_tools import call
            return call(self, name, args)
        if name.startswith("image."):
            from .neyvia_image_tools import call
            if name == "image.state":
                return call(self, name, args)
            with self.image_lock:
                return call(self, name, args)
        if name.startswith("connections."):
            from .neyvia_connections import call
            return call(self, name, args)
        if name.startswith("mobile."):  # builds wait outside the shared lock
            from .neyvia_mobile_studio import call
            return call(self, name, args)
        if name == "sidebar.tidy":  # lists and checks every chat; takes the lock only to archive
            from .neyvia_sidebar_cleanup import call
            return call(self, name, args)
        if name.startswith("dictation."):  # the speech engine is its own process; never under the lock
            from .neyvia_dictation import call
            return call(self, name, args)
        if name.startswith("prompt."):
            from .prompt_amplifier import call
            return call(self, name, args)
        if name in {"activity", "message"} or name.startswith("claude.") and name != "claude.mods" and name != "claude.runs":
            from .claude_code_mods import call  # reads and talks to other sessions; never under the workspace lock
            return call(self, name, args)
        if name.startswith("terminal.") or name == "pane.state":  # reads Paul's terminal buffers; never under the lock
            from .neyvia_panes import call_tool
            return call_tool(self, name, args)
        with self.lock:
            if name.startswith(("time.", "timer.")) or name == "schedule.after":
                from .neyvia_time_tools import call
                return call(self, name, args)
            if name.startswith("watch."):
                from .neyvia_run_watches import call
                return call(self, name, args)
            if name.startswith("work.") or name in {"impact", "intent.checklist", "plan.update"}:
                from .neyvia_awareness import call
                return call(self, name, args)
            if name.startswith("claude."):
                from .claude_code_mods import call
                return call(self, name, args)
            if name == "attention.list":
                from .neyvia_attention import call
                return call(self, args)
            if name == "session.cluster":
                from .neyvia_session_clustering import cluster
                return cluster(self, args)
            if name.startswith("sidebar."):
                from .neyvia_sidebar_cleanup import call
                return call(self, name, args)
            if name == "state" or name.startswith("manual."):
                from .neyvia_manuals import call
                return call(self, name, args)
            if name == "lab.state":
                from .neyvia_lab_board import state
                return state(self.bus.root)
            if name == "runtime.list":
                from .neyvia_runtime import compact
                return compact(self)
            if name.startswith("mission."):
                from .neyvia_missions import call
                from .nightshift import nightshift_for
                return call(nightshift_for(self.bus.root, self.backend), name, args)
            if name in {"folder.create", "project.create"}:
                return self.create_project(args, name == "folder.create")
            if name == "folder.list":
                folders = list(self.bus.get("projects", {}).values())
                return {**self.result("notify", {"message": f"{len(folders)} project folders", "level": "info"}), "folders": folders}
            if name == "folder.open":
                path = str(self.safe_path(args["path"]))
                if not Path(path).is_dir():
                    raise ValueError("Folder does not exist")
                self.bus.put("activeProject", path)
                from .cl.renderer_effects import show
                return show(self, {"kind": "file", "target": path})
            if name.startswith("session."):
                identity = args["id"]
                if identity not in self.bus.get("sessions", {}) and self.broker().find_summary(identity) is None:
                    raise ValueError("Unknown session")
                verb = name.split(".")[1]
                if verb == "archive" and args.get("archived", True):
                    from .neyvia_sidebar_cleanup import guard_archive
                    refusal = guard_archive(self, identity)
                    if refusal:
                        return refusal
                patch = {"move": {"project": args.get("project")}, "rename": {"title": args.get("title")},
                         "pin": {"pinned": args.get("pinned", True)}, "archive": {"archived": args.get("archived", True)}}[verb]
                if verb == "move" and patch["project"] is not None and patch["project"] not in self.bus.get("projects", {}):
                    raise ValueError("Unknown project")
                current = self.bus.get("sessions", {}).get(identity, {})
                self.bus.update("sessions", {identity: {**current, **patch}})
                return self.result("session." + {"move": "moved", "rename": "renamed", "pin": "pinned", "archive": "archived"}[verb], {"id": identity, **patch})
            if name in {"pane.show", "view.layout"}:
                if name == "view.layout":
                    from .neyvia_settings import update
                    result = update(self, {"density": args.get("level")})
                    event = next((row for row in result["events"] if row["action"] == "view.layout"), None)
                    return {"ok": True, **result, "level": args["level"], **({"event": event} if event else {})}
                if args.get("kind") == "browser":
                    from .neyvia_browser import service_for
                    browser = service_for(self.bus.root)
                    tab = browser.tab({"tabId": args.get("target")})
                    if tab.get("engine") != "obscura" or not tab.get("live"):
                        raise ValueError("Browser panes require a live owned headless tab id")
                    args = {**args, "runtimeSessionId": browser.headless.status()["sessionId"], "status": "queued"}
                from .cl.renderer_effects import show
                return show(self, args)
            if name.startswith("view.") and name != "view.layout":
                from .neyvia_view_tools import call
                return call(self, name, args)
            if name.startswith("schedule."):
                return self.schedule(name, args)
            if name == "notify":
                message = args.get("message") or args.get("msg")
                if not message:
                    raise ValueError("message is required")
                return self.result("notify", {"message": message, "level": args.get("level", "info")})
            raise ValueError("Unknown Neyvia action")

    def schedule(self, name, args):
        schedules = self.bus.get("schedules", {})
        if name == "schedule.create":
            identity = str(args.get("requestId") or "").strip()
            if not identity:
                raise ValueError("requestId is required; reuse it for retries")
            if identity in schedules:
                previous = schedules[identity]
                if any(previous.get(key) != args.get(key) for key in ("when", "prompt", "scope")):
                    raise ValueError("requestId was already used for a different follow-up")
                return {"ok": True, "schedule": previous, "replayed": True}
            when = datetime.fromisoformat(args["when"].replace("Z", "+00:00"))
            if when.tzinfo is None or when.timestamp() <= datetime.now(timezone.utc).timestamp():
                raise ValueError("when must be a future timestamp with timezone")
            scope = args["scope"]
            if scope.get("app"):
                self.safe_path(scope["folder"])
                harness_mode(scope["app"], scope.get("permissionMode", "read-only"))
            if scope.get("app") and scope.get("permissionMode", "read-only") not in {"read-only", "plan"}:
                raise ValueError("Scheduled chats are read-only; use Night Shift for approved write tasks")
            schedules[identity] = {"id": identity, **args, "status": "waiting", "due": when.timestamp()}
            self.bus.put("schedules", schedules)
            self.start_timers()
            self.wake.set()
            return {**self.result("notify", {"message": "Follow-up scheduled", "level": "info", "scheduleId": identity}), "schedule": schedules[identity]}
        if name == "schedule.cancel":
            row = schedules.get(args["id"])
            if not row or row["status"] != "waiting":
                raise ValueError("Pending schedule not found")
            row["status"] = "cancelled"
            self.bus.put("schedules", schedules)
            self.wake.set()
            return self.result("notify", {"message": "Follow-up cancelled", "level": "info", "scheduleId": row["id"]})
        return {**self.result("notify", {"message": f"{len(schedules)} follow-ups", "level": "info"}), "schedules": list(schedules.values())}

    def start_timers(self):
        with self.lock:
            if self.backend and not self.closed.is_set() and not self._timer:
                self._timer = threading.Thread(target=self._timers, name="neyvia-follow-ups", daemon=True)
                self._timer.start()

    def close(self):
        if hasattr(self, "_perception_browser"):
            self._perception_browser.close()
        self.closed.set()
        self.wake.set()
        if self._usage_broker:
            self._usage_broker.remove_event_listener(self._watch_event)
        if self._timer and self._timer is not threading.current_thread():
            self._timer.join(2)
        if not self._timer or not self._timer.is_alive():
            self._retire_network_policy()

    def _retire_network_policy(self):
        from .local_network_policy import release
        release(self)
        self.backend = None
        atexit.unregister(self.close)

    def _timers(self):
        while not self.closed.is_set():
            delay = None
            with self.lock:
                self.wake.clear()
                from .neyvia_sidebar_cleanup import automatic_tick
                delay = automatic_tick(self)
                from .neyvia_run_watches import evaluate
                if self._watching:
                    evaluate(self)
                schedules = self.bus.get("schedules", {})
                for row in schedules.values():
                    if row["status"] != "waiting":
                        continue
                    remaining = row["due"] - datetime.now(timezone.utc).timestamp()
                    if remaining > 0:
                        delay = remaining if delay is None else min(delay, remaining)
                        continue
                    try:
                        scope = row["scope"]
                        result = self.launch({**scope, "prompt": row["prompt"], "requestId": "schedule-" + row["id"]}) if scope.get("app") else self.call("notify", {"message": row["prompt"]})
                        row.update(status="done", result=result)
                    except Exception as exc:
                        row.update(status="blocked", reason=str(exc))
                        self.bus.emit("notify", {"message": "Follow-up failed: " + str(exc), "level": "error"})
                self.bus.put("schedules", schedules)
            # Respect the OS lock's representable timeout for far-future reminders.
            self.wake.wait(min(delay, threading.TIMEOUT_MAX) if delay is not None else None)
        self._retire_network_policy()


_services = {}
_lock = threading.Lock()


def workspace_for(root: Path, backend=None) -> WorkspaceTools:
    key = str(state_root(root))
    with _lock:
        if key not in _services or _services[key].closed.is_set():
            _services[key] = WorkspaceTools(Path(key))
        service = _services[key]
        if backend is not None:
            service.backend = backend
        return service
