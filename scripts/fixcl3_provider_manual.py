"""Append the exact provider procedures without rewriting historical CL types."""
from pathlib import Path
import json
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl


def main():
    path = REPO / 'manuals/runtime-provider.manual.json'
    clpath = REPO / 'manuals/cl/runtime-provider.cl'
    data = json.loads(path.read_bytes())
    text = clpath.read_text(encoding='utf-8')
    if cl_to_manual(text) != data:
        raise ValueError('Provider manual source differs from its artifact')
    if 'provider-effects' in data['chapters']:
        return
    chapter = {'title': 'Exact provider owner effects', 'state': {}, 'actions': {}, 'checks': {},
        'procedures': {}, 'judge': {}, 'pitfalls': [{'failure': 'A saved session or import receipt is treated as generated model output',
            'recovery': 'Observe actual provider output separately; local peer proves only transport and storage'}],
        'frontier': ['image.generate requires approved configured Codex subscription and a real saved generated image',
            'scroll.generate requires configured Luna CLI, actual generated cards and validation; no account read admitted here',
            'codex.plugins.call requires the plugin own effect observer; generic plugin return is insufficient'],
        'guidance': ['Reuse requestId for a retry; a changed prompt under the same requestId is refused before transport.',
            'CL imports require explicit codexHome; safe skill files stay disabled until review.']}
    cases = [
        ('session.new', 'neyvia.session.new', {'app': {'type':'string'}, 'folder': {'type':'string'},
            'prompt': {'type':'string'}, 'model': {'type':'string'}, 'permissionMode': {'type':'string'},
            'requestId': {'type':'string'}}, ['app','folder','prompt','requestId'], 'create-provider-session',
            'Create the selected provider session, bound to the exact durable request fingerprint'),
        ('claude.mods', 'neyvia.claude.mods', {'enabled': {'type':'boolean'}}, ['enabled'], 'set-claude-mods',
            'Persist the selected workspace plugin launch setting and read it back'),
        ('codex.assets.import', 'codex.assets.import', {'codexHome': {'type':'string'}}, ['codexHome'], 'import-reviewed-assets',
            'Copy exact safe reviewed skills and verify bytes, pointer, catalog and disabled activation policy')]
    data['chapters']['provider-effects'] = chapter
    for action, tool, properties, required, procedure, goal in cases:
        schema = {'type':'object','properties':properties,'required':required,'additionalProperties':False}
        data['schemas'][tool] = schema
        chapter['actions'][action] = {'tool':tool,'schema':tool,'pre':goal,'effect':goal,
            'returns':{'type':'object'},
            'reversible': action == 'claude.mods'}
        chapter['procedures'][procedure] = {'goal':goal,'inputs':schema,
            'steps':[{'action':action,'args':{key:{'$input':key} for key in properties},'save':'observed'}]}
    generated = manual_to_cl(data, {row[1]:{} for row in cases})
    # Preserve the original chapter order and text while taking new lossless
    # type declarations and metadata from the canonical compiler.
    original_lines = text.splitlines()
    original_lines[2] = generated.splitlines()[2]
    original_lines[3:3] = [line for line in generated.splitlines() if line.startswith('T ')]
    chapter_source = generated[generated.index('L runtime-provider.provider-effects v1 --'):]
    text = '\n'.join(original_lines) + '\n' + chapter_source
    if cl_to_manual(text) != data:
        raise ValueError('Provider additions do not roundtrip')
    for target, content in ((path,json.dumps(data,indent=2,ensure_ascii=False)+'\n'),(clpath,text)):
        ending = '\r\n' if b'\r\n' in target.read_bytes() else '\n'
        target.write_bytes(content.replace('\n',ending).encode())
    print(json.dumps({'ok':True,'procedures':[row[4] for row in cases]}))


if __name__ == '__main__':
    main()
