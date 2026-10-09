"""Real Windows asyncio wakeup sockets inside INTCL's explicit port assignment.

This fixture helper uses connected TCP sockets, like Python's Windows fallback,
but its temporary listener binds only the caller's declared ports
(NEYVIA_PROOF_SOCKETPAIR_PORTS, default 48524 through 48529) instead of port zero.
"""
from __future__ import annotations

import socket
import os
import sys
from pathlib import Path

try:
    from grant_agent.browser_ports import parse_ports
except ImportError:  # standalone script use without src on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from grant_agent.browser_ports import parse_ports


def explicit_socketpair(family=None, type=socket.SOCK_STREAM, proto=0):
    if family is None:
        family = socket.AF_INET
    if family not in (socket.AF_INET, socket.AF_INET6) or type != socket.SOCK_STREAM or proto != 0:
        raise ValueError("INTCL wakeup pairs support only IPv4/IPv6 TCP sockets")
    host = "127.0.0.1" if family == socket.AF_INET else "::1"
    listener = socket.socket(family, type, proto)
    client = None
    accepted = None
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        last_error = None
        configured = os.environ.get('NEYVIA_PROOF_SOCKETPAIR_PORTS')
        ports = [int(value) for value in configured.split(',')] if configured else list(range(48524, 48530))
        # The caller's declared assignment must obey the same limits as every
        # other proof range (unprivileged, bounded, never a live Neyvia port);
        # a new integration track needs no edit to a hard-coded list.
        try:
            parse_ports(ports)
        except ValueError as error:
            raise ValueError('Socketpair ports must belong to the assigned integration proof ranges') from error
        for port in ports:
            try:
                listener.bind((host, port))
                break
            except OSError as error:
                last_error = error
        else:
            raise OSError("All assigned INTCL wakeup ports are occupied") from last_error
        listener.listen(1)
        listener.settimeout(5)
        client = socket.socket(family, type, proto)
        client.setblocking(False)
        try:
            client.connect(listener.getsockname())
        except (BlockingIOError, InterruptedError):
            pass
        client.setblocking(True)
        accepted, _ = listener.accept()
        if accepted.getsockname() != client.getpeername() or client.getsockname() != accepted.getpeername():
            raise ConnectionError("Unexpected peer connected to the INTCL wakeup listener")
        return accepted, client
    except BaseException:
        if accepted is not None:
            accepted.close()
        if client is not None:
            client.close()
        raise
    finally:
        listener.close()


def install_explicit_socketpair() -> None:
    """Call before creating a Windows event loop in a task-owned proof process."""
    socket.socketpair = explicit_socketpair
