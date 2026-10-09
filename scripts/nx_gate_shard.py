"""pytest plugin for `nx_promote.py gate`: run only this worker's share of the tests.

`nx_promote.py` writes a plan (NX_GATE_PLAN) that gives each known test to one worker,
balanced by measured duration, and lists tests the baseline already fails. This worker
(NX_GATE_WORKER) keeps its own tests, plus the unknown (new) tests of files it owns.
"""
from __future__ import annotations

import json
import os

from _pytest.junitxml import mangle_test_address


def test_key(nodeid: str) -> str:
    """The same `classname::name` key the junit report uses, so plans can come from past reports."""
    names = mangle_test_address(nodeid)
    return ".".join(names[:-1]) + "::" + names[-1]


def pytest_collection_modifyitems(config, items):
    plan_path, worker = os.environ.get("NX_GATE_PLAN"), os.environ.get("NX_GATE_WORKER")
    if not plan_path or worker is None:
        return
    plan = json.loads(open(plan_path, encoding="utf-8").read())
    mine, skip, owners = int(worker), set(plan["skip"]), plan["owners"]
    keep, drop = [], []
    for item in items:
        key = test_key(item.nodeid)
        owner = plan["assign"].get(key)
        if owner is None:
            owner = owners.get(item.nodeid.split("::", 1)[0].replace("\\", "/"), mine)
        (keep if owner == mine and key not in skip else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
