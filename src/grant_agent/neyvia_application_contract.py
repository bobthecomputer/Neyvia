"""N-E-Y-V-I-A application contract — two developer propositions, one core.

``sdk-external``
    An independent product that uses Neyvia services through the SDK and keeps
    its own interface and brand. It never renders the Neyvia shell and is *not*
    automatically a marketplace application.

``ecosystem-native``
    An application built through Neyvia that uses Neyvia surfaces, sessions,
    context, files, permissions, runtime services, artifacts and evidence, and
    that can be packaged and proposed to the Marketplace.

Both share identity, capability descriptions, events, artifacts, permissions
and receipts. Only ecosystem applications may declare *where* and *how* they
embed, and an application that is not active provides no capabilities at all —
activation must connect real declared capabilities, not paint a tile.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse

from .github_release_source import download_asset
from .subprocess_utils import hidden_windows_subprocess_kwargs

APPLICATION_CONTRACT_SCHEMA = "neyvia.application.contract.v1"
APPLICATION_REGISTRY_SCHEMA = "neyvia.application.registry.v1"

APPLICATION_KINDS = ("sdk-external", "ecosystem-native")

#: Services usable from outside the Neyvia frontend (the SDK surface) versus
#: services that only exist because the shell is rendering the application.
SERVICE_CONTRACTS: dict[str, bool] = {
    "provider-routing": True,
    "agents": True,
    "memory": True,
    "tools": True,
    "permissions": True,
    "evidence": True,
    "artifacts": True,
    "orchestration": True,
    "runtime-supervision": True,
    "sessions": True,
    "events": True,
    "shell-surfaces": False,
    "embedded-workspace": False,
}

EMBED_ZONES = (
    "chat",
    "notebook",
    "lab",
    "orchestration",
    "library",
    "marketplace",
    "office",
    "personal-mesh",
    "image-playground",
)

EMBED_PRESENTATIONS = (
    "inline-card",
    "dock-right",
    "dock-left",
    "floating-center",
    "fullscreen",
)

_SDK_REGISTRY_RELATIVE = Path(".agent_control") / "neyvia" / "sdk_applications.json"
_BUNDLED_APP_REGISTRY_RELATIVE = (
    Path(".agent_control") / "neyvia" / "bundled_applications.json"
)
_EXTERNAL_APP_ROOT_RELATIVE = (
    Path(".agent_control") / "neyvia" / "external_applications"
)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

# These are product workspaces that already ship in the Neyvia bundle. Installing
# one records an explicit local activation; it does not download code or pretend
# an external connector exists. The launch target always points at a real surface
# or panel that is already hosted by the shell.
def _bundled_workspace(
    application_id: str,
    name: str,
    summary: str,
    *,
    target: str,
    launch_kind: str,
    capability_id: str,
    capability_label: str,
    category: str,
    icon_tool_id: str,
    surfaces: tuple[str, ...] = ("lab", "chat"),
    permissions: tuple[str, ...] = ("workspace.read", "artifacts.write"),
) -> dict[str, Any]:
    """Declare an already-hosted workspace without overstating external runtime readiness."""

    return {
        "applicationId": application_id,
        "name": name,
        "summary": summary,
        "version": "1.0.0",
        "services": ["tools", "artifacts", "evidence", "shell-surfaces", "embedded-workspace"],
        "provides": [{"capabilityId": capability_id, "label": capability_label}],
        "permissions": list(permissions),
        "surfaces": list(surfaces),
        "presentations": ["fullscreen", "dock-right"],
        "launch": {"kind": launch_kind, "target": target},
        "iconToolId": icon_tool_id,
        "category": category,
    }


BUNDLED_APPLICATIONS: tuple[dict[str, Any], ...] = (
    {
        "applicationId": "neyvia.browser",
        "name": "Browser",
        "summary": "Inspect real pages, interact with previews, and attach visual proof.",
        "version": "1.0.0",
        "services": ["tools", "evidence", "artifacts", "shell-surfaces", "embedded-workspace"],
        "provides": [
            {"capabilityId": "device.browser-session", "label": "Browser session"},
            {"capabilityId": "ui.observe", "label": "Observe page"},
            {"capabilityId": "ui.do", "label": "Interact with page"},
        ],
        "permissions": ["browser.navigate", "browser.interact", "evidence.capture"],
        "surfaces": ["lab", "orchestration"],
        "presentations": ["fullscreen"],
        "launch": {"kind": "surface", "target": "browser"},
        "iconToolId": "device.browser-session",
        "category": "Workspaces",
    },
    {
        "applicationId": "neyvia.images",
        "name": "Image Playground",
        "summary": "Generate, compare, reopen, and export image artifacts with provider receipts.",
        "version": "1.0.0",
        "services": ["provider-routing", "tools", "artifacts", "evidence", "shell-surfaces"],
        "provides": [
            {"capabilityId": "media.image-generation", "label": "Image generation"},
            {"capabilityId": "media.photo-editing", "label": "Image editing"},
        ],
        "permissions": ["artifacts.write", "providers.invoke"],
        "surfaces": ["image-playground", "chat"],
        "presentations": ["fullscreen", "dock-right"],
        "launch": {"kind": "surface", "target": "images"},
        "iconToolId": "media.image-generation",
        "category": "Creative",
    },
    {
        "applicationId": "neyvia.workbench",
        "name": "Workbench",
        "summary": "Review files, terminal output, diffs, runtime activity, and proof in one workspace.",
        "version": "1.0.0",
        "services": ["tools", "artifacts", "evidence", "runtime-supervision", "shell-surfaces"],
        "provides": [
            {"capabilityId": "software.application-engineering", "label": "Application engineering"},
            {"capabilityId": "tool.git", "label": "Git"},
        ],
        "permissions": ["workspace.read", "workspace.write", "runtime.execute"],
        "surfaces": ["lab", "orchestration"],
        "presentations": ["fullscreen"],
        "launch": {"kind": "surface", "target": "workbench"},
        "iconToolId": "software.application-engineering",
        "category": "Development",
    },
    {
        "applicationId": "neyvia.builder",
        "name": "Builder",
        "summary": "Compose application changes and review the resulting live program and receipts.",
        "version": "1.0.0",
        "services": ["agents", "tools", "artifacts", "evidence", "shell-surfaces"],
        "provides": [
            {"capabilityId": "software.delivery-pipeline", "label": "Delivery pipeline"},
        ],
        "permissions": ["workspace.read", "workspace.write", "runtime.execute"],
        "surfaces": ["orchestration", "lab"],
        "presentations": ["fullscreen"],
        "launch": {"kind": "surface", "target": "builder"},
        "iconToolId": "software.delivery-pipeline",
        "category": "Development",
    },
    {
        "applicationId": "neyvia.skills",
        "name": "Skills",
        "summary": "Browse installed skills and attach a real workflow to a conversation or mission.",
        "version": "1.0.0",
        "services": ["tools", "agents", "orchestration", "shell-surfaces"],
        "provides": [
            {"capabilityId": "capability.search", "label": "Capability search"},
            {"capabilityId": "capability.describe", "label": "Capability details"},
        ],
        "permissions": ["skills.read", "missions.attach-skill"],
        "surfaces": ["chat", "orchestration"],
        "presentations": ["fullscreen", "dock-right"],
        "launch": {"kind": "surface", "target": "skills"},
        "iconToolId": "capability.search",
        "category": "Automation",
    },
    {
        "applicationId": "neyvia.office",
        "name": "Office Suite",
        "summary": "Open document, spreadsheet, presentation, and PDF work through verified adapters.",
        "version": "1.0.0",
        "services": ["tools", "artifacts", "evidence", "embedded-workspace"],
        "provides": [
            {"capabilityId": "office.report-authoring", "label": "Document authoring"},
            {"capabilityId": "office.spreadsheet-edit", "label": "Spreadsheet editing"},
            {"capabilityId": "office.presentation-authoring", "label": "Presentation authoring"},
            {"capabilityId": "document.pdf-analysis", "label": "PDF analysis"},
        ],
        "permissions": ["workspace.read", "workspace.write", "artifacts.write"],
        "surfaces": ["office", "library", "chat"],
        "presentations": ["floating-center", "fullscreen"],
        "launch": {"kind": "panel", "target": "office-suite"},
        "iconToolId": "office.report-authoring",
        "category": "Productivity",
    },
    {
        "applicationId": "neyvia.app.pdf-studio",
        "name": "Neyvia PDF Studio",
        "summary": (
            "Open, inspect, search, annotate, fill, and export PDFs through "
            "one MCP App shared by the user and the agent."
        ),
        "version": "0.1.1",
        "services": ["tools", "artifacts", "evidence", "embedded-workspace"],
        "provides": [
            {"capabilityId": "document.pdf-analysis", "label": "PDF analysis"},
            {"capabilityId": "document.pdf-annotation", "label": "PDF annotation"},
        ],
        "permissions": [
            "workspace.read",
            "workspace.write-on-explicit-save",
            "network.read-allowlisted-pdf-sources",
        ],
        "surfaces": ["office", "library", "chat"],
        "presentations": ["fullscreen", "floating-center"],
        "launch": {
            "kind": "mcp-app",
            "target": "ui://pdf-viewer/mcp-app.html",
        },
        "iconToolId": "document.pdf-analysis",
        "category": "Productivity",
        "installSource": "github-release",
        "publisherId": "app.neyvia.github.bobthecomputer",
        "sourceUrl": "https://github.com/bobthecomputer/neyvia-app-pdf",
        "integrity": (
            "Downloads the pinned v0.1.1 GitHub release and verifies SHA-256 "
            "before installing with package scripts disabled."
        ),
        "distribution": {
            "assetName": "neyvia-app-pdf-0.1.1.tgz",
            "assetUrl": (
                "https://github.com/bobthecomputer/neyvia-app-pdf/releases/"
                "download/v0.1.1/neyvia-app-pdf-0.1.1.tgz"
            ),
            "assetSha256": (
                "1be14f569c2713faf168ef4cd6aba083"
                "640ec4a6a11077b6dd441244a76e73f0"
            ),
            "assetBytes": 3262,
            "npmPackage": "neyvia-app-pdf",
        },
    },
    {
        "applicationId": "neyvia.files",
        "name": "Files",
        "summary": "Choose local or NAS folders and keep the active workspace scope visible.",
        "version": "1.0.0",
        "services": ["artifacts", "permissions", "shell-surfaces"],
        "provides": [
            {"capabilityId": "artifact.register", "label": "Register artifact"},
            {"capabilityId": "artifact.lineage", "label": "Artifact lineage"},
        ],
        "permissions": ["workspace.read", "workspace.select"],
        "surfaces": ["library", "chat", "orchestration"],
        "presentations": ["floating-center"],
        "launch": {"kind": "panel", "target": "folders"},
        "iconToolId": "artifact.register",
        "category": "Productivity",
    },
    {
        "applicationId": "neyvia.session-tools",
        "name": "Session Tools",
        "summary": "Browse the complete tool catalog with real readiness and per-tool identities.",
        "version": "1.0.0",
        "services": ["tools", "permissions", "shell-surfaces"],
        "provides": [
            {"capabilityId": "tool.suite.search", "label": "Search tool suite"},
            {"capabilityId": "tool.suite.describe", "label": "Describe managed tool"},
        ],
        "permissions": ["tools.discover", "tools.request"],
        "surfaces": ["chat", "lab", "orchestration"],
        "presentations": ["dock-right", "fullscreen"],
        "launch": {"kind": "panel", "target": "tools"},
        "iconToolId": "tool.suite.search",
        "category": "Automation",
    },
    {
        "applicationId": "neyvia.personal-mesh",
        "name": "Personal Mesh",
        "summary": "Inspect connected personal devices and private workspace routes without inventing links.",
        "version": "1.0.0",
        "services": ["sessions", "events", "permissions", "shell-surfaces"],
        "provides": [
            {"capabilityId": "computer_use.verify", "label": "Computer-use verification"},
        ],
        "permissions": ["devices.read", "sessions.read"],
        "surfaces": ["personal-mesh", "lab"],
        "presentations": ["fullscreen", "floating-center"],
        "launch": {"kind": "panel", "target": "personal-mesh"},
        "iconToolId": "computer_use.verify",
        "category": "Connections",
    },
    _bundled_workspace(
        "neyvia.research",
        "Research Desk",
        "Collect sources, preserve citations, and hand evidence to the active agent session.",
        target="research",
        launch_kind="panel",
        capability_id="research.web",
        capability_label="Evidence research",
        category="Research",
        icon_tool_id="research.web",
        surfaces=("chat", "library"),
        permissions=("network.read", "artifacts.write"),
    ),
    _bundled_workspace(
        "neyvia.translate",
        "Translate",
        "Translate selected text and artifacts while retaining the source and output lineage.",
        target="translate",
        launch_kind="panel",
        capability_id="language.translate",
        capability_label="Translation",
        category="Writing",
        icon_tool_id="language.translate",
        surfaces=("chat", "office"),
    ),
    _bundled_workspace(
        "neyvia.grammar",
        "Grammar",
        "Review writing and return suggested edits as a reversible artifact.",
        target="grammar",
        launch_kind="panel",
        capability_id="language.grammar",
        capability_label="Grammar review",
        category="Writing",
        icon_tool_id="language.grammar",
        surfaces=("chat", "office"),
    ),
    _bundled_workspace(
        "neyvia.charts",
        "Chart Studio",
        "Turn session data into inspectable charts and reusable visual artifacts.",
        target="chart",
        launch_kind="panel",
        capability_id="data.visualization",
        capability_label="Data visualization",
        category="Data",
        icon_tool_id="data.visualization",
    ),
    _bundled_workspace(
        "neyvia.data-studio",
        "Data Studio",
        "Inspect tabular data and coordinate analysis with the active session.",
        target="data",
        launch_kind="panel",
        capability_id="data.analysis",
        capability_label="Data analysis",
        category="Data",
        icon_tool_id="data.analysis",
    ),
    _bundled_workspace(
        "neyvia.web-capture",
        "Web Capture",
        "Capture a page into a reviewable artifact with origin and receipt metadata.",
        target="web-capture",
        launch_kind="panel",
        capability_id="web.capture",
        capability_label="Web capture",
        category="Capture",
        icon_tool_id="web.capture",
        permissions=("network.read", "evidence.capture", "artifacts.write"),
    ),
    _bundled_workspace(
        "neyvia.sources",
        "Sources",
        "Inspect the evidence and source lineage attached to the current mission.",
        target="sources",
        launch_kind="panel",
        capability_id="artifact.lineage",
        capability_label="Source lineage",
        category="Research",
        icon_tool_id="artifact.lineage",
        permissions=("workspace.read", "evidence.read"),
    ),
    _bundled_workspace(
        "neyvia.terminal",
        "Terminal",
        "Run supervised workspace commands and keep their output attached to the mission.",
        target="terminal",
        launch_kind="panel",
        capability_id="runtime.shell",
        capability_label="Supervised terminal",
        category="Development",
        icon_tool_id="runtime.shell",
        permissions=("workspace.read", "runtime.execute"),
    ),
    _bundled_workspace(
        "neyvia.managed-cli",
        "CLI Workbench",
        "Attach compatible coding CLIs to shared Neyvia context, approvals, and receipts.",
        target="managed-cli",
        launch_kind="panel",
        capability_id="runtime.managed-cli",
        capability_label="Managed coding CLI",
        category="Development",
        icon_tool_id="runtime.managed-cli",
        surfaces=("chat", "orchestration"),
        permissions=("workspace.read", "runtime.execute", "providers.invoke"),
    ),
    _bundled_workspace(
        "neyvia.workflows",
        "Workflow Studio",
        "Compose reusable workflows from real skills, tools, approvals, and artifacts.",
        target="workflows",
        launch_kind="surface",
        capability_id="workflow.compose",
        capability_label="Workflow composition",
        category="Automation",
        icon_tool_id="workflow.compose",
        surfaces=("orchestration", "lab"),
    ),
    _bundled_workspace(
        "neyvia.notebook",
        "Notebook",
        "Keep research, experiments, code, and generated artifacts together in one session.",
        target="notebook",
        launch_kind="surface",
        capability_id="notebook.session",
        capability_label="Session notebook",
        category="Research",
        icon_tool_id="notebook.session",
    ),
    _bundled_workspace(
        "neyvia.engineering-lab",
        "Engineering Lab",
        "Open the software, device, hardware, security, and experimental capability workspaces.",
        target="lab",
        launch_kind="surface",
        capability_id="engineering.lab",
        capability_label="Engineering lab",
        category="Engineering",
        icon_tool_id="engineering.lab",
        surfaces=("lab", "orchestration"),
    ),
    _bundled_workspace(
        "neyvia.app-factory",
        "App Factory",
        (
            "Turn a plain-language brief into a working local app, inspect every "
            "pipeline stage, preview it immediately, and compile a native Tauri desktop app."
        ),
        target="app-factory",
        launch_kind="surface",
        capability_id="software.local-app-factory",
        capability_label="Local and native app factory",
        category="Development",
        icon_tool_id="software.application-engineering",
        surfaces=("lab", "orchestration", "marketplace"),
        permissions=(
            "workspace.read",
            "workspace.write",
            "runtime.execute",
            "artifacts.write",
        ),
    ),
    _bundled_workspace(
        "neyvia.ios-studio",
        "iOS Studio",
        "Create and preview cross-platform iOS projects on Windows, then hand native build and simulator proof to an authorized Mac/Xcode worker.",
        target="ios-studio",
        launch_kind="surface",
        capability_id="software.ios-build",
        capability_label="iOS project and remote build",
        category="Development",
        icon_tool_id="device.apple-remote-test",
        surfaces=("lab", "orchestration"),
        permissions=("workspace.read", "workspace.write", "runtime.execute", "remote-builder.request"),
    ),
    _bundled_workspace(
        "neyvia.harness-manager",
        "Harness Manager",
        "Connect provider identities once, choose models, and inspect the readiness of every supported coding harness.",
        target="harnesses",
        launch_kind="surface",
        capability_id="runtime.harness-manager",
        capability_label="Harness management",
        category="Automation",
        icon_tool_id="runtime.harness-manager",
        surfaces=("orchestration", "chat"),
        permissions=("providers.read", "providers.authenticate", "runtime.configure"),
    ),
    {
        **_bundled_workspace(
            "neyvia.app.lumaforge",
            "LumaForge",
            (
                "Edit images non-destructively, generate through the installed image skill, "
                "inspect the provider receipt, and export the visible canvas as PNG."
            ),
            target="lumaforge",
            launch_kind="surface",
            capability_id="creative.image-studio",
            capability_label="Image editing studio",
            category="Creative",
            icon_tool_id="media.photo-editing",
            surfaces=("image-playground", "lab", "chat"),
            permissions=("workspace.read", "artifacts.write", "providers.invoke"),
        ),
        "logoUrl": "/neyvia-apps/lumaforge.png?v=20260728",
    },
    {
        **_bundled_workspace(
            "neyvia.app.frameweave",
            "Frameweave",
            (
                "Inspect local footage, define exact in and out points, capture a real frame, "
                "and export a portable edit decision without uploading the source video."
            ),
            target="frameweave",
            launch_kind="surface",
            capability_id="creative.video-studio",
            capability_label="Video edit decision studio",
            category="Creative",
            icon_tool_id="media.video-editing",
            surfaces=("lab", "chat"),
            permissions=("workspace.read", "artifacts.write"),
        ),
        "logoUrl": "/neyvia-apps/frameweave.png?v=20260728",
    },
    {
        **_bundled_workspace(
            "neyvia.app.citecraft",
            "Citecraft",
            (
                "Build a durable source ledger and claim matrix, preserve source identifiers, "
                "and export a readable Markdown research packet."
            ),
            target="citecraft",
            launch_kind="surface",
            capability_id="research.claim-matrix",
            capability_label="Source and claim matrix",
            category="Research",
            icon_tool_id="research.web",
            surfaces=("library", "notebook", "chat"),
            permissions=("workspace.read", "artifacts.write", "network.read"),
        ),
        "logoUrl": "/neyvia-apps/citecraft.png?v=20260728",
    },
    {
        **_bundled_workspace(
            "neyvia.app.aegis-range",
            "Aegis Range",
            (
                "Gate security work on explicit authorization and scope, record evidence and "
                "remediation, and export a defensible assessment report."
            ),
            target="aegis-range",
            launch_kind="surface",
            capability_id="security.authorized-assessment",
            capability_label="Authorized security assessment",
            category="Cybersecurity",
            icon_tool_id="security.assessment",
            surfaces=("lab", "orchestration", "chat"),
            permissions=("workspace.read", "artifacts.write", "security.assessment"),
        ),
        "logoUrl": "/neyvia-apps/aegis-range.png?v=20260728",
    },
    {
        **_bundled_workspace(
            "neyvia.app.cueledger",
            "CueLedger",
            (
                "Review local audio without uploading the source, mark an exact playback "
                "range, capture timestamped notes, and export a portable cue sheet."
            ),
            target="cueledger",
            launch_kind="surface",
            capability_id="creative.audio-review",
            capability_label="Local audio review studio",
            category="Creative",
            icon_tool_id="media.audio-transcription",
            surfaces=("lab", "notebook", "chat"),
            permissions=("workspace.read", "artifacts.write"),
        ),
        "logoUrl": "/neyvia-apps/cueledger.png?v=20260728",
    },
    {
        "applicationId": "neyvia.app.signal-briefs",
        "name": "Signal Briefs",
        "summary": (
            "Turn a followed-source graph and live alternative API captures into "
            "a model-authored, independently reviewed evidence brief."
        ),
        "version": "0.1.0",
        "services": [
            "provider-routing",
            "agents",
            "tools",
            "permissions",
            "artifacts",
            "evidence",
            "orchestration",
            "runtime-supervision",
            "sessions",
            "events",
            "shell-surfaces",
            "embedded-workspace",
        ],
        "provides": [
            {"capabilityId": "intelligence.source-graph", "label": "Source graph collection"},
            {"capabilityId": "intelligence.evidence-brief", "label": "Evidence briefing"},
            {"capabilityId": "artifact.progressive-preview", "label": "Progressive build preview"},
        ],
        "permissions": [
            "network.read:api.fxtwitter.com",
            "network.read:api.folo.is",
            "providers.invoke:codex",
            "providers.invoke:ollama",
            "artifacts.write",
            "approval.request",
        ],
        "surfaces": ["orchestration", "library", "chat"],
        "presentations": ["fullscreen", "dock-right"],
        "entryPointUrl": "http://127.0.0.1:3025/",
        "launch": {"kind": "embedded-web", "target": "http://127.0.0.1:3025/"},
        "iconToolId": "intelligence.briefing",
        "category": "Intelligence",
        "installSource": "github-source",
        "publisherId": "app.neyvia.github.bobthecomputer",
        "sourceUrl": "https://github.com/bobthecomputer/neyvia-app-signal-briefs",
        "integrity": (
            "Pinned to source commit f4011b8f4829f33fa17ce39e3a3e8abf3ceceb8b; "
            "the local runtime must pass its health probe and evidence gates before approval."
        ),
    },
    {
        "applicationId": "neyvia.app.solentir",
        "name": "Solentir",
        "summary": (
            "Create durable intelligence programs and supervise Signal Briefs "
            "evidence runs from collection through internal approval."
        ),
        "version": "0.1.0",
        "services": [
            "applications",
            "provider-routing",
            "agents",
            "tools",
            "permissions",
            "artifacts",
            "evidence",
            "orchestration",
            "runtime-supervision",
            "sessions",
            "events",
            "shell-surfaces",
            "embedded-workspace",
        ],
        "provides": [
            {"capabilityId": "intelligence.programs", "label": "Intelligence programs"},
            {
                "capabilityId": "intelligence.evidence-supervision",
                "label": "Evidence run supervision",
            },
        ],
        "permissions": [
            "applications.invoke:neyvia.app.signal-briefs",
            "artifacts.read",
            "approval.request",
        ],
        "surfaces": ["orchestration", "library", "chat"],
        "presentations": ["fullscreen", "dock-right"],
        "entryPointUrl": "http://127.0.0.1:3035/",
        "launch": {"kind": "embedded-web", "target": "http://127.0.0.1:3035/"},
        "iconToolId": "intelligence.programs",
        "category": "Intelligence",
        "installSource": "github-source",
        "publisherId": "app.neyvia.github.bobthecomputer",
        "sourceUrl": "https://github.com/bobthecomputer/neyvia-app-solentir",
        "integrity": (
            "Pinned to source commit a9dea968ca85446ef9b0613db8482b8821d5ea36; "
            "the native runtime delegates evidence collection to the separately verified "
            "Signal Briefs app and keeps approval internal."
        ),
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: object, fallback: str = "") -> str:
    out = str(value or "").strip()
    return out or fallback


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _safe_entry_point_url(value: object) -> str | None:
    """Accept only browser-loadable hosted endpoints, never local file paths."""

    url = _text(value)
    if not url:
        return None
    if url.startswith("/") and not url.startswith("//"):
        return url
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.netloc:
        return url
    if (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        and parsed.netloc
    ):
        return url
    return None


def normalize_application_kind(value: object) -> str:
    item = _text(value)
    return item if item in APPLICATION_KINDS else "sdk-external"


def normalize_application_manifest(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a manifest by refusal, never by silent grant."""

    item = value if isinstance(value, dict) else {}
    kind = normalize_application_kind(item.get("kind") or item.get("applicationKind"))
    embeddable = kind == "ecosystem-native"
    problems: list[str] = []

    application_id = _text(item.get("applicationId") or item.get("moduleId") or item.get("id"))
    if not application_id:
        problems.append("Manifest has no application id.")

    services: list[str] = []
    for raw in _as_list(item.get("services") or item.get("capabilitiesRequested")):
        service = _text(raw)
        if service not in SERVICE_CONTRACTS:
            problems.append(f"Unknown service contract: {service or '(blank)'}.")
            continue
        if not embeddable and not SERVICE_CONTRACTS[service]:
            problems.append(f"{service} is only available to ecosystem applications.")
            continue
        if service not in services:
            services.append(service)

    surfaces: list[str] = []
    for raw in _as_list(item.get("surfaces") or item.get("embedIn")):
        zone = _text(raw)
        if zone and zone not in EMBED_ZONES:
            problems.append(f"Unknown embedding surface: {zone}.")
            continue
        if zone and zone not in surfaces:
            surfaces.append(zone)

    presentations: list[str] = []
    for raw in _as_list(item.get("presentations")):
        presentation = _text(raw)
        if presentation and presentation not in EMBED_PRESENTATIONS:
            problems.append(f"Unknown presentation: {presentation}.")
            continue
        if presentation and presentation not in presentations:
            presentations.append(presentation)

    if not embeddable and (surfaces or presentations):
        problems.append("An SDK application cannot declare Neyvia embedding surfaces.")
        surfaces = []
        presentations = []
    if embeddable and not surfaces:
        problems.append("An ecosystem application must declare the surfaces it can appear in.")

    provides: list[dict[str, str]] = []
    for raw in _as_list(item.get("provides") or item.get("capabilities")):
        entry = raw if isinstance(raw, dict) else {"capabilityId": raw}
        capability_id = _text(entry.get("capabilityId") or entry.get("id"))
        if capability_id:
            provides.append(
                {
                    "capabilityId": capability_id,
                    "label": _text(entry.get("label") or entry.get("name"), capability_id),
                }
            )

    provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
    publisher = item.get("publisher") if isinstance(item.get("publisher"), dict) else {}
    version = _text(item.get("version"))
    marketplace_proposed = embeddable and item.get("marketplaceProposed") is True
    if marketplace_proposed:
        if not version:
            problems.append("Marketplace publication requires a version.")
        if not _text(provenance.get("publisher") or publisher.get("id")):
            problems.append("Marketplace publication requires a publisher identity.")

    return {
        "schema": APPLICATION_CONTRACT_SCHEMA,
        "applicationId": application_id,
        "kind": kind,
        "name": _text(item.get("name"), application_id),
        "summary": _text(item.get("summary")),
        "version": version or None,
        "previousVersion": _text(item.get("previousVersion")) or None,
        "services": services,
        "provides": provides,
        "permissions": [_text(entry) for entry in _as_list(item.get("permissions")) if _text(entry)],
        "surfaces": surfaces,
        "presentations": presentations or (["inline-card"] if embeddable else []),
        "entryPointUrl": _safe_entry_point_url(
            item.get("entryPointUrl")
            or (item.get("runtime") or {}).get("entryPointUrl")
            if isinstance(item.get("runtime"), dict)
            else item.get("entryPointUrl")
        )
        or _safe_entry_point_url(
            (item.get("runtime") or {}).get("servedUrl")
            if isinstance(item.get("runtime"), dict)
            else None
        ),
        "rendersNeyviaShell": embeddable,
        "marketplaceEligible": embeddable,
        "marketplaceProposed": marketplace_proposed,
        "provenance": {
            "publisher": _text(provenance.get("publisher") or publisher.get("id")) or None,
            "origin": _text(provenance.get("origin") or item.get("origin")) or None,
            "signature": _text(provenance.get("signature")) or None,
            "compatibility": _text(provenance.get("compatibility") or item.get("compatibility")) or None,
        },
        "problems": problems,
        "valid": not problems,
    }


