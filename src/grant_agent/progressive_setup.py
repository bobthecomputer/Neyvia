"""Plain-language, resumable first-run contract for Neyvia.

The older onboarding snapshot is intentionally detailed because it doubles as a
doctor surface.  First run needs a smaller projection: essentials first,
optional CLIs second, advanced capabilities last.  This module derives that
projection from real detector results and stores only the user's choices.
"""

from __future__ import annotations

import json
import threading
from functools import wraps
from pathlib import Path
from typing import Any

from .cli_catalog import STATE_READY, STATE_UPDATE_RECOMMENDED, build_catalog, recommend
from .connected_chrome import connection_status
from .durability import atomic_write_json
from .proofs_a_cli import checked

FIRST_RUN_SCHEMA = "neyvia.first_run.v1"
_STATE_RELATIVE = Path(".agent_control") / "neyvia" / "first_run.json"
_STATE_LOCKS: dict[str, threading.RLock] = {}
_STATE_LOCKS_GUARD = threading.Lock()


def _state_path(root: Path) -> Path:
    return root.resolve() / _STATE_RELATIVE


def _serialize_update(action):
    """Keep merge, publication and the persistence check in one owned lease."""
    @wraps(action)
    def update(root, patch):
        from .harness_jobs import _exclusive_job_lock
        path = _state_path(Path(root))
        path.parent.mkdir(parents=True, exist_ok=True)
        with _STATE_LOCKS_GUARD:
            lock = _STATE_LOCKS.setdefault(str(path), threading.RLock())
        with lock, _exclusive_job_lock(path):
            return action(root, patch)
    return update


