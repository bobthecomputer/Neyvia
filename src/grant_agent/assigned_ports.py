"""Explicitly assigned port blocks and scratch output roots for proof harnesses.

A proof script keeps its historical owned ports and output folders when nothing is passed.
A caller that owns a different allocation (the lead, a verifier) assigns it explicitly:

    --port-block 49171-49179      or  NEYVIA_ASSIGNED_PORTS=49171-49179
    --scratch-root D:/NeyviaRuns/X or  NEYVIA_SCRATCH_ROOT=D:/NeyviaRuns/X

A block is one contiguous range of at least two ports. It is refused when it overlaps any
block registered to another track (plan 27 §0 and plans/12-board.md); a script may use a
sub-block of its own track's block. Pairs are handed out from the start: (first, first+1),
(first+2, first+3), ... ``apply`` exports both settings so child processes and library code
(Harness, laya_ui_fix.render, laya_glance_gate.run) see the same allocation.

With a scratch root, evidence/manual writes and large outputs go under it, and small
runtime state goes under ``<scratch>/.agent_control`` on the same drive.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
ENV_PORTS = 'NEYVIA_ASSIGNED_PORTS'
ENV_OWNER = 'NEYVIA_ASSIGNED_PORTS_OWNER'
ENV_SCRATCH = 'NEYVIA_SCRATCH_ROOT'

# (owner, first, last): plan 27 §0 tracks, the laya-3d / P22 / integrator blocks, and every
# other block recorded on plans/12-board.md up to 7 Oct 2026.
REGISTERED = (
    ('integrator', 48871, 48889), ('P22', 49081, 49089), ('LAYA3D', 49101, 49109),
    ('CORE', 49111, 49119), ('TRADE', 49121, 49129), ('VISION', 49131, 49139), ('EVOLVE', 49141, 49149),
    ('ANIM', 49151, 49159), ('VIDEO', 49161, 49169),
    *(('board', int(a), int(b)) for a, b in (r.split('-') for r in (
        '48261-48269 48311-48319 48361-48369 48431-48439 48441-48449 48461-48469 48471-48479 48491-48499 '
        '48501-48509 48521-48529 48591-48599 48601-48609 48611-48619 48661-48669 48701-48709 48711-48719 '
        '48721-48739 48741-48749 48761-48769 48771-48779 48801-48809 48821-48829 48911-48919 48941-48976 '
        '48981-48989').split())),
)
# A track may use (a sub-block of) its own registered blocks; the 3D harness lineage owns LAYA3D too.
OWNS = {'CORE': {'CORE', 'LAYA3D'}, 'ANIM': {'ANIM', 'LAYA3D'}}


class PortBlock(NamedTuple):
    first: int
    last: int

    def __contains__(self, port):
        return self.first <= int(port) <= self.last

    def __str__(self):
        return f'{self.first}-{self.last}'

    def pairs(self):
        return [(p, p + 1) for p in range(self.first, self.last, 2)]

    def pair(self, index=0):
        pairs = self.pairs()
        if not 0 <= index < len(pairs):
            raise ValueError(f'Port block {self} has {len(pairs)} pairs; pair {index} requested')
        return pairs[index]

    def require(self, *ports):
        ports = [int(p) for p in ports]
        if len(set(ports)) != len(ports) or not all(p in self for p in ports):
            raise ValueError(f'Ports {ports} are not distinct ports inside the assigned block {self}')
        return ports


def parse_block(text):
    match = re.fullmatch(r'\s*(\d{4,5})\s*-\s*(\d{4,5})\s*', str(text or ''))
    if not match:
        raise ValueError(f'Port block must look like 49171-49179, got {text!r}')
    first, last = int(match[1]), int(match[2])
    if not (1024 <= first < last <= 65535):
        raise ValueError(f'Port block {text!r} must be an ascending range of at least two ports in 1024-65535')
    return PortBlock(first, last)


def validate(block, owner=None):
    """Refuse a block that overlaps another track's registered block (own sub-blocks are fine)."""
    owned = OWNS.get(owner, {owner} if owner else set())
    if any(name in owned and first <= block.first and block.last <= last for name, first, last in REGISTERED):
        return block
    clashes = [f'{name} {first}-{last}' for name, first, last in REGISTERED if block.first <= last and first <= block.last]
    if clashes:
        raise ValueError(f'Port block {block} overlaps registered blocks: {", ".join(clashes)}')
    return block


def assigned_block(value=None, owner=None, env=None):
    """The explicitly assigned block (argument, else NEYVIA_ASSIGNED_PORTS), validated; None when unassigned."""
    env = os.environ if env is None else env
    text = value if value is not None else env.get(ENV_PORTS)
    if not text:
        return None
    return validate(parse_block(text), owner if owner is not None else env.get(ENV_OWNER))


def check_ports(ports, legacy, message):
    """Assigned block when one is set, else the script's historical rule ``legacy(ports) -> bool``."""
    block = assigned_block()
    if block is not None:
        return block.require(*ports)
    if not legacy(ports):
        raise ValueError(message)
    return list(ports)


def choose_port(explicit, default, index=0):
    """--port when given, else the assigned block's pair ``index``, else the historical default."""
    if explicit is not None:
        return explicit
    block = assigned_block()
    return block.pair(index)[0] if block is not None else default


def scratch_root(value=None, env=None):
    env = os.environ if env is None else env
    text = value if value is not None else env.get(ENV_SCRATCH)
    return Path(text).resolve() if text else None


def under(relative, default):
    """A large-output folder: <scratch>/<relative> with a scratch root, else ``default``."""
    root = scratch_root()
    return root / relative if root else Path(default)


def output(relative):
    """A repository output file (scripts/evidence/..., manuals/cl/...): redirected under the scratch root."""
    root = scratch_root()
    return (root / relative) if root else REPO / relative


def readable(relative):
    """Read side of ``output``: the scratch copy when it exists, else the repository file."""
    path = output(relative)
    return path if path.exists() else REPO / relative


def state(relative):
    """Keep runtime state on the explicit scratch drive, or under local .agent_control by default."""
    root = scratch_root()
    if root is None:
        return REPO / '.agent_control' / relative
    return root / '.agent_control' / relative


def add_arguments(parser):
    parser.add_argument('--port-block', default=None, help='explicitly assigned contiguous port block, e.g. 49171-49179 '
                        '(default: env NEYVIA_ASSIGNED_PORTS, else the historical owned ports)')
    parser.add_argument('--scratch-root', default=None, help='redirect evidence/manual writes and outputs under this folder '
                        '(default: env NEYVIA_SCRATCH_ROOT, else the historical locations)')
    return parser


def apply(args, owner):
    """Validate the CLI/env allocation and export it for child processes and library code."""
    block = assigned_block(getattr(args, 'port_block', None), owner)
    if block is not None:
        os.environ[ENV_PORTS] = str(block)
        os.environ[ENV_OWNER] = owner
    root = scratch_root(getattr(args, 'scratch_root', None))
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        os.environ[ENV_SCRATCH] = str(root)
    return block, root


def describe():
    """Receipt fragment: the allocation this process runs under."""
    block = assigned_block()
    return {'portBlock': str(block) if block else None, 'owner': os.environ.get(ENV_OWNER),
            'scratchRoot': str(scratch_root()) if scratch_root() else None}
