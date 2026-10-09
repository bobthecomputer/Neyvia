"""Catalogue of optional CLIs, for the setup screen a nontechnical user sees.

Detection already exists and works: :func:`grant_agent.runtimes.detect_runtime_statuses`
probes each adapter and returns a :class:`~grant_agent.models.RuntimeInstallStatus`
with the command, version, and update information. This module does not repeat
that work. It adds the two things the setup screen needs and detection does not
provide: the declarative facts about each CLI (who publishes it, where it comes
from, how you sign in, whether sessions resume) and a single honest state per
entry.

The catalogue deliberately contains gaps. Where a fact is not established by the
repository's own adapter data or by a source that can be checked, the field is
``None`` and surfaces as "unverified" rather than as a confident-looking guess.
A setup screen that states a wrong publisher or a wrong download size is worse
than one that admits it does not know, because the user has no way to tell the
difference.

Sizes are never hardcoded here. They are resolved from the package registry at
the moment they are shown, so the number the user approves is the real one.
"""

from __future__ import annotations

import json
import platform
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import RuntimeInstallStatus
from .runtimes import detect_runtime_statuses
from .proofs_a_cli import checked

# --- states shown to the user ---------------------------------------------

STATE_READY = "detected_ready"
STATE_UPDATE_RECOMMENDED = "detected_update_recommended"
STATE_CONNECTION_REQUIRED = "installed_connection_required"
STATE_AVAILABLE = "available_to_install"
STATE_UNSUPPORTED = "unsupported_on_system"
STATE_UNAVAILABLE = "temporarily_unavailable"

#: Human wording for each state. Kept beside the constants so the UI and the
#: backend can never drift into describing the same state differently.
STATE_LABELS = {
    STATE_READY: "Ready to use",
    STATE_UPDATE_RECOMMENDED: "Ready — update recommended",
    STATE_CONNECTION_REQUIRED: "Installed — sign-in required",
    STATE_AVAILABLE: "Available to install",
    STATE_UNSUPPORTED: "Not supported on this system",
    STATE_UNAVAILABLE: "Temporarily unavailable",
}

#: Confidence markers for declared facts.
VERIFIED = "verified"
UNVERIFIED = "unverified"


@dataclass(frozen=True)
class CatalogEntry:
    """Declarative facts about one optional CLI.

    ``None`` means "not established". It is rendered as unverified and never
    filled in with a plausible-looking default.
    """

    runtime_id: str
    useful_for: str
    publisher: str | None = None
    official_source: str | None = None
    package_kind: str | None = None  # "npm" | "installer" | "wsl" | None
    package_name: str | None = None
    command_name: str | None = None
    auth_method: str | None = None
    resume_support: str = UNVERIFIED  # "supported" | "unsupported" | UNVERIFIED
    transcript_streaming: str = UNVERIFIED
    platforms: tuple[str, ...] = ("Windows", "Darwin", "Linux")
    notes: str = ""


#: Facts asserted only where they are established. Several entries deliberately
#: leave publisher and package identity unset: the repository's adapters know how
#: to *detect* those CLIs without recording who ships them, and inventing an npm
#: package name from a product name is exactly the guess this catalogue refuses
#: to make. Those fields fill in as each adapter's install path is confirmed.
CATALOG: dict[str, CatalogEntry] = {
    "codex": CatalogEntry(
        runtime_id="codex",
        useful_for="OpenAI's coding agent, using your ChatGPT plan or API account.",
        publisher="OpenAI",
        official_source="https://developers.openai.com/codex/cli/",
        package_kind="npm",
        package_name="@openai/codex",
        command_name="codex",
        auth_method="oauth",
        resume_support="supported",
        transcript_streaming="supported",
    ),
    "claude-code": CatalogEntry(
        runtime_id="claude-code",
        useful_for="Writing and changing code across a whole project, with tool use and file edits.",
        publisher="Anthropic",
        official_source="https://www.npmjs.com/package/@anthropic-ai/claude-code",
        package_kind="npm",
        package_name="@anthropic-ai/claude-code",
        command_name="claude",
        auth_method="oauth",
        resume_support="supported",
        transcript_streaming="supported",
    ),
    "opencode": CatalogEntry(
        runtime_id="opencode",
        useful_for="Open-source coding agent that runs locally against your chosen model provider.",
        package_kind="npm",
        package_name="opencode-ai",
        command_name="opencode",
        auth_method="api_key",
        # Established from the adapter's own declared capability, not assumed.
        transcript_streaming="supported",
    ),
    "openclaw": CatalogEntry(
        runtime_id="openclaw",
        useful_for="Routing work and approvals across chat channels, with command-backed jobs.",
        auth_method="api_key",
    ),
    "hermes": CatalogEntry(
        runtime_id="hermes",
        useful_for="Long-running scheduled agents with persistent skills and memory.",
        notes="Detected through WSL on Windows.",
        platforms=("Linux", "Darwin", "Windows"),
    ),
    "cursor": CatalogEntry(
        runtime_id="cursor",
        useful_for="Cursor's editor-integrated coding agent.",
        official_source="https://cursor.com",
    ),
    "kimi-code": CatalogEntry(
        runtime_id="kimi-code",
        useful_for="Moonshot's coding CLI.",
        publisher="Moonshot AI",
        official_source="https://www.kimi.com/code/docs/en/kimi-code-cli/guides/getting-started.html",
        package_kind="npm",
        package_name="@moonshot-ai/kimi-code",
        command_name="kimi",
        auth_method="oauth",
        resume_support="supported",
        transcript_streaming="supported",
    ),
    "grok-build": CatalogEntry(
        runtime_id="grok-build",
        useful_for="xAI's coding CLI.",
        official_source="https://x.ai",
    ),
}


