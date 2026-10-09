"""Read only scoped product-replay token counters; never prompts or credentials."""
from pathlib import Path
import json
import sqlite3

def conductor_usage(repo):
    paths = [repo/'scripts/evidence/FIXCL7-conductor.json',
        *(repo/'.agent_control/fixcl7/previous').glob('*/FIXCL7-conductor.json')]
    roots = {Path(json.loads(path.read_bytes())['root']).resolve() for path in paths if path.is_file()}
    sessions = {}
    for root in roots:
        if not root.is_relative_to((repo/'.agent_control/proofs').resolve()):
            raise ValueError('Usage root is outside owned disposable proofs')
        db = root/'.agent_control/connected_chats.sqlite3'
        if not db.is_file(): continue
        with sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True) as connection:
            # JSON extraction returns counters and identity only, never the run
            # prompt, response, launch environment or broker configuration.
            for identity, session, raw in connection.execute("SELECT run_id, json_extract(data,'$.sessionId'), json_extract(data,'$.usage') FROM connected_session_runs"):
                if not raw or not session or not session.startswith('external:codex:'): continue
                usage = json.loads(raw)
                if usage.get('reportedByTransport') is not True: continue
                sessions[session] = {'runId':identity,'totalTokens':usage.get('totalTokens',0),
                    'cachedInputTokens':usage.get('cachedInputTokens',0),'coverage':usage.get('coverage')}
    return sessions
