"""Recheck the three already-fixed T1 backend policy glitches on FOLLOW ports."""
import json
from pathlib import Path
import sys
import urllib.request

BASE = 'http://127.0.0.1:48447'
receipt = {'schema': 'neyvia.FOLLOW.dictation.v1', 'base': BASE, 'checks': []}
with urllib.request.urlopen(urllib.request.Request(BASE + '/api/auth/local-session', data=b'{}', headers={'Content-Type': 'application/json'})) as response:
    cookie = response.headers['Set-Cookie'].split(';')[0]

def process(text):
    req = urllib.request.Request(BASE + '/api/ui/dictation/process', data=json.dumps({'text': text}).encode(), headers={'Content-Type': 'application/json', 'Cookie': cookie})
    with urllib.request.urlopen(req) as response:
        result = json.load(response)
        assert result['ok'], result
        return result['data']

def checked(name, data, boundary='Real authenticated HTTP on task-local backend'):
    receipt['checks'].append({'name': name, 'passed': True, 'data': data, 'boundary': boundary})
    print('PASS', name)

punctuation = process('Check the parser. new paragraph. , ask cloud code to review it.')
assert all(not segment['text'].startswith(('.', ',')) for segment in punctuation['segments'] if segment['type'] == 'text'), punctuation
checked('T1 removes punctuation after command', punctuation)
french = process('Bonjour je veux écrire cette phrase en français.')
assert french['route_note'] == "That sounded French. The French engine isn't running, so check the text.", french
checked('T1 plain French unavailable-engine message', french)
sys.path.insert(0, 'src')
from grant_agent.neyvia_prompt_dictation import frontier_text
cases = [
    ('Let epsilon be', 'Let epsilon be positive.', '', 'Let epsilon be', True),
    ('Let let epsilon', 'Let let epsilon be positive.', '', 'Let let epsilon', True),
    ('Hello, world', 'Hello, world this is new.', 'Hello, world', '', True),
]
for row in cases:
    stable, provisional = frontier_text(*row)
    assert provisional and stable not in provisional
checked('T1 stable frontier occurs once despite punctuation and stutter', [{'args': row, 'result': frontier_text(*row)} for row in cases], 'Direct production policy call; no new microphone/ASR stream claim')
receipt['limitations'] = ['The named source glitches were already repaired before FOLLOW; no recognizer weights or physical microphone stream replay in this check.']
Path('scripts/evidence/FOLLOW-dictation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
