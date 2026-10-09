import { spawnSync } from 'node:child_process';

const python = process.env.PYTHON ?? 'python';
const harness = String.raw`
import base64, io, json, pathlib, tempfile, zipfile
from src.grant_agent.skill_import import inspect_skills, install_skills

with tempfile.TemporaryDirectory(prefix='neyvia-skill-import-check-') as tmp:
    root = pathlib.Path(tmp)
    md_a = b'---\nname: Alpha\ndescription: First skill\n---\nAlpha instructions\n'
    md_b = b'---\nname: Beta\ndescription: Second skill\n---\nBeta instructions\n'
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('pack/one/SKILL.md', md_a)
        z.writestr('pack/one/references/help.md', b'Reference material')
        z.writestr('pack/two/skill.md', md_b)
    files = [
        {'name': 'local.md', 'dataBase64': base64.b64encode(b'---\nname: Local\ndescription: Individual\n---\nLocal instructions\n').decode()},
        {'name': 'skills.zip', 'dataBase64': base64.b64encode(zbuf.getvalue()).decode()},
    ]
    inspected = inspect_skills(root, {'files': files})
    assert inspected['ok'], inspected
    assert {row['name'] for row in inspected['items']} == {'Alpha', 'Beta', 'Local'}, inspected
    assert next(row for row in inspected['items'] if row['name'] == 'Alpha')['fileCount'] == 2
    chosen = [row['id'] for row in inspected['items'] if row['name'] in ('Alpha', 'Local')]
    installed = install_skills(root, {'importId': inspected['importId'], 'selectedIds': chosen})
    assert installed['ok'] and {row['name'] for row in installed['results']} == {'Alpha', 'Local'}, installed
    assert (root/'.codex/skills/Alpha/references/help.md').read_text() == 'Reference material'
    assert (root/'.codex/skills/Local/SKILL.md').read_bytes().endswith(b'Local instructions\n')
    assert not (root/'.codex/skills/Beta').exists(), 'unselected skill must not install'
    repeat = inspect_skills(root, {'files': files})
    overwrite = install_skills(root, {'importId': repeat['importId'], 'selectedIds': [row['id'] for row in repeat['items'] if row['name'] in ('Alpha','Local')]})
    assert all(row['status'] == 'skipped' for row in overwrite['results']), overwrite
    expired = install_skills(root, {'importId': inspected['importId'], 'selectedIds': chosen})
    assert not expired['ok'], expired
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, 'w') as z: z.writestr('../escape/SKILL.md', 'unsafe')
    rejected = inspect_skills(root, {'files': [{'name':'bad.zip','dataBase64':base64.b64encode(bad.getvalue()).decode()}]})
    assert not rejected['ok'] and 'traversal' in rejected['error'].lower(), rejected
    for bad_path in ['x/SKILL.md:stream', 'CON/SKILL.md', 'x./SKILL.md']:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z: z.writestr(bad_path, md_a)
        outcome = inspect_skills(root, {'files':[{'name':'unsafe.zip','dataBase64':base64.b64encode(archive.getvalue()).decode()}]})
        assert not outcome['ok'], bad_path
    linked = io.BytesIO()
    with zipfile.ZipFile(linked, 'w') as z:
        info = zipfile.ZipInfo('link/SKILL.md'); info.create_system = 3; info.external_attr = 0o120777 << 16
        z.writestr(info, '../../outside')
    assert not inspect_skills(root, {'files':[{'name':'link.zip','dataBase64':base64.b64encode(linked.getvalue()).decode()}]})['ok']
    assert not inspect_skills(root, {'files':[{'name':'large.md','dataBase64':base64.b64encode(b'x'*(512*1024+1)).decode()}]})['ok']
    rar = pathlib.Path('proof/skill-import-20260927/sample-skill.rar')
    rar_preview = inspect_skills(root, {'files':[{'name':'sample.rar','dataBase64':base64.b64encode(rar.read_bytes()).decode()}]})
    assert rar_preview['ok'], rar_preview
    rar_install = install_skills(root, {'importId':rar_preview['importId'], 'selectedIds':[row['id'] for row in rar_preview['items']]})
    assert rar_install['ok'], rar_install
    assert (root/'.codex/skills/neyvia-import-check-rar/reference.md').read_bytes() == b'RAR reference preserved.\n'
    print(json.dumps({'ok':True,'installed':['Alpha','Local'],'unselected':'Beta','overwrite':'skipped','expired':'rejected','traversal':'rejected','windowsPaths':'rejected','symlink':'rejected','instructionLimit':'enforced','rar':'installed'}))
`;
const result = spawnSync(python, ['-c', harness], { encoding: 'utf8', timeout: 60000 });
if (result.status !== 0) {
  process.stderr.write(result.stderr || `skill import verifier failed: ${result.status}\n`);
  process.exit(result.status ?? 1);
}
process.stdout.write(result.stdout);
