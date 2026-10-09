"""Prove a message against its fresh successful delivery event."""
from __future__ import annotations

from ..agents_message import deliveries

SUPPORTED = {"neyvia.message"}


def readonly(name, args):
    return True if name == "neyvia.agents.deliveries" else None


def snapshot_for(protocol, name, args):
    return deliveries(protocol.gateway.root, args["to"])


def checks_for(protocol, name, args):
    if protocol.scope is not None and "neyvia.agents.deliveries" not in protocol.scope:
        return []

    def verify(arguments, value, before):
        observed = deliveries(protocol.gateway.root, arguments["to"])
        last = observed["last"] or {}
        return bool(value.get("ok") and observed["lastId"] > before["lastId"]
                    and last.get("to") == arguments["to"]
                    and last.get("from") == arguments.get("from")
                    and last.get("delivery") == value.get("delivery"))

    return [{"name": "effect-agent-message-delivered", "observer": True, "effect": True,
             "subjectKey": "agent-message:" + args["to"],
             "bindSubject": lambda arguments, value, previous: "agent-message:" + arguments["to"],
             "observerTool": "neyvia.agents.deliveries", "subject": {"to": args["to"]},
             "expectation": "A new successful delivery event matches the exact destination, sender and delivery mode",
             "check": verify}]
