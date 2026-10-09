"""Extract Paul's own user turns (no assistant text, no credential files) for the manual of Paul.

Reads ~/.claude/projects/C--Users-paul-Projects-Neyvia/*.jsonl and ~/.codex/sessions/2026/**
(only desktop/Neyvia/voice user threads; subagent and exec threads skipped) and writes
messages.jsonl into the CURRENT directory. Run it from a scratch folder, never the repo.
"""
import json, glob, os, hashlib, collections
out = []; seen = set()
SKIP_PREFIX = ('<', '# AGENTS.md', '# Context from my IDE', '[Request interrupted', 'Caveat:')


def add(src, sess, ts, text):
    t = text.strip()
    if not t:
        return
    h = hashlib.sha1(t.encode()).hexdigest()
    if h in seen:
        return
    seen.add(h)
    out.append({"src": src, "session": sess, "ts": ts, "text": t, "words": len(t.split()), "sha1": h})


KEEP = {("Codex Desktop", "vscode", "user"), ("Codex Desktop", "vscode", None),
        ("neyvia-connected-sessions", "vscode", "user"), ("neyvia-connected-sessions", "vscode", None),
        ("Codex Desktop", "vscode", "realtime_voice"), ("codex_work_desktop", "vscode", "user")}
for f in sorted(glob.glob(r'C:/Users/user/.codex/sessions/2026/**/*.jsonl', recursive=True)):
    with open(f, encoding='utf-8', errors='replace') as h:
        try:
            p = json.loads(h.readline())['payload']
        except Exception:
            continue
        src = p.get('source'); src = src if isinstance(src, str) else 'subagent'
        k = (p.get('originator'), src, p.get('thread_source'))
        if k not in KEEP:
            continue
        tag = 'codex:' + ('neyvia' if 'neyvia' in k[0] else 'voice' if k[2] == 'realtime_voice' else 'desktop')
        sess = p.get('id'); cwd = (p.get('cwd') or '').replace(chr(92), '/').split('/')[-1]
        for line in h:
            if '"role":"user"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            q = o.get('payload', {})
            if o.get('type') == 'response_item' and q.get('type') == 'message' and q.get('role') == 'user':
                for x in q.get('content', []):
                    t = (x.get('text') or '').strip() if isinstance(x, dict) else ''
                    if '## My request for Codex:' in t:
                        t = t.split('## My request for Codex:', 1)[1].strip()
                    if not t or t.startswith(SKIP_PREFIX) or '<INSTRUCTIONS>' in t[:400]:
                        continue
                    add(tag + '|' + cwd, sess, o.get('timestamp'), t)
for f in sorted(glob.glob(r'C:/Users/user/.claude/projects/C--Users-paul-Projects-Neyvia/*.jsonl')):
    sess = os.path.basename(f)[:-6]
    with open(f, encoding='utf-8', errors='replace') as h:
        for line in h:
            if '"type":"user"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get('type') != 'user' or o.get('isMeta') or o.get('isSidechain'):
                continue
            c = o.get('message', {}).get('content')
            if isinstance(c, list):
                if any(isinstance(x, dict) and x.get('type') == 'tool_result' for x in c):
                    continue
                c = '\n'.join(x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text')
            if not isinstance(c, str):
                continue
            s = c.strip()
            if s.startswith(SKIP_PREFIX):
                continue
            add('claude|Neyvia', sess, o.get('timestamp'), s)
out.sort(key=lambda r: r['ts'] or '')
with open('messages.jsonl', 'w', encoding='utf-8') as w:
    for r in out:
        w.write(json.dumps(r, ensure_ascii=False) + '\n')
print(len(out), collections.Counter(r['src'].split('|')[0] for r in out), sum(r['words'] >= 150 for r in out))