def load_first_run_state(root: str | Path) -> dict[str, Any]:
    path = _state_path(Path(root))
    if not path.exists():
        return {
            "schema": FIRST_RUN_SCHEMA,
            "goals": [],
            "completedItemIds": [],
            "skippedRuntimeIds": [],
            "permissionsReviewed": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    return {
        "schema": FIRST_RUN_SCHEMA,
        "goals": [
            str(item)
            for item in payload.get("goals", [])
            if str(item) in {"software", "automation", "research", "creative", "writing"}
        ],
        "completedItemIds": sorted(
            {str(item) for item in payload.get("completedItemIds", []) if str(item).strip()}
        ),
        "skippedRuntimeIds": sorted(
            {str(item) for item in payload.get("skippedRuntimeIds", []) if str(item).strip()}
        ),
        "permissionsReviewed": bool(payload.get("permissionsReviewed")),
    }


@_serialize_update
@checked('a-cli.setup.state')
def update_first_run_state(root: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    current = load_first_run_state(root)
    if "goals" in patch:
        current["goals"] = [
            str(item)
            for item in patch.get("goals", [])
            if str(item) in {"software", "automation", "research", "creative", "writing"}
        ]
    for key in ("completedItemIds", "skippedRuntimeIds"):
        if key in patch:
            current[key] = sorted(
                {str(item) for item in patch.get(key, []) if str(item).strip()}
            )
    if "permissionsReviewed" in patch:
        current["permissionsReviewed"] = bool(patch.get("permissionsReviewed"))
    atomic_write_json(_state_path(Path(root)), current)
    return current


@checked('a-cli.setup.view')
def build_progressive_setup(
    root: str | Path,
    *,
    provider_presence: dict[str, bool] | None = None,
    force: bool = False,
    browser_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the three-stage first-run view without changing machine state."""

    root_path = Path(root).resolve()
    state = load_first_run_state(root_path)
    catalog = build_catalog(root_path, force=force, with_sizes=False)
    ready_runtimes = [
        row
        for row in catalog.get("entries", [])
        if row.get("state") in {STATE_READY, STATE_UPDATE_RECOMMENDED}
    ]
    providers = provider_presence or {}
    provider_ready = any(bool(value) for value in providers.values())
    if browser_state is None:
        chrome = connection_status(root_path)
        chrome_ready = chrome.get("state") in {"connected", "ready"}
    else:
        # The caller observes Neyvia's own browser service; this projection
        # neither probes a legacy debug port nor grants browser authority.
        if (not isinstance(browser_state, dict) or browser_state.get("ok") is not True
                or not isinstance(browser_state.get("runtime"), dict)
                or not isinstance(browser_state["runtime"].get("connected"), bool)):
            raise ValueError("browser_state must be an observed Neyvia browser service view")
        chrome = browser_state
        chrome_ready = browser_state["runtime"]["connected"] or bool((browser_state.get("headless") or {}).get("connected"))
    runtime_ready = bool(ready_runtimes or provider_ready)
    permissions_ready = bool(state.get("permissionsReviewed"))

    essential = [
        {
            "itemId": "neyvia_core",
            "label": "Neyvia core",
            "description": "The desktop shell and local backend are running.",
            "status": "ready",
            "requiredForMission": True,
            "action": None,
        },
        {
            "itemId": "workspace_storage",
            "label": "Workspace and storage",
            "description": f"Mission state will be stored under {root_path}.",
            "status": "ready" if root_path.exists() else "setup_required",
            "requiredForMission": True,
            "action": {"actionId": "settings:storage", "label": "Choose folder"},
        },
        {
            "itemId": "model_or_runtime",
            "label": "AI account or runtime",
            "description": (
                "At least one connected provider or detected runtime can perform work."
                if runtime_ready
                else "Connect an AI account or choose an optional runtime before starting a mission."
            ),
            "status": "ready" if runtime_ready else "setup_required",
            "requiredForMission": True,
            "action": {"actionId": "settings:providers", "label": "Connect account"},
        },
        {
            "itemId": "browser_connection",
            "label": "Browser connection",
            "description": str(
                chrome.get("detail")
                or ("Open Neyvia's browser when a task needs a website." if browser_state is not None
                    else "Connect Chrome only when a task needs an authenticated website.")
            ),
            "status": "ready" if chrome_ready else "available_after_setup",
            "requiredForMission": False,
            "action": {"actionId": "workbench:browser" if browser_state is not None else "workbench:computer-use",
                       "label": "Open browser" if browser_state is not None else "Connect Chrome"},
        },
        {
            "itemId": "permission_review",
            "label": "Permissions",
            "description": "Review when Neyvia may edit files, use paid services, or ask for approval.",
            "status": "ready" if permissions_ready else "setup_required",
            "requiredForMission": True,
            "action": {"actionId": "settings:rules", "label": "Review permissions"},
        },
    ]

    goals = state.get("goals") or ["software"]
    recommendations = recommend(catalog, goals, limit=2)
    recommended = [
        {
            "itemId": f"runtime:{row.get('runtimeId')}",
            "label": row.get("label"),
            "description": row.get("usefulFor") or row.get("reason"),
            "status": row.get("state"),
            "optional": True,
            "selected": row.get("runtimeId") not in state.get("skippedRuntimeIds", []),
            "actions": row.get("actions", []),
            "publisher": row.get("publisher"),
            "officialSource": row.get("officialSource"),
        }
        for row in catalog.get("entries", [])
    ]
    advanced = [
        {
            "itemId": "advanced:desktop_automation",
            "label": "Desktop automation",
            "description": "Add supervised computer-use capabilities only when needed.",
            "status": "available_after_setup",
            "optional": True,
        },
        {
            "itemId": "advanced:remote_workers",
            "label": "Remote workers and GPU",
            "description": "Connect external compute without adding GPU libraries to the core installer.",
            "status": "available_after_setup",
            "optional": True,
        },
        {
            "itemId": "advanced:developer_ecosystem",
            "label": "Developer and marketplace tools",
            "description": "Install SDK and application-development tools separately.",
            "status": "available_after_setup",
            "optional": True,
        },
    ]
    required_items = [item for item in essential if item["requiredForMission"]]
    blocked = [item for item in required_items if item["status"] != "ready"]
    current_stage = "essential" if blocked else "recommended"

    return {
        "schema": FIRST_RUN_SCHEMA,
        "resumable": True,
        "shellCanOpen": True,
        "missionCanStart": not blocked,
        "currentStage": current_stage,
        "stages": [
            {
                "stageId": "essential",
                "label": "Essential setup",
                "description": "Only the choices required to perform real work.",
                "items": essential,
            },
            {
                "stageId": "recommended",
                "label": "Recommended integrations",
                "description": "Optional CLIs and accounts. Neyvia works without installing all of them.",
                "items": recommended,
                "recommendations": recommendations,
                "continueWithoutAny": True,
            },
            {
                "stageId": "advanced",
                "label": "Advanced capabilities",
                "description": "Heavy or specialist tools remain separate until requested.",
                "items": advanced,
            },
        ],
        "blockingItemIds": [item["itemId"] for item in blocked],
        "state": state,
        "cliCatalog": catalog,
        "browser": chrome,
    }
