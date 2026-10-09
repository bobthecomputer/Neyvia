"""Caller-assigned local port ranges for Neyvia's browser.

Callers state the ports they own, as "48811-48819,48725", through the
NEYVIA_BROWSER_PROOF_PORTS environment variable or an explicit argument.
Nothing here is a hard-coded allowlist of ranges; instead every assignment
must satisfy the same safety limits, so a new track needs no code change.
"""
from __future__ import annotations

# Ports of the live Neyvia app, its helpers and the shipped UI. A caller can
# never claim them as its own fixture or engine range.
LIVE_PORTS = frozenset({4173, 47880, 47881, 47908})
MIN_PORT, MAX_PORT, MAX_ASSIGNED = 1024, 65535, 64


def parse_ports(spec):
    """Parse "a-b,c" (or an iterable of ints) into a validated set of ports."""
    if isinstance(spec, str):
        tokens = [token.strip() for token in spec.split(",") if token.strip()]
        ports = set()
        for token in tokens:
            first, dash, last = token.partition("-")
            try:
                low, high = int(first), int(last if dash else first)
            except ValueError:
                raise ValueError("Browser ports must be integers or low-high ranges: " + repr(token)) from None
            if high < low or high - low >= MAX_ASSIGNED:
                raise ValueError("Browser port range is empty or larger than %d ports: %r" % (MAX_ASSIGNED, token))
            ports.update(range(low, high + 1))
    else:
        ports = set(spec)
        if any(type(port) is not int for port in ports):
            raise ValueError("Browser ports must be integers")
    if not ports or len(ports) > MAX_ASSIGNED:
        raise ValueError("Browser proof ports need between 1 and %d assigned ports" % MAX_ASSIGNED)
    if any(not MIN_PORT <= port <= MAX_PORT for port in ports):
        raise ValueError("Browser proof ports must be unprivileged local ports")
    if ports & LIVE_PORTS:
        raise ValueError("Browser proof ports cannot include the live Neyvia ports")
    return ports
