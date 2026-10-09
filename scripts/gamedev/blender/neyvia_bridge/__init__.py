"""Blender-native scene bridge; networking never calls bpy from its worker."""
bl_info = {"name": "Neyvia Game Dev Bridge", "author": "Neyvia", "version": (1, 0, 0), "blender": (4, 0, 0), "location": "Scene properties", "category": "Development"}

import json
import hashlib
import math
import queue
import threading
import time
import urllib.request
import urllib.parse
from pathlib import Path
import bpy
import uuid

_incoming = queue.Queue()
_outgoing = queue.Queue()
_stop = threading.Event()
_worker = None
_config = None
_session = None
_last_error = ""
_version = ""
_client_id = ""
CAPABILITIES = ["inspect", "select", "edit", "render", "export", "load_asset",
                "transcribe", "mesh_fix", "canonical", "snapshot", "restore", "shape_program"]


def _project_path(value, suffixes=None):
    root = Path(_config["projectPath"]).resolve()
    path = Path(value)
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path must stay inside configured project")
    if suffixes and path.suffix.lower() not in suffixes:
        raise ValueError("Unsupported file extension")
    return path


def _post(action, payload):
    url = _config["httpUrl"].rstrip("/") + "/api/gamedev/bridge/" + action
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Authorization": "Bearer " + _config["token"], "Content-Type": "application/json"})
    # Disable ambient proxies: the capability token is only sent to literal loopback.
    # A durable assignment/completion can include a disk flush. Keep transport
    # time below the host action deadline without discarding a slow assignment.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30) as response:
        reply = json.load(response)
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error", "Bridge request refused"))
    return reply["data"]


def _network():
    global _session, _last_error
    pending = None
    while not _stop.is_set():
        try:
            if _session is None:
                _session = _post("register", {"engine": "blender", "projectPath": _config["projectPath"], "context": "Edit", "capabilities": CAPABILITIES, "version": _version, "clientId": _client_id})["sessionId"]
            if pending is None:
                try:
                    pending = _outgoing.get_nowait()
                except queue.Empty:
                    pass
            if pending is not None:
                _post("complete", dict(pending, sessionId=_session))
                pending = None
            else:
                data = _post("poll", {"sessionId": _session})
                if data.get("request"):
                    _incoming.put(data["request"])
            _last_error = ""
        except Exception as exc:
            _last_error = str(exc)
            # Do not re-register/replay a native action after an ambiguous failure.
        _stop.wait(0.3)


def _object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError("Object does not exist: " + name)
    return obj


def _vector(value):
    if not isinstance(value, list) or len(value) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError("Expected three finite numbers")
    return value


def _inspect():
    scene = bpy.context.scene
    return {"scene": scene.name, "camera": scene.camera.name if scene.camera else None, "frame": scene.frame_current, "objects": [{"name": obj.name, "type": obj.type, "location": list(obj.location), "rotation": list(obj.rotation_euler), "scale": list(obj.scale), "selected": obj.select_get()} for obj in scene.objects]}


