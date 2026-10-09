#!/usr/bin/env python3
"""Fail closed when GitHub Actions can silently mutate NEYVIA publication state.

The default branch is the reviewable source of truth. Workflows may validate,
build, publish artifacts, or create releases with narrowly scoped permissions, but
they must not contain unattended source-branch mutation machinery. A future
exception must change this policy in an ordinary reviewed commit rather than hide
behind an allowlist embedded in a workflow.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

LEGACY_NATIVE_BRANCH = "codex/neyvia-native-hybrid-evolution-20260826"
WRITE_ALL_PERMISSION_RE = re.compile(
    r"(?mi)^\s*permissions\s*:\s*write-all\s*(?:#.*)?$"
)
MUTATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("git-push", re.compile(r"(?m)(?:^|[;&|]\s*|\s)git\s+push\b")),
    ("pull-request-mutation", re.compile(r"(?m)\bgh\s+pr\s+(?:create|edit|close|merge|reopen)\b")),
    (
        "write-api-call",
        re.compile(
            r"(?im)\bgh\s+api\b[^\n]*(?:(?:--method|-X)\s+(?:POST|PUT|PATCH|DELETE)|/cancel\b)"
        ),
    ),
)


def _workflow_paths(root: Path) -> Iterable[Path]:
    workflow_root = root / ".github" / "workflows"
    if not workflow_root.is_dir():
        return ()
    return sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")))


def audit_workflows(root: Path) -> list[dict[str, str]]:
    """Return deterministic findings for publication-integrity violations.

    Repository mutation commands are rejected regardless of the declared
    ``GITHUB_TOKEN`` permissions. A workflow can otherwise supply a PAT, deploy
    key, GitHub App token, or future credential and silently bypass a permission-
    gated scanner. Explicit ``permissions: write-all`` is separately rejected so
    a future workflow cannot acquire broad write authority even before it grows a
    recognized mutation command.
    """

    findings: list[dict[str, str]] = []
    for path in _workflow_paths(root):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()

        if LEGACY_NATIVE_BRANCH in text:
            findings.append(
                {
                    "path": rel,
                    "rule": "legacy-self-mutating-branch",
                    "detail": f"workflow still targets retired branch {LEGACY_NATIVE_BRANCH}",
                }
            )

        if WRITE_ALL_PERMISSION_RE.search(text):
            findings.append(
                {
                    "path": rel,
                    "rule": "write-all-permissions",
                    "detail": "workflow grants the GitHub token blanket write authority",
                }
            )

        # Join ordinary shell line continuations before matching so a mutating
        # command cannot evade the audit merely by splitting its arguments.
        command_text = re.sub(r"\\\r?\n\s*", " ", text)
        for rule, pattern in MUTATION_PATTERNS:
            if pattern.search(command_text):
                findings.append(
                    {
                        "path": rel,
                        "rule": rule,
                        "detail": "workflow contains unattended repository/control-plane mutation",
                    }
                )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = args.root.resolve()
    findings = audit_workflows(root)
    payload = {
        "schema": "neyvia.workflow-publication-integrity/v1",
        "root": str(root),
        "workflowCount": sum(1 for _ in _workflow_paths(root)),
        "findingCount": len(findings),
        "findings": findings,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif findings:
        for finding in findings:
            print(f"{finding['path']}: {finding['rule']}: {finding['detail']}")
    else:
        print(f"NEYVIA_WORKFLOW_PUBLICATION_INTEGRITY_OK workflows={payload['workflowCount']}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