# --- size resolution -------------------------------------------------------


@checked('a-cli.catalog.size')
def resolve_package_size(entry: CatalogEntry, *, timeout: float = 8.0) -> dict[str, Any]:
    """Resolve a CLI's real download size, or explain why it is not known yet.

    Queries the npm registry for npm-backed entries. Never returns an invented
    number: an unresolved size is reported as ``None`` with a reason, so the UI
    can say "size shown before download" instead of displaying a fiction.
    """
    if entry.package_kind != "npm" or not entry.package_name:
        return {
            "bytes": None,
            "source": None,
            "detail": "Size is resolved from the publisher when you choose to install.",
        }

    url = f"https://registry.npmjs.org/{entry.package_name}/latest"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return {
            "bytes": None,
            "source": "npm",
            "detail": f"Could not reach the npm registry to check the size ({exc}).",
        }

    dist = payload.get("dist") or {}
    unpacked = dist.get("unpackedSize")
    download = dist.get("size")

    missing = []
    if not isinstance(unpacked, int):
        missing.append("installed size")
    if not isinstance(download, int):
        missing.append("download size")

    return {
        "bytes": int(unpacked) if isinstance(unpacked, int) else None,
        "downloadBytes": int(download) if isinstance(download, int) else None,
        "version": payload.get("version"),
        "source": "npm",
        # Naming exactly which figure is unavailable keeps a partially resolved
        # size from reading as a fully resolved one.
        "detail": (
            f"The registry did not report the {' or '.join(missing)}." if missing else ""
        ),
    }


# --- classification --------------------------------------------------------


def _platform_name() -> str:
    return platform.system() or "Unknown"


@checked('a-cli.catalog.classify')
def classify(status: RuntimeInstallStatus, entry: CatalogEntry | None) -> tuple[str, str]:
    """Return ``(state, reason)`` for one CLI.

    Detection is the source of truth for presence; the catalogue only supplies
    context. An entry we cannot classify confidently becomes
    ``temporarily_unavailable`` rather than silently defaulting to installable.
    """
    current_platform = _platform_name()
    if entry is not None and current_platform not in entry.platforms:
        return (
            STATE_UNSUPPORTED,
            f"{status.label} is not supported on {current_platform}.",
        )

    if not status.detected:
        if status.install_hint:
            return STATE_AVAILABLE, status.install_hint
        # Detection says absent but nothing knows how to install it. Presenting
        # an Install button here would be a button that cannot work.
        return (
            STATE_UNAVAILABLE,
            f"{status.label} was not detected and Neyvia has no verified install route for it.",
        )

    # Present. Issues reported by the adapter are the authority on whether it is
    # actually usable — a CLI on disk that cannot authenticate is not "ready".
    auth_issues = [
        issue
        for issue in status.issues
        if any(word in issue.lower() for word in ("auth", "login", "sign in", "token", "api key", "credential"))
    ]
    if auth_issues:
        return STATE_CONNECTION_REQUIRED, auth_issues[0]

    if status.update_available:
        latest = status.latest_version or "a newer version"
        return (
            STATE_UPDATE_RECOMMENDED,
            f"Installed {status.version or 'version unknown'}; {latest} is available.",
        )

    return STATE_READY, status.doctor_summary or f"{status.label} is ready."


@checked('a-cli.catalog.fact')
def _fact(value: object, confidence_when_present: str = VERIFIED) -> dict[str, Any]:
    """Wrap a declared fact with its confidence so the UI can render honestly."""
    if value in (None, "", UNVERIFIED):
        return {"value": None, "confidence": UNVERIFIED}
    return {"value": value, "confidence": confidence_when_present}


