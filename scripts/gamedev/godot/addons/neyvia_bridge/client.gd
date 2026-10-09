@tool
extends Node

signal request_received(request: Dictionary)
# Server frames are bounded at 2 MiB; Godot's 64 KiB default would close the socket
# on a large scene transcript or its echoed completion receipt.
const MESSAGE_BUFFER := 4 * 1024 * 1024
const RECONNECT_SECONDS := 1.0
var context := "Edit"
var capabilities: Array = []
var session_id := ""
var client_id := str(OS.get_process_id()) + ":" + str(Time.get_ticks_usec())
var config: Dictionary = {}
var peer := WebSocketPeer.new()
var waiting := false
var elapsed := 0.0
var error_text := ""
var last_op := ""
var connected_once := false
var drops := 0

func _ready() -> void:
	var file := FileAccess.open("res://.neyvia/gamedev-bridge.json", FileAccess.READ)
	if file == null:
		fail("Project bridge config missing; run Neyvia setup first")
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		fail("Invalid bridge config JSON")
		return
	config = parsed
	var endpoint := RegEx.new()
	endpoint.compile("^ws://127\\.0\\.0\\.1:([0-9]+)$")
	var endpoint_match = endpoint.search(str(config.get("websocketUrl", "")))
	var port := int(endpoint_match.get_string(1)) if endpoint_match != null else 0
	if port < 1024 or port > 65535 or port == 47881 or config.get("token", "") == "":
		fail("Bridge requires an explicit non-public loopback WebSocket port and project token")
		return
	if String(config.get("projectPath", "")).replace("\\", "/").trim_suffix("/") != ProjectSettings.globalize_path("res://").replace("\\", "/").trim_suffix("/"):
		fail("Bridge config projectPath does not match this project")
		return
	open_socket()

func open_socket() -> void:
	# The editor's first filesystem scan and layout load block _process, so an early
	# handshake can exceed the server's open timeout. Reconnect with the same clientId;
	# the backend maps an identical registration back to the same session.
	peer = WebSocketPeer.new()
	peer.inbound_buffer_size = MESSAGE_BUFFER
	peer.outbound_buffer_size = MESSAGE_BUFFER
	waiting = false
	elapsed = 0.0
	var err := peer.connect_to_url(config["websocketUrl"])
	if err != OK:
		push_warning("Neyvia: WebSocket connect failed (" + str(err) + "); retrying")

func fail(message: String) -> void:
	error_text = message
	push_error("Neyvia: " + message)
	set_process(false)

func send(payload: Dictionary) -> void:
	payload["token"] = config["token"]
	last_op = str(payload.get("op", ""))
	var err := peer.send_text(JSON.stringify(payload))
	if err != OK:
		push_warning("Neyvia: WebSocket send failed (" + str(err) + "); reconnecting")
		peer.close()

func _process(delta: float) -> void:
	peer.poll()
	var state := peer.get_ready_state()
	if state == WebSocketPeer.STATE_CLOSED:
		elapsed += delta
		if elapsed >= RECONNECT_SECONDS:
			drops += 1
			if drops == 1 or drops % 30 == 0:
				push_warning("Neyvia: bridge socket closed (code " + str(peer.get_close_code()) + "); reconnecting")
			open_socket()
		return
	if state != WebSocketPeer.STATE_OPEN:
		return
	if not connected_once:
		connected_once = true
		print("Neyvia: bridge socket open")
	while peer.get_available_packet_count() > 0:
		var reply = JSON.parse_string(peer.get_packet().get_string_from_utf8())
		if not reply is Dictionary or not reply.get("ok", false):
			var reason := str(reply.get("error", "Invalid reply") if reply is Dictionary else "Invalid reply")
			if last_op == "register":
				fail("Bridge refused registration: " + reason)
				return
			# A restarted backend forgets live sessions; register again under the same clientId.
			push_warning("Neyvia: bridge refused " + last_op + ": " + reason)
			session_id = ""
			waiting = false
			continue
		waiting = false
		var data: Dictionary = reply.get("data", {})
		if data.has("sessionId") and last_op == "register":
			session_id = str(data["sessionId"])
			print("Neyvia: registered Edit session")
		if data.get("request") is Dictionary:
			waiting = true
			request_received.emit(data["request"])
	elapsed += delta
	if waiting or elapsed < 0.3:
		return
	elapsed = 0.0
	waiting = true
	if session_id.is_empty():
		send({"op": "register", "engine": "godot", "projectPath": config["projectPath"], "context": context, "capabilities": capabilities, "version": Engine.get_version_info().get("string", ""), "clientId": client_id})
	else:
		send({"op": "poll", "sessionId": session_id})

func complete(request: Dictionary, result: Dictionary, error: String = "") -> void:
	send({"op": "complete", "sessionId": session_id, "requestId": request["requestId"], "status": "succeeded" if error.is_empty() else "failed", "result": result, "error": error})

func _exit_tree() -> void:
	peer.close()
