"""Read successful inbox delivery metadata, without exposing message text."""
from __future__ import annotations

import json


def deliveries(root, target):
    from .ui_command_bus import bus_for
    with bus_for(root).connect() as db:
        rows = db.execute("SELECT id,payload FROM events WHERE action='agents.message.sent' "
                          "AND json_extract(payload,'$.to')=? ORDER BY id DESC LIMIT 1", (target,)).fetchall()
    return {"lastId": rows[0][0] if rows else 0,
            "last": json.loads(rows[0][1]) if rows else None}