@checked('a-cli.catalog.selection')
def build_catalog(
    workspace_root: str | Path,
    *,
    force: bool = False,
    with_sizes: bool = False,
    size_runtime_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build the CLI selection screen's data.

    ``with_sizes`` performs network lookups and is off by default: opening a
    setup screen should not reach out to package registries until the user shows
    interest in a specific CLI. ``size_runtime_ids`` narrows that lookup to the
    runtime the user selected instead of contacting every package registry.
    """
    statuses = detect_runtime_statuses(Path(workspace_root), force=force)
    entries: list[dict[str, Any]] = []

    for status in statuses:
        entry = CATALOG.get(status.runtime_id)
        state, reason = classify(status, entry)
        managed = _managed_install_state(entry, status.runtime_id)
        row: dict[str, Any] = {
            "runtimeId": status.runtime_id,
            "label": status.label,
            "state": state,
            "stateLabel": STATE_LABELS[state],
            "reason": reason,
            "detected": status.detected,
            "version": status.version,
            "latestVersion": status.latest_version,
            "command": status.command,
            "issues": list(status.issues),
            "usefulFor": entry.useful_for if entry else "",
            "publisher": _fact(entry.publisher if entry else None),
            "officialSource": _fact(
                (entry.official_source if entry else None) or status.update_source_url
            ),
            "authMethod": _fact(entry.auth_method if entry else None),
            "resumeSupport": (entry.resume_support if entry else UNVERIFIED),
            "transcriptStreaming": (entry.transcript_streaming if entry else UNVERIFIED),
            "installHint": status.install_hint,
            "notes": entry.notes if entry else "",
            # Every entry states which actions are actually possible for it, so
            # the UI never renders a control that cannot do anything.
            "actions": _actions_for(
                state,
                managed_install=managed["installAvailable"],
                managed_owned=managed["managed"],
            ),
            "managedInstall": managed,
        }
        should_resolve_size = (
            with_sizes
            and entry is not None
            and (
                size_runtime_ids is None
                or status.runtime_id in size_runtime_ids
            )
        )
        if should_resolve_size:
            row["size"] = resolve_package_size(entry)
        entries.append(row)

    return {
        "schema": "neyvia.cli_catalog/1",
        "platform": _platform_name(),
        "entries": entries,
        "summary": {
            "ready": sum(1 for row in entries if row["state"] == STATE_READY),
            "installable": sum(1 for row in entries if row["state"] == STATE_AVAILABLE),
            "needsConnection": sum(
                1 for row in entries if row["state"] == STATE_CONNECTION_REQUIRED
            ),
        },
        # Stated explicitly: nothing here is required to use Neyvia.
        "optional": True,
        "continueWithoutAny": True,
    }


def _managed_install_state(
    entry: CatalogEntry | None,
    runtime_id: str,
) -> dict[str, Any]:
    from .cli_installer import installer_support

    return installer_support(entry, runtime_id=runtime_id)


@checked('a-cli.catalog.actions')
def _actions_for(
    state: str,
    *,
    managed_install: bool = True,
    managed_owned: bool = True,
) -> list[str]:
    if state == STATE_READY:
        return ["repair", "uninstall"] if managed_owned else []
    if state == STATE_UPDATE_RECOMMENDED:
        return ["update", "repair", "uninstall"] if managed_owned else []
    if state == STATE_CONNECTION_REQUIRED:
        return (
            ["connect", "repair", "uninstall"]
            if managed_owned
            else ["connect"]
        )
    if state == STATE_AVAILABLE:
        return ["install", "skip"] if managed_install else ["skip"]
    return ["skip"]


# --- recommendations -------------------------------------------------------

#: Goal -> runtimes that genuinely serve it. Kept as data so a recommendation can
#: always be explained and changed, rather than being an unexplainable ranking.
GOAL_AFFINITY: dict[str, tuple[str, ...]] = {
    "writing": (),
    "software": ("claude-code", "opencode", "cursor"),
    "automation": ("hermes", "openclaw"),
    "research": ("claude-code",),
    "creative": (),
}


@checked('a-cli.catalog.recommend')
def recommend(catalog: dict[str, Any], goals: list[str], *, limit: int = 2) -> list[dict[str, Any]]:
    """Recommend at most ``limit`` CLIs for the user's stated goals.

    Only ever recommends something installable or already present, and always
    returns the reason, so a recommendation can be argued with rather than
    merely obeyed.
    """
    by_id = {row["runtimeId"]: row for row in catalog.get("entries", [])}
    seen: set[str] = set()
    recommendations: list[dict[str, Any]] = []

    for goal in goals:
        for runtime_id in GOAL_AFFINITY.get(goal, ()):
            if runtime_id in seen or runtime_id not in by_id:
                continue
            row = by_id[runtime_id]
            if row["state"] in (STATE_UNSUPPORTED, STATE_UNAVAILABLE):
                continue
            seen.add(runtime_id)
            recommendations.append(
                {
                    "runtimeId": runtime_id,
                    "label": row["label"],
                    "state": row["state"],
                    "because": f"You chose '{goal}', and {row['label']} is used for: {row['usefulFor']}",
                }
            )
            if len(recommendations) >= limit:
                return recommendations
    return recommendations
