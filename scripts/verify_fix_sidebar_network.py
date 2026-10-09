"""Real controlled TCP/TLS/Settings journey for the loopback I/O policy fast path."""
from pathlib import Path
import argparse
import hashlib
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
args = parser.parse_args()
assert args.port == 48668
root = REPO / '.agent_control/proofs' / ('FIX-sidebar-network-' + str(time.time_ns()))
root.mkdir(parents=True)
receipt = {'schema': 'neyvia.FIX.sidebar-network.v1', 'root': str(root), 'port': args.port,
           'boundary': 'Only this process and its owned physical-interface same-host listener are targets; no external network request, credentials, Tailscale or NAS. Real settings owner writes, connected TCP, loopback TCP and TLS.', 'checks': []}
listener = None
address = ''
connections = []
def check(name, detail):
    receipt['checks'].append({'name': name, 'ok': True, 'detail': detail})
try:
    # Physical adapters only: never query a virtual/Tailscale interface.
    command = "Get-NetAdapter -Physical | Where-Object Status -eq Up | ForEach-Object { Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 } | Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } | Select-Object -First 1 -ExpandProperty IPAddress"
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                         check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    address = run.stdout.strip()
    assert ipaddress.ip_address(address).is_private and not ipaddress.ip_address(address).is_loopback
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent import local_network_policy as policy
    from grant_agent import neyvia_settings as settings
    from grant_agent.neyvia_workspace_tools import workspace_for
    service = workspace_for(root)
    observed = settings.get(service)
    assert observed['settings']['localOnly'] is False
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('0.0.0.0', args.port))
    listener.listen(4)
    listener.settimeout(4)
    def pair(host):
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(4)
        client.connect((host, args.port))
        accepted, _ = listener.accept()
        accepted.settimeout(4)
        connections.extend([client, accepted])
        return client, accepted
    remote, remote_peer = pair(address)
    remote.sendall(b'BEFORE')
    assert remote_peer.recv(6) == b'BEFORE'
    local, local_peer = pair('127.0.0.1')
    switched = settings.update(service, {'localOnly': True}, observed['revision'])
    assert switched['settings']['localOnly'] is True
    assert remote.fileno() == -1 and remote_peer.fileno() == -1
    try:
        remote.sendall(b'AFTER')
        raise AssertionError('Existing nonloopback connection survived Settings transition')
    except OSError:
        pass
    check('Real connection established online is closed by Settings localOnly transition', {'closedBothEndpoints': True})
    local.sendall(b'LOCAL')
    assert local_peer.recv(5) == b'LOCAL'
    check('Existing literal loopback connection remains usable after Settings transition', {'exactBytes': True})
    def refused():
        stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            stream.connect((address, args.port))
            raise AssertionError('Nonloopback connection was allowed')
        except policy.LocalOnlyError:
            pass
        finally:
            stream.close()
    refused()
    check('New nonloopback connection is refused before its controlled same-host syscall', {'code': 'local_only'})
    # An actual SQL read failure must remain fail-closed, without a cached policy.
    with service.bus.connect() as db:
        db.execute('ALTER TABLE state RENAME TO state_unavailable')
    try:
        assert policy.enabled() is True
        refused()
        local.sendall(b'FAILED_POLICY_LOCAL')
        assert local_peer.recv(19) == b'FAILED_POLICY_LOCAL'
        check('Unreadable existing SQLite state fails closed for nonloopback while literal loopback remains permitted', {'sqlError': 'missing state table', 'externalRefused': True, 'loopbackExactBytes': True})
    finally:
        with service.bus.connect() as db:
            db.execute('ALTER TABLE state_unavailable RENAME TO state')
    for stream in connections:
        stream.close()
    listener.close()
    listener = None
    # Disposable self-signed certificate belongs only to this TLS fixture.
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from datetime import datetime, timedelta, timezone
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Owned loopback fixture')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False).sign(key, hashes.SHA256()))
    cert_path, key_path = root/'owned-cert.pem', root/'owned-tls-material.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    client_context = ssl.create_default_context(cafile=str(cert_path))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', args.port))
    listener.listen(1)
    errors = []
    def tls_server():
        try:
            accepted, _ = listener.accept()
            with server_context.wrap_socket(accepted, server_side=True) as tls:
                assert tls.recv(8) == b'TLS_REAL'
                tls.sendall(b'TLS_REPLY')
        except Exception as error:
            errors.append(type(error).__name__)
    worker = threading.Thread(target=tls_server, daemon=True)
    worker.start()
    with client_context.wrap_socket(socket.socket(), server_hostname='127.0.0.1') as client:
        client.settimeout(5)
        client.connect(('127.0.0.1', args.port))
        client.sendall(b'TLS_REAL')
        assert client.recv(9) == b'TLS_REPLY'
    worker.join(5)
    assert not worker.is_alive() and not errors
    check('Real certificate-verified loopback TLS sends and receives exact bytes with localOnly active', {'exactBytes': True, 'certificateVerified': True})
    receipt['ok'] = True
except Exception as error:
    receipt['ok'] = False
    receipt['errorType'] = type(error).__name__
    receipt['error'] = str(error) if not address or address not in str(error) else 'Controlled same-host fixture failed'
    raise
finally:
    for stream in connections:
        stream.close()
    if listener:
        listener.close()
    receipt['cleanup'] = True
    receipt['sources'] = {p: hashlib.sha256((REPO/p).read_bytes()).hexdigest() for p in ['src/grant_agent/local_network_policy.py', 'src/grant_agent/neyvia_settings.py', 'scripts/verify_fix_sidebar_network.py']}
    (REPO/'scripts/evidence/FIX-sidebar-network.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
