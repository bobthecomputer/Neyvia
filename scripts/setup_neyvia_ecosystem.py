from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = ROOT.parent


class EcosystemProject(NamedTuple):
    project_id: str
    root: Path
    test_script: str
    build_script: str


def discover_projects(project_root: Path = DEFAULT_PROJECT_ROOT) -> list[EcosystemProject]:
    return [
        EcosystemProject("neyvia-platform", ROOT, "test:frontend", "frontend:build"),
        EcosystemProject(
            "signal-briefs",
            project_root / "neyvia-app-signal-briefs",
            "test",
            "build",
        ),
        EcosystemProject(
            "solentir",
            project_root / "neyvia-app-solentir",
            "test",
            "build",
        ),
    ]


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=str(cwd), env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def setup_project(
    project: EcosystemProject,
    *,
    npm_command: str,
    install: bool,
    test: bool,
    build: bool,
) -> dict[str, object]:
    package_json = project.root / "package.json"
    if not package_json.exists():
        return {
            "projectId": project.project_id,
            "root": str(project.root),
            "status": "missing",
        }
    env = dict(os.environ)
    env["NEYVIA_ECOSYSTEM_PROJECT"] = project.project_id
    if install:
        run([npm_command, "ci"], cwd=project.root, env=env)
    if test:
        run([npm_command, "run", project.test_script], cwd=project.root, env=env)
    if build:
        run([npm_command, "run", project.build_script], cwd=project.root, env=env)
    return {
        "projectId": project.project_id,
        "root": str(project.root.resolve()),
        "status": "ready",
        "installed": install,
        "tested": test,
        "built": build,
        "dependencyRoot": str((project.root / "node_modules").resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install, test, and build each Neyvia ecosystem project in its own environment."
    )
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        choices=("neyvia-platform", "signal-briefs", "solentir"),
    )
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    npm_command = shutil.which("npm")
    if not npm_command:
        raise SystemExit("npm was not found. Run install_nas_runtime_stack.py first.")
    selected = set(args.project)
    projects = [
        project
        for project in discover_projects(args.project_root)
        if not selected or project.project_id in selected
    ]
    results = [
        setup_project(
            project,
            npm_command=npm_command,
            install=not args.skip_install,
            test=not args.skip_tests,
            build=not args.skip_build,
        )
        for project in projects
    ]
    missing = [item["projectId"] for item in results if item["status"] == "missing"]
    payload = {
        "ready": not missing,
        "projectRoot": str(args.project_root.resolve()),
        "projects": results,
        "missingProjects": missing,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for result in results:
            print(f"{result['projectId']}: {result['status']} ({result['root']})")
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
