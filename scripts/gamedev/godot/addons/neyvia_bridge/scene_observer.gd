@tool
extends RefCounted

static func transcribe(root: Node) -> Dictionary:
	var nodes: Array = []
	var pending: Array = [root]
	while not pending.is_empty() and nodes.size() < 2000:
		var node: Node = pending.pop_back()
		var attributes: Dictionary = {"requiresCollider": bool(node.get_meta("laya_requires_collider", false))}
		var measurements: Dictionary = {"brokenReferences": 0, "colliderCount": 0}
		if node is Node3D:
			attributes["scale"] = [node.scale.x, node.scale.y, node.scale.z]
			measurements["scaleError"] = maxf(maxf(absf(node.scale.x - 1), absf(node.scale.y - 1)), absf(node.scale.z - 1))
		if node is CollisionShape3D:
			measurements["brokenReferences"] = 1 if node.shape == null else 0
			measurements["colliderCount"] = 1 if node.shape != null and not node.disabled else 0
		for child in node.get_children():
			if child is CollisionShape3D and child.shape != null and not child.disabled:
				measurements["colliderCount"] += 1
			pending.append(child)
		if node is MeshInstance3D:
			measurements["brokenReferences"] += 1 if node.mesh == null else 0
			if node.mesh != null:
				measurements["surfaces"] = node.mesh.get_surface_count()
				var bounds: AABB = node.get_aabb()
				attributes["boundsSize"] = [bounds.size.x, bounds.size.y, bounds.size.z]
		if node is Light3D:
			measurements["lightEnergy"] = node.light_energy
		nodes.append({"id": str(root.get_path_to(node)), "kind": node.get_class(), "certainty": "observed",
			"attributes": attributes, "measurements": measurements,
			"relations": {"parent": str(root.get_path_to(node.get_parent())) if node != root else ""}})
	return {"schema": "neyvia.scene.v1", "domain": "godot", "surface": "native-editor", "nodes": nodes,
		"truncated": not pending.is_empty(), "unknown": ["Occlusion, z-fighting and lighting intent require rendered evidence."]}
