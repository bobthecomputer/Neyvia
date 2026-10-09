"""Count reported provider usage from this task's owned synthetic chat runs.

No provider logs, saved sign-in files, prompts or memory bodies are read.
Executor usage is not exposed; this is explicitly a lower bound, not a bill.
"""
from pathlib import Path
import json
import re
import sqlite3

REPO = Path(__file__).resolve().parents[1]


def main():
    astra = json.loads((REPO / 'docs/memory/astra-usage.json').read_text(encoding='utf-8'))
    runs, seen, empty_stores = [], set(), []
    fixture_root = (REPO / '.agent_control/mem/browser').resolve()
    for folder in sorted(fixture_root.iterdir()):
        if not re.fullmatch('[0-9a-f]{32}', folder.name) or not folder.resolve().is_relative_to(fixture_root):
            continue
        database = folder / '.agent_control/connected_chats.sqlite3'
        if not database.is_file():
            continue
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='connected_session_runs'").fetchone():
                # Early HTTP-only fixtures never admitted a provider turn.
                empty_stores.append(folder.name)
                continue
            rows = db.execute("SELECT run_id, state, json_extract(data, '$.usage'), json_extract(data, '$.model') FROM connected_session_runs").fetchall()
        for identity, state, usage, model in rows:
            if identity in seen:
                continue
            seen.add(identity)
            value = json.loads(usage) if usage else {}
            counts = {key: value.get(key) for key in ('inputTokens', 'outputTokens', 'cachedInputTokens', 'totalTokens')}
            runs.append({'runId': identity, 'fixture': folder.name, 'state': state, 'model': model, **counts,
                'reported': value.get('reportedByTransport') is True})
    total = {'inputTokens': astra['input_tokens'], 'outputTokens': astra['output_tokens'],
             'cachedInputTokens': astra['cached_input_tokens']}
    for row in runs:
        for key in total:
            value = row[key]
            if type(value) is int:
                total[key] += value
    total['grossReportedTokens'] = total['inputTokens'] + total['outputTokens']
    total['uncachedInputTokens'] = total['inputTokens'] - total['cachedInputTokens']
    report = {'ok': True, 'coverage': 'lower-bound', 'executorUsage': 'not_exposed', 'providerUsage': total,
        'astra': astra, 'chatRuns': runs, 'fixturesWithoutRunStore': empty_stores,
        'unreportedChatRuns': sum(not row['reported'] for row in runs),
        'accounting': 'Input includes cached input; output includes reasoning. No double counting of cache or reasoning. All owned attempts included, including failures. Missing usage is not zero.'}
    target = REPO / 'scripts/evidence/MEM-token-usage.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ok': True, 'coverage': report['coverage'], 'providerUsage': total, 'chatRuns': len(runs), 'unreportedChatRuns': report['unreportedChatRuns']}))


if __name__ == '__main__':
    main()
