"""Ground synchronous command observations in the existing native action journal."""
from __future__ import annotations
from copy import deepcopy
import json
from .host import unwrap
from ..action_receipts import _digest

def observe(gateway, output, arguments):
    """Read a completed, request-bound journal result; never execute a command.

    NativeActionStore already records the request before dispatch and prevents
    unsafe replay. CL's extra check rereads the result/hash and checks the exact
    returned command, cwd and exit code rather than trusting a success label.
    """
    if not isinstance(output, dict) or not output.get('actionId'):
        return None
    identity=output['actionId']
    record=gateway.actions.inspect(identity)
    if record.get('toolId')!='terminal.exec' or record.get('status')!='completed':
        return None
    path=gateway.actions._path(identity)
    if output.get('actionReceiptPath')!=str(path):
        return None
    saved=json.loads(path.with_suffix('.result').read_text(encoding='utf-8'))
    if _digest(saved)!=record.get('resultHash'):
        return None
    # Action IDs and replay metadata are added after hashing the saved result.
    returned={k:v for k,v in output.items() if k not in
              {'actionId','actionReceiptPath','duplicateSuppressed','observation'}}
    if returned!=saved:
        return None
    envelope=unwrap(saved)
    result=envelope.get('toolResult',envelope)
    if not isinstance(result,dict) or result.get('command')!=arguments.get('command'):
        return None
    if result.get('exitCode')!=0 or result.get('timedOut') or result.get('captureIncomplete'):
        return None
    return deepcopy(result)

def verified(gateway, output, arguments, value):
    try:
        observed=observe(gateway,output,arguments)
        command = value.get('toolResult',value)
        command = {key:item for key,item in command.items() if key != 'terminalActionId'}
        return observed is not None and observed==command
    except (ValueError,KeyError,OSError,TypeError):
        return False
