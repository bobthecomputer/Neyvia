"""Application egress boundary. Loopback services remain usable; children fail closed.

Installed before backend startup work. This is not a sandbox for hostile native
code or for other applications on the PC. Never log addresses, argv or secrets.
"""
from __future__ import annotations

import functools
import ipaddress
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import weakref
from contextlib import closing, contextmanager
from pathlib import Path

_lock = threading.RLock()
# Socket registration never reads policy. Keep accepted local sockets off the
# policy lock, which may wait for an unreadable/locked durable Settings store.
_socket_lock = threading.RLock()
_roots: set[Path] = set()
_owners = weakref.WeakKeyDictionary()
_sockets = weakref.WeakSet()
_targets = weakref.WeakKeyDictionary()
_children = {}
_idle_children = {}
_starting_children = 0
_installed = False
_blocked = 0


class LocalOnlyError(PermissionError):
    code = "local_only"
    status = 403


def enabled():
    with _lock:
        roots = set(_roots) | set(_owners.values())
    for root in roots:
        path = root / ".agent_control" / "ui_commands.sqlite3"
        if not path.exists():
            # Closed disposable backends can leave hundreds of registrations.
            # A removed state directory has no policy left to consult; Settings
            # registers it again before reading or writing a recreated store.
            if not root.exists():
                with _lock:
                    # Settings may have recreated it while this reader waited.
                    if not root.exists():
                        _roots.discard(root)
                        for owner, registered in list(_owners.items()):
                            if registered == root:
                                _owners.pop(owner, None)
            continue
        try:
            with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=15)) as db:
                row = db.execute("SELECT value FROM state WHERE key='settings'").fetchone()
            if row:
                saved = json.loads(row[0])
                if not isinstance(saved, dict) or type(saved.get("localOnly", False)) is not bool or saved.get("localOnly") is True:
                    return True
        except (sqlite3.Error, ValueError):
            # An unreadable existing policy cannot confer network authority.
            return True
    return False


