"""Bounded public assets for explicitly authorized local Obscura render fixtures."""
from __future__ import annotations
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

MAX_ASSET = 20 * 1024 * 1024


def fetch_asset(url, depth=0):
    parsed = urlsplit(url)
    if depth > 5 or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError('Only bounded public HTTPS subresources are permitted')
    addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('Private subresource addresses are prohibited')
    # Pin the validated address while preserving TLS and HTTP origin identity.
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=15)
    sock = socket.create_connection((sorted(addresses)[0], 443), timeout=15)
    connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
    try:
        connection.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
                           headers={'User-Agent': 'NeyviaAgent/1.0 (Automation; Obscura)', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308} and response.getheader('Location'):
            return fetch_asset(urljoin(url, response.getheader('Location')), depth + 1)
        if int(response.getheader('Content-Length', '0')) > MAX_ASSET:
            raise ValueError('Render subresource exceeds 20 MB')
        data = response.read(MAX_ASSET + 1)
        if len(data) > MAX_ASSET:
            raise ValueError('Render subresource exceeds 20 MB')
        headers = {key: value for key, value in response.getheaders() if key.lower() not in {'transfer-encoding', 'connection', 'content-length', 'set-cookie'}}
        return response.status, headers, data
    finally:
        connection.close()
