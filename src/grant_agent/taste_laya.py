"""C13 routine advice only; no service start and no completion authority."""
from urllib.parse import urlsplit
from .laya_service import endpoint, system1, triage
from .laya_ledger import record

def advise(root, question, options, context, *, path, system1_fn=None):
    def scoped(prompt, schema, **kwargs):
        try:
            url = endpoint()
        except ValueError as exc:
            return {'available':False,'reason':str(exc)}
        if urlsplit(url).port not in range(48801,48810):
            return {'available':False,'reason':'LAYA endpoint outside explicit C13 ports; no network call made'}
        return system1(prompt,schema,**kwargs)
    return triage(root,'C13-taste',question,options,context=context,path=path,
                  system1_fn=system1_fn or scoped,estimate_savings=False)

def check_triage(root, report):
    blocked=[c['check'] for c in report.get('checks',[]) if not c.get('passed') and c.get('level')=='block']
    warnings=[c['id'] for c in report.get('checks',[]) if not c.get('passed') and c.get('severity')=='warn']
    if blocked:
        record(root,task='C13-taste',path='taste.c13.check-triage',decision='repair_required',
               outcome='deterministic',detail='Blocking host checks retain authority',tokensSavedEstimate=0)
        return {'route':'deterministic','decision':'repair_required','blocking':blocked}
    return advise(root,'Triage nonblocking rendered taste observations; choose inspect warnings or continue the existing checked loop.',
                  ['inspect_warnings','continue_checked_loop'],{'warnings':warnings},
                  path='taste.c13.check-triage')

def repair_route(root, differences, *, system1_fn=None):
    rows=[{'rowId':d['rowId'],'cause':d['cause'],'axis':d['axis'],'gap':d['gap'],'repair':d['repair'][:240]}
          for d in differences[:8]]
    if len(rows)<2:
        record(root,task='C13-taste',path='taste.c13.repair-route',decision='single_route',
               outcome='deterministic',tokensSavedEstimate=0)
        return {'route':'deterministic','decision':rows[0]['rowId'] if rows else None}
    return advise(root,'Choose the existing failing difference to repair first. Prefer verified source or broken input repairs before polish; never waive any difference.',
                  [d['rowId'] for d in rows],{'differences':rows},path='taste.c13.repair-route',system1_fn=system1_fn)


def repair_first(gate, path, folder, checks, verdict, change=None):
    """A confident triage may defer criticism, never invent rubric scores or a pass."""
    from .laya_hooks import GATE
    if verdict.get('route') != 'laya' or verdict.get('decision') != 'repair_first' or \
            not isinstance(verdict.get('confidence'), (int, float)) or verdict['confidence'] < GATE:
        return None
    failed = [row for row in checks.get('checks', []) if not row.get('passed')]
    if not failed or checks.get('renderValid') is False:
        return None  # Renderer failures and empty repairs keep the checked route.
    from .taste_checks import FIX, _summary
    from .taste_context import SourceIndex
    from .taste_gate import digest, save
    source = SourceIndex(path.read_text(encoding='utf-8'))
    differences = []
    for row in failed:
        if row['check'] not in FIX:
            return None
        selector = next((hit.get('selector') for hit in row.get('hits', [])
                         if hit.get('selector') and source.find(hit['selector'])), 'body')
        differences.append({'rowId': 'host-' + row['check'], 'axis': 'finish', 'gap': 3,
            'ours': _summary(row), 'better': FIX[row['check']], 'evidence': ['page-checks.json ' + row['check']],
            'cause': 'broken', 'repair': FIX[row['check']], 'scope': 'section', 'selector': selector})
    pending = {'sha256': digest(path), 'folder': str(folder), 'critique': {'differences': differences},
               'pageChecks': checks, 'priorChange': change}
    pending['hostSeal'] = gate._seal(pending)
    gate.repairs['triage:' + str(path)] = pending
    result = {'ok': False, 'status': 'repair_required', 'criticSkipped': True, 'triage': verdict,
              'pageChecks': checks, 'differences': differences, 'folder': str(folder)}
    save(folder / 'repair-required.json', result)
    record(gate.root, task='taste-triage', path='taste.critic_gate', decision='repair_first',
           outcome='answered', confidence=verdict['confidence'],
           prompt_chars=len(path.read_text(encoding='utf-8')), detail='Model critique deferred; completion remains blocked')
    return result
