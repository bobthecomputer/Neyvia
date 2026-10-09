"""neyvia.agents.state: the bot side of the agents dashboard, on the same read the UI shows."""
from __future__ import annotations

DEFINITIONS = [
    ("agents.deliveries", "Read the latest successful message delivery metadata for a canonical session; no message text.", {"to": {"type": "string"}}, ["to"]),
    ("agents.overview", "Read the cached live agent tree across connected sessions, subagents, Conductor, Missions, Night Shift and Parallel. Includes edges, source availability, plan limits and measured new tokens; no provider launches.", {}, []),
    ("agents.limits", "Read live subscription limits from the installed CLIs, or refresh them on demand. "
                      "Timestamped last-known values survive restart. Missing quotas remain unavailable.",
     {"refresh": {"type": "boolean"}, "wait": {"type": "boolean"}}, []),
    ("agents.state", "Everything working right now: each running chat (Claude Code, Codex, Neyvia) with what it is doing, "
                     "its checklist progress, context tokens and its sub-agents; the 5-hour and weekly plan limits the apps "
                     "last reported; and work-board claims when that board exists. Read-only.",
     {"limit": {"type": "integer", "minimum": 1, "maximum": 100},
      "offset": {"type": "integer", "minimum": 0}}, []),
]


def call(service, name, args):
    if name == "agents.deliveries":
        from .agents_message import deliveries
        return deliveries(service.bus.root, args["to"])
    if name == "agents.overview":
        from .agents_overview import overview
        return overview(service)
    if name == "agents.limits":
        for key in ("refresh", "wait"):
            if key in args and type(args[key]) is not bool:
                raise ValueError(key + " must be boolean")
        from .connected_sessions.live_limits import service_for
        live = service_for(service.bus.root)
        return live.refresh(wait=args.get("wait", False)) if args.get("refresh") else live.snapshot()
    if name != "agents.state":
        raise ValueError("Unknown agents action")
    limit = args.get("limit", 16)
    offset = args.get("offset", 0)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit is 1-100")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset is a nonnegative integer")
    from .connected_sessions.dashboard import build
    return build(service.broker(), service=service, limit=limit, offset=offset)