def bind_application_capabilities(
    manifest: dict[str, Any],
    *,
    state: str = "installed",
) -> dict[str, Any]:
    """Runtime binding for an installed application.

    A disabled or merely installed application binds nothing: its declared
    capabilities are not connected until it is active, and rolling it back or
    disabling it removes them again.
    """

    item = (
        manifest
        if isinstance(manifest, dict) and manifest.get("schema") == APPLICATION_CONTRACT_SCHEMA
        else normalize_application_manifest(manifest)
    )
    active = _text(state).lower() == "active"
    capabilities = (
        [
            {
                "capabilityId": entry["capabilityId"],
                "label": entry.get("label") or entry["capabilityId"],
                "moduleId": item["applicationId"],
                "surfaces": item["surfaces"],
                "presentations": item["presentations"],
                "adapterId": "marketplace-app",
            }
            for entry in item["provides"]
        ]
        if active
        else []
    )
    return {
        "schema": "neyvia.application.binding.v1",
        "applicationId": item["applicationId"],
        "kind": item["kind"],
        "state": _text(state, "installed"),
        "capabilities": capabilities,
        "services": item["services"],
        "permissions": item["permissions"],
        "detail": (
            "Active: declared capabilities are connected to their declared surfaces."
            if active
            else "Not active: declared capabilities are not connected. Activation is required."
        ),
    }


