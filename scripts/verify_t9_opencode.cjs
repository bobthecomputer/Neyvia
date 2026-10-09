/* Real installed OpenCode ACP edit/approval/diff/interrupt/resume journey.
 * Explicit provider choice; no provider fallback and no package installation.
 * Usage: node scripts/verify_t9_opencode.cjs [advertised OpenCode model ID]
 */
const { spawn } = require('node:child_process');
const { resolve } = require('node:path');
const model = process.argv[2] || 'opencode-go/deepseek-v4.1-flash';
const python = process.env.T9_PYTHON || 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const source = String.raw`
import json, sys, time, uuid
from pathlib import Path
from grant_agent.connected_sessions.opencode import OpenCodeAdapter
from grant_agent.connected_sessions.model import TurnOptions
from grant_agent.connected_sessions.broker import make_session_id
from grant_agent.external_chat_inventory import _host
folder = Path('.agent_control/t9-opencode/real-' + uuid.uuid4().hex[:12]).resolve()
folder.mkdir(parents=True)
target = folder / 'acceptance.txt'
target.write_text('first\n', encoding='utf-8')
adapter = OpenCodeAdapter(folder)
receipt = {'providerModel': sys.argv[1], 'transport': 'installed OpenCode ACP stdio', 'folder': str(folder), 'checks': {}, 'turns': []}
started = time.monotonic()
try:
    options = adapter.options()
    receipt['version'] = options.get('version')
    assert any(row['id'] == sys.argv[1] for row in options['models']), 'Explicit model is not advertised; no fallback allowed'
    turn_options = TurnOptions(model=sys.argv[1], permission_mode='workspace')
    def run_turn(sid, text, action):
        events, runid = [], 't9-' + uuid.uuid4().hex
        approvals = []
        def emit(event):
            events.append(event)
            pending = event.get('pendingRequest')
            if event.get('type') == 'run.state' and pending:
                approvals.append(pending['requestId'])
                if action == 'interrupt':
                    adapter.interrupt(runid)
                else:
                    adapter.answer(runid, pending['requestId'], {'decision': 'approve'})
        error, native = None, None
        try:
            native = adapter.start_turn(sid, text, turn_options, cwd=str(folder), run_id=runid, emit=emit)
        except Exception as exc:
            error = {'code': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)[:600]}
        turn = {'action': action, 'sessionId': native, 'error': error, 'approvalCount': len(approvals), 'events': events}
        receipt['turns'].append(turn)
        print(json.dumps({'progress': action, 'error': error, 'approvalCount': len(approvals)}), flush=True)
        return turn
    first = run_turn(None, 'Read acceptance.txt. Use the edit tool to replace first with second in that file. Change no other file. Then say EDIT_DONE.', 'approve')
    receipt['checks']['editApproved'] = target.read_text(encoding='utf-8') == 'second\n' and first['approvalCount'] > 0 and not first['error']
    assert receipt['checks']['editApproved'], 'First edit or provider failed'
    receipt['checks']['liveDiff'] = any(e.get('item', {}).get('kind') == 'diff' and '-first' in e['item']['data'].get('patch', '') and '+second' in e['item']['data'].get('patch', '') for e in first['events'])
    sid = make_session_id('opencode', _host()['deviceId'], first['sessionId'])
    interrupted = run_turn(sid, 'Use the edit tool to replace second with third in acceptance.txt. Change no other file.', 'interrupt')
    receipt['checks']['interruptedBeforeEdit'] = interrupted['approvalCount'] > 0 and target.read_text(encoding='utf-8') == 'second\n' and interrupted['error'] is not None
    resumed = run_turn(sid, 'The last change was interrupted. Read acceptance.txt and use the edit tool to replace second with third. Change no other file. Then say RESUMED_DONE.', 'approve')
    receipt['checks']['sameSessionResume'] = resumed['sessionId'] == first['sessionId'] and target.read_text(encoding='utf-8') == 'third\n' and not resumed['error']
    page = OpenCodeAdapter(folder).read(sid)
    receipt['checks']['persistedDiff'] = any(item.kind == 'diff' for item in page.items)
    receipt['checks']['persistedTool'] = any(item.kind == 'tool' for item in page.items)
    receipt['persistedKinds'] = [item.kind for item in page.items]
    receipt['checks']['pagedHistory'] = [item.id for item in adapter.read(sid, before_seq=page.items[-1].seq, limit=2).items] == [item.id for item in page.items[-3:-1]]
    receipt['checks']['cursorHasNoDuplicates'] = not adapter.read(sid, cursor=page.cursor).items
except Exception as exc:
    receipt['blocker'] = {'code': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)[:600]}
finally:
    adapter.close()
    receipt['elapsedSeconds'] = round(time.monotonic() - started, 3)
    receipt['ok'] = bool(receipt['checks']) and all(receipt['checks'].values()) and 'blocker' not in receipt
    destination = Path('scripts/evidence/T9-opencode.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'ok': receipt['ok'], 'checks': receipt['checks'], 'blocker': receipt.get('blocker'), 'receipt': str(destination)}), flush=True)
sys.exit(0 if receipt['ok'] else 1)
`;
const child = spawn(python, ['-u', '-c', source, model], {
  cwd: resolve(__dirname, '..'),
  env: { ...process.env, PYTHONPATH: resolve(__dirname, '../src') },
  windowsHide: true, stdio: ['ignore', 'inherit', 'inherit'],
});
const timeout = setTimeout(() => {
  if (process.platform === 'win32') spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
  else child.kill('SIGKILL');
  console.error('T9 OpenCode proof exceeded 240 seconds; stopped only its owned process tree.');
}, 240000);
child.on('error', error => { clearTimeout(timeout); console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { clearTimeout(timeout); process.exitCode = code ?? 1; });
