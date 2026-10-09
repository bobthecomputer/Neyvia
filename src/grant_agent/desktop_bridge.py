"""Bounded Tauri bridge into Neyvia's durable Python backend.

The browser build reaches :class:`FluxioWebBackend` over ``/api/backend``.
Tauri's asset protocol has no HTTP backend, so the desktop shell invokes this
module through one local command instead. Keeping the dispatch here means web
and desktop share the same SQLite lifecycle and runtime behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .connected_sessions.api import CONNECTED_COMMANDS
from .neyvia_memory_tools import COMMANDS as MEMORY_COMMANDS
from .neyvia_cua import COMMANDS as CUA_COMMANDS
from .neyvia_remote import COMMANDS as REMOTE_COMMANDS
from .subprocess_utils import install_hidden_subprocess_default


MAX_REQUEST_BYTES = 2 * 1024 * 1024
# Controller completion can carry a result accepted by desktop_controller's
# 8 MiB result limit. Keep the ordinary command envelope cap unchanged and
# allow bounded JSON overhead only for the trusted local completion command.
MAX_COMPLETION_REQUEST_BYTES = 10 * 1024 * 1024
MAX_SKILL_IMPORT_REQUEST_BYTES = 29 * 1024 * 1024
# A connected-session turn can carry pasted images as base64.
MAX_CONNECTED_TURN_REQUEST_BYTES = 26 * 1024 * 1024

# These screens share durable jobs, catalogues and state with the HTTP app.
# An IPC child must forward to that owner instead of creating another backend.
CLASSIC_SERVICE_COMMANDS = frozenset({
    "get_app_factory_catalog_command", "create_app_factory_job_command",
    "get_capability_evolution_command", "get_capability_ui_contract_command",
    "get_installed_module_catalog_command", "install_module_package_command",
    "get_security_runtime_audit_command", "get_mcp_broker_snapshot_command",
    "describe_tool_suite_command", "execute_tool_suite_command",
    "discover_nearby_devices_command", "get_nearby_active_transfer_command",
    "get_nearby_transfer_history_command", "get_nearby_receiver_sidecar_status_command",
    "get_mesh_enrollment_trust_command", "get_nearby_send_compatibility_command",
    "get_folder_sync_compatibility_command",
    "get_communication_fabric_command", "get_deep_benchmark_lab_command",
    "get_experimental_systems_command", "list_authored_tools_command",
    "get_operator_preferences_command", "get_workspace_intelligence_command",
    "get_neyvia_semantic_objects_command", "build_neyvia_ecosystem_context_pack_command",
    "run_neyvia_orchestration_command", "get_harness_comparison_command",
    "get_html_site_benchmark_command", "manage_cli_proxy_api_command",
    "create_codex_skill_command", "get_control_room_mission_events_command",
    "get_ios_studio_status_command", "create_ios_app_command", "start_ios_build_command",
})
LEGACY_CONNECTED_COMMANDS = frozenset({
    "send_connected_app_chat_command", "answer_connected_app_chat_command",
    "cancel_connected_app_chat_command", "list_connected_app_windows_command",
    "get_connected_app_window_command", "act_connected_app_window_command",
})

# This is deliberately narrower than FluxioWebBackend.dispatch. Native Tauri
# commands remain authoritative for keyring, URL, filesystem-picker, and other
# operating-system operations.
ALLOWED_DESKTOP_COMMANDS = frozenset(
    {
        "call_native_tool_command",
        # Computer use drives the PC, so it runs in the PC app for the desktop
        # and for a browser that controls it.
        "list_computer_use_twins_command",
        "validate_computer_use_twin_command",
        "save_computer_use_twin_command",
        "run_computer_use_twin_command",
        "dispatch_computer_use_twin_command",
        "verify_computer_use_change_command",
        "dispatch_computer_use_verification_command",
        "desktop_controller_poll_command",
        "desktop_controller_complete_command",
        "call_situation_command",
        "get_agent_collaboration_command",
        "get_agent_prompt_library_command",
        "get_provider_model_catalog_command",
        "set_opencode_provider_api_key_command",
        "get_runtime_capability_inventory_command",
        "get_native_tool_catalog_command",
        "get_skill_library_command",
        "inspect_skill_import_command",
        "install_skill_import_command",
        "save_agent_collaboration_command",
        "save_agent_prompt_library_command",
        "reset_agent_prompt_library_command",
        "review_agent_brief_command",
        "set_host_session_control_command",
        "append_neyvia_conversation_turn_command",
        "approval_modes_command",
        "create_neyvia_conversation_command",
        "clear_conversation_state_command",
        "delete_neyvia_conversations_command",
        "create_neyvia_orchestration_plan_command",
        "create_neyvia_question_branch_command",
        "get_capability_os_snapshot_command",
        "get_connected_devices_command",
        "get_neyvia_attention_inbox_command",
        "get_neyvia_conversation_command",
        "get_neyvia_conversation_deletion_snapshot_command",
        "get_neyvia_conversations_command",
        "get_external_chats_command",
        "get_external_chat_command",
        "send_connected_app_chat_command",
        "get_connected_app_chat_run_command",
        "answer_connected_app_chat_command",
        "cancel_connected_app_chat_command",
        "list_connected_app_windows_command",
        "get_connected_app_window_command",
        "act_connected_app_window_command",
        "get_conversation_state_command",
        "get_control_room_summary_command",
        "get_conversation_session_state_command",
        "save_conversation_state_command",
        "get_task_continuity_command",
        "save_task_continuity_command",
        "list_workspace_directory_command",
        "search_workspace_directories_command",
        "save_workspace_profile_command",
        "get_harness_catalog_command",
        "list_harness_jobs_command",
        "get_harness_job_command",
        "start_harness_job_command",
        "cancel_harness_job_command",
        "prepare_harness_batch_command",
        "list_harness_batches_command",
        "get_harness_batch_command",
        "start_harness_batch_command",
        "cancel_harness_batch_command",
        "get_harness_runtime_inspection_command",
        "get_harness_instruction_command",
        "save_harness_instruction_command",
        "save_harness_profile_command",
        "get_provider_auth_queue_command",
        "get_hermes_anthropic_auth_status_command",
        "get_hermes_subscription_status_command",
        "setup_hermes_subscription_command",
        "start_hermes_anthropic_oauth_command",
        "start_provider_auth_queue_command",
        "advance_provider_auth_queue_command",
        "skip_provider_auth_queue_item_command",
        "cancel_provider_auth_queue_command",
        "start_codex_device_auth_command",
        "inspect_managed_cli_runtime_command",
        "image_playground_operation_command",
        "record_neyvia_synthesis_command",
        "reopen_neyvia_conversation_command",
        "retrieve_neyvia_context_command",
        "send_agent_chat_command",
        "cancel_agent_chat_command",
        "get_agent_chat_run_status_command",
        "get_agent_chat_stream_command",
        "set_approval_mode_command",
        "set_neyvia_conversation_project_command",
        "set_neyvia_conversation_goal_mode_command",
        "get_archived_neyvia_conversations_command",
        "restore_neyvia_conversation_command",
        "set_neyvia_conversation_title_command",
        "settle_neyvia_conversation_command",
        "snooze_neyvia_conversation_command",
        "transition_neyvia_agent_node_command",
        "wake_neyvia_conversation_command",
    }
)
# The connected-sessions broker lives in the persistent PC service; the bridge forwards to it.
# Accounts are managed by the persistent service; the bridge signs in there as the PC owner.
from .neyvia_accounts import ACCOUNT_COMMANDS  # noqa: E402
from .neyvia_awareness import AWARENESS_COMMANDS  # noqa: E402
from .neyvia_onboarding import COMMANDS as ONBOARDING_COMMANDS  # noqa: E402
from .neyvia_dictation import COMMANDS as DICTATION_COMMANDS  # noqa: E402
from .neyvia_voice import COMMANDS as VOICE_COMMANDS  # noqa: E402
from .neyvia_autopilot import COMMANDS as AUTOPILOT_COMMANDS  # noqa: E402
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | CONNECTED_COMMANDS | ACCOUNT_COMMANDS | AWARENESS_COMMANDS | ONBOARDING_COMMANDS | DICTATION_COMMANDS | MEMORY_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | VOICE_COMMANDS
from .neyvia_nightshift import COMMANDS as NIGHTSHIFT_COMMANDS  # noqa: E402
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | NIGHTSHIFT_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | AUTOPILOT_COMMANDS
from .neyvia_outputs import COMMANDS as OUTPUT_COMMANDS  # noqa: E402
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | frozenset(OUTPUT_COMMANDS)
from .neyvia_sidebar import COMMANDS as SIDEBAR_COMMANDS  # noqa: E402
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | SIDEBAR_COMMANDS
from .neyvia_gamedev import COMMANDS as GAMEDEV_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | GAMEDEV_COMMANDS
from .neyvia_browser import COMMANDS as BROWSER_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | BROWSER_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | CONNECTED_COMMANDS | ACCOUNT_COMMANDS | AWARENESS_COMMANDS | ONBOARDING_COMMANDS | DICTATION_COMMANDS | CUA_COMMANDS
from .neyvia_settings import COMMANDS as SETTINGS_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | SETTINGS_COMMANDS
from .neyvia_modules import COMMANDS as MODULE_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | MODULE_COMMANDS
from .source_marketplace import COMMANDS as SOURCE_MARKETPLACE_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | SOURCE_MARKETPLACE_COMMANDS
from .components import COMMANDS as COMPONENT_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | COMPONENT_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | REMOTE_COMMANDS
from .neyvia_evolver import COMMANDS as EVOLVER_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | EVOLVER_COMMANDS
from .neyvia_app_sdk import COMMANDS as APP_SDK_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | APP_SDK_COMMANDS
from .neyvia_scroll import COMMANDS as SCROLL_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | SCROLL_COMMANDS
ALLOWED_DESKTOP_COMMANDS = ALLOWED_DESKTOP_COMMANDS | CLASSIC_SERVICE_COMMANDS


class DesktopBridgeError(RuntimeError):
    """Raised when a desktop request cannot enter the bounded backend bridge."""


def _install_bundled_image_skill(state_root: Path) -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / ".codex"
        / "skills"
        / "imagegen"
        / "SKILL.md"
    )
    destination = state_root / ".codex" / "skills" / "imagegen" / "SKILL.md"
    if destination.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _resolve_catalog_workspace(state_root: Path, requested: object) -> Path:
    """Apply the same saved-workspace allowlist used by FluxioWebBackend."""
    candidate = Path(str(requested or state_root)).expanduser().resolve()
    allowed = [state_root.resolve()]
    for env_name in ("FLUXIO_WORKSPACE_ROOTS", "FLUXIO_FOLDER_ROOTS"):
        for value in re.split(r"[;\n]", os.environ.get(env_name, "")):
            value = str(value or "").strip().strip('"')
            if value:
                allowed.append(Path(value).expanduser().resolve())
    try:
        workspaces = json.loads((state_root / ".agent_control" / "workspaces.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        workspaces = []
    rows = (
        workspaces
        if isinstance(workspaces, list)
        else workspaces.get("workspaces", [])
        if isinstance(workspaces, dict)
        else []
    )
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        value = str(row.get("root_path") or row.get("rootPath") or "").strip()
        if value:
            allowed.append(Path(value).expanduser().resolve())
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise DesktopBridgeError(f"Directory is outside configured workspace roots: {candidate}")
    if not candidate.is_dir():
        raise DesktopBridgeError(f"Directory does not exist: {candidate}")
    return candidate


def dispatch_desktop_command(
    root: Path,
    command: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    normalized = str(command or "").strip()
    if normalized not in ALLOWED_DESKTOP_COMMANDS:
        raise DesktopBridgeError(f"Desktop backend command is not allowed: {normalized or '<empty>'}")
    state_root = root.expanduser().resolve()
    request_payload = dict(payload or {})
    if normalized in APP_SDK_COMMANDS:
        from .neyvia_app_sdk import handle_command
        return handle_command(state_root, normalized, request_payload)
    from .local_network_policy import install as install_network_policy
    install_network_policy(state_root)
    if normalized in CLASSIC_SERVICE_COMMANDS or normalized in LEGACY_CONNECTED_COMMANDS:
        explicit_port = None
        for name in ("NEYVIA_CONNECTED_SERVICE_PORT", "NEYVIA_WEB_PORT", "FLUXIO_WEB_PORT"):
            try:
                value = int(os.environ.get(name) or 0)
            except ValueError:
                continue
            if 0 < value < 65536:
                explicit_port = value
                break
        if explicit_port is None:
            raise DesktopBridgeError("Set the persistent workspace service port before opening classic tools")
        from .connected_sessions.forward import forward_connected_command
        return forward_connected_command(state_root, normalized, request_payload)
    if normalized in SCROLL_COMMANDS:
        if normalized in {"scroll_generate_command", "scroll_concepts_command", "scroll_preview_command", "scroll_send_command"}:
            if not os.environ.get("NEYVIA_UI_BACKEND_URL"):
                raise DesktopBridgeError("Set the explicit workspace backend URL before using the study generator")
            from .neyvia_ui_client import call_tool
            return call_tool("scroll." + normalized.removeprefix("scroll_").removesuffix("_command"), request_payload, expected_root=state_root)
        from .neyvia_scroll import handle_command
        return handle_command(state_root, normalized, request_payload)
    if normalized in EVOLVER_COMMANDS:
        if normalized == "evolver_run_command":
            if not os.environ.get("NEYVIA_UI_BACKEND_URL"):
                raise DesktopBridgeError("Set the explicit workspace backend URL before starting evolution")
            from .neyvia_ui_client import call_tool
            return call_tool("evolver.run", request_payload, expected_root=state_root)
        from .neyvia_evolver import handle_command
        return handle_command(state_root, normalized, request_payload)
    if normalized in BROWSER_COMMANDS:
        from .neyvia_browser import forward_command
        return forward_command(state_root, normalized, request_payload)
    if normalized in NIGHTSHIFT_COMMANDS:
        from .connected_sessions.forward import forward_connected_command
        return forward_connected_command(state_root, normalized, request_payload)
    if normalized in AUTOPILOT_COMMANDS:
        from .neyvia_autopilot import forward_command
        return forward_command(state_root, normalized, request_payload)
    if normalized in OUTPUT_COMMANDS:
        from .connected_sessions.forward import forward_connected_command
        return forward_connected_command(state_root, normalized, request_payload)
    if normalized == "call_native_tool_command" and (str(request_payload.get("tool") or request_payload.get("name") or "").startswith("neyvia.perception.") or str(request_payload.get("tool") or request_payload.get("name") or "") in {"neyvia.cl", "neyvia.cl.describe"}):
        # A private browser must outlive this IPC child. Use the explicit
        # persistent service URL; never fall through to a default live port.
        if not os.environ.get("NEYVIA_UI_BACKEND_URL"):
            raise DesktopBridgeError("CL and perception need the persistent service URL")
        from .neyvia_ui_client import call_tool
        return call_tool(str(request_payload.get("tool") or request_payload.get("name"))[7:], request_payload.get("arguments") or {}, expected_root=state_root)
    if normalized in SIDEBAR_COMMANDS:
        from .neyvia_sidebar import forward_command
        return forward_command(state_root, normalized, request_payload)
    if normalized in GAMEDEV_COMMANDS:
        from .neyvia_gamedev import forward_command
        return forward_command(state_root, normalized, request_payload)
    if normalized in COMPONENT_COMMANDS:
        # Plain file and CLI work on this PC; the owner's desktop app is the caller. No backend needed.
        from .components import handle_command as handle_component
        return handle_component(None, normalized, request_payload.get("payload") if isinstance(request_payload.get("payload"), dict) else request_payload)
    if normalized in SETTINGS_COMMANDS or normalized in MODULE_COMMANDS or normalized in SOURCE_MARKETPLACE_COMMANDS:
        from .connected_sessions.forward import forward_connected_command
        return forward_connected_command(state_root, normalized, request_payload)
    if normalized in VOICE_COMMANDS:
        from .neyvia_voice import forward_command
        return forward_command(state_root, normalized, request_payload)
    if normalized in CUA_COMMANDS:
        from .neyvia_cua import forward_desktop
        nested = request_payload.get("payload")
        return forward_desktop(state_root, normalized, nested if isinstance(nested, dict) else request_payload)
    if normalized in REMOTE_COMMANDS:
        if normalized == "remote_frame_command":
            from .neyvia_remote_frames import forward_frame
            return forward_frame(state_root, request_payload)
        from .neyvia_remote import forward_desktop
        nested = request_payload.get("payload")
        return forward_desktop(state_root, normalized, nested if isinstance(nested, dict) else request_payload)
    if normalized in CONNECTED_COMMANDS or normalized in ACCOUNT_COMMANDS or normalized in MEMORY_COMMANDS:
        from .connected_sessions.forward import forward_connected_command
        return forward_connected_command(state_root, normalized, request_payload)
    if normalized in ONBOARDING_COMMANDS:
        # Small same-root state files and a detached download worker: no backend needed.
        from .neyvia_onboarding import handle as handle_onboarding
        return handle_onboarding(state_root, normalized, request_payload)
    # These two commands are a Tauri child-process fastpath. Raw HTTP dispatch
    # is blocked at the gateway; keeping this before backend construction also
    # avoids recursively entering FluxioWebBackend while a chat stream is live.
    if normalized in DICTATION_COMMANDS:
        # IPC workers exit after every call. The persistent service owns PCM,
        # agreement, final retries and late re-decodes for the entire utterance.
        from .connected_sessions.forward import forward_connected_command
        return forward_connected_command(state_root, normalized, request_payload)
    if normalized in AWARENESS_COMMANDS:
        # The work board is one small JSON file and the impact map reads source files; no backend needed.
        from .neyvia_awareness import handle_command
        nested = request_payload.get("payload")
        return handle_command(state_root, normalized, nested if isinstance(nested, dict) else request_payload)
    if normalized in {"desktop_controller_poll_command", "desktop_controller_complete_command"}:
        from . import desktop_controller

        if normalized == "desktop_controller_poll_command":
            return desktop_controller.desktop_poll(state_root, request_payload)
        return desktop_controller.desktop_complete(state_root, request_payload)
    if normalized == "get_agent_chat_stream_command":
        # Polling a running turn only needs its bounded event file. Constructing
        # the complete backend here delays every visible chunk on desktop.
        from .chat_stream import read_chat_stream

        # UI commands use the same nested payload envelope as web dispatch.
        # Direct bridge clients may still send the flat command arguments.
        stream_payload = request_payload.get("payload")
        if not isinstance(stream_payload, dict):
            stream_payload = request_payload
        return read_chat_stream(state_root, stream_payload.get("turnId"), stream_payload.get("cursor"))
    if normalized in {"cancel_agent_chat_command", "get_agent_chat_run_status_command"}:
        # Stop and status only touch the turn's small run record. Answering
        # without building the backend keeps Stop responsive during a run.
        from .chat_run_control import chat_run_status, request_chat_cancellation

        run_payload = request_payload.get("payload")
        if not isinstance(run_payload, dict):
            run_payload = request_payload
        turn_id = run_payload.get("turnId") or run_payload.get("assistantTurnId") or run_payload.get("assistant_turn_id")
        if normalized == "cancel_agent_chat_command":
            return request_chat_cancellation(state_root, turn_id)
        return chat_run_status(state_root, turn_id)
    # These commands only read/write two small same-root stores. Reuse the
    # backend's authoritative helpers directly so the desktop subprocess skips
    # constructing its heavyweight runtime and background services per poll.
    if normalized in {
        "get_conversation_state_command",
        "get_conversation_session_state_command",
        "save_conversation_state_command",
    }:
        from .web_backend import (
            CONVERSATION_STATE_BOOTSTRAP_TURNS_PER_SESSION,
            CONVERSATION_STATE_MAX_TURNS_PER_SESSION,
            _conversation_session_state,
            _conversation_state_bootstrap,
            _load_conversation_state,
            _save_conversation_state,
        )

        state_root = Path(request_payload.get("root") or state_root).resolve()
        if normalized == "get_conversation_state_command":
            if str(request_payload.get("summaryMode") or "").strip().lower() == "bootstrap":
                return _conversation_state_bootstrap(
                    state_root,
                    active_session_id=(
                        request_payload.get("activeChatSessionId")
                        if "activeChatSessionId" in request_payload
                        else request_payload.get("active_chat_session_id")
                    ),
                    turn_limit=(
                        request_payload.get("turnLimit")
                        or request_payload.get("turn_limit")
                        or CONVERSATION_STATE_BOOTSTRAP_TURNS_PER_SESSION
                    ),
                )
            return _load_conversation_state(state_root)
        if normalized == "get_conversation_session_state_command":
            return _conversation_session_state(
                state_root,
                session_id=request_payload.get("sessionId") or request_payload.get("session_id"),
                turn_limit=(
                    request_payload.get("turnLimit")
                    or request_payload.get("turn_limit")
                    or CONVERSATION_STATE_MAX_TURNS_PER_SESSION
                ),
                if_revision=request_payload.get("ifRevision"),
            )
        return _save_conversation_state(state_root, request_payload)
    if normalized in {
        "get_agent_prompt_library_command",
        "save_agent_prompt_library_command",
        "reset_agent_prompt_library_command",
    }:
        from .agent_prompt_library import load_prompt_library, reset_prompt_library, save_prompt_library

        if normalized == "get_agent_prompt_library_command":
            return load_prompt_library(state_root, **{key: request_payload.get(key) for key in ("runtime", "provider", "model")})
        if normalized == "save_agent_prompt_library_command":
            return save_prompt_library(state_root, request_payload)
        return reset_prompt_library(
            state_root,
            str(request_payload.get("role") or ""),
            request_payload.get("expectedRevision"),
            scope_id=request_payload.get("scopeId"),
            **{key: request_payload.get(key) for key in ("runtime", "provider", "model")},
        )
    # Runtime capability browsing is read-only and must not shell out to a CLI
    # verb: the installed CLI does not define `native-tools`. Keep these paths
    # in process, matching FluxioWebBackend.dispatch while avoiding a full
    # backend/service initialization for a catalog refresh.
    if normalized in {"get_native_tool_catalog_command", "get_skill_library_command"}:
        nested_payload = request_payload.get("payload")
        if isinstance(nested_payload, dict):
            request_payload = nested_payload
    if normalized in {"inspect_skill_import_command", "install_skill_import_command"}:
        from .skill_import import inspect_skills, install_skills
        nested_payload = request_payload.get("payload")
        if isinstance(nested_payload, dict):
            request_payload = nested_payload
        catalog_root = _resolve_catalog_workspace(state_root, request_payload.get("root"))
        return (inspect_skills if normalized == "inspect_skill_import_command" else install_skills)(catalog_root, request_payload)
    if normalized == "get_native_tool_catalog_command":
        from .native_tools import NativeToolRegistry

        catalog_root = _resolve_catalog_workspace(state_root, request_payload.get("root"))
        registry = NativeToolRegistry(
            catalog_root,
            nas_root=(request_payload.get("nasRoot") or request_payload.get("nas_root") or None),
        )
        query = str(request_payload.get("query") or "").strip()
        describe = str(request_payload.get("describe") or request_payload.get("tool") or "").strip()
        if describe:
            return registry.describe(describe)
        if query:
            return {
                "schema": "fluxio.native_tool_search.v1",
                "query": query,
                "matches": registry.search(query),
            }
        return registry.snapshot()
    if normalized == "get_skill_library_command":
        from .mission_control import ControlRoomStore

        catalog_root = _resolve_catalog_workspace(state_root, request_payload.get("root"))
        return ControlRoomStore(catalog_root)._fast_summary_skill_catalog_payload(
            focus_skill_id=str(
                request_payload.get("focusSkillId")
                or request_payload.get("focus_skill_id")
                or ""
            ).strip()
        )
    if normalized == "call_native_tool_command":
        tool = str(request_payload.get("tool") or request_payload.get("name") or "").strip()
        if tool not in {"lab.status", "lab.complexity", "lab.instrument", "lab.competition", "runtime.preflight", "runtime.evidence", "runtime.completion", "preview.inspect", "preview.taste", "host.programs", "host.sessions", "host.launch", "host.status", "host.stop", "host.inspect_preview", "host.prepare_file", "host.launch_file", "laya.native.capabilities"}:
            raise DesktopBridgeError("This native tool is not available through the desktop Preview bridge")
        request_payload["root"] = str(state_root)
    if normalized in {"set_host_session_control_command", "call_situation_command", "save_agent_collaboration_command", "review_agent_brief_command", "set_opencode_provider_api_key_command"}:
        # This entry point is the existing local desktop IPC boundary. Do not
        # accept a caller-supplied web account identity as the operator identity.
        request_payload["_operatorIdentity"] = "local-desktop"
    state_root.mkdir(parents=True, exist_ok=True)
    if normalized == "image_playground_operation_command":
        _install_bundled_image_skill(state_root)

    from .web_backend import FluxioWebBackend

    backend = FluxioWebBackend(state_root, state_root)
    return backend.dispatch(normalized, request_payload)


def _json_safe(value: Any) -> Any:
    """Keep malformed provider Unicode from breaking the Tauri JSON boundary."""
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, dict):
        return {_json_safe(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _emit_envelope(envelope: dict[str, Any]) -> None:
    # The desktop command runs through a Windows pipe whose text encoding can
    # be cp1252. An ASCII JSON byte stream also makes surrogate handling
    # explicit before serde_json reads it in Tauri.
    encoded = json.dumps(_json_safe(envelope), ensure_ascii=True, allow_nan=False)
    try:
        sys.stdout.buffer.write(encoded.encode("ascii") + b"\n")
        sys.stdout.buffer.flush()
    except OSError:
        # The desktop window that asked has gone (closed or crashed). A chat
        # result is already recorded for the window that reconnects.
        pass


def main() -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(description="Dispatch one bounded Neyvia desktop backend command.")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    raw = sys.stdin.buffer.read(MAX_SKILL_IMPORT_REQUEST_BYTES + 1)
    if len(raw) > MAX_SKILL_IMPORT_REQUEST_BYTES:
        _emit_envelope({"ok": False, "error": "Desktop backend request exceeds the bounded completion size."})
        return 2
    try:
        request = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(request, dict):
            raise DesktopBridgeError("Desktop backend request must be a JSON object.")
        command = str(request.get("command") or "").strip()
        request_limit = (MAX_SKILL_IMPORT_REQUEST_BYTES if command == "inspect_skill_import_command"
                         else MAX_COMPLETION_REQUEST_BYTES if command == "desktop_controller_complete_command"
                         else MAX_CONNECTED_TURN_REQUEST_BYTES if command in {"connected_session_send_command", "connected_session_new_command"}
                         else MAX_REQUEST_BYTES)
        if len(raw) > request_limit:
            _emit_envelope({"ok": False, "error": "Desktop backend request is too large."})
            return 2
        payload = request.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise DesktopBridgeError("Desktop backend payload must be a JSON object.")
        result = dispatch_desktop_command(
            Path(args.root),
            command,
            payload,
        )
        _emit_envelope({"ok": True, "data": result})
        return 0
    except (DesktopBridgeError, RuntimeError, ValueError, KeyError) as exc:
        _emit_envelope({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
