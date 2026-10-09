"""Author LAYAT chapters in the existing CL manuals and compile their artifacts."""
import json
from pathlib import Path
import sys
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.neyvia_laya_capabilities import DEFINITIONS
from grant_agent.neyvia_efficiency import DEFINITIONS as EFFICIENCY_DEFINITIONS


def author(manual, names, checks, procedures):
    path = ROOT / 'manuals/cl' / (manual + '.cl')
    baseline = Path('D:/NeyviaRuns/laya-train/manual-baselines') / path.name
    if not baseline.exists():
        baseline.parent.mkdir(parents=True, exist_ok=True)
        # These two files were clean at task start; preserve their exact archival CL.
        baseline.write_bytes(subprocess.check_output(['git', 'show', 'HEAD:manuals/cl/' + path.name], cwd=ROOT))
    base = baseline.read_text(encoding='utf-8')
    if manual == 'efficiency':
        # Extend the existing selfcheck's enum in both its archived record and visible type.
        base = base.replace('"preview","route"]', '"preview","route","shutdown","instant"]')
        base = base.replace(r'\"preview\",\"route\"]', r'\"preview\",\"route\",\"shutdown\",\"instant\"]')
        base = base.replace('"taste_triage","page_done","cl_route"]', '"taste_triage","page_done","cl_route","repair_retention"]')
        base = base.replace(r'\"taste_triage\",\"page_done\",\"cl_route\"]', r'\"taste_triage\",\"page_done\",\"cl_route\",\"repair_retention\"]')
    data = cl_to_manual(base)
    schemas = data.setdefault('schemas', {})
    actions = {}
    for procedure in procedures.values():
        for index, step in enumerate(procedure['steps']):
            step.setdefault('save', 'observed' + str(index))
    for name, description, props, required in DEFINITIONS + EFFICIENCY_DEFINITIONS:
        if name not in names:
            continue
        tool = 'neyvia.' + name
        schema = {'type': 'object', 'properties': props, 'required': required}
        schemas[tool] = schema
        actions[name.split('.')[-1]] = {'tool': tool, 'schema': tool, 'returns': {'type': 'object'},
                                      'pre': 'Task-local learned artifacts exist', 'effect': description, 'reversible': True}
    data['chapters']['learned-capabilities'] = {'title': 'Calibrated LAYA capabilities and separate personal conditioning',
        'state': {}, 'actions': actions, 'checks': checks, 'procedures': procedures, 'judge': {},
        'pitfalls': [{'failure': 'Similarity, a draft, static lint or caller-supplied render measurements are mistaken for quality proof',
                      'recovery': 'Keep escalation; require fresh rendering and independent calibrated evidence'}],
        'frontier': ['Frozen LAYA weights are unchanged. Sparse retrieval and original grammar composition are explicitly identified; uncalibrated areas abstain.',
                     'Personal identity votes remain context, never quality labels. Rendered component novelty has not been rated by Paul.'],
        'guidance': ['These same native tools are available to agents, App Factory and the taste loop. They never publish or execute generated code.']}
    if manual == 'efficiency':
        checks['instant-effects'] = {'tool': 'neyvia.efficiency.laya_selfcheck', 'args': {'part': 'instant'},
            'expect': {'op': 'schema', 'path': '', 'schema': {'type': 'object', 'required': [
                'writeChangesNextAnswer', 'correctionChangesNextAnswer', 'survivesReopen', 'contradictionAbstains',
                'forgetResolvesConflict', 'personalWins', 'userIsolated', 'novelAbstains', 'weakNeverExactAuthority',
                'triageUsesEpisodes', 'verifyUsesEpisodes', 'forgetRemovesAnswer', 'calibratesOnWrite', 'novelCrossConformalAnswer', 'evaluationHoldoutExcluded', 'forgetRecalibrates', 'atomicImportRollback', 'atomicImportCommits', 'personalVotesPreserveTieAndAbstention', 'holdoutSupersedesTrainingRevision', 'incrementalMatchesRebuild', 'manualTriageUsesRoutingEpisodes', 'toolVerifyUsesOutcomeEpisodes'], 'properties': {
                key: {'const': True} for key in ['writeChangesNextAnswer', 'correctionChangesNextAnswer',
                'survivesReopen', 'contradictionAbstains', 'forgetResolvesConflict', 'personalWins', 'userIsolated',
                'novelAbstains', 'weakNeverExactAuthority', 'triageUsesEpisodes', 'verifyUsesEpisodes', 'forgetRemovesAnswer', 'calibratesOnWrite', 'novelCrossConformalAnswer', 'evaluationHoldoutExcluded', 'forgetRecalibrates', 'atomicImportRollback', 'atomicImportCommits', 'personalVotesPreserveTieAndAbstention', 'holdoutSupersedesTrainingRevision', 'incrementalMatchesRebuild', 'manualTriageUsesRoutingEpisodes', 'toolVerifyUsesOutcomeEpisodes']}}}}
        procedures['prove-instant-learning'] = {'goal': 'Write a real label and correction; next answer changes durably, conflicts abstain and forgetting removes its effect',
            'inputs': {'type': 'object', 'properties': {}},
            'steps': [
                {'action': 'laya_learn', 'args': {'domain': 'cl-instant', 'input': 'next answer', 'label': False, 'source': 'cl-write-effect'}, 'save': 'first', 'check': 'instant-first'},
                {'action': 'laya_learn', 'args': {'domain': 'cl-instant', 'input': 'next answer', 'label': True, 'source': 'cl-write-effect'}, 'save': 'second', 'check': 'instant-second'},
                {'action': 'laya_forget', 'args': {'source': 'cl-write-effect'}, 'save': 'forgotten', 'check': 'instant-forgotten'},
                {'action': 'laya_selfcheck', 'args': {'part': 'instant'}, 'save': 'instant', 'check': 'instant-effects'}]}
        for key, field, expected in [('first', 'answer', False), ('second', 'answer', True), ('forgotten', 'escalate', True)]:
            checks['instant-' + key] = check('efficiency.laya_query', {'domain': 'cl-instant', 'input': 'next answer'}, field, expected)
    data['chapters']['learned-capabilities']['guidance'].append(
        'LAYA Instant: efficiency.laya_learn writes domain/input/label/source with layer personal and user paul for taste; efficiency.laya_query reads it, efficiency.laya_forget removes a source. Service callers use triage(task=manual-routing) with manual ID options, or verify(question=tool_outcome) with a toolId/result receipt and success/failure candidate, under the same selected workspace root. Explicit replay is not a statistical guarantee. Novel inputs use store leave-one-out scores, an out-of-fold agreement filter and a singleton cross-conformal set at nominal 0.95. Scores update on each write. This is empirical admission, not a selective accuracy guarantee; independently held-out families must measure at least 0.95 selective accuracy. Evaluation holdouts never enter neighbours, calibration or exact replay. Duplicate vectors do not multiply support. Image cold encoding is measured separately from warm text writes. Never convert author guesses into quality labels.')
    generated = manual_to_cl(data)
    rename = lambda text: re.sub(r'\bt(\d+)\b', r'layat\1', text)
    header_line = next(line for line in base.splitlines() if line.startswith('-- @manual '))
    header = json.loads(header_line[len('-- @manual '):])
    added_header = json.loads(rename(next(line[len('-- @manual '):] for line in generated.splitlines() if line.startswith('-- @manual '))))
    header['chapters']['learned-capabilities'] = added_header['chapters']['learned-capabilities']
    for name in names:
        tool = 'neyvia.' + name
        header['schemas'][tool] = added_header['schemas'][tool]
        header.setdefault('tool_metadata', {})[tool] = added_header['tool_metadata'][tool]
    types = '\n'.join(rename(line) for line in generated.splitlines() if line.startswith('T '))
    chapter = rename(generated[generated.index('L ' + manual + '.learned-capabilities '):])
    result = base.replace(header_line, '-- @manual ' + json.dumps(header, sort_keys=True, separators=(',', ':')))
    result += '\n' + types + '\n' + chapter
    if cl_to_manual(result) != data:
        raise ValueError('Additive authored CL changed an existing contract')
    path.write_bytes(result.encode('utf-8'))


