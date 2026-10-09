"""Bounded CL check expressions, with read-only observers and no eval."""
from __future__ import annotations

from datetime import datetime, timezone

from .parser import Action, BareWord, Handle, Quantity, Reader, CLParseError


def select(value, parts):
    for key in parts:
        if isinstance(value, list):
            if key.isdigit():
                value = value[int(key)]
            else:
                value = [select(item, [key]) for item in value]
        elif isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def bind(value, environment, store=None):
    if isinstance(value, Handle):
        if store is None:
            raise ValueError("Handle resolution requires this agent's context")
        return store.resolve(value)
    if isinstance(value, BareWord):
        parts = str(value).split(".")
        if parts[0] in environment:
            return select(environment[parts[0]], parts[1:])
        return str(value)
    if isinstance(value, Quantity):
        scale = {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400,
                 "B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "px": 1, "%": .01}
        return value.value * scale[value.unit]
    if isinstance(value, dict):
        return {key: bind(item, environment, store) for key, item in value.items()}
    if isinstance(value, list):
        return [bind(item, environment, store) for item in value]
    return value


class Evaluator:
    def __init__(self, source, environment, observe, store=None):
        self.reader = Reader(source)
        self.environment, self.observe, self.store = environment, observe, store
        self.observers = []
        self.observer_errors = []

    def expression(self):
        value = self.conjunction()
        while self.reader.peek("or"):
            self.reader.take()
            right = self.conjunction()  # never skip a declared observer read
            value = bool(value) or bool(right)
        return value

    def conjunction(self):
        value = self.comparison()
        while self.reader.peek("and"):
            self.reader.take()
            right = self.comparison()
            value = bool(value) and bool(right)
        return value

    def comparison(self):
        if self.reader.peek("not"):
            self.reader.take()
            return not self.comparison()
        value = self.sum()
        token = self.reader.peek()
        if token and token.text in {"==", "!=", "<", ">", "<=", ">=", "has", "in", "~"}:
            operation = self.reader.take().text
            right = self.sum()
            if operation == "==": return value == right
            if operation == "!=": return value != right
            if operation == "has":
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    value = [next(iter(item.values()), None) for item in value]
                return value is not None and right in value
            if operation == "in": return right is not None and value in right
            if operation == "~":
                if len(str(right)) > 1000 or len(str(value)) > 100000:
                    raise ValueError("Regex check exceeds supported bounds")
                try:
                    import regex
                except ImportError as exc:
                    raise ValueError("Timed regex checks require the optional cl dependency") from exc
                try:
                    return bool(regex.search(str(right), str(value), timeout=.05))
                except TimeoutError as exc:
                    raise ValueError("Regex check exceeded its 50 ms execution budget") from exc
            if value is None or right is None: return False
            if operation == "<": return value < right
            if operation == ">": return value > right
            if operation == "<=": return value <= right
            if operation == ">=": return value >= right
        return value

    def sum(self):
        value = self.term()
        while self.reader.peek("+"):
            self.reader.take()
            value += self.term()
        return value

    def term(self):
        if self.reader.peek("("):
            self.reader.take()
            value = self.expression()
            self.reader.take(")")
            return value
        value = self.reader.value()
        if isinstance(value, Action):
            args = [bind(item, self.environment, self.store) for item in value.positional]
            kwargs = {key: bind(item, self.environment, self.store) for key, item in value.arguments.items()}
            builtins = {"len": len, "count": len, "bytes": lambda x: len(str(x).encode("utf-8")),
                        "lower": lambda x: str(x).lower(), "now": lambda: datetime.now(timezone.utc).isoformat()}
            if value.name in builtins:
                value = builtins[value.name](*args, **kwargs)
            else:
                call = Action(value.name, kwargs, args)
                self.observers.append(value.name)
                try:
                    value = self.observe(call)
                except (ValueError, KeyError, RuntimeError, OSError, TypeError) as exc:
                    self.observer_errors.append({"observer": call.name, "error": str(exc)})
                    value = None
        else:
            value = bind(value, self.environment, self.store)
        while self.reader.peek() and self.reader.peek().kind == "word" and self.reader.peek().text.startswith("."):
            value = select(value, self.reader.take().text.lstrip(".").split("."))
        return value


def evaluate(source, environment, observe, *, store=None):
    evaluator = Evaluator(source, environment, observe, store)
    value = evaluator.expression()
    if evaluator.reader.peek():
        raise CLParseError("Unexpected expression suffix")
    return {"passed": bool(value), "observed": evaluator.observers,
            "observerErrors": evaluator.observer_errors}
