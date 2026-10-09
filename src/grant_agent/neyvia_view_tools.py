"""neyvia.view.*: the agent arranges the interface through the same bus the user's layout lives on.

The UI validates every request again (web/src/neyvia/next/nxLayoutModel.js, nxOsStore.js), so these checks only
give the model a clear refusal before anything is emitted. The user can always undo in Arrange mode.
"""
from __future__ import annotations

TEXT = {"type": "string"}
REGIONS = ("sidebar", "main", "panel", "canopy")
WIDGETS = ("continue", "needs", "running", "nightshift", "projects", "usage")
THEMES = ("dark", "light", "sunset", "night", "terminal", "paper", "ember")  # the shell ids; web/src/neyvia/next/nxThemeRegistry.js is the list
SCENES = ("focus", "workshop", "cockpit")
TRANSPARENCY_LEVELS = ("everything", "summaries", "minimal")
PLACEMENTS = ("main", "side", "full", "bubble", "close")

DEFINITIONS = [
    ('view.state', 'Read fresh mounted shell state and DOM observations from the same user interface.', {}, []),
    ("view.place", "Move an already open app or pane by its view.state window id: main beside chat, side panel, full screen, bubble, or close. Keeps its mounted state; side selects left or right.",
     {"id": TEXT, "placement": {"type": "string", "enum": list(PLACEMENTS)},
      "side": {"type": "string", "enum": ["left", "right"]}}, ["id", "placement"]),
    ("view.arrange", "Rearrange the interface: region order left to right, chat dock side, Canopy visibility, sidebar, "
                     "home widgets. Fields left out keep their value; the user can always undo in Arrange.",
     {"order": {"type": "array", "items": {"type": "string", "enum": list(REGIONS)}},
      "dock": {"type": "string", "enum": ["left", "right"]}, "canopy": {"type": "string", "enum": ["auto", "on", "off"]},
      "sidebarHidden": {"type": "boolean"},
      "widgets": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string", "enum": list(WIDGETS)},
                                                                            "size": {"type": "string", "enum": ["s", "m", "l"]}}, "required": ["id"]}}}, []),
    ("view.scene", "Switch the whole setup in one step (focus = just the conversation, workshop = chats and tools, "
                   "cockpit = every agent in view, or a scene the user saved), or save what is on screen with save=<name>.",
     {"name": TEXT, "save": TEXT}, []),
    ("view.float", "Float a chat as a bubble over every screen so its progress stays in view (floating=false brings it back).",
     {"id": TEXT, "floating": {"type": "boolean"}}, ["id"]),
    ("view.theme", "Switch the theme: dark (Forest), light (Morning), sunset, night (Night Green), terminal (green phosphor, monospace), paper (ink on paper, light) or ember (warm coals).", {"theme": {"type": "string", "enum": list(THEMES)}}, ["theme"]),
    ("view.transparency", "Choose how much the thread shows: everything (default), summaries, or minimal. Capture always retains all reasoning and actions the provider exposes.", {"level": {"type": "string", "enum": list(TRANSPARENCY_LEVELS)}}, ["level"]),
    ("view.transparency.state", "Read the durable thread detail choice without scanning provider sessions.", {}, []),
    ("view.ambient", "Turn the ambient light behind the chat on or off (it warms up while an agent works).",
     {"on": {"type": "boolean"}}, ["on"]),
]


def _arrange(args):
    arrangement = {key: args[key] for key in ("order", "dock", "canopy", "sidebarHidden", "widgets") if key in args}
    if not arrangement:
        raise ValueError("Name at least one of order, dock, canopy, sidebarHidden or widgets")
    order = arrangement.get("order")
    if order is not None and (len(set(order)) != len(order) or not set(order) <= set(REGIONS)):
        raise ValueError("order lists each region once: " + ", ".join(REGIONS))
    if any(not isinstance(item, dict) or item.get("id") not in WIDGETS for item in arrangement.get("widgets", [])):
        raise ValueError("Unknown widget; widgets are " + ", ".join(WIDGETS))
    return arrangement


def call(workspace, name, args):
    bus = workspace.bus
    if name == 'view.state':
        from .cl.fixcl4_render_effects import observe
        return {'ok': True, 'state': observe(bus)}
    if name == "view.place":
        from .cl.fixcl4_render_effects import observe
        identity, placement = args.get("id"), args.get("placement")
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("id must name an open window from view.state")
        if placement not in PLACEMENTS:
            raise ValueError("placement must be main, side, full, bubble or close")
        if "side" in args and (placement != "side" or args["side"] not in {"left", "right"}):
            raise ValueError("side is left or right and only applies to side placement")
        current = observe(bus)
        if not current.get("fresh") or not current.get("dom", {}).get("mounted"):
            raise ValueError("Open Neyvia first; a fresh mounted view.state is required")
        if not any(window.get("id") == identity for window in current.get("windows", [])):
            raise ValueError("Unknown open window; read view.state again")
        return workspace.result(name, {"id": identity, "placement": placement,
                                      **({"side": args["side"]} if "side" in args else {})})
    if name == "view.transparency.state":
        return {"ok": True, "transparency": bus.get("transparency", "everything")}
    if name == "view.arrange":
        arrangement = _arrange(args)
        prior = bus.get("arrangement", {})
        bus.update("arrangement", arrangement)
        result = workspace.result(name, arrangement)
        from .proofs_d_ui_planning import check_arranged
        check_arranged(bus, prior, arrangement, result)
        return result
    if name == "view.scene":
        save, scene = str(args.get("save") or "").strip(), str(args.get("name") or "").strip()
        if bool(save) == bool(scene):
            raise ValueError("Give either name (to switch) or save (to keep what is on screen)")
        if save and save.lower() in SCENES:
            raise ValueError(f"{save} is a built-in scene; choose another name")
        payload = {"save": save} if save else {"name": scene}
        return workspace.result(name, payload)
    if name == "view.float":
        identity = str(args.get("id") or "")
        if identity not in bus.get("sessions", {}) and workspace.broker().find_summary(identity) is None:
            raise ValueError("Unknown session")
        floating = args.get("floating", True) is not False
        bus.update("floating", {identity: floating})
        return workspace.result(name, {"id": identity, "floating": floating})
    if name == "view.theme":
        if args.get("theme") not in THEMES:
            raise ValueError("Themes are " + ", ".join(THEMES))
        from .neyvia_settings import THEMES as SETTING_THEMES, update
        result = update(workspace, {"theme": {value: key for key, value in SETTING_THEMES.items()}[args["theme"]]})
        event = next((row for row in result["events"] if row["action"] == name), None)
        return {"ok": True, **result, "theme": args["theme"], **({"event": event} if event else {})}
    if name == "view.transparency":
        if args.get("level") not in TRANSPARENCY_LEVELS:
            raise ValueError("Choose everything, summaries or minimal")
        bus.put("transparency", args["level"])
        from .proofs_settings import check_view
        check_view(bus, "transparency", args["level"])
        return workspace.result(name, {"level": args["level"]})
    if name == "view.ambient":
        if not isinstance(args.get("on"), bool):
            raise ValueError("on must be true or false")
        bus.put("ambient", args["on"])
        from .proofs_settings import check_view
        check_view(bus, "ambient", args["on"])
        return workspace.result(name, {"on": args["on"]})
    raise ValueError("Unknown view action")
