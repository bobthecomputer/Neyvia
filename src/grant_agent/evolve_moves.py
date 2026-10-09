"""LAYA's library of known code moves and known exploits for the plan-25 evolving engine.

A move is data (``-- @move`` lines in ``manuals/cl/evolve-moves.cl``): an id, a family, a
CL procedure, an applicability description and a transform. A ``transform`` names either a
deterministic source rewrite in this module or ``luna``: a model instantiates the move's CL
text on one hot function. Rewrites only ever return new source text; the engine's judges
decide whether a rewrite is kept. Exploits are the adversary's library: rewrites that are
deliberately fast and wrong, used to harden the judge.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re

HELPERS = {
    # Validator-purity assumption (explicit, and the reason this move may be applied at all):
    # the wrapped validator's outcome depends only on the JSON value of its arguments, it has
    # no side effects, and success means returning None (failure means raising). Only
    # successful validations are remembered, so an invalid input raises on every call; a
    # non-None result is never remembered. The memo is bounded (LRU of SHA-256 digests), so a
    # long-lived process keeps at most _EVOLVE_VALIDATED_MAX entries of 32 bytes each.
    'skip-repeated-validation': '''
import threading as _evolve_threading
_EVOLVE_VALIDATED = {}
_EVOLVE_VALIDATED_MAX = 4096
_EVOLVE_VALIDATED_LOCK = _evolve_threading.Lock()
def _evolve_once(label, call, *args):
    """Skip a repeated call of a PURE validator on an identical JSON input in this process.

    Purity assumption: the outcome depends only on the JSON value of the arguments, the call
    has no side effects, success returns None and failure raises. Only successes are kept;
    errors and non-None results are never remembered. Bounded LRU of SHA-256 digests.
    """
    import hashlib as _hashlib
    import json as _json
    try:
        payload = _json.dumps([label, args], sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return call(*args)
    key = _hashlib.sha256(payload.encode('utf-8')).digest()
    with _EVOLVE_VALIDATED_LOCK:
        if key in _EVOLVE_VALIDATED:
            _EVOLVE_VALIDATED[key] = _EVOLVE_VALIDATED.pop(key)
            return None
    result = call(*args)
    if result is None:
        with _EVOLVE_VALIDATED_LOCK:
            _EVOLVE_VALIDATED[key] = True
            while len(_EVOLVE_VALIDATED) > _EVOLVE_VALIDATED_MAX:
                del _EVOLVE_VALIDATED[next(iter(_EVOLVE_VALIDATED))]
    return result
''',
    'skip-unchanged-write': '''
def _evolve_write_json_if_changed(write, path, payload, *rest, **options):
    """Leave an identical file untouched instead of rewriting and fsyncing it."""
    import json as _json
    from pathlib import Path as _Path
    try:
        if _json.loads(_Path(path).read_text(encoding='utf-8')) == payload:
            return _Path(path)
    except (OSError, ValueError):
        pass
    return write(path, payload, *rest, **options)
''',
    'statement-walk': '''
def _evolve_walk_statements(tree):
    """Statement nodes only: statements never occur inside expressions."""
    import ast as _ast
    pending = [tree]
    while pending:
        node = pending.pop()
        yield node
        for field in ('body', 'orelse', 'finalbody', 'handlers', 'cases'):
            children = getattr(node, field, None)
            if isinstance(children, list):
                pending.extend(child for child in reversed(children) if isinstance(child, _ast.AST))
''',
    'call-once': '''
def _evolve_call_once(function):
    """Process-local memo for a zero-argument function; callers receive a copy."""
    import copy as _copy
    import functools as _functools
    cell = []
    @_functools.wraps(function)
    def wrapper():
        if not cell:
            cell.append(function())
        return _copy.deepcopy(cell[0])
    return wrapper
''',
}

STATEMENT_TYPES = {'Import', 'ImportFrom', 'FunctionDef', 'AsyncFunctionDef', 'ClassDef', 'Return', 'Delete',
                   'Assign', 'AugAssign', 'AnnAssign', 'For', 'AsyncFor', 'While', 'If', 'With', 'AsyncWith',
                   'Match', 'Raise', 'Try', 'TryStar', 'Assert', 'Global', 'Nonlocal', 'Expr', 'Pass',
                   'Break', 'Continue', 'TypeAlias'}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _lines(text):
    return text.splitlines(keepends=True)


def insert_helper(text: str, name: str) -> str:
    """Insert a helper block after the docstring and __future__ imports, once."""
    marker = f'# evolve-helper: {name}\n'
    if marker in text:
        return text
    tree = ast.parse(text)
    position = 0
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(getattr(node, 'value', None), ast.Constant) and isinstance(node.value.value, str) and position == 0:
            position = node.end_lineno
            continue
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            position = node.end_lineno
            continue
        break
    lines = _lines(text)
    block = marker + HELPERS[name].lstrip('\n') + '\n'
    return ''.join(lines[:position]) + ('\n' if position else '') + block + ''.join(lines[position:])


def _segment_replace(text, node, replacement):
    lines = _lines(text)
    # col offsets are UTF-8 byte offsets; convert through the line's bytes.
    def offset(lineno, col):
        prefix = lines[lineno - 1].encode('utf-8')[:col].decode('utf-8', 'ignore')
        return sum(len(line) for line in lines[:lineno - 1]) + len(prefix)
    start, end = offset(node.lineno, node.col_offset), offset(node.end_lineno, node.end_col_offset)
    return text[:start] + replacement + text[end:]


def enclosing_function(tree, node):
    best = None
    for candidate in ast.walk(tree):
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)) and candidate.lineno <= node.lineno <= candidate.end_lineno:
            if best is None or candidate.lineno >= best.lineno:
                best = candidate
    return best.name if best else '<module>'


# ---------------------------------------------------------------- deterministic moves

def skip_repeated_validation(text, hot=None):
    """Expression-statement calls to check/validate/verify-named validators."""
    tree = ast.parse(text)
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and not node.value.keywords:
            call = node.value
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
            if re.search(r'^(check|validate|verify)', name or '') and call.args and not any(isinstance(a, ast.Starred) for a in call.args):
                # The label must identify the validator: a callee built by a call is
                # only allowed when that inner call depends on the outer arguments alone.
                outer = {ast.unparse(a) for a in call.args}
                inner = [n for n in ast.walk(call.func) if isinstance(n, ast.Call)]
                if all({ast.unparse(a) for a in n.args} <= outer and not n.keywords for n in inner):
                    sites.append(node)
    variants = []
    for node in sites:
        call = node.value
        label = ast.unparse(call.func)
        replacement = f'_evolve_once({label!r}, {label}, {", ".join(ast.unparse(a) for a in call.args)})'
        new = _segment_replace(text, node.value, replacement)
        variants.append((insert_helper(new, 'skip-repeated-validation'),
                         {'site': f'{enclosing_function(tree, node)}:{node.lineno}', 'function': enclosing_function(tree, node), 'callee': label}))
    return variants


def skip_unchanged_write(text, hot=None):
    tree = ast.parse(text)
    variants = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
            if name == 'atomic_write_json' and len(call.args) >= 2:
                label = ast.unparse(call.func)
                args = ', '.join([label] + [ast.unparse(a) for a in call.args] + [ast.unparse(k) for k in call.keywords])
                new = _segment_replace(text, call, f'_evolve_write_json_if_changed({args})')
                variants.append((insert_helper(new, 'skip-unchanged-write'),
                                 {'site': f'{enclosing_function(tree, node)}:{node.lineno}', 'function': enclosing_function(tree, node), 'callee': label}))
    return variants


def statement_walk(text, hot=None):
    """`for x in ast.walk(t)` whose body only tests x against statement node types."""
    tree = ast.parse(text)
    variants = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.For) and isinstance(node.iter, ast.Call) and ast.unparse(node.iter.func) == 'ast.walk'
                and isinstance(node.target, ast.Name)):
            continue
        variable = node.target.id
        tested = []
        def statement_only(body):
            for stmt in body:
                if not isinstance(stmt, ast.If):
                    return False
                test = stmt.test
                if not (isinstance(test, ast.Call) and ast.unparse(test.func) == 'isinstance' and len(test.args) == 2
                        and ast.unparse(test.args[0]) == variable):
                    return False
                kinds = test.args[1].elts if isinstance(test.args[1], ast.Tuple) else [test.args[1]]
                for kind in kinds:
                    text_kind = ast.unparse(kind)
                    if not text_kind.startswith('ast.') or text_kind[4:] not in STATEMENT_TYPES:
                        return False
                    tested.append(text_kind)
                if stmt.orelse and not statement_only(stmt.orelse):
                    return False
            return True
        if node.orelse or not statement_only(node.body):
            continue
        new = _segment_replace(text, node.iter, f'_evolve_walk_statements({ast.unparse(node.iter.args[0])})')
        variants.append((insert_helper(new, 'statement-walk'),
                         {'site': f'{enclosing_function(tree, node)}:{node.lineno}', 'function': enclosing_function(tree, node), 'callee': 'ast.walk', 'tested': tested}))
    return variants


def hoist_regex(text, hot=None):
    tree = ast.parse(text)
    variants = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 're' and node.func.attr in {'findall', 'search', 'match', 'fullmatch', 'sub', 'finditer'}
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and not node.keywords
                and enclosing_function(tree, node) != '<module>'):
            pattern = node.args[0].value
            name = '_EVOLVE_RE_' + sha(pattern)[:10].upper()
            new = _segment_replace(text, node, f'{name}.{node.func.attr}({", ".join(ast.unparse(a) for a in node.args[1:])})')
            definition = f'# evolve-helper: {name}\nimport re as _evolve_re\n{name} = _evolve_re.compile({pattern!r})\n'
            if definition not in new:
                new = _insert_definition(new, definition)
            variants.append((new, {'site': f'{enclosing_function(tree, node)}:{node.lineno}', 'function': enclosing_function(tree, node), 'callee': 're.' + node.func.attr}))
    return variants


def _insert_definition(text, definition):
    tree = ast.parse(text)
    position = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(getattr(node, 'value', None), ast.Constant)):
            position = node.end_lineno
            continue
        break
    lines = _lines(text)
    return ''.join(lines[:position]) + definition + ''.join(lines[position:])


def call_once(text, hot=None):
    """Zero-argument top-level functions the profile shows called more than once per process."""
    tree = ast.parse(text)
    repeated = {row['function'] for row in (hot or []) if row.get('calls', 0) >= 2}
    variants = []
    for node in tree.body:
        if (isinstance(node, ast.FunctionDef) and not node.args.args and not node.args.kwonlyargs and not node.args.vararg
                and not node.args.kwarg and not node.decorator_list and node.name in repeated):
            lines = _lines(text)
            new = ''.join(lines[:node.lineno - 1]) + '@_evolve_call_once\n' + ''.join(lines[node.lineno - 1:])
            variants.append((insert_helper(new, 'call-once'), {'site': f'{node.name}:{node.lineno}', 'function': node.name, 'callee': node.name}))
    return variants


TRANSFORMS = {
    'skip-repeated-validation': skip_repeated_validation,
    'skip-unchanged-write': skip_unchanged_write,
    'statement-walk': statement_walk,
    'hoist-regex': hoist_regex,
    'call-once': call_once,
}


# ---------------------------------------------------------------- function surgery (Luna / big-model edits)

def function_node(text, name):
    tree = ast.parse(text)
    owner, _, member = name.rpartition('.')
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and owner and node.name == owner.split('.')[-1]:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == member:
                    return child
        if not owner and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == member and node.col_offset == 0:
            return node
    return None


def function_source(text, name):
    node = function_node(text, name)
    if node is None:
        return None
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return ''.join(_lines(text)[start - 1:node.end_lineno])


def replace_function(text, name, new_source):
    node = function_node(text, name)
    if node is None:
        raise ValueError('No function named ' + name)
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    lines = _lines(text)
    indent = ' ' * node.col_offset
    body = [line for line in new_source.replace('\r\n', '\n').split('\n')]
    while body and not body[-1].strip():
        body.pop()
    common = min((len(line) - len(line.lstrip(' ')) for line in body if line.strip()), default=0)
    body = [(indent + line[common:]) if line.strip() else '' for line in body]
    new = ''.join(lines[:start - 1]) + '\n'.join(body) + '\n' + ''.join(lines[node.end_lineno:])
    ast.parse(new)
    return new


def add_module_imports(text, imports):
    """Imports a model edit needs at module level (only plain import statements)."""
    wanted = [line.strip() for line in imports or [] if re.fullmatch(r'(from [\w.]+ )?import [\w., ]+( as \w+)?', line.strip())]
    missing = [line for line in wanted if line not in text]
    return _insert_definition(text, ''.join(line + '\n' for line in missing)) if missing else text


# ---------------------------------------------------------------- adversary exploits

def exploit_stale_cache(text):
    """Trust any cached entry for a path without comparing its stamp."""
    pattern = re.compile(r'cached\.get\(name, \{\}\)\.get\("stamp"\) == stamp')
    return [(pattern.sub('name in cached', text, count=1), {'exploit': 'stale-cache', 'claim': 'source edits keep the old import edges'})] if pattern.search(text) else []


def exploit_disk_memo(text, function='select'):
    """Persist a function's result across processes keyed only by its arguments."""
    node = function_node(text, function)
    if node is None:
        return []
    lines = _lines(text)
    wrapper = f'''
def _evolve_disk_memo(function):
    import functools, hashlib, pickle
    from pathlib import Path as _P
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        key = hashlib.sha256(repr((args, sorted(kwargs.items()))).encode()).hexdigest()[:24]
        path = _P(__file__).resolve().parents[2] / '.agent_control/p22' / ('memo-' + key + '.pkl')
        if path.is_file():
            return pickle.loads(path.read_bytes())
        value = function(*args, **kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(value))
        return value
    return wrapper
'''
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    new = ''.join(lines[:start - 1]) + wrapper.lstrip('\n') + '\n\n@_evolve_disk_memo\n' + ''.join(lines[start - 1:])
    return [(new, {'exploit': 'disk-memo', 'claim': 'repository edits after the first run are ignored'})]


