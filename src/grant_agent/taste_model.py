"""Metered, tool-free Luna image judgement and bounded targeted repair transport."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import time

from .subprocess_utils import capture_bounded_process

REPO = Path(__file__).resolve().parents[2]
DISABLED = ['shell_tool', 'unified_exec', 'apps', 'plugins', 'skill_search', 'memories',
            'multi_agent', 'multi_agent_v2', 'browser_use', 'browser_use_external',
            'computer_use', 'in_app_browser', 'image_generation', 'goals', 'hooks',
            'daemon_auto_start', 'sleep_tool', 'view_image']


def successful_call(out):
    usage=Path(out)/'usage.json'
    if not usage.is_file(): return False
    receipt=json.loads(usage.read_text(encoding='utf-8'))
    return receipt.get('exitCode')==0 and not receipt.get('timedOut') and receipt.get('usageComplete', False)


def measured_usage(stdout):
    """Missing, malformed, or impossible counters are never treated as free calls."""
    usages = []
    valid = True
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'turn.completed':
            row = event.get('usage')
            keys = ('input_tokens', 'cached_input_tokens', 'output_tokens')
            if not isinstance(row, dict) or any(type(row.get(k)) is not int or row[k] < 0 for k in keys):
                valid = False
                continue
            if row['cached_input_tokens'] > row['input_tokens']:
                valid = False
                continue
            usages.append(row)
    usage = {key: sum(row[key] for row in usages)
             for key in ('input_tokens', 'cached_input_tokens', 'output_tokens')}
    usage['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
    return usage, bool(usages) and valid and usage['total_tokens'] > 0


def rejected_before_inference(stdout):
    """Only the explicit capacity rejection with no model/tool activity is zero.

    Warnings represented as error items are client preparation, not inference.
    Generic network failures, partial output and malformed streams remain unknown.
    """
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            if line.strip():
                return False
    capacity = 'Selected model is at capacity. Please try a different model.'
    failed = any(e.get('type') == 'turn.failed' and e.get('error', {}).get('message') == capacity for e in events)
    if not failed:
        return False
    for event in events:
        if event.get('usage') or event.get('type') == 'turn.completed':
            return False
        item = event.get('item')
        if item is not None and item.get('type') != 'error':
            return False
        if event.get('type') not in {'thread.started', 'turn.started', 'turn.failed', 'error', 'item.completed'}:
            return False
    return True


def measured_reservation(prompt, schema, images, prices, budget, *, search=False, model=None):
    """Measure supplied text; reserve uncached input and observed overhead."""
    from .cl.tokens import count_tokens
    from PIL import Image
    import math
    kind='draft' if 'html' in schema.get('properties',{}) else 'repair' if 'edits' in schema.get('properties',{}) else 'critique' if images else 'research'
    text=count_tokens(prompt)+count_tokens(json.dumps(schema))
    image_tokens=0
    for path in images:
        with Image.open(path) as pixels:
            image_tokens+=max(1536,math.ceil(pixels.width/32)*math.ceil(pixels.height/32))
    supplied=text+image_tokens
    overhead=4096
    # Similar prior calls calibrate hidden envelope/input costs, never cache savings.
    comparable = [row for row in [*budget.calibration, *budget.calls]
                  if (model is None or row.get('model') == model) and row.get('callKind') == kind]
    for row in comparable:
        breakdown=row.get('inputBreakdown',{})
        old=breakdown.get('promptTextTokens',0)
        if row.get('searchEnabled')==search and old and row.get('usageComplete'):
            measured=row['usage']['input_tokens']
            old_images=len(breakdown.get('images',[]))*1536
            overhead=max(overhead,math.ceil(max(0,measured-old-old_images)*1.25))
    input_tokens=math.ceil(supplied*1.25)+overhead+(90000 if search and not budget.calibration else 0)
    if search:
        observed=[row['usage']['input_tokens'] for row in [*budget.calibration,*budget.calls]
                  if row.get('usageComplete') and row.get('searchEnabled')]
        input_tokens=max(input_tokens,math.ceil(max(observed,default=90000)*1.5)+supplied*4)
    output_tokens=16000 if kind=='draft' else 2000 if kind=='repair' and comparable else 6000
    for row in comparable:
        prior_kind=row.get('callKind') or ('draft' if not row.get('images') else 'critique')
        if row.get('usageComplete') and row.get('searchEnabled')==search and prior_kind==kind:
            output_tokens=max(output_tokens,math.ceil(row['usage']['output_tokens']*1.25))
    return {'tokens':input_tokens+output_tokens,
            'usd':(input_tokens*prices['input']+output_tokens*prices['output'])/1e6,
            'textTokens':text,'imageAllowance':image_tokens,'overheadAllowance':overhead,
            'outputAllowance':output_tokens,'searchAllowance':90000 if search and not budget.calibration else 0,
            'callKind':kind,'basis':'Measured o200k prompt/schema, image tiles, observed overhead; uncached list price. Estimate, not provider hard cap.'}


def invoke(prompt, out, schema, *, images=(), search=False, timeout=1800, effort='medium', bounded=False,
           model='gpt-6-luna', budget=None, reservation_tokens=None, reservation_usd=None):
    """All image paths are explicit; no model may launch a browser or command."""
    out = Path(out)
    if model not in {'gpt-6-luna', 'gpt-6.1-sol'}:
        raise ValueError('Unsupported explicit taste model')
    if effort not in {'low', 'medium', 'high'}:
        raise ValueError('Explicit supported reasoning effort required')
    prices = json.loads((REPO / 'config/scroll-study-prices.json').read_text(encoding='utf-8'))[model]
    reservation = None
    estimate = None
    if budget is not None:
        estimate=measured_reservation(prompt,schema,images,prices,budget,search=search,model=model)
        tokens=reservation_tokens if reservation_tokens is not None else estimate['tokens']
        reserved_usd=reservation_usd if reservation_usd is not None else estimate['usd']
        reservation=budget.admit(model=model,tokens=tokens,usd=reserved_usd)
    out.mkdir(parents=True, exist_ok=True)
    # Every previous paid invocation must survive a resumed call, including a
    # successful response that did not satisfy the caller's patch contract.
    usage_path = out / 'usage.json'
    if usage_path.is_file():
        previous = json.loads(usage_path.read_text(encoding='utf-8'))
        if previous:
            ordinal=1
            prefix='failed-invocation-' if previous.get('exitCode') != 0 or previous.get('timedOut') or not previous.get('usageComplete',False) else 'prior-invocation-'
            while (out / (prefix+str(ordinal))).exists(): ordinal+=1
            archive=out / (prefix+str(ordinal));archive.mkdir()
            for name in ('usage.json','events.jsonl','stderr.txt','prompt.txt','response-schema.json','response.json'):
                source=out/name
                if source.is_file():source.replace(archive/name)
    schema_path = out / 'response-schema.json'
    schema_path.write_text(json.dumps(schema), encoding='utf-8')
    entry = Path(os.environ['APPDATA']) / 'npm/node_modules/@openai/codex/bin/codex.js'
    args = ['node', str(entry), 'exec', '--ignore-user-config', '--ignore-rules',
            '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
            '--model', model, '--json', '--cd', str(out),
            '-c', 'project_doc_max_bytes=0', '-c', 'model_reasoning_effort='+json.dumps(effort),
            '-c', 'skills.include_instructions=false', '-c', 'skills.max_context_tokens=1',
            '-c', 'web_search="live"' if search else 'web_search="disabled"',
            '--enable', 'skip_host_skill_discovery', '--output-schema', str(schema_path),
            '--output-last-message', str(out / 'response.json')]
    for feature in DISABLED:
        args += ['--disable', feature]
    for path in images:
        args += ['--image', str(Path(path).resolve())]
    if bounded:
        args += ['-c', 'model_context_window=64000', '-c', 'model_auto_compact_token_limit=56000']
    args += ['-']
    (out / 'prompt.txt').write_text(prompt, encoding='utf-8')
    started = time.monotonic()
    try:
        result = capture_bounded_process(args, cwd=out, env=os.environ.copy(), input_text=prompt, timeout=timeout)
    except Exception as exc:
        failure = {'model':model, 'usage':{}, 'usageComplete':False, 'costUsd':None,
                   'exitCode':None, 'timedOut':False, 'elapsedSec':time.monotonic()-started,
                   'errorType':type(exc).__name__, 'reservation':reservation}
        if budget is not None:
            failure['budget'] = budget.account(failure)
        usage_path.write_text(json.dumps(failure, indent=2), encoding='utf-8')
        raise
    (out / 'events.jsonl').write_text(result['stdout'], encoding='utf-8')
    (out / 'stderr.txt').write_text(result['stderr'], encoding='utf-8')
    usage, usage_complete = measured_usage(result['stdout'])
    usage_complete = usage_complete and result['returncode'] == 0 and not result['timedOut']
    rejected = not result['timedOut'] and rejected_before_inference(result['stdout'])
    if rejected:
        usage_complete = True
    cost = ((usage['input_tokens'] - usage['cached_input_tokens']) * prices['input'] +
            usage['cached_input_tokens'] * prices['cached'] + usage['output_tokens'] * prices['output']) / 1e6
    receipt = {'model': model, 'images': [str(p) for p in images], 'usage': usage,
               'usageComplete':usage_complete, 'reservation':reservation, 'reservationEstimate':estimate,
               'rejectedBeforeInference':rejected,
               'costUsd': cost if usage_complete else None, 'knownCostUsd': cost,
               'costBasis': 'repository list-price equivalent; not an invoice; unknown usage is not free',
               'elapsedSec': time.monotonic() - started, 'exitCode': result['returncode'],
               'timedOut': result['timedOut'], 'searchEnabled': search, 'reasoningEffort': effort,
               'callKind':estimate['callKind'] if estimate else None}
    # Optional attribution must never prevent preservation of paid usage.
    try:
        from .cl.tokens import count_tokens
        from PIL import Image
        dimensions=[]
        for path in images:
            with Image.open(path) as pixels:
                dimensions.append({'path':str(path),'width':pixels.width,'height':pixels.height})
        receipt['inputBreakdown']={'promptCharacters':len(prompt),'promptTextTokens':count_tokens(prompt),
            'images':dimensions,'imagePixels':sum(i['width']*i['height'] for i in dimensions),
            'attribution':'Exact text encoding and pixels; provider usage cannot isolate image/hidden tokens',
            'boundedContext':bounded}
    except (ImportError, OSError, ValueError) as exc:
        receipt['inputBreakdown']={'promptCharacters':len(prompt), 'boundedContext':bounded,
                                   'attributionError':type(exc).__name__}
    if budget is not None:
        receipt['budget'] = budget.account(receipt)
    (out / 'usage.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if result['returncode'] != 0 or result['timedOut'] or not usage_complete:
        raise RuntimeError('Model invocation failed or usage unavailable; see ' + str(out / 'usage.json'))
    return json.loads((out / 'response.json').read_text(encoding='utf-8')), receipt


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}

AXES = ['fidelity', 'concept', 'content', 'density', 'illustration', 'motion', 'type', 'color', 'spacing', 'finish']
AXIS_SCHEMA = {'type': 'string', 'enum': AXES}

CRITIQUE_SCHEMA = object_schema({
    'passes': {'type': 'boolean'}, 'quality': {'type': 'number'},
    'anchorVerdict': {'type': 'string', 'enum': ['candidate', 'tie', 'anchor']},
    'briefPasses': {'type': 'boolean'},
    'difference': {'type': 'string'},
    'defects': {'type': 'array', 'items': {'type': 'string'}},
    'lessons': {'type': 'array', 'items': {'type': 'string'}},
    'repairs': {'type': 'array', 'items': {'type': 'string'}},
    'rubric': {'type': 'array', 'items': object_schema({
        'axis': AXIS_SCHEMA, 'score': {'type': 'number', 'minimum': 0, 'maximum': 4},
        'evidence': {'type': 'array', 'items': {'type': 'string'}}, 'fix': {'type': 'string'}})},
    'differences': {'type': 'array', 'items': object_schema({
        'rowId': {'type': 'string'}, 'axis': AXIS_SCHEMA, 'gap': {'type': 'number', 'minimum': 0, 'maximum': 4},
        'ours': {'type': 'string'}, 'better': {'type': 'string'},
        'evidence': {'type': 'array', 'items': {'type': 'string'}},
        'cause': {'type': 'string', 'enum': ['research', 'concept', 'content', 'density', 'visual', 'motion', 'type', 'color', 'spacing', 'finish', 'broken', 'keep']}, 'repair': {'type': 'string'},
        'scope': {'type': 'string', 'enum': ['element', 'section', 'page']},
        'selector': {'type': 'string'}})},
    'rareElements': {'type': 'array', 'items': object_schema({
        'name': {'type': 'string'}, 'primarySource': {'type': 'string', 'pattern':'^https://', 'description':'Exact primary URL from the candidate element credit link; never a prose citation'},
        'uncommon': {'type': 'boolean'}, 'implemented': {'type': 'boolean'},
        'selector': {'type': 'string'}, 'author': {'type': 'string', 'description':'Exact visible credited author string in that element section'},
        'venue': {'type': 'string', 'description':'Exact visible venue string in that element section'}, 'year': {'type': 'integer'}, 'mechanism': {'type': 'string'}})},
})

REPAIR_SCHEMA = object_schema({'edits': {'type': 'array', 'items': object_schema({
    'old': {'type': 'string'}, 'new': {'type': 'string'}, 'rowId': {'type': 'string'}})}, 'explanation': {'type': 'string'}})
