"""Work with the user's existing Thunder Compute account through connected Chrome.

Neyvia does not reimplement Thunder Compute, schedule GPUs, or own the training
architecture. The user already has an account, instances, and a workflow. This
module lets Neyvia reach that workflow the same way the user does — through the
browser they are already signed into — and act inside it under approval.

A deliberate choice about robustness: this module does **not** hardcode Thunder's
DOM. Selectors scraped from a console today break silently the next time it ships
a redesign, and a silent break in a module that starts and stops paid GPUs is the
worst possible failure. Instead everything is driven by visible text and the
generic element discovery in :mod:`grant_agent.connected_chrome`, and every
observation reports its own confidence. When Neyvia is unsure it says so and
hands the user the controls rather than guessing.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import connected_chrome as cc
from . import connected_chrome_policy as policy

#: Where the console lives. Overridable because a URL is exactly the kind of
#: detail that changes without notice, and a wrong constant should be a setting
#: the user can correct, not a code change.
DEFAULT_CONSOLE_URL = "https://console.thundercompute.com"

#: Hosts that count as "this is Thunder Compute" when scanning open tabs.
CONSOLE_HOST_HINTS = ("thundercompute.com", "thunder.compute")

#: Text that indicates we are looking at a sign-in wall rather than the console.
_SIGNED_OUT_MARKERS = (
    "sign in",
    "log in",
    "login",
    "continue with google",
    "create an account",
    "forgot password",
)

#: Text that indicates a usable, signed-in console.
_SIGNED_IN_MARKERS = (
    "instances",
    "instance",
    "gpu",
    "dashboard",
    "billing",
    "storage",
    "sign out",
    "log out",
)


class ThunderComputeError(RuntimeError):
    """Raised when the Thunder Compute workflow cannot proceed."""


# ---------------------------------------------------------------------------
# Locating the console
# ---------------------------------------------------------------------------


def _is_console_url(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in CONSOLE_HOST_HINTS)


def find_console_tab(*, port: int = cc.DEFAULT_DEBUG_PORT) -> cc.BrowserTab | None:
    """Return an already-open Thunder Compute tab, if there is one."""
    for tab in cc.list_tabs(port=port):
        if _is_console_url(tab.url):
            return tab
    return None


def open_console(
    *,
    port: int = cc.DEFAULT_DEBUG_PORT,
    console_url: str = DEFAULT_CONSOLE_URL,
) -> dict[str, Any]:
    """Focus the existing Thunder Compute tab, or open one.

    Reusing an open tab matters: the user may have a page mid-workflow, and
    opening a duplicate would both lose that state and confuse which tab
    subsequent actions apply to.
    """
    existing = find_console_tab(port=port)
    if existing is not None:
        return {"tab": existing.as_dict(), "targetId": existing.target_id, "opened": False}

    tab = cc.open_tab(console_url, port=port)
    return {"tab": tab.as_dict(), "targetId": tab.target_id, "opened": True}


# ---------------------------------------------------------------------------
# Reading the console
# ---------------------------------------------------------------------------


@dataclass
class ConsoleReading:
    authenticated: bool | None
    confidence: str
    detail: str
    instances: list[dict[str, Any]]
    observation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "neyvia.thunder.reading/1",
            "authenticated": self.authenticated,
            "confidence": self.confidence,
            "detail": self.detail,
            "instances": self.instances,
            "url": self.observation.get("url"),
            "title": self.observation.get("title"),
            "settled": self.observation.get("settled"),
            "screenshotPath": self.observation.get("screenshotPath"),
        }


def _assess_authentication_unchecked(text: str) -> tuple[bool | None, str, str]:
    """Decide whether the page shows a signed-in console.

    Returns ``(authenticated, confidence, detail)`` where ``authenticated`` may be
    ``None`` — genuinely not knowing is a valid and important answer here.
    """
    lowered = text.lower()
    signed_out_hits = [marker for marker in _SIGNED_OUT_MARKERS if marker in lowered]
    signed_in_hits = [marker for marker in _SIGNED_IN_MARKERS if marker in lowered]

    if not lowered.strip():
        return None, "none", "The page had no readable text; it may still be loading."

    if signed_out_hits and not signed_in_hits:
        return (
            False,
            "high",
            f"The page shows sign-in controls ({', '.join(signed_out_hits[:3])}) and no console content.",
        )
    if signed_in_hits and not signed_out_hits:
        return (
            True,
            "high",
            f"The page shows console content ({', '.join(signed_in_hits[:3])}).",
        )
    if signed_in_hits and signed_out_hits:
        # Common on a signed-in page that still renders a "sign out" control, and
        # also on a session that just expired. Not worth guessing.
        return (
            True if len(signed_in_hits) > len(signed_out_hits) else None,
            "low",
            "The page shows both console content and sign-in wording; confirm before acting.",
        )
    return None, "none", "The page did not match anything recognisable as Thunder Compute."


#: Rows in a compute console overwhelmingly read "<name> ... <status>". This
#: captures the common shapes without pretending to understand the layout.
_STATUS_WORDS = (
    "running",
    "stopped",
    "starting",
    "stopping",
    "pending",
    "provisioning",
    "terminated",
    "failed",
    "queued",
    "idle",
)


def _assess_authentication(text: str) -> tuple[bool | None, str, str]:
    result = _assess_authentication_unchecked(text)
    from .proofs_a_control import check_console_authentication
    check_console_authentication(text, result)
    return result


def _extract_instances(text: str) -> list[dict[str, Any]]:
    """Pull candidate instance rows out of visible text.

    Heuristic by design and labelled as such wherever it surfaces. Its job is to
    give the user something concrete to confirm, not to be authoritative.
    """
    instances: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 200:
            continue
        lowered = line.lower()
        status = next((word for word in _STATUS_WORDS if re.search(rf"\b{word}\b", lowered)), None)
        if status is None:
            continue
        gpu = None
        gpu_match = re.search(r"\b(a100|h100|v100|t4|l4|rtx\s?\d{3,4}|\d+\s?x\s?gpu)\b", lowered)
        if gpu_match:
            gpu = gpu_match.group(0)
        instances.append(
            {
                "line": line,
                "status": status,
                "gpu": gpu,
                "source": "visible-text-heuristic",
            }
        )
        if len(instances) >= 25:
            break
    from .proofs_a_control import require
    require(len(instances) <= 25 and all(row["source"] == "visible-text-heuristic"
            and row["line"] in {line.strip() for line in text.splitlines()}
            and re.search(rf"\b{row['status']}\b", row["line"].lower()) for row in instances),
            "control.console-observation", "heuristic instance rows lost visible provenance or status")
    return instances


def read_console(
    target_id: str,
    *,
    port: int = cc.DEFAULT_DEBUG_PORT,
    evidence_dir: str | Path | None = None,
) -> ConsoleReading:
    """Observe the console and report what Neyvia can actually tell from it."""
    observation = cc.observe(target_id, port=port, evidence_dir=evidence_dir)
    text = str(observation.get("text") or "")

    if not _is_console_url(str(observation.get("url") or "")):
        return ConsoleReading(
            authenticated=None,
            confidence="none",
            detail=(
                "This tab is not on Thunder Compute "
                f"({observation.get('url')}). Open the console before continuing."
            ),
            instances=[],
            observation=observation,
        )

    authenticated, confidence, detail = _assess_authentication(text)
    if observation.get("settled") is False:
        confidence = "low"
        detail = f"{detail} The page had not finished loading."

    return ConsoleReading(
        authenticated=authenticated,
        confidence=confidence,
        detail=detail,
        instances=_extract_instances(text) if authenticated else [],
        observation=observation,
    )


# ---------------------------------------------------------------------------
# Acting under approval
# ---------------------------------------------------------------------------


def propose_action(
    target_id: str,
    control_label: str,
    *,
    port: int = cc.DEFAULT_DEBUG_PORT,
) -> dict[str, Any]:
    """Locate a control by its visible label and describe what clicking it would do.

    Proposal and execution are separate calls on purpose: the user approves a
    described action, and the approval is bound to that description.
    """
    matches = cc.find_elements(target_id, control_label, port=port)
    if not matches:
        raise ThunderComputeError(
            f"No control labelled {control_label!r} is visible on this page. "
            "Re-observe the console — the layout may have changed, or the control "
            "may need scrolling into view."
        )

    observation = cc.observe(target_id, port=port, with_screenshot=False)
    chosen = matches[0]
    action = {"kind": "click", "x": chosen["x"], "y": chosen["y"]}
    assessment = policy.assess(
        action,
        label=str(chosen.get("label") or ""),
        page_url=str(observation.get("url") or ""),
        page_text=str(observation.get("text") or ""),
    )

    return {
        "schema": "neyvia.thunder.proposal/1",
        "action": action,
        "control": chosen,
        "alternatives": matches[1:5],
        "assessment": assessment.as_dict(),
        "pageUrl": observation.get("url"),
    }


def execute_proposal(
    target_id: str,
    proposal: dict[str, Any],
    *,
    approval: dict[str, Any] | None = None,
    port: int = cc.DEFAULT_DEBUG_PORT,
    evidence_dir: str | Path | None = None,
    expect: str = "",
) -> dict[str, Any]:
    """Execute a previously described proposal, if it is approved.

    Re-derives the assessment rather than trusting the one embedded in the
    proposal, so a caller cannot downgrade a risk classification by editing the
    payload it sends back.
    """
    control = proposal.get("control") or {}
    action = dict(proposal.get("action") or {})
    if expect:
        action["expect"] = expect

    observation = cc.observe(target_id, port=port, with_screenshot=False)
    assessment = policy.assess(
        action,
        label=str(control.get("label") or ""),
        page_url=str(observation.get("url") or ""),
        page_text=str(observation.get("text") or ""),
    )
    policy.ensure_approved(assessment, approval)

    result = cc.act(target_id, action, port=port, evidence_dir=evidence_dir, settle_seconds=2.5)
    result["assessment"] = assessment.as_dict()
    result["approval"] = (
        {"fingerprint": approval.get("fingerprint"), "grantedBy": approval.get("grantedBy")}
        if approval
        else None
    )
    from .proofs_a_control import require
    require(not (expect and result.get("verdict") == "verified") or result.get("expectationMet") is True,
            "control.chrome-live-action", "expected browser result claimed verified without observed expectation")
    return result


# ---------------------------------------------------------------------------
# Project memory
# ---------------------------------------------------------------------------


def execute_neyvia_proposal(
    browser_service,
    tab_id: str,
    proposal: dict[str, Any],
    *,
    approval: dict[str, Any] | None = None,
    expect: str = "",
) -> dict[str, Any]:
    """Execute an explicit observed-element proposal in Neyvia's native browser.

    The caller supplies an attached BrowserService and an owner-granted tab.
    This route never selects an external browser, grants itself permission,
    translates coordinates, or substitutes a DOM model for native completion.
    """
    from .neyvia_browser import BrowserError, BrowserService, wait_observation
    from .proofs_a_control import require

    if not isinstance(browser_service, BrowserService):
        raise TypeError("A real Neyvia BrowserService is required")
    action = dict(proposal.get("action") or {})
    unknown = set(action) - {"revision", "element", "action", "value", "expect"}
    if unknown or action.get("action") not in {"click", "fill", "select", "scroll"}:
        raise ValueError("Supply an explicit Neyvia observed-element action")
    if not action.get("revision") or "element" not in action:
        raise ValueError("The observed revision and element are required")
    expectation = str(expect or action.get("expect") or "").strip()

    def observe():
        value = browser_service.request("observe", {"tabId": tab_id})
        return wait_observation(browser_service, value) if value.get("actionId") else value

    before = observe()
    if action["revision"] != before["revision"]:
        raise BrowserError("stale_projection", "Refresh the native observation before proposing an action")
    element = next((row for row in before.get("elements", [])
                    if str(row.get("id")) == str(action["element"])), None)
    if (element is None or element.get("secret") or element.get("enabled") is False
            or action["action"] not in element.get("actions", [])):
        raise BrowserError("invalid_target", "The current observed element does not support this action")
    assessed_action = {
        **action,
        "kind": "type" if action["action"] in {"fill", "select"} else action["action"],
        **({"text": str(action.get("value", ""))} if action["action"] in {"fill", "select"} else {}),
    }
    assessment = policy.assess(assessed_action, label=str(element.get("name") or ""),
                               page_url=str(before.get("url") or ""), page_text=str(before.get("text") or ""))
    policy.ensure_approved(assessment, approval)
    dispatched = browser_service.request("action", {"tabId": tab_id,
        **{key: action[key] for key in ("revision", "element", "action", "value") if key in action}})
    completed = (browser_service.request("wait", {"actionId": dispatched["actionId"], "timeoutMs": 30000})
                 if dispatched.get("actionId") else dispatched)
    require(completed.get("status") == "done" and completed.get("ok") is True,
            "control.neyvia-live-action", "native action did not complete; inspect its receipt without replay")
    after = observe()
    changed = before["revision"] != after["revision"]
    haystack = "\n".join(str(after.get(key) or "") for key in ("url", "title", "text")).lower()
    expectation_met = expectation.lower() in haystack if expectation else None
    verified = expectation_met is True if expectation else changed
    def compact(value):
        return {key: str(value.get(key) or "")[:4000] for key in ("url", "title", "text", "revision")}
    result = {"backend": "neyvia-integrated-browser", "tabId": tab_id,
        "status": "done", "verdict": "verified" if verified else "unverified", "readBack": True,
        "changed": changed, "expectationMet": expectation_met,
        "before": compact(before), "after": compact(after),
        "nativeActionId": dispatched.get("actionId"), "assessment": assessment.as_dict(),
        "approval": {"fingerprint": approval.get("fingerprint"), "grantedBy": approval.get("grantedBy")} if approval else None,
        "boundary": "Actual Neyvia native DOM/action/readback; no external browser, provider, account or physical-device claim"}
    require(not (expectation and result["verdict"] == "verified") or result["expectationMet"] is True,
            "control.neyvia-live-action", "expected native page result claimed verified without observed expectation")
    return result


def project_memory_path(root: str | Path) -> Path:
    return Path(root) / ".agent_control" / "thunder_compute" / "project.json"


def load_project_memory(root: str | Path) -> dict[str, Any]:
    """Load what Neyvia remembers about the user's Thunder Compute work.

    Deliberately holds pointers and status only — never credentials, dataset
    contents, or anything that would be sensitive if this file leaked.
    """
    path = project_memory_path(root)
    if not path.exists():
        return {
            "schema": "neyvia.thunder.project/1",
            "known": False,
            "detail": "Neyvia has not recorded a Thunder Compute project yet.",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "schema": "neyvia.thunder.project/1",
            "known": False,
            "detail": f"The stored project context could not be read: {exc}",
        }
    payload["known"] = True
    return payload


_ALLOWED_MEMORY_FIELDS = frozenset(
    {
        "purpose",
        "consoleUrl",
        "instanceLabel",
        "repository",
        "notebook",
        "datasetLocation",
        "latestCheckpoint",
        "latestStatus",
        "lastCompletedAction",
        "nextProposedAction",
        "artifacts",
        "knownFailure",
    }
)


_PROJECT_MEMORY_LOCKS = tuple(threading.RLock() for _ in range(64))


def save_project_memory(root: str | Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into the stored project context.

    Unknown fields are dropped rather than persisted, which keeps this file from
    quietly becoming a place credentials or dataset contents end up.
    """
    from .harness_jobs import _exclusive_job_lock
    path = project_memory_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _PROJECT_MEMORY_LOCKS[hash(str(path.resolve()).casefold()) % len(_PROJECT_MEMORY_LOCKS)]
    with lock, _exclusive_job_lock(path, timeout_seconds=30):
        return _save_project_memory_locked(root, updates)


def _save_project_memory_locked(root: str | Path, updates: dict[str, Any]) -> dict[str, Any]:
    current = load_project_memory(root)
    current.pop("known", None)
    current.pop("detail", None)

    rejected = sorted(set(updates) - _ALLOWED_MEMORY_FIELDS)
    for key, value in updates.items():
        if key in _ALLOWED_MEMORY_FIELDS:
            current[key] = value

    current["schema"] = "neyvia.thunder.project/1"
    current["updatedAt"] = time.time()

    path = project_memory_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    from .durability import atomic_write_text
    atomic_write_text(path, json.dumps(current, indent=2, sort_keys=True))
    from .proofs_a_control import require
    stored = json.loads(path.read_text(encoding="utf-8"))
    require(stored == current and not set(rejected) & stored.keys()
            and all(stored.get(key) == value for key, value in updates.items() if key in _ALLOWED_MEMORY_FIELDS),
            "control.console-memory", "project memory changed accepted fields or persisted unknown input")

    result = dict(current)
    result["known"] = True
    if rejected:
        result["rejectedFields"] = rejected
    return result