def resolve_application_embedding(
    manifest: dict[str, Any],
    zone: str,
    presentation: str | None = None,
) -> dict[str, Any]:
    item = (
        manifest
        if isinstance(manifest, dict) and manifest.get("schema") == APPLICATION_CONTRACT_SCHEMA
        else normalize_application_manifest(manifest)
    )
    if not item["marketplaceEligible"]:
        return {
            "allowed": False,
            "reason": "SDK applications run in their own product and are not embedded in Neyvia surfaces.",
        }
    zone_id = _text(zone)
    if zone_id not in item["surfaces"]:
        return {
            "allowed": False,
            "reason": f"{item['name']} did not declare the {zone_id or 'requested'} surface.",
            "surfaces": item["surfaces"],
        }
    requested = _text(presentation) or (item["presentations"][0] if item["presentations"] else "")
    if requested not in item["presentations"]:
        return {
            "allowed": False,
            "reason": f"{item['name']} did not declare the \"{requested}\" presentation.",
            "presentations": item["presentations"],
        }
    return {
        "allowed": True,
        "applicationId": item["applicationId"],
        "zoneId": zone_id,
        "presentation": requested,
        "adapterId": "marketplace-app",
        "permissions": item["permissions"],
    }


def _sdk_registry_path(root: Path) -> Path:
    return Path(root) / _SDK_REGISTRY_RELATIVE