def _execute(action, args):
    if action == 'shape_program':
        from .shape_program import execute
        return execute(args['program'], _project_path)
    if action in {"transcribe", "mesh_fix", "canonical", "snapshot", "restore"}:
        from .mesh_quality import execute
        return execute(action, args, _project_path)
    if action == "inspect":
        return _inspect()
    if action == "select":
        obj = _object(args["object"])
        for other in bpy.context.view_layer.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        return {"selected": obj.name}
    if action == "edit":
        obj = _object(args["object"])
        fields = set(args) - {"object"}
        if not fields or not fields <= {"location", "rotation", "scale"}:
            raise ValueError("Edit supports location, rotation (radians), scale")
        values = {key: _vector(args[key]) for key in fields}
        for key, value in values.items():
            setattr(obj, "rotation_euler" if key == "rotation" else key, value)
        bpy.context.view_layer.update()
        return {"object": obj.name, "location": list(obj.location), "rotation": list(obj.rotation_euler), "scale": list(obj.scale)}
    if action == "render":
        scene = bpy.context.scene
        camera = _object(args["camera"]) if args.get("camera") else scene.camera
        if camera is None or camera.type != "CAMERA":
            raise ValueError("Render requires a scene camera or camera argument")
        path = _project_path(args["path"], {".png"})
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != args.get("expectedSha256"):
            raise ValueError("Existing render needs its current expectedSha256")
        path.parent.mkdir(parents=True, exist_ok=True)
        previous = (scene.camera, scene.render.filepath, scene.render.image_settings.file_format)
        try:
            scene.camera = camera
            scene.render.filepath = str(path)
            scene.render.image_settings.file_format = "PNG"
            result = bpy.ops.render.render(write_still=True)
            if "FINISHED" not in result or not path.is_file():
                raise RuntimeError("Render did not produce its requested PNG")
            return {"path": str(path), "bytes": path.stat().st_size, "camera": camera.name, "frame": scene.frame_current, "resolution": [scene.render.resolution_x, scene.render.resolution_y], "percentage": scene.render.resolution_percentage}
        finally:
            scene.camera, scene.render.filepath, scene.render.image_settings.file_format = previous
    if action == "export":
        path = _project_path(args["path"], {".gltf", ".glb"})
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != args.get("expectedSha256"):
            raise ValueError("Existing export needs its current expectedSha256")
        path.parent.mkdir(parents=True, exist_ok=True)
        result = bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB" if path.suffix.lower() == ".glb" else "GLTF_SEPARATE", use_selection=bool(args.get("selectedOnly", False)))
        if "FINISHED" not in result or not path.is_file():
            raise RuntimeError("Export did not produce its requested asset")
        return {"path": str(path), "bytes": path.stat().st_size, "format": path.suffix[1:], "objects": [obj.name for obj in bpy.context.scene.objects]}
    if action == "load_asset":
        path = _project_path(args["path"], {".gltf", ".glb"})
        if not path.is_file():
            raise ValueError("Asset does not exist")
        if path.suffix.lower() == ".gltf":
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document.get("buffers", []) + document.get("images", []):
                uri = entry.get("uri", "")
                if not uri or uri.startswith("data:"):
                    continue
                if urllib.parse.urlparse(uri).scheme or uri.startswith(("/", "\\")):
                    raise ValueError("Asset references must be project-local")
                dependency = _project_path(str(path.parent / urllib.parse.unquote(uri)))
                if not dependency.is_file():
                    raise ValueError("Missing asset dependency")
        before = set(bpy.data.objects.keys())
        result = bpy.ops.import_scene.gltf(filepath=str(path))
        if "FINISHED" not in result:
            raise RuntimeError("Native glTF import failed")
        return {"path": str(path), "objects": sorted(set(bpy.data.objects.keys()) - before)}
    raise ValueError("Unsupported Blender action: " + action)


def _tick():
    if _stop.is_set():
        return None
    try:
        request = _incoming.get_nowait()
    except queue.Empty:
        return 0.1
    completion = {"requestId": request["requestId"], "status": "succeeded", "result": {}}
    try:
        completion["result"] = _execute(request["action"], request.get("args", {}))
    except Exception as exc:
        completion.update(status="failed", error=str(exc))
    _outgoing.put(completion)
    return 0.1


class NEYVIA_OT_connect(bpy.types.Operator):
    bl_idname = "neyvia.connect"
    bl_label = "Connect Neyvia bridge"
    def execute(self, context):
        global _worker, _config, _session, _version, _client_id
        if _worker and _worker.is_alive():
            self.report({"INFO"}, "Bridge already active")
            return {"FINISHED"}
        try:
            project = Path(bpy.path.abspath(context.scene.neyvia_project_path)).resolve()
            config = json.loads((project / ".neyvia" / "gamedev-bridge.json").read_text(encoding="utf-8"))
            if Path(config["projectPath"]).resolve() != project:
                raise ValueError("Config projectPath differs from selected project")
            endpoint = urllib.parse.urlsplit(config["httpUrl"])
            if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port
                    or not 1024 <= endpoint.port <= 65535 or endpoint.port == 47881
                    or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in ("", "/")):
                raise ValueError("Bridge URL must use an explicit non-public literal loopback HTTP port")
            _config, _session, _version = config, None, bpy.app.version_string
            _client_id = uuid.uuid4().hex
            _stop.clear()
            _worker = threading.Thread(target=_network, daemon=True, name="neyvia-blender-network")
            _worker.start()
            if not bpy.app.timers.is_registered(_tick):
                bpy.app.timers.register(_tick, persistent=True)
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class NEYVIA_PT_bridge(bpy.types.Panel):
    bl_label = "Neyvia bridge"
    bl_idname = "NEYVIA_PT_bridge"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    def draw(self, context):
        self.layout.prop(context.scene, "neyvia_project_path")
        self.layout.operator("neyvia.connect")
        self.layout.label(text="Connected" if _session else "Disconnected")
        if _last_error:
            self.layout.label(text=_last_error[:100], icon="ERROR")


def register():
    bpy.utils.register_class(NEYVIA_OT_connect)
    bpy.utils.register_class(NEYVIA_PT_bridge)
    bpy.types.Scene.neyvia_project_path = bpy.props.StringProperty(name="Project", subtype="DIR_PATH", default="//")


def unregister():
    global _worker, _session
    _stop.set()
    if _worker:
        _worker.join(timeout=4)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _worker, _session = None, None
    bpy.utils.unregister_class(NEYVIA_PT_bridge)
    bpy.utils.unregister_class(NEYVIA_OT_connect)
    del bpy.types.Scene.neyvia_project_path
