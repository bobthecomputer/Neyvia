"""Host-side manual contracts. Trusted local code, never eval or manual imports.

Shape checks apply to every action at the Native and workspace boundaries.
Domain contracts live at the common app entry points, so UI and direct callers
cannot bypass them. Scratch verification never grants network/device authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import re
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
_LOCK = threading.RLock()


class ContractViolation(ValueError):
    pass


def _stamp():
    from .neyvia_manuals import catalog_stamp
    return catalog_stamp(include_manifest=True)


@lru_cache(maxsize=2)
def _catalog(stamp):
    from .neyvia_manuals import records, document
    actions = {}
    declarations = {}
    for record in records():
        _, manual = document(record)
        for chapter_id, chapter in manual["chapters"].items():
            for action_id, action in chapter["actions"].items():
                row = {"id": f"{manual['id']}.{chapter_id}.{action_id}",
                       "input": Draft202012Validator(manual["schemas"][action["schema"]]),
                       "output": Draft202012Validator(action["returns"]),
                       "where": record["path"], "impact": action["effect"]}
                actions.setdefault(action["tool"], []).append(row)
        for contract in manual.get("proofs", {}).get("contracts", []):
            if contract["id"] in declarations:
                raise ContractViolation("Duplicate manual proof ID: " + contract["id"])
            declarations[contract["id"]] = {**contract, "manual": record["path"]}
    return actions, declarations


def catalog():
    with _LOCK:
        return _catalog(_stamp())


@lru_cache(maxsize=128)
def _action_rows(tool, stamp):
    """Compile only the current manual contracts that name this native tool."""
    from .neyvia_manuals import compiled_manual_owners, document, records
    owners = compiled_manual_owners()
    if owners is None:
        from .cl.manual_routing import source_owners
        owners = source_owners()
    if owners is None and not tool.startswith('neyvia.parallel.'):
        return _catalog(stamp)[0].get(tool, [])
    selected = {'parallel'} if owners is None else set(owners[0].get(tool, ()))
    rows = []
    for record in records():
        if selected is not None and record['id'] not in selected:
            continue
        _, manual = document(record)
        for chapter_id, chapter in manual['chapters'].items():
            for action_id, action in chapter['actions'].items():
                if action['tool'] != tool:
                    continue
                rows.append({'id': f"{manual['id']}.{chapter_id}.{action_id}",
                             'input': Draft202012Validator(manual['schemas'][action['schema']]),
                             'output': Draft202012Validator(action['returns']),
                             'where': record['path'], 'impact': action['effect']})
    return rows


def _validate(validator, value, identity, phase):
    error = next(validator.iter_errors(value), None)
    if error:
        # Avoid including argument/result contents (which may contain secrets).
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        raise ContractViolation(f"{identity}: {phase} at {location} violates {error.validator}")


def before_action(tool, arguments):
    with _LOCK:
        rows = _action_rows(tool, _stamp())
    for row in rows:
        _validate(row["input"], arguments, row["id"], "precondition")
    return rows


def after_action(rows, result):
    if not isinstance(result, dict):
        raise ContractViolation("Action result must be an object")
    if result.get("ok") is False or result.get("status") in {"failed", "error", "blocked", "approval_required", "frontier", "conflict"}:
        return []  # Failure responses do not promise success postconditions.
    for row in rows:
        _validate(row["output"], result, row["id"], "postcondition")
    return [row["id"] for row in rows]


def invoke(tool, arguments, action):
    rows = before_action(tool, arguments)
    result = action()
    after_action(rows, result)
    return result


def manifest_files():
    return [p for p in sorted((REPO / "config/proofs").glob("*.json")) if p.name != "test-inventory.json"]


def declarations():
    return catalog()[1]


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_digest(path):
    # Text source uses a logical LF digest, stable under Windows Git checkout.
    return hashlib.sha256(Path(path).read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def source_bindings():
    paths = {REPO / "config/neyvia_manuals.json", REPO / "config/neyvia_remote.json", REPO / "src/grant_agent/native_tools.py",
             REPO / "src/grant_agent/neyvia_workspace_tools.py", REPO / "src/grant_agent/manual_contracts.py",
             REPO / "src/grant_agent/neyvia_manuals.py", REPO / "src/grant_agent/neyvia_gateway.py",
             REPO / "src/grant_agent/web_backend.py",
             REPO / "src/grant_agent/subprocess_utils.py",
             REPO / "src/grant_agent/chrome_environment.py",
             REPO / "tests/fixtures/fake_claude_cli.py",
             REPO / "scripts/fluxio-cli.mjs"}
    paths.update((REPO / "src/grant_agent").glob("proof*.py"))
    # Focused fixture helpers are executable proof owners too. Binding only a
    # registered facade would let changed imported checks retain old receipts.
    paths.update((REPO / "src/grant_agent").glob("edge_fixture*.py"))
    paths.update((REPO / "scripts").glob("*proof*.py"))
    paths.update((REPO / "scripts").glob("generate_C7e_*.py"))
    paths.update((REPO / "scripts").glob("proofs*.mjs"))
    paths.update((REPO / "manuals").glob("*.manual.json"))
    paths.update((REPO / "manuals/cl").glob("*.cl"))
    paths.add(REPO / "src/grant_agent/cl/manuals.py")
    paths.update(manifest_files())
    for manifest in manifest_files():
        for source in json.loads(manifest.read_text(encoding="utf-8")).get("sourceFiles", []):
            candidate = (REPO / source).resolve()
            candidate.relative_to(REPO)
            if not candidate.is_file():
                raise ContractViolation("Missing declared proof source: " + source)
            paths.add(candidate)
    for row in declarations().values():
        for site in row["checkedAt"]:
            # Nested owners (connected_sessions.broker, for example) must bind
            # their actual source, rather than a nonexistent flat module.
            for name in re.findall(r"\bgrant_agent\.([a-z_][a-z_0-9.]*)", site):
                parts = name.rstrip(".").split(".")
                for end in range(len(parts), 0, -1):
                    stem = REPO / "src/grant_agent" / Path(*parts[:end])
                    candidate = stem.with_suffix(".py")
                    if candidate.is_file():
                        paths.add(candidate)
                        break
            for module in re.findall(r"\b(?:grant_agent\.)?([a-z_][a-z_0-9]*)[.:][A-Za-z_]", site):
                candidate = REPO / "src/grant_agent" / (module + ".py")
                if candidate.is_file():
                    paths.add(candidate)
            for path in re.findall(r"\b(?:web/[\w/.-]+\.(?:jsx?|tsx?)\b|scripts/[\w/.-]+\.py\b)", site):
                candidate = (REPO / path).resolve()
                candidate.relative_to(REPO)
                if candidate.is_file():
                    paths.add(candidate)
            for path in re.findall(r"\b(?:scripts|config|plugins|web|src|sdk)/[\w/.-]+\.(?:py|[cm]?js|tsx?|jsx|json|rs|toml)\b", site):
                candidate = (REPO / path).resolve()
                candidate.relative_to(REPO)
                if candidate.is_file():
                    paths.add(candidate)
    paths.update((REPO / "web/src/neyvia/next").glob("nx*Contracts.js"))
    return {p.relative_to(REPO).as_posix(): source_digest(p) for p in sorted(paths)}


def source_binding_digest(bindings):
    return hashlib.sha256(json.dumps(bindings, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
