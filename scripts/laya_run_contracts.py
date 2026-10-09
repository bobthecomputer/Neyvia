"""Run the authored CL contracts, compile repeated verified runs and replay them."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train/contracts')
sys.path.insert(0, str(ROOT / 'src'))
os.environ['NEYVIA_TOOL_AUTO_UPDATE'] = '0'
os.environ['FLUXIO_WATCHDOG_AUTOSTART'] = '0'
os.environ['NEYVIA_COORDINATOR_AUTOSTART'] = '0'
os.environ['NEYVIA_TASTE_ASSETS'] = 'C:/Users/user/Projects/nx-c13-taste/.agent_control/c13h-assets'
os.environ['NEYVIA_TASTE_DEPS'] = 'C:/Users/user/Projects/nx-c13-taste/.agent_control/c13h-deps'
os.environ['NEYVIA_TASTE_STATE'] = str(RUN.parent / 'vision')
os.environ['NEYVIA_TASTE_READ_CACHE'] = str(ROOT / 'proof/r11/learning/embeddings')
from grant_agent.neyvia_gateway import NeyviaToolGateway
from grant_agent.neyvia_manuals import unwrap


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    gateway = NeyviaToolGateway(RUN, allow_mutations=True, permission_mode='workspace', managed_capabilities=False)
    run_id = str(time.time_ns())
    receipts = []
    for manual, procedure in [('efficiency', 'prove-learned-abstention'), ('efficiency', 'prove-instant-learning'), ('design', 'prove-component-advice')]:
        args = {'id': manual, 'chapter': 'learned-capabilities', 'procedure': procedure, 'inputs': {}}
        for index in range(2):
            result = gateway.call_native('neyvia.manual.run', args, action_id=f'layat-{run_id}-{procedure}-{index}')
            receipts.append({'tool': 'neyvia.manual.run', 'manual': manual, 'result': result})
            (RUN / 'receipt.json').write_text(json.dumps(receipts, indent=2, default=str), encoding='utf-8')
            print(manual, 'run', index, result.get('ok'), result.get('status'), flush=True)
            if not result.get('ok'):
                raise RuntimeError(json.dumps(result, default=str)[-1500:])
        compiled = gateway.call_native('neyvia.manual.compile', {**args, 'minRuns': 2}, action_id='layat-compile-' + run_id + procedure)
        receipts.append({'tool': 'neyvia.manual.compile', 'result': compiled})
        script = unwrap(compiled)
        if 'scriptId' not in script:
            raise RuntimeError(json.dumps(compiled, default=str)[-1500:])
        replay = gateway.call_native('neyvia.manual.script.run', {'scriptId': script['scriptId'], 'inputs': {}}, action_id='layat-replay-' + run_id + procedure)
        receipts.append({'tool': 'neyvia.manual.script.run', 'result': replay})
        if not replay.get('ok'):
            raise RuntimeError(json.dumps(replay, default=str)[-1500:])
        print(manual, 'compiled and replayed', flush=True)
    (RUN / 'receipt.json').write_text(json.dumps(receipts, indent=2, default=str), encoding='utf-8')
    summary = {'passed': True, 'procedures': 3, 'verifiedRuns': 6, 'compiledReplays': 3,
               'receipt': str(RUN / 'receipt.json'), 'boundary': 'Fresh worktree native gateway and actual CL manual runner; attached long-lived MCP catalog not restarted'}
    pixel_gateway = NeyviaToolGateway(RUN.parent, allow_mutations=True, permission_mode='workspace', managed_capabilities=False)
    pixel = pixel_gateway.call_native('neyvia.manual.run', {'id':'design','chapter':'learned-capabilities',
        'procedure':'prove-pixel-advice','inputs':{'before':'invented/repair-390-light-before.png',
            'after':'invented/repair-390-light-after.png'}}, action_id='layat-pixels-'+run_id)
    result = unwrap(pixel)
    if not pixel.get('ok'):
        raise RuntimeError('Actual pixel-head tool path failed: ' + json.dumps(pixel,default=str)[-1000:])
    summary['procedures'] += 1
    summary['verifiedRuns'] += 1
    summary['pixelTool'] = result
    (ROOT / 'scripts/evidence/LAYAT-cl-contracts.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
