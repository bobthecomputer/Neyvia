"""Contracts for read-only connected-app observation and scoped persistence."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import json
import os
import threading
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .proofs_a_capabilities import require


_STATE_WRITE_LOCK = threading.RLock()


def checked_state_save(action):
    @wraps(action)
    def checked(root, state):
        path = root / ".agent_control/connected_apps_state.json"
        with _STATE_WRITE_LOCK:
            serialized = json.dumps(state, indent=2)
            previous = path.read_text(encoding="utf-8") if path.is_file() else None
            stamp = path.stat().st_mtime_ns if previous is not None else None
            result = action(root, state)
            require(path.read_text(encoding="utf-8") == serialized and all("last_seen_at" not in row for row in state.values()), "a.app-state", "durable session differs or includes volatile last_seen_at")
            if previous == serialized:
                require(path.stat().st_mtime_ns == stamp, "a.app-state", "unchanged observation rewrote durable state")
            return result
    return checked


def check_snapshot(result, root):
    manifests = {row["app_id"]: row for row in result["discoveredApps"]}
    ids = [row["app_id"] for row in result["connectedSessions"]]
    require(set(ids) == set(manifests) and len(ids) == len(set(ids)) and len(result["bridgeHandshakes"]) == len(ids), "a.app-observation", "snapshot lost or duplicated a manifest session/handshake")
    for session in result["connectedSessions"]:
        require({row["capability_key"] for row in session["granted_capabilities"]} <= set(manifests[session["app_id"]]["permissions"]), "a.app-observation", "session granted undeclared capability")


def check_storage_plan(result, manifest, status_payload, job_payload):
    from .app_capability_standard import _as_bool, _safe_int
    approval = _as_bool(manifest.bridge.get("requires_approval_for_write"), default=True)
    require(result["requiresApprovalForWrite"] == approval and result["autoSyncEnabled"] == (_as_bool(manifest.bridge.get("auto_sync"), default=False) and not approval) and result["safeDirections"] == (["upload", "download"] if result["sourceRoot"] and result["targetReady"] else []), "a.app-storage", "storage plan lost approval policy or advertised unsafe direction")
    require(result["controlProtocol"] == str(manifest.bridge.get("control_protocol") or "ssh").strip().lower() and result["controlPort"] == _safe_int(manifest.bridge.get("control_port") or manifest.bridge.get("requested_ssh_port") or manifest.bridge.get("ssh_port") or 22) and result["remoteProjectRoot"] == str(manifest.bridge.get("remote_project_root") or manifest.bridge.get("remote_root") or "").strip(), "a.app-storage", "storage observer changed explicit control metadata")
    if result["activationRequired"]:
        require(not result["targetReady"] and bool(result["activationHint"]) and result["activationProject"] == str(manifest.bridge.get("activation_project") or "Core"), "a.app-storage", "unready mapping lost activation guidance")


def check_storage_session(result, *, manifest, app_root, previous_state, grants):
    hints = result.ui_hints
    payload = result.latest_task_result["payload"]
    require(result.status in {"connected", "available"} and result.app_id == manifest.app_id and hints["bridgeRole"] == "nas_storage" and result.approval_callback["channel"] == "mobile_web" and payload["safeDirections"] == hints["safeDirections"] and payload["requiresApprovalForWrite"] == hints["requiresApprovalForWrite"], "a.app-storage", "storage session was lost for absent local root or disagrees with read-only plan")


def check_cloud_plan(result, root, manifest):
    require(result["requiresApprovalForWrite"] is True and result["writePolicy"] == "preview_then_approve" and result["targetReady"] == bool(result["primaryRoot"] or result["googleLoginReady"]) and result["safeDirections"] == (["upload", "download"] if result["targetReady"] else []), "a.app-cloud", "cloud discovery skipped approval or confused presence with configured target")


def self_check(scratch):
    """Read finite local HTTP status fixtures; never starts a sync or NAS call."""
    from .app_capability_standard import build_connected_apps_snapshot
    root = scratch / "app-standard"
    (root / "config").mkdir(parents=True)
    local_app = root / "local-app"; local_app.mkdir()
    target = root / "target"; target.mkdir()
    config = root / "config/connected_apps.json"
    def manifest(app_id, bridge):
        return {"manifest_id": "manifest_" + app_id, "schema_version": "fluxio.app-capability/v0-draft", "app_id": app_id, "name": app_id, "description": "Bounded local bridge observation", "bridge": bridge, "auth": {"mode": "local_session", "scopes": ["status.read"]}, "permissions": ["task.run", "context.read"], "tasks": [{"task_id": "observe", "label": "Observe bridge", "description": "Read status"}], "context_surfaces": [{"surface_id": "status", "label": "Status", "description": "Read status", "access": "read"}], "action_hooks": [{"hook_id": "review", "label": "Review selection", "description": "Review", "mutability": "write"}]}
    base = {"transport": "http", "endpoint": proof_text("http://127.0.0.1:48462"), "healthcheck": "/api/status", "event_stream": "/api/job", "workspace_root": str(local_app), "source_root": str(root), "target_root": str(target), "nas_host": "fixture.local", "control_protocol": "ssh", "ssh_user": "fixture-user", "ssh_port": 22, "requested_ssh_port": 22, "remote_project_root": str(target), "connection_mode": "lan"}
    def observe(payload):
        config.write_text(json.dumps([payload]), encoding="utf-8")
        return build_connected_apps_snapshot(root)["connectedSessions"][0]
    generic = manifest("scratch-observer", base)
    observe(generic)
    state_path = root / ".agent_control/connected_apps_state.json"
    old = state_path.read_bytes(); stamp = state_path.stat().st_mtime_ns
    observe(generic)
    require(state_path.read_bytes() == old and state_path.stat().st_mtime_ns == stamp and "last_seen_at" not in json.loads(old)["scratch-observer"], "a.app-state", "unchanged snapshot rewrote session state")
    status = {"message": "Fixture Fast Sync ready on LAN", "selectedMode": "lan", "selectedHost": "fixture.local", "targetReady": True, "targetRoot": str(target), "sourceRoot": str(root)}
    job = {"state": "running", "direction": "upload", "completedFiles": 3, "remainingFiles": 2, "currentPath": "proof/result.txt"}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = status if self.path == "/api/status" else job if self.path == "/api/job" else None
            if data is None:
                self.send_response(404); self.end_headers(); return
            body = json.dumps(data).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48462)), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        live = observe(manifest("synology-fast-sync", base)); payload = live["latest_task_result"]["payload"]
        require(live["status"] == "connected" and "Upload output" in live["latest_task_result"]["resultSummary"] and "Fixture Fast Sync ready" in live["context_preview"][0]["summary"] and live["ui_hints"]["sourceRoot"] == str(root) and live["ui_hints"]["targetRoot"] == str(target) and payload["safeDirections"] == ["upload", "download"] and payload["requiresApprovalForWrite"] and payload["bridgePlan"]["writePolicy"] == "preview_then_approve", "a.app-storage", "HTTP observation lost status, progress or approved direction policy")
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    # All later endpoints remain explicit at the same closed owned port.
    inactive_bridge = {**base, "target_root": str(root / "unavailable-target"), "remote_project_root": str(root / "unavailable-target"), "activation_project": "Core", "ssh_port_status": "fixture metadata: port22", "activation_command": "review-only-map-command"}
    inactive = observe(manifest("synology-fast-sync", inactive_bridge))["latest_task_result"]["payload"]
    require(not inactive["targetReady"] and inactive["activationRequired"] and inactive["activationProject"] == "Core" and "Activate the Core project" in inactive["activationHint"] and inactive["controlProtocol"] == "ssh" and inactive["controlPort"] == inactive["requestedSshPort"] == 22 and inactive["sshPortStatus"] == "fixture metadata: port22" and inactive["sshUser"] == "fixture-user" and inactive["remoteProjectRoot"] == str(root / "unavailable-target"), "a.app-storage", "inactive mapping lost explicit reviewed activation metadata")
    automatic = observe(manifest("synology-fast-sync", {**base, "requires_approval_for_write": False, "auto_sync": True, "write_policy": "automatic_bidirectional"}))["latest_task_result"]["payload"]
    require(not automatic["requiresApprovalForWrite"] and automatic["bridgePlan"]["autoSyncEnabled"] and automatic["bridgePlan"]["writePolicy"] == "automatic_bidirectional" and automatic["safeDirections"] == ["upload", "download"], "a.app-storage", "explicit automatic policy was silently overwritten")
    missing = observe(manifest("synology-fast-sync", {**base, "workspace_root": str(root / "missing-local-app"), "target_root": "Q:/proofs-a-unavailable-fixture", "remote_project_root": str(target)}))
    require(missing["status"] != "missing" and missing["latest_task_result"]["payload"]["targetRoot"] == str(target) and missing["latest_task_result"]["payload"]["targetReady"], "a.app-storage", "missing mapped drive/local app suppressed reviewed remote-root observation")
    cloud = root / "cloud"; cloud.mkdir()
    names = ["FLUXIO_GOOGLE_DRIVE_ROOT", "FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT", "FLUXIO_CLOUD_DRIVE_ROOT"]
    previous = {name: os.environ.get(name) for name in names}
    os.environ["FLUXIO_GOOGLE_DRIVE_ROOT"] = str(cloud); os.environ["FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT"] = "1"; os.environ.pop("FLUXIO_CLOUD_DRIVE_ROOT", None)
    try:
        cloud_session = observe(manifest("cloud-drive-sync", {"transport": "local_mount_oauth", "endpoint": "local://cloud-drive", "healthcheck": "provider-presence", "event_stream": "local-events", "source_root": str(root)}))
        payload = cloud_session["latest_task_result"]["payload"]
        require(cloud_session["status"] == "connected" and cloud_session["ui_hints"]["bridgeRole"] == "cloud_storage" and payload["googleLoginReady"] and payload["safeDirections"] == ["upload", "download"] and payload["requiresApprovalForWrite"] and payload["mountedRoots"][0]["provider"] == "google-drive", "a.app-cloud", "cloud presence discovery lost login, mounted root or approval boundary")
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
