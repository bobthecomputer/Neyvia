extends Node

const Client = preload("res://addons/neyvia_bridge/client.gd")
var bridge

func _ready() -> void:
	if Engine.is_editor_hint():
		return
	bridge = Client.new()
	bridge.context = "Play"
	bridge.capabilities = ["inspect", "interact", "stop"]
	bridge.request_received.connect(_request)
	add_child(bridge)

func _snapshot(node: Node, depth: int = 0) -> Dictionary:
	var result := {"name": str(node.name), "path": str(node.get_path()), "type": node.get_class(), "children": []}
	if node is Node3D:
		result["position"] = [node.position.x, node.position.y, node.position.z]
	if node is Node2D:
		result["position"] = [node.position.x, node.position.y]
	if node.has_method("neyvia_inspect"):
		result["state"] = node.call("neyvia_inspect")
	if depth < 20:
		for child in node.get_children():
			result["children"].append(_snapshot(child, depth + 1))
	return result

func _request(request: Dictionary) -> void:
	var root := get_tree().current_scene
	var args: Dictionary = request.get("args", {})
	var action := str(request.get("action", ""))
	if root == null:
		bridge.complete(request, {}, "No running current scene")
		return
	if action == "inspect":
		bridge.complete(request, {"tree": _snapshot(root), "frames": Engine.get_process_frames()})
	elif action == "interact":
		var node := root.get_node_or_null(NodePath(str(args.get("node", "."))))
		if node == null or not (node == root or root.is_ancestor_of(node)) or not node.has_method("neyvia_interact"):
			bridge.complete(request, {}, "Target needs a game-owned neyvia_interact(args) method")
			return
		var result = node.call("neyvia_interact", args.get("input", {}))
		if not result is Dictionary:
			bridge.complete(request, {}, "Game interaction must return a result Dictionary")
			return
		bridge.complete(request, {"interaction": result, "tree": _snapshot(root)})
	elif action == "stop":
		# The editor stop action proves the process exited. This receipt is a quit request.
		bridge.complete(request, {"quitRequested": true})
		get_tree().create_timer(0.2).timeout.connect(func(): get_tree().quit())
	else:
		bridge.complete(request, {}, "Unsupported runtime action: " + action)
