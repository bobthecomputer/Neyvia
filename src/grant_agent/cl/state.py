"""CL view of the existing immutable observer stream; JSON remains archival."""
from __future__ import annotations
from .renderer import render_state, render_delta


def observation_text(layer, result, store, lookup):
    """A retained T5 handle points to the actual state, including large sources."""
    value = lookup(result["handle"])["value"]
    if result.get("mode") == "diff":
        header = render_state(layer, value, store=store, budget=0)
        delta = result.get("diff")
        if delta is None and result.get("diffHandle"):
            delta = lookup(result["diffHandle"])["value"]
        return header + (render_delta(layer, delta, store=store) if delta else "D " + layer + " same\n")
    return render_state(layer, value, store=store)