def _bundled_registry_path(root: Path) -> Path:
    return Path(root) / _BUNDLED_APP_REGISTRY_RELATIVE


def _load_bundled_installations(root: Path) -> dict[str, dict[str, Any]]:
    path = _bundled_registry_path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = payload.get("applications") if isinstance(payload, dict) else []
    return {
        _text(item.get("applicationId")): item
        for item in _as_list(entries)
        if isinstance(item, dict) and _text(item.get("applicationId"))
    }


def _write_bundled_installations(
    root: Path,
    installations: dict[str, dict[str, Any]],
) -> None:
    path = _bundled_registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "neyvia.bundled-applications/v1",
        "updatedAt": _now(),
        "applications": sorted(
            installations.values(),
            key=lambda item: _text(item.get("applicationId")),
        ),
    }
    from .durability import atomic_write_text
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def bundled_application_catalog(root: Path) -> list[dict[str, Any]]:
    installed = _load_bundled_installations(Path(root))
    catalog: list[dict[str, Any]] = []
    for source in BUNDLED_APPLICATIONS:
        publisher_id = _text(source.get("publisherId"), "app.neyvia.bundled")
        install_source = _text(source.get("installSource"), "bundled")
        manifest = normalize_application_manifest(
            {
                **source,
                "kind": "ecosystem-native",
                "marketplaceProposed": True,
                "publisher": {"id": publisher_id},
                "provenance": {
                    "publisher": publisher_id,
                    "origin": (
                        "pinned-github-release"
                        if install_source == "github-release"
                        else "signed-neyvia-application-bundle"
                    ),
                    "compatibility": "neyvia-desktop >=0.1.0",
                },
            }
        )
        installation = installed.get(source["applicationId"])
        catalog.append(
            {
                **manifest,
                "category": source["category"],
                "iconToolId": source["iconToolId"],
                "logoUrl": _text(source.get("logoUrl")) or None,
                "launch": dict(source["launch"]),
                "installed": installation is not None,
                "state": "active" if installation is not None else "available",
                "installedAt": installation.get("installedAt") if installation else None,
                "installSource": install_source,
                "sourceUrl": _text(source.get("sourceUrl")) or None,
                "distribution": dict(source.get("distribution") or {}),
                "runtime": dict(installation.get("runtime") or {}) if installation else {},
                "integrity": _text(
                    source.get("integrity"),
                    "Included in this Neyvia build; no external code is downloaded.",
                ),
            }
        )
    from .proofs_d_neyvia import check_bundled
    check_bundled(BUNDLED_APPLICATIONS, installed, catalog)
    return catalog