def loopback(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    try:
        address = ipaddress.ip_address(str(host).split("%")[0])
        return address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def refuse():
    global _blocked
    _blocked += 1
    raise LocalOnlyError("Local-only mode blocks this network or child-process operation. Turn it off in Settings to continue.")


def check_address(address):
    if isinstance(address, tuple) and address and loopback(address[0]):
        return  # Literal loopback is permitted in both policy modes.
    if enabled() and (not isinstance(address, tuple) or not loopback(address[0])):
        refuse()


def _audit(event, args):
    if event not in {"socket.connect", "socket.sendto", "socket.getaddrinfo", "socket.gethostbyname",
                     "socket.gethostbyaddr", "subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "_winapi.CreateProcess", "os.startfile", "os.startfile/2"}:
        return
    if event == "socket.connect":
        with _socket_lock:
            _targets[args[0]] = args[1]
        if isinstance(args[1], tuple) and args[1] and loopback(args[1][0]):
            return
    elif event == "socket.sendto":
        if isinstance(args[-1], tuple) and args[-1] and loopback(args[-1][0]):
            return
    elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        if loopback(args[0]):
            return
    with _lock:
        if not enabled():
            return
        if event == "socket.connect":
            check_address(args[1])
        elif event == "socket.sendto":
            check_address(args[-1])
        else:
            refuse()


def child_inventory():
    with _lock:
        for pid, child in tuple(_children.items()):
            if child.poll() is not None:
                _children.pop(pid, None)
                _idle_children.pop(pid, None)
        children = {pid: {"pid": pid, "kind": "subprocess"} for pid in _children}
        try:
            import psutil
            for process in psutil.Process().children(recursive=True):
                try:
                    if process.is_running():
                        # Windows creates this console host for the backend itself.
                        # It is not a CLI/MCP job; require the OS executable path,
                        # never exempt an arbitrary child merely by its name.
                        console = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "conhost.exe"
                        if os.path.normcase(process.exe()) == os.path.normcase(str(console)):
                            continue
                        children[process.pid] = {"pid": process.pid, "kind": process.name()}
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied:
                    children[process.pid] = {"pid": process.pid, "kind": "unverified child"}
        except ImportError:
            pass  # audited Popen starts remain tracked when psutil is unavailable
        return list(children.values())


def register_idle_child(process, *, kind, busy, stop):
    """Only the component owning a child can attest it is safe to stop."""
    with _lock:
        _idle_children[process.pid] = (process, kind, busy, stop)


def stop_child(process):
    """Terminate this owned process tree without launching another child CLI."""
    if process.poll() is not None:
        return True
    try:
        import psutil
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        _, alive = psutil.wait_procs([parent, *children], timeout=3)
        if alive:
            return False
    except ImportError:
        process.kill()
    except (ProcessLookupError, psutil.NoSuchProcess):
        pass
    process.wait(timeout=3)
    return True


def stop_idle_children():
    """Refuse active/unknown jobs before stopping any idle owned services."""
    from .neyvia_settings import SettingsConflict
    inventory = child_inventory()
    covered = set()
    callbacks = []
    for pid, (process, kind, busy, stop) in tuple(_idle_children.items()):
        if process.poll() is not None:
            _idle_children.pop(pid, None)
            continue
        if busy():
            raise SettingsConflict(f"{kind} is working. Finish or stop it before enabling local-only mode.")
        covered.add(pid)
        try:
            import psutil
            covered.update(child.pid for child in psutil.Process(pid).children(recursive=True))
        except ImportError:
            pass
        except psutil.NoSuchProcess:
            continue
        callbacks.append(stop)
    if _starting_children or any(row["pid"] not in covered for row in inventory):
        raise SettingsConflict("Finish or stop active backend child jobs before enabling local-only mode")
    for stop in callbacks:
        if stop() is False:
            raise SettingsConflict("A backend child became active. Finish or stop it before enabling local-only mode")
    if active_children():
        raise SettingsConflict("A backend child did not stop; local-only mode was not enabled")


def active_children():
    with _lock:
        return _starting_children + len(child_inventory())


@contextmanager
def child_start():
    """Serialize native child launches that bypass Python subprocess auditing."""
    global _starting_children
    with _lock:
        if enabled():
            refuse()
        _starting_children += 1
    try:
        yield
    finally:
        with _lock:
            _starting_children -= 1


@contextmanager
def transition(local_only):
    """Serialize starts, socket I/O and activation; caller commits within this lock."""
    with _lock:
        if local_only:
            stop_idle_children()
            with _socket_lock:
                streams = [(stream, _targets.get(stream)) for stream in tuple(_sockets)]
            for stream, target in streams:
                try:
                    peer = target or stream.getpeername()
                    if isinstance(peer, tuple) and not loopback(peer[0]):
                        stream.close()
                except OSError:
                    pass
        yield


def status():
    local = enabled()
    return {"localOnly": local, "enforced": _installed, "policy": "loopback-only" if local else "online",
            "blockedAttempts": _blocked, "activeChildren": active_children(), "children": child_inventory()}


def release(owner):
    """Release only this closed service's registration; other owners remain."""
    with _lock:
        before = dict(_owners)
        _owners.pop(owner, None)
        from .proofs_d_host import check_policy_release
        check_policy_release(owner, before, dict(_owners))


def install(root, *, owner=None):
    global _installed
    with _lock:
        if owner is None:
            _roots.add(Path(root).resolve())
        else:
            _owners[owner] = Path(root).resolve()
            from .proofs_d_host import require
            require(_owners.get(owner) == Path(root).resolve(), "d.host.policy-owner", "Settings owner registration differs from its selected root")
        if _installed:
            return
        sys.addaudithook(_audit)
        original_socket = socket.socket.__init__
        @functools.wraps(original_socket)
        def socket_init(stream, *args, **kwargs):
            original_socket(stream, *args, **kwargs)
            with _socket_lock:
                _sockets.add(stream)
        socket.socket.__init__ = socket_init
        def wrap_lookup(original):
            @functools.wraps(original)
            def guarded(*args, **kwargs):
                if loopback(args[0] if args else kwargs.get("host")):
                    return original(*args, **kwargs)
                with _lock:
                    if enabled() and not loopback(args[0] if args else kwargs.get("host")):
                        refuse()
                return original(*args, **kwargs)
            return guarded
        for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
            setattr(socket, name, wrap_lookup(getattr(socket, name)))

        def wrap_io(original, *, destination=False):
            @functools.wraps(original)
            def guarded(stream, *args, **kwargs):
                address = args[-1] if destination and args else None
                if not destination:
                    try:
                        address = stream.getpeername()
                    except OSError:
                        pass
                if isinstance(address, tuple) and address and loopback(address[0]):
                    if destination:
                        with _socket_lock:
                            _targets[stream] = address
                    return original(stream, *args, **kwargs)
                with _lock:
                    if destination and args:
                        with _socket_lock:
                            _targets[stream] = args[-1]
                    if destination:
                        peer = args[-1] if args else None
                    else:
                        try:
                            peer = stream.getpeername()
                        except OSError:
                            peer = None
                    # Literal loopback is permitted by every policy. Avoid a
                    # SQLite policy read for each bounded localhost body chunk.
                    local_peer = isinstance(peer, tuple) and loopback(peer[0])
                    if not local_peer and enabled():
                        if destination:
                            check_address(args[-1])
                        else:
                            if peer is not None:
                                check_address(peer)
                return original(stream, *args, **kwargs)
            return guarded
        for cls, names in ((socket.socket, ("connect", "connect_ex", "send", "sendall", "sendto", "sendfile")),
                           (ssl.SSLSocket, ("send", "sendall", "write"))):
            for name in names:
                setattr(cls, name, wrap_io(getattr(cls, name), destination=name in {"connect", "connect_ex", "sendto"}))
        if hasattr(socket.socket, "sendmsg"):
            original_sendmsg = socket.socket.sendmsg
            def sendmsg(stream, buffers, ancdata=(), flags=0, address=None):
                if isinstance(address, tuple) and address and loopback(address[0]):
                    return original_sendmsg(stream, buffers, ancdata, flags, address)
                if address is not None:
                    with _lock:
                        check_address(address)
                return wrap_io(original_sendmsg)(stream, buffers, ancdata, flags, address)
            socket.socket.sendmsg = sendmsg
        original_child = subprocess.Popen.__init__
        @functools.wraps(original_child)
        def child_init(child, *args, **kwargs):
            with child_start():
                original_child(child, *args, **kwargs)
                with _lock:
                    _children[child.pid] = child
        subprocess.Popen.__init__ = child_init
        if sys.platform == "win32":
            # Windows asyncio uses overlapped Winsock directly, bypassing socket.connect/send.
            from asyncio.windows_events import IocpProactor
            def proactor_io(original, name):
                @functools.wraps(original)
                def guarded(proactor, stream, *args, **kwargs):
                    address = None
                    if isinstance(stream, socket.socket):
                        if name == "connect":
                            address = args[0]
                        elif name == "sendto":
                            address = kwargs.get("addr", args[2] if len(args) > 2 else None)
                        else:
                            try:
                                address = stream.getpeername()
                            except OSError:
                                pass
                        if isinstance(address, tuple) and address and loopback(address[0]):
                            if name in {"connect", "sendto"}:
                                with _socket_lock:
                                    _targets[stream] = address
                            return original(proactor, stream, *args, **kwargs)
                    with _lock:
                        if isinstance(stream, socket.socket):
                            address = None
                            if name == "connect":
                                address = args[0]
                            elif name == "sendto":
                                address = kwargs.get("addr", args[2] if len(args) > 2 else None)
                            if address is not None:
                                with _socket_lock:
                                    _targets[stream] = address
                                check_address(address)
                            elif enabled():
                                check_address(stream.getpeername())
                        return original(proactor, stream, *args, **kwargs)
                return guarded
            for name in ("connect", "send", "sendto", "sendfile"):
                setattr(IocpProactor, name, proactor_io(getattr(IocpProactor, name), name))
        _installed = True
