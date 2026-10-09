"""CL 1.1 observer goals: bounded Python expressions without eval or imports."""
from __future__ import annotations

import ast
from pathlib import Path
from jsonschema import Draft202012Validator


def qname(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and not node.attr.startswith('_'):
        return qname(node.value) + '.' + node.attr
    raise ValueError('Expected a public observer name')


class GoalEvaluator:
    def __init__(self, observe, readonly, environment=None, types=None):
        self.observe, self.readonly = observe, readonly
        self.environment, self.types = environment or {}, types or {}
        self.observations, self.failures, self.comparisons = [], [], []
        self.budget = 10000

    def run(self, source):
        if len(source) > 12000:
            raise ValueError('Goal exceeds expression budget')
        tree = ast.parse(source, mode='eval')
        if len(list(ast.walk(tree))) > 500:
            raise ValueError('Goal exceeds syntax budget')
        # Validate ALL branches before executing: short circuits cannot hide effects.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                try:
                    name = qname(node.func)
                except ValueError:
                    name = ''
                if name in {'len', 'base', 'count', 'matches'}:
                    continue
                if isinstance(node.func, ast.Attribute) and node.func.attr in {'startswith', 'endswith', 'lower', 'strip', 'count'}:
                    continue
                if not name or not self.readonly(name):
                    raise ValueError('Goals may call only grounded read-only observers: ' + name)
        value = self.visit(tree.body, dict(self.environment))
        return {'passed': bool(value) and not self.failures, 'value': value,
                'observed': [row['observer'] for row in self.observations],
                'observations': self.observations, 'observerErrors': self.failures,
                'comparisons': self.comparisons}

    def visit(self, node, env):
        self.budget -= 1
        if self.budget < 0:
            raise ValueError('Goal exceeded evaluation budget')
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in {'true', 'false', 'null'}:
                return {'true': True, 'false': False, 'null': None}[node.id]
            if node.id in env:
                return env[node.id]
            if node.id in self.types:
                return self.types[node.id]
            raise ValueError('Unknown goal binding: ' + node.id)
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self.visit(item, env) for item in node.elts]
        if isinstance(node, ast.Dict):
            return {self.visit(k, env): self.visit(v, env) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Attribute):
            if node.attr.startswith('_'):
                raise ValueError('Private goal attributes are forbidden')
            value = self.visit(node.value, env)
            return value.get(node.attr) if isinstance(value, dict) else None
        if isinstance(node, ast.Subscript):
            value, key = self.visit(node.value, env), self.visit(node.slice, env)
            try:
                return value[key] if value is not None else None
            except (KeyError, IndexError, TypeError):
                return None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self.visit(node.operand, env)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -self.visit(node.operand, env)
        if isinstance(node, ast.BoolOp):
            for item in node.values:
                value = self.visit(item, env)
                if isinstance(node.op, ast.And) and not value: return value
                if isinstance(node.op, ast.Or) and value: return value
            return value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            left, right = self.visit(node.left, env), self.visit(node.right, env)
            return left + right if isinstance(node.op, ast.Add) else left - right
        if isinstance(node, ast.Compare):
            left = self.visit(node.left, env)
            passed = True
            for op, rightnode in zip(node.ops, node.comparators):
                right = self.visit(rightnode, env)
                try:
                    if isinstance(op, ast.Eq): result = left == right
                    elif isinstance(op, ast.NotEq): result = left != right
                    elif isinstance(op, ast.In): result = left in right
                    elif isinstance(op, ast.NotIn): result = left not in right
                    elif isinstance(op, ast.Lt): result = left < right
                    elif isinstance(op, ast.LtE): result = left <= right
                    elif isinstance(op, ast.Gt): result = left > right
                    elif isinstance(op, ast.GtE): result = left >= right
                    else: raise ValueError('Unsupported goal comparison')
                except TypeError:
                    result = False
                self.comparisons.append({'expression': ast.unparse(node), 'left': left,
                                         'right': right, 'passed': result})
                passed = passed and result
                left = right
            return passed
        if isinstance(node, ast.ListComp):
            if len(node.generators) != 1:
                raise ValueError('Only one bounded comprehension generator is supported')
            gen = node.generators[0]
            if gen.is_async or not isinstance(gen.target, ast.Name):
                raise ValueError('Invalid comprehension binding')
            rows = self.visit(gen.iter, env)
            if rows is None: return []
            if not isinstance(rows, list) or len(rows) > 3000:
                raise ValueError('Comprehension requires an observed list of at most 3000 rows')
            output = []
            for row in rows:
                local = {**env, gen.target.id: row}
                if all(self.visit(cond, local) for cond in gen.ifs):
                    output.append(self.visit(node.elt, local))
            return output
        if isinstance(node, ast.Call):
            if any(key.arg is None for key in node.keywords):
                raise ValueError('Goal argument expansion is forbidden')
            args = [self.visit(item, env) for item in node.args]
            kwargs = {key.arg: self.visit(key.value, env) for key in node.keywords}
            try: name = qname(node.func)
            except ValueError: name = ''
            if name == 'len': return len(args[0]) if args[0] is not None else 0
            if name == 'base': return Path(str(args[0])).name
            if name == 'count': return args[0].count(args[1]) if len(args) == 2 else len(args[0])
            if name == 'matches': return not list(Draft202012Validator(args[1]).iter_errors(args[0]))
            if self.readonly(name):
                try:
                    value = self.observe(name, args, kwargs)
                    if isinstance(value, dict) and value.get('ok') is False:
                        raise ValueError(str(value.get('error', 'Observer failed')))
                    self.observations.append({'observer': name, 'arguments': kwargs, 'value': value})
                    return value
                except Exception as exc:
                    self.failures.append({'observer': name, 'error': str(exc)})
                    self.observations.append({'observer': name, 'value': None})
                    return None
            if isinstance(node.func, ast.Attribute) and node.func.attr in {'startswith', 'endswith', 'lower', 'strip', 'count'}:
                value = self.visit(node.func.value, env)
                if not isinstance(value, str):
                    return None
                return getattr(value, node.func.attr)(*args, **kwargs)
        raise ValueError('Unsupported goal syntax: ' + type(node).__name__)


def evaluate_goal(source, observe, readonly, environment=None, types=None):
    return GoalEvaluator(observe, readonly, environment, types).run(source)
