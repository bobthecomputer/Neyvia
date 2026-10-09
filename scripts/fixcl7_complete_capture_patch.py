"""Extend the native child raster to region/PDF captures; retain portable patch."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess

repo = Path(__file__).resolve().parents[1]
source = repo / '.agent_control/fixcl7/obscura-source'
relative = 'crates/obscura-js/src/runtime.rs'
path = source / relative
text = path.read_text(encoding='utf-8')
for name in ('paint_prepared_region_with_surface_color', 'screenshot_prepared_region_with_backgrounds',
             'screenshot_prepared_region_at_scroll_with_backgrounds'):
    start = text.index('fn ' + name + '(')
    end = text.index('        let mut state = self.state.borrow_mut();', start)
    hook = '        self.realm_states().borrow().render_embedded_frames(&self.state, 0);\n'
    if hook not in text[start:end]:
        text = text[:end] + hook + text[end:]
path.write_text(text, encoding='utf-8', newline='\n')
receipt_path = repo / 'scripts/evidence/FIXCL7-renderer-patch.json'
receipt = json.loads(receipt_path.read_bytes())
donor = Path('C:/Users/user/Projects/nx-c2-browser/.agent_control/C2f/upstream-v0.2.4/obscura-0.2.4')
patch = ''
for row in receipt['changes']:
    baseline = (donor / row['path']).read_text(encoding='utf-8')
    current = (source / row['path']).read_text(encoding='utf-8')
    row['afterSha256'] = hashlib.sha256(current.encode()).hexdigest()
    patch += ''.join(difflib.unified_diff(baseline.splitlines(True), current.splitlines(True),
        fromfile='a/' + row['path'], tofile='b/' + row['path']))
(repo / 'scripts/obscura-FIXCL7-iframe-paint.patch').write_text(patch, encoding='utf-8', newline='\n')
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'capturePaths':4, 'patchBytes':len(patch)}))
