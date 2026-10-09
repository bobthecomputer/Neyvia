"""The remote bot API observes existing consent; it grants no remote input.

Native snapshot reads capture a fresh frame/tree under the owner's exact-window
and password protection gates. They are observations, not remote mutations.
"""

SUPPORTED = frozenset()


def readonly(name, args):
    if name == 'neyvia.remote.snapshot':
        return (set(args) <= {'connectionId', 'windowId'}
                and isinstance(args.get('connectionId'), str)
                and bool(args['connectionId']) and type(args.get('windowId')) is int)
    return None
