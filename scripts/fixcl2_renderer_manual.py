"""Append the renderer chapter without rewriting existing authored CL records."""
from pathlib import Path
from difflib import SequenceMatcher
import json
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def preserve_lines(previous, updated):
    """Retain exact line endings in unchanged authored records."""
    old = previous.decode('utf-8').splitlines(keepends=True)
    new = updated.splitlines(keepends=True)
    match = SequenceMatcher(None, [line.rstrip('\r\n') for line in old],
                            [line.rstrip('\r\n') for line in new], autojunk=False)
    for tag, first, last, start, end in match.get_opcodes():
        if tag == 'equal':
            new[start:end] = old[first:last]
    return ''.join(new).encode('utf-8')


def main():
    from grant_agent.cl.manuals import cl_to_manual, _source_lines
    from grant_agent.cl.schema import schema_to_type
    from grant_agent.neyvia_workspace_tools import DEFINITIONS
    path = REPO / 'manuals/cl/neyvia-reference.cl'
    previous = path.read_bytes()
    artifact = REPO/'manuals/neyvia-reference.manual.json'
    previous_artifact = artifact.read_bytes()
    text = path.read_text(encoding='utf-8')
    header_line = next(line for line in text.splitlines() if line.startswith('-- @manual '))
    header = json.loads(header_line[len('-- @manual '):])
    if 'renderer' in header['chapters']:
        raise ValueError('Renderer chapter already exists; inspect before changing its contract')
    schemas = {}
    for name, _, properties, required in DEFINITIONS:
        if name in {'pane.show', 'pane.observe'}:
            schemas['neyvia.' + name] = {'type':'object','properties':properties,'required':required}
    chapter = {'title':'Renderer pane acknowledgement', 'state':{}, 'actions':{}, 'checks':{},
               'procedures':{}, 'judge':{}, 'pitfalls':[], 'frontier':[], 'guidance':[]}
    chapter['state']['visible-pane'] = {'tool':'neyvia.pane.observe','args':{},
        'inputs':{'type':'object','properties':{},'required':[]}, 'shape':{'type':'object'}}
    for tool in schemas:
        chapter['actions'][tool.removeprefix('neyvia.')] = {'tool':tool,'schema':tool,
            'pre':'Authenticated owner renderer uses this workspace event channel',
            'effect':'Fresh content observation' if tool.endswith('.observe') else 'Request a pane; completion waits for mounted visible content acknowledgement',
            'reversible':True,'returns':{'type':'object'}}
    chapter['checks']['visible'] = {'tool':'neyvia.pane.observe','args':{},
        'expect':{'op':'eq','path':'visible','value':True}}
    chapter['procedures']['show-observed-pane'] = {'goal':'Mount the requested pane and verify its fresh rendered content',
        'inputs':schemas['neyvia.pane.show'], 'steps':[{'action':'pane.show',
            'args':{'kind':{'$input':'kind'},'target':{'$input':'target'}},'save':'request','check':'visible'}]}
    chapter['pitfalls'] = [{'failure':'No renderer content report or stale observation',
        'recovery':'Mount in the owner shell and report content over /api/ui/ack; never invent a renderer receipt'}]
    chapter['frontier'] = ['Claude UI wiring and real Neyvia renderer mount/content proof remain required; queued pane events are incomplete']
    chapter['guidance'] = ['ACK observation: paneId, runtimeId, kind, target, contentHash (SHA-256 of UTF-8 displayed content), mounted, visible. Heartbeat at most 5 seconds; reports expire after 30 seconds. File content uses normalized editor text.']
    chapter = json.loads(json.dumps(chapter,sort_keys=True))
    header['chapters']['renderer'] = {'title':chapter['title']}
    additions = []
    for ordinal, (tool, schema) in enumerate(schemas.items()):
        alias = 'fixcl_renderer_' + str(ordinal)
        header['schemas'][tool] = alias
        header['tool_metadata'][tool] = {'mutability_class':'read' if tool.endswith('.observe') else 'none'}
        additions.append('T ' + alias + ' ' + schema_to_type(schema))
    text = text.replace(header_line, '-- @manual ' + json.dumps(header,sort_keys=True,separators=(',',':')), 1)
    additions.append('L neyvia-reference.renderer v1 -- Renderer pane acknowledgement')
    for section in ('state','actions','checks','procedures','judge','pitfalls','frontier','guidance'):
        rows = chapter[section]
        for key, row in (rows.items() if isinstance(rows,dict) else enumerate(rows)):
            additions.append('-- @record ' + json.dumps({'chapter':'renderer','section':section,'key':str(key),'data':row},sort_keys=True,separators=(',',':')))
            additions.extend(_source_lines(section,str(key),row,chapter,schemas,'neyvia-reference',header['tool_metadata'],version='1.1'))
    text = text.rstrip('\n') + '\n' + '\n'.join(additions) + '\n'
    data = cl_to_manual(text)
    path.write_bytes(preserve_lines(previous, text))
    artifact.write_bytes(preserve_lines(previous_artifact, json.dumps(data,indent=2,ensure_ascii=False)+'\n'))
    print(json.dumps({'manual':data['id'],'rendererChapter':True}))


if __name__ == '__main__':
    main()
