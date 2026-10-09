@tool
extends EditorPlugin

const Client = preload("res://addons/neyvia_bridge/client.gd")
var bridge

func _enter_tree() -> void:
	add_autoload_singleton("NeyviaGameBridge", "res://addons/neyvia_bridge/runtime.gd")
	bridge = Client.new()
	bridge.context = "Edit"
	bridge.capabilities = ["inspect", "transcribe", "select", "edit", "validate", "run", "stop", "load_asset"]
	bridge.request_received.connect(_request)
	add_child(bridge)

func _exit_tree() -> void:
	remove_autoload_singleton("NeyviaGameBridge")
	if is_instance_valid(bridge):
		bridge.queue_free()

func _tree(node: Node, depth: int = 0) -> Dictionary:
	var result := {"name": str(node.name), "type": node.get_class(), "path": str(node.get_path()), "children": []}
	if node is Node3D:
		result["position"] = [node.position.x, node.position.y, node.position.z]
	if node is Node2D:
		result["position"] = [node.position.x, node.position.y]
	if depth < 20:
		for child in node.get_children():
			result["children"].append(_tree(child, depth + 1))
	return result

func _numbers(value, count: int) -> bool:
	if not value is Array or value.size() != count:
		return false
	for item in value:
		if not (item is int or item is float) or not is_finite(float(item)):
			return false
	return true

func _request(request: Dictionary) -> void:
	var args: Dictionary = request.get("args", {})
	var action := str(request.get("action", ""))
	var editor := get_editor_interface()
	var root := editor.get_edited_scene_root()
	if action == "run":
		if ProjectSettings.get_setting("application/run/main_scene", "") == "":
			bridge.complete(request, {}, "Set a project main scene first")
		else:
			editor.play_main_scene()
			bridge.complete(request, {"launchRequested": true, "note": "Select the separate Play session when its runtime registers"})
		return
	if action == "stop":
		editor.stop_playing_scene()
		bridge.complete(request, {"playing": editor.is_playing_scene()})
		return
	if action == "validate":
		var path := str(args.get("path", ""))
		if not path.begins_with("res://") or not path.ends_with(".gd") or path.contains("..") or not FileAccess.file_exists(path):
			bridge.complete(request, {}, "Validate requires a project res:// script .gd path")
			return
		var script := GDScript.new()
		script.source_code = FileAccess.get_file_as_string(path)
		var err := script.reload()
		bridge.complete(request, {"path": path, "valid": err == OK, "errorCode": err}, "Script compilation failed: " + str(err) if err != OK else "")
		return
	if action == "edit" and args.has("source"):
		var path := str(args.get("path", ""))
		if not path.begins_with("res://") or not path.ends_with(".gd") or path.contains("..") or not FileAccess.file_exists(path):
			bridge.complete(request, {}, "Source edit needs an existing project res:// .gd script")
			return
		var context := HashingContext.new()
		context.start(HashingContext.HASH_SHA256)
		context.update(FileAccess.get_file_as_bytes(path))
		var previous := context.finish().hex_encode()
		if str(args.get("expectedSha256", "")) != previous:
			bridge.complete(request, {}, "Script SHA256 changed; inspect source before editing")
			return
		var file := FileAccess.open(path, FileAccess.WRITE)
		if file == null:
			bridge.complete(request, {}, "Native script file could not be opened")
			return
		file.store_string(str(args["source"]))
		file.close()
		context.start(HashingContext.HASH_SHA256)
		context.update(FileAccess.get_file_as_bytes(path))
		editor.get_resource_filesystem().scan()
		bridge.complete(request, {"path": path, "sha256": context.finish().hex_encode(), "validationRequired": true})
		return
	if action == "inspect" and str(args.get("path", "")).ends_with(".gd"):
		var path := str(args["path"])
		if not path.begins_with("res://") or path.contains("..") or not FileAccess.file_exists(path):
			bridge.complete(request, {}, "Inspect requires an existing project res:// script")
			return
		var context := HashingContext.new()
		context.start(HashingContext.HASH_SHA256)
		context.update(FileAccess.get_file_as_bytes(path))
		bridge.complete(request, {"path": path, "source": FileAccess.get_file_as_string(path), "sha256": context.finish().hex_encode()})
		return
	if root == null:
		bridge.complete(request, {}, "Open a scene in the native editor first")
		return
	if action == "transcribe":
		bridge.complete(request, preload("res://addons/neyvia_bridge/scene_observer.gd").transcribe(root))
		return
	if action == "inspect":
		bridge.complete(request, {"scene": root.scene_file_path, "tree": _tree(root), "playing": editor.is_playing_scene()})
		return
	if action == "load_asset":
		var path := str(args.get("path", ""))
		if not path.begins_with("res://") or path.contains("..") or not (path.ends_with(".glb") or path.ends_with(".gltf")):
			bridge.complete(request, {}, "Load asset requires imported project res:// glTF/GLB")
			return
		var asset = load(path)
		if not asset is PackedScene:
			bridge.complete(request, {}, "Asset is not yet imported as PackedScene; wait for native import")
			return
		var instance: Node = asset.instantiate()
		root.add_child(instance)
		instance.owner = root
		editor.mark_scene_as_unsaved()
		bridge.complete(request, {"path": path, "node": str(instance.get_path()), "tree": _tree(instance)})
		return
	var node := root.get_node_or_null(NodePath(str(args.get("node", "."))))
	if node == null or not (node == root or root.is_ancestor_of(node)):
		bridge.complete(request, {}, "Node must exist in the edited scene")
		return
	if action == "select":
		editor.get_selection().clear()
		editor.get_selection().add_node(node)
		bridge.complete(request, {"selected": str(node.get_path())})
		return
	if action == "edit":
		var property := str(args.get("property", ""))
		var value = args.get("value")
		if property in ["position", "rotation", "scale"] and node is Node3D and _numbers(value, 3):
			value = Vector3(float(value[0]), float(value[1]), float(value[2]))
		elif property in ["position", "rotation", "scale"] and node is Node2D:
			if property == "rotation" and (value is float or value is int) and is_finite(float(value)):
				value = float(value)
			elif property != "rotation" and _numbers(value, 2):
				value = Vector2(float(value[0]), float(value[1]))
			else:
				bridge.complete(request, {}, "Node2D requires two numbers; rotation is radians")
				return
		elif property == "visible" and value is bool and (node is Node3D or node is CanvasItem):
			pass
		else:
			bridge.complete(request, {}, "Edit supports typed position, rotation, scale and visibility")
			return
		var undo := get_undo_redo()
		undo.create_action("Neyvia edit " + property)
		undo.add_do_property(node, property, value)
		undo.add_undo_property(node, property, node.get(property))
		undo.commit_action()
		editor.mark_scene_as_unsaved()
		bridge.complete(request, {"node": str(node.get_path()), "property": property, "tree": _tree(node)})
		return
	bridge.complete(request, {}, "Unsupported editor action: " + action)
