"""Example optional mod: deterministic personal greeting, without side effects."""


def greet(args, *, root):
    name = args["name"].strip()
    if not name or len(name) > 80:
        raise ValueError("Choose a name between 1 and 80 characters")
    return {"ok": True, "greeting": "Hello, " + name + "!", "module": "hello-module"}
