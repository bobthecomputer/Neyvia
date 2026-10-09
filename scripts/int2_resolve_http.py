"""Retain night-specific HTTP guards in FOLLOW's extracted HTTP owner."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    original = subprocess.check_output(['git', 'show', 'HEAD:src/grant_agent/web_backend.py'], cwd=ROOT, text=True)
    tree = ast.parse(original)
    handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'make_handler')
    lines = original.splitlines(keepends=True)
    def segment(node):
        return ''.join(lines[node.lineno - 1:node.end_lineno])
    cls = next(n for n in handler.body if isinstance(n, ast.ClassDef))
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    options = ''.join(segment(n) for n in methods['do_OPTIONS'].body[:-1])
    post = methods['do_POST']
    dispatch = next(n for n in ast.walk(post) if isinstance(n, ast.Try)
                    and any(isinstance(s, ast.ImportFrom) and s.module == 'neyvia_scroll' for s in n.body))
    start = next(i for i, n in enumerate(dispatch.body) if isinstance(n, ast.ImportFrom) and n.module == 'neyvia_scroll')
    end = next(i for i, n in enumerate(dispatch.body) if isinstance(n, ast.ImportFrom) and n.module == 'neyvia_browser')
    guards = ''.join(segment(n) for n in dispatch.body[start:end])
    # These globals are deliberately late-bound through the existing facade.
    for name in ('urlparse', '_json_response', '_as_payload', 'Path'):
        import re
        options = re.sub(r'\b' + name + r'\b', '_facade.' + name, options)
        guards = re.sub(r'\b' + name + r'\b', '_facade.' + name, guards)
    owner = ROOT / 'src/grant_agent/web_backend_http.py'
    text = owner.read_text(encoding='utf-8')
    text = text.replace('        def do_OPTIONS(self) -> None:  # noqa: N802\n',
                        '        def do_OPTIONS(self) -> None:  # noqa: N802\n' + options, 1)
    anchor = '                from .neyvia_browser import COMMANDS as BROWSER_COMMANDS\n'
    assert text.count(anchor) == 1
    text = text.replace(anchor, guards + anchor, 1)
    owner.write_text(text, encoding='utf-8')
    facade = ROOT / 'src/grant_agent/web_backend.py'
    text = facade.read_text(encoding='utf-8')
    begin = text.index('<<<<<<< ours\n', text.index('def make_handler('))
    finish = text.index('>>>>>>> theirs\n', begin) + len('>>>>>>> theirs\n')
    text = text[:begin] + '    return _web_backend_http.make_handler(backend, _facade=sys.modules[__name__])\n' + text[finish:]
    facade.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))

if __name__ == '__main__':
    main()
