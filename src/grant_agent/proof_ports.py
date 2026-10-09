"""Explicit fixture port selection; sockets are never intercepted or remapped."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

PORT_ENV = 'NEYVIA_PROOF_PORT_MAP'
ALLOWED_ENV = 'NEYVIA_PROOF_ALLOWED_PORTS'
ROLES_ENV = 'NEYVIA_PROOF_PORT_ROLES'
C7_PORTS = (tuple(range(48741, 48750)) + tuple(range(48871, 48890))
            + tuple(range(48941, 49000)) + tuple(range(48731, 48740)))
C7_PORT_SCHEMA = {'type': 'integer', 'enum': list(C7_PORTS)}


def c7_run_root():
    """Keep default receipts local; admit an explicit D: integration proof root."""
    default = Path(__file__).resolve().parents[2] / '.agent_control/proofs/c7'
    selected = Path(os.environ.get('NEYVIA_C7_RUN_ROOT', default)).resolve()
    if selected != default.resolve():
        selected.relative_to(Path(r'D:\NeyviaRuns').resolve())
    return selected


def c7_port_block(port):
    """Select the caller's explicitly assigned task block without remapping sockets."""
    if type(port) is not int or port not in C7_PORTS:
        raise ValueError('Explicit assigned C7 port required')
    if 48871 <= port <= 48889:
        return list(range(48871, 48880)) if port < 48880 else list(range(48880, 48890))
    if port < 48941:
        first = 48731 if port < 48740 else 48741
        return list(range(first, first + 9))
    first = min(48989, 48941 + ((port - 48941) // 6) * 6)
    return list(range(first, 49000 if first == 48989 else first + 6))


def c7_worker_ports():
    """Native observers share the worker's explicit block; legacy callers keep nine ports."""
    return c7_port_block(int(os.environ.get('NEYVIA_C7_PORT', '48743')))

REQUIRED_PORTS = (48461, 48462, 48463, 48465, 48466, 48467, 48468, 48469,
                  48472, 48473, 48474, 48475, 48476, 48477, 48478, 48479,
                  48481, 48487, 48488, 48489, 48491, 48492, 48494,
                  48495, 48496, 48497, 48498, 48499, 48501, 48502, 48503, 48508, 48509)
INT3_PORT_MAP = dict(zip(REQUIRED_PORTS, (48652, 48654, 48655, 48658, 48656, 48657, 48655, 48652,
                                       48654, 48654, 48655, 48656, 48656, 48657, 48658, 48652,
                                       48652, 48654, 48655, 48656, 48652, 48656, 48654,
                                       48655, 48656, 48657, 48658, 48654, 48652, 48654, 48655, 48656, 48657)))
_PORT_PATTERN = re.compile(r'(?<!\d)(' + '|'.join(map(str, REQUIRED_PORTS)) + r')(?!\d)')


def selected_ports(environment=None):
    """Require one complete reviewed map when enabled; unset preserves old defaults."""
    raw = (os.environ if environment is None else environment).get(PORT_ENV)
    if raw is None:
        return {port: port for port in REQUIRED_PORTS}
    try:
        supplied = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(PORT_ENV + ' must contain a complete JSON port map') from error
    expected = {str(port) for port in REQUIRED_PORTS}
    if not isinstance(supplied, dict) or set(supplied) != expected:
        raise ValueError(PORT_ENV + ' must map exactly all required original fixture ports')
    allowed = {48652, 48654, 48655, 48656, 48657, 48658}
    declaration = (os.environ if environment is None else environment).get(ALLOWED_ENV)
    if declaration is not None:
        try:
            ports = json.loads(declaration)
        except (TypeError, ValueError) as error:
            raise ValueError(ALLOWED_ENV + ' must be an explicit JSON port list') from error
        if (not isinstance(ports, list) or not ports
                or any(type(port) is not int or not 1024 <= port <= 65535 or port == 47881 for port in ports)
                or len(set(ports)) != len(ports)):
            raise ValueError('Proof allowed ports must be distinct explicit non-public integer ports')
        allowed = set(ports)
    if any(type(value) is not int or value not in allowed for value in supplied.values()):
        raise ValueError('Proof fixture targets must belong to the explicit allowed port declaration')
    result = {int(key): value for key, value in supplied.items()}
    roles = json.loads((os.environ if environment is None else environment).get(ROLES_ENV, json.dumps(REQUIRED_PORTS)))
    if not isinstance(roles, list) or any(type(port) is not int or port not in REQUIRED_PORTS for port in roles):
        raise ValueError('Proof fixture roles must name known original ports')
    for group in ((48461, 48462), (48473, 48474), (48487, 48488), (48491, 48492, 48494), (48491, 48499), (48501, 48502)):
        active = set(group) & set(roles)
        if len({result[port] for port in active}) != len(active):
            raise ValueError('Simultaneous or distinct positive/negative fixture ports must remain distinct: ' + str(group))
    return result


def configure_ports(ports, *, roles=None, phases=None):
    """Preserve the reviewed six fixture roles on a caller's assigned ports."""
    if roles is not None:
        if not ports or any(port not in REQUIRED_PORTS for port in roles):
            raise ValueError('Every declared fixture role needs an assigned port')
        if phases is None:
            phases = [roles]
        if (not isinstance(phases, list) or not phases
                or any(not isinstance(phase, list) or len(phase) > len(ports)
                       or len(set(phase)) != len(phase) or any(role not in roles for role in phase) for phase in phases)
                or set(role for phase in phases for role in phase) != set(roles)):
            raise ValueError('Declare complete sequential phases within assigned simultaneous capacity')
        mapping = {str(original): ports[index % len(ports)] for index, original in enumerate(REQUIRED_PORTS)}
        # Only explicitly sequential roles may share an assigned listener.
        bindings = {}
        for phase in phases:
            occupied = {bindings[role] for role in phase if role in bindings}
            for role in phase:
                if role not in bindings:
                    free = [port for port in ports if port not in occupied]
                    if not free:
                        raise ValueError('Simultaneous fixture roles must remain distinct')
                    bindings[role] = free[0]
                    occupied.add(free[0])
            if len({bindings[role] for role in phase}) != len(phase):
                raise ValueError('Simultaneous fixture roles must remain distinct')
        mapping.update({str(role): port for role, port in bindings.items()})
        environment = {ALLOWED_ENV: json.dumps(ports), PORT_ENV: json.dumps(mapping), ROLES_ENV: json.dumps(roles)}
        selected_ports(environment)
        os.environ.update(environment)
        return
    if len(ports) < 6:
        raise ValueError('Verification requires at least six explicitly assigned ports')
    replacements = dict(zip(sorted(set(INT3_PORT_MAP.values())), ports[:6]))
    environment = {ALLOWED_ENV: json.dumps(ports), ROLES_ENV: json.dumps(REQUIRED_PORTS), PORT_ENV: json.dumps({
        str(original): replacements[target] for original, target in INT3_PORT_MAP.items()})}
    selected_ports(environment)  # Validate before modifying the worker environment.
    os.environ.update(environment)


def proof_port(original):
    if type(original) is not int or original not in REQUIRED_PORTS:
        raise ValueError('Unknown original proof fixture port')
    if ROLES_ENV in os.environ and original not in json.loads(os.environ[ROLES_ENV]):
        raise ValueError('Fixture port role was not declared by this worker')
    return selected_ports()[original]


def configure_asyncio(ports, *, pairs=1):
    """Use declared ports for Windows asyncio's private wake-up socket pair.

    No socket calls are intercepted. Only the worker's event-loop factory is
    configured; peer identity is verified before accepting the private pair.
    """
    if os.name != 'nt':
        return
    import asyncio
    import socket
    admitted = tuple(ports)
    if type(pairs) is not int or not 1 <= pairs <= 8:
        raise ValueError('Asyncio proof reserves one to eight bounded event-loop pairs')
    if len(admitted) < 2 or any(p not in range(49081,49090) and p not in range(48871,48890) for p in admitted):
        raise ValueError('Asyncio wake-up sockets require assigned gate ports')

    def wake_pair():
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            for port in reversed(admitted[-2:]):
                try:
                    listener.bind(('127.0.0.1', port))
                    break
                except OSError:
                    if port == admitted[-2]:
                        raise
            listener.listen(1)
            listener.settimeout(5)
            client=socket.socket()
            try:
                client.connect(listener.getsockname())
                server,_=listener.accept()
                if server.getsockname()!=client.getpeername() or server.getpeername()!=client.getsockname():
                    server.close()
                    raise ConnectionError('Unexpected asyncio wake-up peer')
            except BaseException:
                client.close()
                raise
        return server,client

    # Reserve the first private pair before the fixture and engine occupy the
    # two assigned listener ports; the accepted sockets need no listener.
    pending = [wake_pair() for _ in range(pairs)] if len(admitted) == 2 else []
    import atexit
    def close_unused():
        for pair in pending:
            for sock in pair:sock.close()
        pending.clear()
    atexit.register(close_unused)
    class AssignedProactor(asyncio.ProactorEventLoop):
        def _make_self_pipe(self):
            self._ssock,self._csock = pending.pop() if pending else wake_pair()
            self._ssock.setblocking(False)
            self._csock.setblocking(False)
            self._internal_fds+=1

    class AssignedPolicy(asyncio.WindowsProactorEventLoopPolicy):
        _loop_factory=AssignedProactor

    asyncio.set_event_loop_policy(AssignedPolicy())


def proof_text(text):
    """Select declared ports in URLs, XML, argv, env strings and generated child code."""
    if not isinstance(text, str):
        raise TypeError('Proof text must be a string')
    mapping = selected_ports()
    return _PORT_PATTERN.sub(lambda match: str(mapping[int(match.group())]), text)


if __name__ == '__main__':
    print(json.dumps(selected_ports(), sort_keys=True))
