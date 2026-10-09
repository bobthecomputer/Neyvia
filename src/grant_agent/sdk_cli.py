"""Safe CLI workflows over Neyvia's typed marketplace and surface services."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from .generated.neyvia_contracts import (
    JsonObject,
    NeyviaApplicationSurface,
    NeyviaModuleManifest,
)
from .sdk import (
    get_application_surface_status,
    list_installed_modules,
    plan_application_surface_launch,
    plan_module_install,
    validate_module_manifest,
)
from .sdk_codegen import LossySchemaError, generate_sdk_bindings


SDK_CLI_ERROR_SCHEMA = "neyvia.sdk-cli-error/v1"
PERMISSION_MODES = (
    "always_ask",
    "workspace_safe",
    "review_only",
    "autonomous_scoped",
)


def register_sdk_cli(subparsers: argparse._SubParsersAction) -> None:
    sdk = subparsers.add_parser(
        "neyvia-sdk",
        help="Generate SDK bindings and run non-executing marketplace/surface workflows",
    )
    actions = sdk.add_subparsers(dest="sdk_action", required=True)

    bindings = actions.add_parser(
        "bindings",
        help="Generate deterministic Python and TypeScript schema bindings",
    )
    bindings.add_argument("--root", default=".", help="Project root path")
    bindings.add_argument(
        "--check",
        action="store_true",
        help="Fail if checked-in bindings are not byte-identical to generation",
    )

    validate = actions.add_parser(
        "manifest-validate",
        help="Validate a marketplace module manifest through ModuleMarketplace",
    )
    validate.add_argument("--root", default=".", help="Project root path")
    validate.add_argument("--manifest", required=True, help="Module manifest JSON path")

    package_plan = actions.add_parser(
        "package-plan",
        help="Inspect a module package and create a non-activating install plan",
    )
    package_plan.add_argument("--root", default=".", help="Project root path")
    package_plan.add_argument("--manifest", required=True, help="Module manifest JSON path")
    package_plan.add_argument("--archive", required=True, help="Immutable .nymod archive path")
    package_plan.add_argument(
        "--current-version",
        default="",
        help="Currently active version for the plan comparison",
    )

    catalog = actions.add_parser(
        "catalog",
        help="Read the verified installed-module catalog",
    )
    catalog.add_argument("--root", default=".", help="Project root path")

    surface_status = actions.add_parser(
        "surface-status",
        help="Inspect application-surface evidence without starting an app",
    )
    surface_status.add_argument("--root", default=".", help="Workspace root path")
    surface_status.add_argument("--manifest", required=True, help="App or surface manifest JSON path")
    surface_status.add_argument("--target-id", default="", help="Optional target identifier")

    launch_plan = actions.add_parser(
        "launch-plan",
        help="Create a permission-bound application-surface plan without executing it",
    )
    launch_plan.add_argument("--root", default=".", help="Workspace root path")
    launch_plan.add_argument("--manifest", required=True, help="App or surface manifest JSON path")
    launch_plan.add_argument("--target-id", required=True, help="Target identifier")
    launch_plan.add_argument(
        "--permission-mode",
        choices=PERMISSION_MODES,
        default="always_ask",
        help="Permission policy used by the non-executing planner",
    )
    launch_plan.add_argument(
        "--approval-id",
        default="",
        help="External approval receipt id to verify; the CLI cannot mint one",
    )


def _json_error(operation: str, message: str, *, path: str = "") -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": SDK_CLI_ERROR_SCHEMA,
        "operation": operation,
        "ok": False,
        "error": message,
    }
    if path:
        payload["path"] = path
    return payload


def _resolve_input_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _load_json_object(root: Path, value: str) -> JsonObject:
    path = _resolve_input_path(root, value)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read JSON input: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be an object")
    return cast(JsonObject, payload)


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def run_sdk_cli(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    operation = str(args.sdk_action)
    try:
        if operation == "bindings":
            result = generate_sdk_bindings(root, check=bool(args.check))
            _print(result)
            return 0 if result["ok"] else 2
        if operation == "manifest-validate":
            manifest = cast(
                NeyviaModuleManifest,
                _load_json_object(root, args.manifest),
            )
            result = validate_module_manifest(manifest, workspace_root=root)
            _print(result)
            return 0 if result.get("valid") else 2
        if operation == "package-plan":
            manifest = cast(
                NeyviaModuleManifest,
                _load_json_object(root, args.manifest),
            )
            archive = _resolve_input_path(root, args.archive)
            result = plan_module_install(
                manifest,
                archive,
                workspace_root=root,
                current_version=str(args.current_version or ""),
            )
            _print(result)
            return 0
        if operation == "catalog":
            _print(list_installed_modules(workspace_root=root))
            return 0
        if operation == "surface-status":
            manifest = cast(
                NeyviaApplicationSurface,
                _load_json_object(root, args.manifest),
            )
            result = get_application_surface_status(
                manifest,
                workspace_root=root,
                target_id=str(args.target_id or ""),
            )
            _print(result)
            return 2 if not result.get("valid") or result.get("errors") else 0
        if operation == "launch-plan":
            manifest = cast(
                NeyviaApplicationSurface,
                _load_json_object(root, args.manifest),
            )
            result = plan_application_surface_launch(
                manifest,
                workspace_root=root,
                target_id=str(args.target_id),
                permission_mode=str(args.permission_mode),
                approval_id=str(args.approval_id or ""),
            )
            _print(result)
            return 0
    except (LossySchemaError, OSError, ValueError) as exc:
        input_path = str(getattr(args, "manifest", "") or getattr(args, "archive", ""))
        _print(_json_error(operation, str(exc), path=input_path))
        return 2
    _print(_json_error(operation, "unknown SDK action"))
    return 2