def exploit_drop_renames(text):
    node = function_node(text, 'exact_renames')
    if node is None:
        return []
    return [(replace_function(text, 'exact_renames', 'def exact_renames(since):\n    return {}\n'),
             {'exploit': 'drop-renames', 'claim': 'moved sources lose their owner path'})]


def exploit_skip_module_check(text, constant):
    """Replace the module-map drift check by the value it returned once."""
    if 'module_check = check()' not in text:
        return []
    return [(text.replace('module_check = check()', 'module_check = ' + repr(constant), 1),
             {'exploit': 'frozen-module-check', 'claim': 'module map drift is never detected'})]


def exploit_skip_validation(text):
    """Drop schema validation entirely (fast; wrong on invalid schemas)."""
    if 'validator_for(schema).check_schema(schema)' not in text:
        return []
    return [(text.replace('validator_for(schema).check_schema(schema)', 'pass', 1),
             {'exploit': 'skip-validation', 'claim': 'invalid schemas compile'})]


EXPLOITS = {
    'stale-cache': exploit_stale_cache,
    'disk-memo': exploit_disk_memo,
    'drop-renames': exploit_drop_renames,
    'skip-validation': exploit_skip_validation,
}


def load_moves(path):
    """``-- @move {json}`` lines of a CL skill file."""
    moves = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('-- @move '):
            moves.append(json.loads(line[len('-- @move '):]))
    ids = [m['id'] for m in moves]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate move identity')
    return moves