def check(tool, args, path, value):
    return {'tool': 'neyvia.' + tool, 'args': args, 'expect': {'op': 'eq', 'path': path, 'value': value}}


if __name__ == '__main__':
    author('efficiency', ['efficiency.laya_route', 'efficiency.laya_outcome', 'efficiency.laya_training', 'efficiency.laya_selfcheck',
        'efficiency.laya_learn', 'efficiency.laya_query', 'efficiency.laya_forget', 'efficiency.laya_ingest', 'efficiency.laya_experience'],
        {'unknown-abstains': check('efficiency.laya_route', {'intent': 'zzqvxtp'}, 'escalate', True),
         'no-evidence-abstains': check('efficiency.laya_outcome', {'receipt': {}}, 'reason', 'missing-independent-receipt-proof'),
         'gate-is-frozen': check('efficiency.laya_training', {}, 'gate', .95),
         'encoder-unchanged': check('efficiency.laya_training', {}, 'baseWeightsChanged', False),
         'shutdown-during-timeout': check('efficiency.laya_selfcheck', {'part': 'shutdown'}, 'staysStoppedAfterTimeout', True),
         'shutdown-during-ready': check('efficiency.laya_selfcheck', {'part': 'shutdown'}, 'staysStoppedAfterReady', True)},
        {'prove-learned-abstention': {'goal': 'Verify unknown routing, missing receipt proof and the frozen confidence gate through real native tools',
            'inputs': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            'steps': [{'action': 'laya_route', 'args': {'intent': 'zzqvxtp'}, 'check': 'unknown-abstains'},
                      {'action': 'laya_outcome', 'args': {'receipt': {}}, 'check': 'no-evidence-abstains'},
                      {'action': 'laya_training', 'args': {}, 'check': 'gate-is-frozen'},
                      {'action': 'laya_training', 'args': {}, 'check': 'encoder-unchanged'},
                      {'action': 'laya_selfcheck', 'args': {'part': 'shutdown'}, 'check': 'shutdown-during-timeout'},
                      {'action': 'laya_selfcheck', 'args': {'part': 'shutdown'}, 'check': 'shutdown-during-ready'}]}})
    author('design', ['component.find', 'component.invent', 'component.feel'],
        {'find-is-advisory': check('component.find', {'intent': 'search choices keyboard input'}, 'advisoryOnly', True),
         'focus-loss-requires-repair': check('component.feel', {'code': 'button { outline: none; }'}, 'corrective.answer', 'repair'),
         'draft-needs-review': check('component.invent', {'intent': 'search preview compare alternatives'}, 'accepted', False),
         'personal-stays-separate': check('component.feel', {'intent': 'plain writing motion'}, 'personal.correctiveLayerSeparate', True),
         'boolean-overflow': check('component.feel', {'render': {'overflow': True}}, 'corrective.answer', 'repair'),
         'max-width-is-responsive': check('component.feel', {'code': 'main {max-width:1060px}'}, 'corrective.answer', None),
         'pixel-head-is-observed': {'tool':'neyvia.component.feel',
             'args':{'render':{'before':{'$input':'before'},'after':{'$input':'after'}}},
             'expect':{'op':'exists','path':'pixels.headSha256'}}},
        {'prove-component-advice': {'goal': 'Find a learned pattern, compose a new draft, reject focus loss and keep personal taste separate',
            'inputs': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            'steps': [{'action': 'find', 'args': {'intent': 'search choices keyboard input'}, 'check': 'find-is-advisory'},
                      {'action': 'invent', 'args': {'intent': 'search preview compare alternatives'}, 'check': 'draft-needs-review'},
                      {'action': 'feel', 'args': {'code': 'button { outline: none; }'}, 'check': 'focus-loss-requires-repair'},
                      {'action': 'feel', 'args': {'intent': 'plain writing motion'}, 'check': 'personal-stays-separate'},
                      {'action': 'feel', 'args': {'render': {'overflow': True}}, 'check': 'boolean-overflow'},
                      {'action': 'feel', 'args': {'code': 'main {max-width:1060px}'}, 'check': 'max-width-is-responsive'}]},
         'prove-pixel-advice': {'goal':'Observe the actual trained pixel head on two scoped renders; no absolute acceptance claim',
             'inputs':{'type':'object','properties':{'before':{'type':'string'},'after':{'type':'string'}},
                       'required':['before','after'],'additionalProperties':False},
             'steps':[{'action':'feel','args':{'render':{'before':{'$input':'before'},'after':{'$input':'after'}}},
                       'check':'pixel-head-is-observed'}]}})
