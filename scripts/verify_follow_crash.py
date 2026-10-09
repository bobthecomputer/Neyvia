"""Exercise an early request error and a successful request on the owned host."""
import argparse
import http.cookiejar
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    assert 48441 <= args.port <= 48449
    base = f'http://127.0.0.1:{args.port}'
    client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def post(path, data):
        try:
            response = client.open(Request(base + path, data=data, headers={'Content-Type': 'application/json'}), timeout=30)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)
    assert post('/api/auth/local-session', b'{}')[0] == 200
    failed = post('/api/backend', b'[]')
    assert failed[0] == 500 and 'SettingsConflict' not in str(failed[1]), failed
    good = post('/api/backend', json.dumps({'command': 'settings_get_command', 'payload': {}}).encode())
    assert good[0] == 200 and good[1]['ok'], good
    receipt = {'item': 'early-error-crash', 'port': args.port, 'checks': {'earlyError': failed, 'recovery': good[0]}, 'passed': True}
    Path('scripts/evidence/FOLLOW-crash.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