def _install_github_release_application(
    root: Path,
    application: dict[str, Any],
    *,
    requested_by: str,
) -> dict[str, Any]:
    distribution = dict(application.get("distribution") or {})
    application_id = _text(application.get("applicationId"))
    version = _text(application.get("version"))
    asset_name = _text(distribution.get("assetName"))
    asset_url = _text(distribution.get("assetUrl"))
    expected_sha256 = _text(distribution.get("assetSha256")).lower()
    package_name = _text(distribution.get("npmPackage"))
    declared_bytes = distribution.get("assetBytes")
    if (
        not application_id
        or not version
        or not asset_name.endswith(".tgz")
        or not asset_url.startswith(
            "https://github.com/bobthecomputer/neyvia-app-pdf/releases/download/"
        )
        or not _SHA256.fullmatch(expected_sha256)
        or not package_name
    ):
        raise RuntimeError("External application distribution metadata is invalid.")

    install_parent = (
        Path(root) / _EXTERNAL_APP_ROOT_RELATIVE / application_id
    ).resolve()
    install_parent.mkdir(parents=True, exist_ok=True)
    final = (install_parent / version).resolve()
    final.relative_to(install_parent)
    marker = final / ".neyvia-install.json"
    if marker.is_file():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if (
            existing.get("archiveSha256") == expected_sha256
            and existing.get("applicationId") == application_id
            and existing.get("version") == version
        ):
            return {
                **existing,
                "alreadyInstalled": True,
                "detail": "Already installed from the verified GitHub release.",
            }
        raise RuntimeError("Existing application version has a different integrity marker.")

    cache = (
        Path(root) / ".agent_control" / "neyvia" / "downloads" / asset_name
    ).resolve()
    download = download_asset(
        {
            "name": asset_name,
            "browser_download_url": asset_url,
            "size": declared_bytes,
        },
        cache,
        expected_sha256=expected_sha256,
    )
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required to install this MCP App.")
    staging = (install_parent / f".installing-{version}-{uuid.uuid4().hex[:8]}").resolve()
    staging.relative_to(install_parent)
    staging.mkdir(parents=False, exist_ok=False)
    try:
        completed = subprocess.run(
            [
                npm,
                "install",
                "--ignore-scripts",
                "--omit=dev",
                "--no-audit",
                "--no-fund",
                "--prefix",
                str(staging),
                str(cache),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=240,
            **hidden_windows_subprocess_kwargs(),
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
            raise RuntimeError(f"npm app installation failed: {detail}")
        package_root = staging / "node_modules" / package_name
        app_manifest_path = package_root / ".neyvia" / "app.json"
        if not app_manifest_path.is_file():
            raise RuntimeError("Installed package does not contain .neyvia/app.json.")
        app_manifest = json.loads(app_manifest_path.read_text(encoding="utf-8"))
        if (
            app_manifest.get("appId") != application_id
            or app_manifest.get("version") != version
            or app_manifest.get("sourceUrl") != application.get("sourceUrl")
        ):
            raise RuntimeError("Installed application identity does not match the catalog.")
        executable = staging / "node_modules" / ".bin" / (
            "neyvia-pdf-app.cmd" if os.name == "nt" else "neyvia-pdf-app"
        )
        if not executable.is_file():
            raise RuntimeError("Installed application entry point is missing.")
        receipt = {
            "schema": "neyvia.github-application-install-receipt/v1",
            "applicationId": application_id,
            "version": version,
            "installedAt": _now(),
            "requestedBy": _text(requested_by, "marketplace-panel"),
            "source": "github-release",
            "sourceUrl": application.get("sourceUrl"),
            "archiveSha256": download["sha256"],
            "archiveBytes": download["bytes"],
            "packageScriptsEnabled": False,
            "runtime": {
                "kind": "mcp-app",
                "transport": "stdio",
                "command": str(
                    final
                    / "node_modules"
                    / ".bin"
                    / ("neyvia-pdf-app.cmd" if os.name == "nt" else "neyvia-pdf-app")
                ),
                "args": ["--stdio"],
                "resourceUri": "ui://pdf-viewer/mcp-app.html",
            },
        }
        marker_tmp = staging / ".neyvia-install.writing"
        marker_tmp.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        marker_tmp.replace(staging / ".neyvia-install.json")
        os.replace(staging, final)
        return {
            **receipt,
            "alreadyInstalled": False,
            "detail": "Downloaded, SHA-256 verified, and installed with scripts disabled.",
        }
    except BaseException:
        if staging.parent == install_parent:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _install_bundled_application_locked(
    root: Path,
    application_id: str,
    *,
    requested_by: str = "marketplace-panel",
) -> dict[str, Any]:
    target = _text(application_id)
    available = {
        item["applicationId"]: item
        for item in bundled_application_catalog(Path(root))
    }
    if target not in available:
        raise ValueError(f"Unknown bundled application: {target or '(blank)'}")
    installations = _load_bundled_installations(Path(root))
    already_installed = target in installations
    if not already_installed:
        external_receipt: dict[str, Any] = {}
        if available[target].get("installSource") == "github-release":
            external_receipt = _install_github_release_application(
                Path(root),
                available[target],
                requested_by=requested_by,
            )
        installations[target] = {
            "applicationId": target,
            "installedAt": _now(),
            "requestedBy": _text(requested_by, "marketplace-panel"),
            "version": available[target]["version"],
            "source": available[target].get("installSource") or "bundled",
            "runtime": dict(external_receipt.get("runtime") or {}),
            "archiveSha256": external_receipt.get("archiveSha256"),
        }
        _write_bundled_installations(Path(root), installations)
    result = {
        "schema": "neyvia.bundled-application-install-receipt/v1",
        "applicationId": target,
        "installed": True,
        "alreadyInstalled": already_installed,
        "state": "active",
        "version": available[target]["version"],
        "launch": available[target]["launch"],
        "detail": (
            "Already installed."
            if already_installed
            else (
                "Downloaded, SHA-256 verified, installed with package scripts "
                "disabled, and activated."
                if available[target].get("installSource") == "github-release"
                else "Installed and activated from the signed Neyvia application bundle."
            )
        ),
    }
    from .proofs_d_neyvia import check_install
    check_install(Path(root), result)
    return result


def install_bundled_application(
    root: Path,
    application_id: str,
    *,
    requested_by: str = "marketplace-panel",
) -> dict[str, Any]:
    """Conserve complete local activation membership through its proof check."""
    from .harness_jobs import _exclusive_job_lock
    target = _bundled_registry_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_job_lock(target, timeout_seconds=120):
        return _install_bundled_application_locked(root, application_id, requested_by=requested_by)


def _uninstall_bundled_application_locked(
    root: Path,
    application_id: str,
    *,
    requested_by: str = "marketplace-panel",
) -> dict[str, Any]:
    del requested_by
    target = _text(application_id)
    available_ids = {item["applicationId"] for item in BUNDLED_APPLICATIONS}
    if target not in available_ids:
        raise ValueError(f"Unknown bundled application: {target or '(blank)'}")
    installations = _load_bundled_installations(Path(root))
    removed = installations.pop(target, None) is not None
    if removed:
        _write_bundled_installations(Path(root), installations)
    return {
        "schema": "neyvia.bundled-application-uninstall-receipt/v1",
        "applicationId": target,
        "installed": False,
        "removed": removed,
        "state": "available",
        "detail": "Bundled application deactivated." if removed else "Application was not installed.",
    }


def uninstall_bundled_application(
    root: Path,
    application_id: str,
    *,
    requested_by: str = "marketplace-panel",
) -> dict[str, Any]:
    from .harness_jobs import _exclusive_job_lock
    target = _bundled_registry_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_job_lock(target, timeout_seconds=120):
        return _uninstall_bundled_application_locked(root, application_id, requested_by=requested_by)


def load_sdk_applications(root: Path) -> list[dict[str, Any]]:
    """SDK consumers registered against this workspace.

    Absent file means none are registered — reported as an empty list, never as
    invented integrations.
    """

    path = _sdk_registry_path(root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("applications") if isinstance(payload, dict) else payload
    return [
        normalize_application_manifest({**entry, "kind": "sdk-external"})
        for entry in _as_list(entries)
        if isinstance(entry, dict)
    ]


def _write_sdk_applications(root: Path, applications: list[dict[str, Any]]) -> None:
    path = _sdk_registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "neyvia.sdk-applications/v1",
        "updatedAt": _now(),
        "applications": applications,
    }
    from .durability import atomic_write_text
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _register_sdk_application_locked(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Register (or update) an SDK consumer of this workspace's services.

    Registration is a *declaration*, not a grant of the Neyvia shell: an invalid
    manifest is refused with its problems instead of being stored. Adding
    services later re-validates the same record, so an application can start
    with a small subset and adopt more without a different manifest shape.
    """

    manifest = normalize_application_manifest({**(payload or {}), "kind": "sdk-external"})
    if not manifest["applicationId"]:
        raise ValueError("applicationId is required")
    if not manifest["valid"]:
        return {
            "schema": APPLICATION_CONTRACT_SCHEMA,
            "registered": False,
            "applicationId": manifest["applicationId"],
            "problems": manifest["problems"],
            "detail": "The manifest was refused. Nothing was registered.",
        }

    existing = load_sdk_applications(root)
    merged: list[dict[str, Any]] = []
    replaced = False
    for entry in existing:
        if entry["applicationId"] == manifest["applicationId"]:
            # Adopting services keeps the identity while a fresh registration
            # may also update the developer-facing metadata.
            manifest = adopt_additional_services(
                {
                    **entry,
                    "name": manifest["name"],
                    "summary": manifest["summary"],
                    "version": manifest["version"],
                    "permissions": manifest["permissions"],
                },
                manifest["services"],
            )
            merged.append(manifest)
            replaced = True
        else:
            merged.append(entry)
    if not replaced:
        merged.append(manifest)

    _write_sdk_applications(root, merged)
    result = {
        "schema": APPLICATION_CONTRACT_SCHEMA,
        "registered": True,
        "updated": replaced,
        "applicationId": manifest["applicationId"],
        "services": manifest["services"],
        "manifest": manifest,
        "detail": (
            "Registered as an independent SDK consumer. This does not make it a "
            "marketplace application and grants no Neyvia surface."
        ),
    }
    from .proofs_d_neyvia import check_sdk
    check_sdk(root, existing, result)
    return result


def register_sdk_application(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve adopted services and identities across competing registrations."""
    from .harness_jobs import _exclusive_job_lock
    target = _sdk_registry_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_job_lock(target, timeout_seconds=120):
        return _register_sdk_application_locked(root, payload)


def _unregister_sdk_application_locked(root: Path, application_id: str) -> dict[str, Any]:
    target = _text(application_id)
    existing = load_sdk_applications(root)
    remaining = [entry for entry in existing if entry["applicationId"] != target]
    removed = len(remaining) != len(existing)
    if removed:
        _write_sdk_applications(root, remaining)
    return {
        "schema": APPLICATION_CONTRACT_SCHEMA,
        "removed": removed,
        "applicationId": target,
        "detail": (
            "Registration removed; the application keeps running as its own product."
            if removed
            else "No registration existed for that application id."
        ),
    }


def unregister_sdk_application(root: Path, application_id: str) -> dict[str, Any]:
    from .harness_jobs import _exclusive_job_lock
    target = _sdk_registry_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_job_lock(target, timeout_seconds=120):
        return _unregister_sdk_application_locked(root, application_id)


def _module_to_manifest(module: dict[str, Any]) -> dict[str, Any]:
    manifest = (
        module.get("manifest")
        if isinstance(module.get("manifest"), dict)
        else module.get("_manifest")
        if isinstance(module.get("_manifest"), dict)
        else {}
    )
    neyvia = manifest.get("neyvia") if isinstance(manifest.get("neyvia"), dict) else {}
    projection = (
        module.get("applicationProjection")
        if isinstance(module.get("applicationProjection"), dict)
        else {}
    )
    runtime = module.get("runtime") if isinstance(module.get("runtime"), dict) else {}
    raw_surfaces = (
        neyvia.get("surfaces")
        or manifest.get("surfaces")
        or projection.get("surfaces")
        or []
    )
    module_surfaces = [item for item in _as_list(raw_surfaces) if isinstance(item, dict)]
    surfaces = list(neyvia.get("embedIn") or [])
    if module_surfaces and "marketplace" not in surfaces:
        surfaces.append("marketplace")
    presentation_by_kind = {
        "embedded": "inline-card",
        "web": "dock-right",
        "desktop": "fullscreen",
        "mobile": "fullscreen",
    }
    presentations = list(neyvia.get("presentations") or [])
    for surface in module_surfaces:
        presentation = presentation_by_kind.get(_text(surface.get("kind")).lower())
        if presentation and presentation not in presentations:
            presentations.append(presentation)
    raw_capabilities = (
        neyvia.get("provides")
        or manifest.get("capabilities")
        or projection.get("capabilities")
        or []
    )
    provides = [
        {
            "capabilityId": item.get("operationId") or item.get("capabilityId") or item.get("id"),
            "label": item.get("name") or item.get("label"),
        }
        if isinstance(item, dict)
        else item
        for item in _as_list(raw_capabilities)
    ]
    services = list(neyvia.get("services") or manifest.get("services") or [])
    if provides and "tools" not in services:
        services.append("tools")
    if module_surfaces:
        for service in ("shell-surfaces", "embedded-workspace"):
            if service not in services:
                services.append(service)
    entry_point_url = (
        runtime.get("entryPointUrl")
        or runtime.get("servedUrl")
        or (
            f"/api/application/{quote(_text(module.get('moduleId')), safe='')}/"
            if _text(runtime.get("entrypoint")).lower().endswith((".html", ".htm"))
            else None
        )
        if _text(module.get("state")).lower() == "active"
        else None
    )
    result = normalize_application_manifest(
        {
            "kind": "ecosystem-native",
            "applicationId": module.get("moduleId") or manifest.get("id"),
            "name": module.get("name") or manifest.get("name"),
            "summary": module.get("summary") or manifest.get("summary"),
            "version": module.get("version") or manifest.get("version"),
            "previousVersion": module.get("previousVersion"),
            "services": services,
            "provides": provides,
            "permissions": module.get("permissions") or manifest.get("permissions") or [],
            "surfaces": surfaces,
            "presentations": presentations,
            "entryPointUrl": entry_point_url,
            "publisher": module.get("publisher") or {},
            "provenance": {
                "publisher": (module.get("publisher") or {}).get("id"),
                "origin": module.get("origin") or "installed-module",
                "signature": (module.get("signatureReceipt") or {}).get("state"),
                "compatibility": manifest.get("compatibility")
                or projection.get("compatibility"),
            },
        }
    )
    from .proofs_d_neyvia import check_projection
    check_projection(module, surfaces, presentations, provides, entry_point_url, result)
    return result


def build_application_registry(root: Path, marketplace: Any = None) -> dict[str, Any]:
    """Both directions in one truthful registry.

    Ecosystem applications come from the installed module catalog; SDK
    applications come from the SDK registration file. Missing sources yield
    empty lists and an explicit disclosure rather than placeholders.
    """

    ecosystem: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        if marketplace is None:
            from .module_marketplace import ModuleMarketplace

            marketplace = ModuleMarketplace(Path(root))
        catalog = marketplace.installed_catalog()
        for module in _as_list(catalog.get("modules")):
            if not isinstance(module, dict):
                continue
            if module.get("origin") == "developer-source" and module.get("kind") == "mod":
                continue
            manifest = _module_to_manifest(module)
            ecosystem.append(manifest)
            bindings.append(
                bind_application_capabilities(manifest, state=_text(module.get("state"), "installed"))
            )
    except Exception as exc:  # pragma: no cover - depends on local install state
        errors.append(f"Installed module catalog unavailable: {exc}")

    bundled = bundled_application_catalog(Path(root))
    existing_ids = {item.get("applicationId") for item in ecosystem}
    for application in bundled:
        if not application["installed"] or application["applicationId"] in existing_ids:
            continue
        manifest = normalize_application_manifest(application)
        ecosystem.append({**manifest, "launch": application["launch"], "iconToolId": application["iconToolId"]})
        bindings.append(bind_application_capabilities(manifest, state="active"))

    sdk = load_sdk_applications(Path(root))
    return {
        "schema": APPLICATION_REGISTRY_SCHEMA,
        "generatedAt": _now(),
        "propositions": describe_developer_propositions(),
        "ecosystemApplications": ecosystem,
        "availableApplications": bundled,
        "sdkApplications": sdk,
        "bindings": bindings,
        "activeCapabilityCount": sum(len(item["capabilities"]) for item in bindings),
        "errors": errors,
        "disclosure": (
            "Bundled applications come from this signed Neyvia build and install without "
            "downloading code. Third-party ecosystem applications remain governed by the "
            "signed module catalog; SDK registrations remain independent products."
        ),
    }


def describe_developer_propositions() -> list[dict[str, Any]]:
    return [
        {
            "id": "sdk-external",
            "label": "SDK application",
            "summary": (
                "An independent product using Neyvia services through the SDK. "
                "Keeps its own interface, brand and architecture."
            ),
            "rendersNeyviaShell": False,
            "marketplaceEligible": False,
            "services": [key for key, external in SERVICE_CONTRACTS.items() if external],
            "publication": (
                "Runs as an independent product. Using the SDK does not make it a "
                "marketplace application."
            ),
        },
        {
            "id": "ecosystem-native",
            "label": "Ecosystem application",
            "summary": (
                "Built through Neyvia. Uses Neyvia surfaces, sessions, context, files, "
                "permissions, runtime services, artifacts and evidence."
            ),
            "rendersNeyviaShell": True,
            "marketplaceEligible": True,
            "services": list(SERVICE_CONTRACTS),
            "publication": (
                "Can be packaged and proposed to the Marketplace with origin, version, "
                "declared capabilities, permissions, compatibility, provenance and rollback."
            ),
        },
    ]


def adopt_additional_services(
    manifest: dict[str, Any],
    services: Iterable[str],
) -> dict[str, Any]:
    """Grow an integration without rewriting it.

    An application starts with a small subset of services and adopts more later;
    this returns the manifest re-validated with the additional services rather
    than requiring a new manifest shape.
    """

    item = (
        manifest
        if isinstance(manifest, dict) and manifest.get("schema") == APPLICATION_CONTRACT_SCHEMA
        else normalize_application_manifest(manifest)
    )
    merged = list(item["services"]) + [_text(entry) for entry in services or () if _text(entry)]
    return normalize_application_manifest(
        {
            **{key: value for key, value in item.items() if key != "schema"},
            "services": merged,
        }
    )
