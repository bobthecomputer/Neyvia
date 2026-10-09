"""Durable local application scaffolding for the Neyvia App Factory.

The factory is an authoring surface, not a shortcut around Marketplace trust:

* a job creates a real, dependency-free local application workspace;
* the same frontend is immediately available through an authenticated preview;
* desktop jobs add a Tauri 2 shell that can be compiled with the local Rust toolchain;
* every stage is persisted atomically and may be resumed;
* Marketplace publication remains a separately signed and attested lifecycle.

The generated starter deliberately implements one useful local workflow (saved
notes or a saved checklist) instead of painting a non-functional mock screen.
An agent handoff prompt carries the exact workspace and proof forward when the
operator wants a more specialised application.
"""

from __future__ import annotations

from .subprocess_utils import process_is_alive

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .neyvia_application_contract import normalize_application_manifest
from .proofs_a_capabilities import checked_action, check_factory_job, check_preview_asset, check_factory_lineage
from .subprocess_utils import hidden_windows_subprocess_kwargs, install_hidden_subprocess_default


APP_FACTORY_SCHEMA = "neyvia.app-factory/v1"
APP_FACTORY_JOB_SCHEMA = "neyvia.app-factory-job/v1"
APP_FACTORY_REGISTRY_SCHEMA = "neyvia.app-factory-registry/v1"
APP_FACTORY_CONFIG_SCHEMA = "neyvia.app-factory-project/v1"
APP_FACTORY_HANDOFF_SCHEMA = "neyvia.app_factory_lineage_handoff.v1"
APP_FACTORY_HANDOFF_RECEIPT_SCHEMA = (
    "neyvia.app_factory_lineage_handoff_receipt.v1"
)
APP_FACTORY_ROOT = Path(".agent_control") / "neyvia" / "app_factory"
APP_FACTORY_JOBS = APP_FACTORY_ROOT / "jobs"
APP_FACTORY_REGISTRY = APP_FACTORY_ROOT / "registry.json"
APP_FACTORY_CARGO_TARGET = APP_FACTORY_ROOT / "cargo-target"
APP_FACTORY_HANDOFFS = APP_FACTORY_ROOT / "handoffs"
APP_FACTORY_STAGE_IDS = ("brief", "scaffold", "assemble", "verify", "register")
SUPPORTED_TARGETS = {"desktop", "neyvia"}
SUPPORTED_TEMPLATES = {"auto", "capability", "checklist", "notes"}
SUPPORTED_THEMES = {"midnight", "paper", "warm"}

_SAFE_JOB_ID = re.compile(r"^app-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")
_SAFE_HANDOFF_ID = re.compile(r"^app_factory_handoff_[a-f0-9]{18}$")
_SAFE_APP_ID = re.compile(r"^local\.[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_SAFE_SKILL_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,95}$")
_SAFE_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_HANDOFF_STABLE_FIELDS = (
    "schema",
    "handoffId",
    "materializationId",
    "trialId",
    "approvedLineageId",
    "parentLineageId",
    "skillId",
    "candidateDigest",
    "skillSha256",
    "metadataSha256",
    "workflowSteps",
    "comparisonRuns",
    "forgeId",
    "forgeDigest",
    "scorecard",
    "authorityComparison",
    "rollback",
    "candidateActivated",
    "appActivated",
    "transcriptsIncluded",
)
_ARCHIVE_EXCLUDED_PARTS = {
    ".git",
    ".idea",
    ".neyvia",
    ".vscode",
    "node_modules",
    "target",
}
_PREVIEW_MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".gif": "image/gif",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml; charset=utf-8",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _job_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _stable_handoff_contract(value: dict[str, Any]) -> dict[str, Any]:
    contract = {
        field: value.get(field) for field in _HANDOFF_STABLE_FIELDS
    }
    if isinstance(value.get("proofLease"), dict):
        contract["proofLease"] = value["proofLease"]
    return contract


def _capability_binding_digest(
    handoff_digest: str,
    *,
    app_id: str,
    name: str,
    brief: str,
    target: str,
    theme: str,
    directory: str,
) -> str:
    return _canonical_digest(
        {
            "schema": "neyvia.app_factory_app_binding.v1",
            "handoffDigest": handoff_digest,
            "appId": app_id,
            "name": name,
            "brief": brief,
            "target": target,
            "template": "capability",
            "theme": theme,
            "directory": directory,
        }
    )


def _slug(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text[:56] or "local-app"


def _safe_rust_name(slug: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", slug.replace("-", "_")).strip("_")
    if not value or value[0].isdigit():
        value = f"app_{value or 'local'}"
    return value[:64]


def _resolved_workspace(root: str | Path) -> Path:
    resolved = Path(root).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise RuntimeError(f"App Factory workspace does not exist: {resolved}")
    return resolved


def _safe_child(root: Path, raw_path: str | Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError("App Factory projects must stay inside the selected workspace.") from exc
    cursor = resolved
    while cursor != root and cursor != cursor.parent:
        if cursor.exists() and cursor.is_symlink():
            raise RuntimeError(f"App Factory refuses linked project paths: {cursor}")
        cursor = cursor.parent
    return resolved


def _clean_text(value: object, *, minimum: int, maximum: int, label: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) < minimum:
        raise RuntimeError(f"{label} must contain at least {minimum} characters.")
    if len(text) > maximum:
        raise RuntimeError(f"{label} must contain at most {maximum} characters.")
    return text


def _template_for(brief: str, requested: str) -> str:
    requested = str(requested or "auto").strip().lower()
    if requested not in SUPPORTED_TEMPLATES:
        raise RuntimeError(f"Unsupported starter: {requested or '(blank)'}")
    if requested != "auto":
        return requested
    if re.search(r"\b(note|notes|journal|diary|memo|writing|ideas?)\b", brief, re.I):
        return "notes"
    return "checklist"


def _theme_tokens(theme: str) -> dict[str, str]:
    if theme == "paper":
        return {
            "page": "#f1eee6",
            "panel": "#fffdf8",
            "panelStrong": "#1e2625",
            "ink": "#1d2524",
            "muted": "#66706d",
            "line": "#d8d2c7",
            "accent": "#2f7c67",
            "accentInk": "#f7fffb",
            "shadow": "rgba(28, 37, 35, .12)",
        }
    if theme == "warm":
        return {
            "page": "#17120f",
            "panel": "#231b17",
            "panelStrong": "#f3e7da",
            "ink": "#f6eee6",
            "muted": "#b8a79a",
            "line": "#3b2e27",
            "accent": "#e48d5d",
            "accentInk": "#26150d",
            "shadow": "rgba(0, 0, 0, .34)",
        }
    return {
        "page": "#0e1115",
        "panel": "#161b21",
        "panelStrong": "#f3f6f8",
        "ink": "#f5f7f8",
        "muted": "#98a4ad",
        "line": "#29323a",
        "accent": "#72e2b5",
        "accentInk": "#082218",
        "shadow": "rgba(0, 0, 0, .38)",
    }


def _starter_copy(template: str) -> dict[str, str]:
    if template == "notes":
        return {
            "noun": "note",
            "nounPlural": "notes",
            "verb": "Save note",
            "placeholder": "Write one useful thought…",
            "emptyTitle": "No notes yet",
            "emptyDetail": "Your first saved note will appear here and remain on this device.",
        }
    return {
        "noun": "item",
        "nounPlural": "items",
        "verb": "Add item",
        "placeholder": "Add the next useful step…",
        "emptyTitle": "Nothing queued",
        "emptyDetail": "Add the first item. It will stay saved locally on this device.",
    }


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _generated_app_icon(theme: str) -> tuple[bytes, bytes]:
    """Return a deterministic PNG and Windows ICO for generated native apps."""

    tokens = _theme_tokens(theme)

    def rgb(value: str) -> tuple[int, int, int]:
        normalized = value.lstrip("#")
        return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))

    background = rgb(tokens["page"])
    accent = rgb(tokens["accent"])
    width = height = 64
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            corner_x = min(x, width - 1 - x)
            corner_y = min(y, height - 1 - y)
            visible = corner_x >= 9 or corner_y >= 9 or (corner_x - 9) ** 2 + (corner_y - 9) ** 2 <= 81
            color = background
            alpha = 255 if visible else 0
            # A compact geometric N: two uprights and a rising diagonal.
            in_left = 17 <= x <= 23 and 16 <= y <= 48
            in_right = 40 <= x <= 46 and 16 <= y <= 48
            diagonal_center = 22 + ((y - 16) * 18 / 32)
            in_diagonal = 16 <= y <= 48 and abs(x - diagonal_center) <= 3
            if in_left or in_right or in_diagonal:
                color = accent
            row.extend((*color, alpha))
        rows.append(bytes(row))
    raw = b"".join(rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
        )
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )
    ico = (
        struct.pack("<HHH", 0, 1, 1)
        + struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(png), 22)
        + png
    )
    return png, ico


def _capability_frontend_files(job: dict[str, Any]) -> dict[str, str]:
    spec = job["spec"]
    handoff = (
        dict(job.get("capabilityHandoff") or {})
        if isinstance(job.get("capabilityHandoff"), dict)
        else {}
    )
    steps = [
        str(item).strip()
        for item in handoff.get("workflowSteps") or []
        if str(item).strip()
    ]
    if not steps:
        raise RuntimeError(
            "A guided capability app requires exact workflow steps from the sealed skill."
        )
    theme = _theme_tokens(spec["theme"])
    evidence = (
        dict(handoff.get("evidenceSummary") or {})
        if isinstance(handoff.get("evidenceSummary"), dict)
        else {}
    )
    scorecard = (
        dict(evidence.get("scorecard") or {})
        if isinstance(evidence.get("scorecard"), dict)
        else {}
    )
    authority = (
        dict(evidence.get("authorityComparison") or {})
        if isinstance(evidence.get("authorityComparison"), dict)
        else {}
    )
    proof_lease = (
        dict(handoff.get("proofLease") or {})
        if isinstance(handoff.get("proofLease"), dict)
        else {}
    )
    config = {
        "schema": "neyvia.guided-capability-app/v1",
        "appFactoryJobId": job["jobId"],
        "appId": spec["appId"],
        "name": spec["name"],
        "brief": spec["brief"],
        "skillId": handoff.get("skillId") or "",
        "handoffId": handoff.get("handoffId") or "",
        "handoffDigest": handoff.get("handoffDigest") or "",
        "candidateDigest": handoff.get("candidateDigest") or "",
        "workflowSteps": steps,
        "evidenceSummary": evidence,
        "proofLease": proof_lease,
        "storageKey": (
            f"neyvia.app-factory.{spec['appId']}.capability-runs.v2"
        ),
        "returnMessageType": "neyvia:capability-run-bundle:v2",
    }
    config_json = json.dumps(
        config,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    outcome_lift = evidence.get("averageOutcomeLift")
    lift_label = (
        f"{float(outcome_lift):+.2f}"
        if isinstance(outcome_lift, (int, float))
        else "Recorded"
    )
    index = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="dark light" />
    <title>{html.escape(spec['name'])}</title>
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body data-neyvia-guided-capability="{html.escape(spec['appId'])}">
    <main class="app-shell">
      <header class="app-intro">
        <div>
          <span class="eyebrow">SEALED CAPABILITY · GUIDED LOCAL RUNNER</span>
          <h1>{html.escape(spec['name'])}</h1>
          <p>{html.escape(spec['brief'])}</p>
        </div>
        <div class="source-state">
          <span><i></i> Exact package carried forward</span>
          <small>Source stays inactive · app stays local</small>
        </div>
      </header>

      <section class="proof-strip" aria-label="Capability source proof">
        <article><span>Skill</span><strong>{html.escape(str(handoff.get('skillId') or 'sealed skill'))}</strong></article>
        <article><span>Qualifying runs</span><strong>{int(evidence.get('qualifyingRunCount') or 0)}</strong></article>
        <article><span>Measured lift</span><strong>{html.escape(lift_label)}</strong></article>
        <article><span>Replay wins</span><strong>{int(scorecard.get('wins') or 0)}</strong></article>
        <article><span>Authority</span><strong>{html.escape(str(authority.get('status') or 'reviewed').replace('_', ' '))}</strong></article>
        <article><span>Proof lease</span><strong>{html.escape(str(proof_lease.get('state') or 'legacy proof').replace('_', ' '))}</strong></article>
      </section>

      <section class="workbench" aria-labelledby="runner-title">
        <header class="workbench-heading">
          <div>
            <span>ONE RUN AT A TIME</span>
            <h2 id="runner-title">Turn the workflow into proof</h2>
          </div>
          <strong id="run-count">0 saved runs</strong>
        </header>

        <form id="run-form" class="run-capture">
          <label for="run-goal">What should this run accomplish?</label>
          <div>
            <input id="run-goal" maxlength="600" placeholder="Describe one concrete outcome…" required />
            <button type="submit">Start guided run</button>
          </div>
        </form>

        <section id="active-run" class="active-run" hidden>
          <header>
            <div><span>ACTIVE RUN</span><strong id="active-goal"></strong></div>
            <em id="active-progress">0/{len(steps)} steps</em>
          </header>
          <ol id="step-list" class="step-list"></ol>
          <div class="completion-grid">
            <label>
              Outcome
              <select id="run-outcome">
                <option value="completed">Completed</option>
                <option value="blocked">Blocked with evidence</option>
              </select>
            </label>
            <label>
              Was this useful?
              <select id="run-value">
                <option value="helpful">Yes, this helped</option>
                <option value="not_sure">Not sure yet</option>
                <option value="not_helpful">No, it did not help</option>
              </select>
            </label>
            <label>
              What slowed you down?
              <select id="run-friction">
                <option value="none">Nothing material</option>
                <option value="repeated_manual_entry">Repeated manual entry</option>
                <option value="context_reentry">Rebuilding context</option>
                <option value="tool_switching">Switching between tools</option>
                <option value="unclear_output">Unclear output</option>
                <option value="verification_gap">Hard-to-verify result</option>
                <option value="permission_wait">Permission interruption</option>
                <option value="runtime_failure">Runtime failure</option>
                <option value="other">Something else</option>
              </select>
            </label>
            <label>
              Friction severity
              <select id="run-friction-severity">
                <option value="none">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label>
              Corrections needed
              <input id="run-corrections" inputmode="numeric" max="100" min="0" type="number" value="0" />
            </label>
            <label>
              Usual method, minutes <small>(optional estimate)</small>
              <input id="run-usual-minutes" inputmode="numeric" max="10080" min="1" placeholder="e.g. 45" type="number" />
            </label>
            <label class="is-wide">
              Proof note
              <textarea id="run-proof" maxlength="1600" placeholder="What changed, where is the proof, and what should happen next?"></textarea>
            </label>
          </div>
          <div class="completion-actions">
            <p id="run-status" role="status">Complete every workflow step and add a proof note.</p>
            <button id="complete-run" type="button">Seal run receipt</button>
          </div>
        </section>

        <section class="history" aria-labelledby="history-title">
          <header>
            <div><span>LOCAL HISTORY</span><h2 id="history-title">Completed runs</h2></div>
            <div class="history-actions">
              <button id="return-button" type="button">Return typed outcomes to Neyvia</button>
              <button id="export-button" class="secondary" type="button">Export proof bundle</button>
            </div>
          </header>
          <p class="return-boundary">Neyvia keeps typed outcomes, timing, and friction. Your goal, proof note, and step notes stay out of its learning ledger.</p>
          <ol id="run-history"></ol>
          <div id="empty-history" class="empty-state">
            <strong>No completed runs yet</strong>
            <p>Start with one real outcome. Neyvia will preserve the exact steps and package identity in every receipt.</p>
          </div>
        </section>
      </section>

      <footer>
        <span>Generated by Neyvia App Factory</span>
        <code>{html.escape(str(handoff.get('handoffDigest') or 'proof pending'))}</code>
      </footer>
    </main>
    <script type="module" src="./app.js"></script>
  </body>
</html>
"""
    css = f"""* {{
  box-sizing: border-box;
}}

:root {{
  color: {theme['ink']};
  background: {theme['page']};
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-synthesis: none;
}}

body {{
  min-width: 320px;
  min-height: 100vh;
  margin: 0;
  background:
    radial-gradient(circle at 84% 0%, color-mix(in srgb, {theme['accent']} 18%, transparent), transparent 36rem),
    {theme['page']};
}}

button,
input,
select,
textarea {{
  font: inherit;
}}

button {{
  cursor: pointer;
}}

button:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible {{
  outline: 3px solid color-mix(in srgb, {theme['accent']} 54%, transparent);
  outline-offset: 2px;
}}

.app-shell {{
  width: min(1080px, calc(100% - 40px));
  margin: 0 auto;
  padding: 64px 0 38px;
}}

.app-intro {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 36px;
}}

.eyebrow,
.workbench-heading span,
.active-run header span,
.history header span {{
  color: {theme['accent']};
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .16em;
}}

h1 {{
  max-width: 780px;
  margin: 12px 0 10px;
  color: {theme['panelStrong']};
  font-size: clamp(42px, 7vw, 72px);
  line-height: .96;
  letter-spacing: -.06em;
}}

.app-intro p {{
  max-width: 720px;
  margin: 0;
  color: {theme['muted']};
  font-size: 17px;
  line-height: 1.58;
}}

.source-state {{
  display: grid;
  gap: 7px;
  padding: 16px 18px;
  border: 1px solid {theme['line']};
  border-radius: 16px;
  background: color-mix(in srgb, {theme['panel']} 86%, transparent);
}}

.source-state span {{
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 12px;
  font-weight: 800;
}}

.source-state i {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: {theme['accent']};
  box-shadow: 0 0 0 5px color-mix(in srgb, {theme['accent']} 12%, transparent);
}}

.source-state small,
.proof-strip span,
.workbench-heading > strong {{
  color: {theme['muted']};
  font-size: 11px;
}}

.proof-strip {{
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  margin: 28px 0 16px;
  border: 1px solid {theme['line']};
  border-radius: 18px;
  overflow: hidden;
}}

.proof-strip article {{
  min-width: 0;
  padding: 15px 17px;
  background: color-mix(in srgb, {theme['panel']} 82%, transparent);
}}

.proof-strip article + article {{
  border-left: 1px solid {theme['line']};
}}

.proof-strip strong {{
  display: block;
  margin-top: 6px;
  overflow: hidden;
  color: {theme['panelStrong']};
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

.workbench {{
  padding: clamp(22px, 5vw, 42px);
  border: 1px solid {theme['line']};
  border-radius: 28px;
  background: color-mix(in srgb, {theme['panel']} 95%, transparent);
  box-shadow: 0 28px 80px {theme['shadow']};
}}

.workbench-heading,
.history > header,
.active-run > header {{
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
}}

h2 {{
  margin: 6px 0 0;
  color: {theme['panelStrong']};
  font-size: 27px;
  letter-spacing: -.035em;
}}

.run-capture {{
  margin-top: 28px;
}}

.run-capture > label,
.completion-grid label {{
  display: block;
  color: {theme['muted']};
  font-size: 12px;
  font-weight: 750;
}}

.completion-grid label small {{
  font-weight: 500;
}}

.run-capture > div {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  margin-top: 8px;
}}

input,
select,
textarea {{
  width: 100%;
  border: 1px solid {theme['line']};
  border-radius: 13px;
  color: {theme['ink']};
  background: color-mix(in srgb, {theme['page']} 58%, transparent);
}}

input,
select {{
  min-height: 48px;
  padding: 0 15px;
}}

textarea {{
  min-height: 92px;
  padding: 12px 14px;
  resize: vertical;
}}

button {{
  min-height: 46px;
  padding: 0 18px;
  border: 0;
  border-radius: 13px;
  color: {theme['accentInk']};
  background: {theme['accent']};
  font-weight: 800;
}}

button.secondary {{
  border: 1px solid {theme['line']};
  color: {theme['ink']};
  background: transparent;
}}

.active-run {{
  margin-top: 28px;
  padding: 22px;
  border: 1px solid color-mix(in srgb, {theme['accent']} 35%, {theme['line']});
  border-radius: 20px;
  background: color-mix(in srgb, {theme['accent']} 5%, transparent);
}}

.active-run header strong {{
  display: block;
  margin-top: 5px;
  color: {theme['panelStrong']};
  font-size: 18px;
}}

.active-run header em {{
  color: {theme['muted']};
  font-size: 12px;
  font-style: normal;
}}

.step-list {{
  display: grid;
  gap: 10px;
  margin: 22px 0;
  padding: 0;
  list-style: none;
  counter-reset: workflow;
}}

.step {{
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 13px;
  padding: 14px;
  border: 1px solid {theme['line']};
  border-radius: 15px;
  background: color-mix(in srgb, {theme['page']} 43%, transparent);
  counter-increment: workflow;
}}

.step > input {{
  width: 19px;
  min-height: 19px;
  margin-top: 2px;
  accent-color: {theme['accent']};
}}

.step strong::before {{
  content: counter(workflow, decimal-leading-zero) " · ";
  color: {theme['accent']};
}}

.step textarea {{
  grid-column: 2;
  min-height: 62px;
  margin-top: 8px;
}}

.step[data-complete="true"] strong {{
  color: {theme['muted']};
}}

.completion-grid {{
  display: grid;
  grid-template-columns: minmax(150px, .35fr) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}}

.completion-grid select,
.completion-grid input,
.completion-grid textarea {{
  margin-top: 8px;
}}

.completion-grid .is-wide {{
  grid-column: 1 / -1;
}}

.completion-actions {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-top: 16px;
}}

.completion-actions p {{
  margin: 0;
  color: {theme['muted']};
  font-size: 12px;
}}

.history {{
  margin-top: 34px;
  padding-top: 28px;
  border-top: 1px solid {theme['line']};
}}

.history-actions {{
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}}

.return-boundary {{
  max-width: 720px;
  margin: 13px 0 0;
  color: {theme['muted']};
  font-size: 12px;
  line-height: 1.5;
}}

.history ol {{
  display: grid;
  gap: 10px;
  margin: 20px 0 0;
  padding: 0;
  list-style: none;
}}

.history li {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid {theme['line']};
  border-radius: 14px;
}}

.history li strong,
.history li small {{
  display: block;
}}

.history li small {{
  margin-top: 5px;
  color: {theme['muted']};
}}

.history li code {{
  display: block;
  margin-top: 7px;
  overflow-wrap: anywhere;
  color: {theme['accent']};
  font-size: 9px;
}}

.history li em {{
  color: {theme['accent']};
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  text-transform: uppercase;
}}

.empty-state {{
  margin-top: 20px;
  padding: 34px 22px;
  border: 1px dashed {theme['line']};
  border-radius: 17px;
  text-align: center;
}}

.empty-state p {{
  max-width: 520px;
  margin: 8px auto 0;
  color: {theme['muted']};
  line-height: 1.5;
}}

footer {{
  display: flex;
  justify-content: space-between;
  gap: 18px;
  margin-top: 18px;
  color: {theme['muted']};
  font-size: 11px;
}}

footer code {{
  max-width: 56%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

@media (max-width: 760px) {{
  .app-shell {{
    width: min(100% - 24px, 1080px);
    padding-top: 36px;
  }}

  .app-intro,
  .completion-grid {{
    grid-template-columns: 1fr;
  }}

  .proof-strip {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}

  .proof-strip article + article {{
    border-left: 0;
    border-top: 1px solid {theme['line']};
  }}

  .run-capture > div {{
    grid-template-columns: 1fr;
  }}
}}

@media (max-width: 520px) {{
  .workbench {{
    border-radius: 20px;
  }}

  .workbench-heading,
  .history > header,
  .completion-actions,
  footer {{
    align-items: stretch;
    flex-direction: column;
  }}

  .history-actions {{
    justify-content: flex-start;
  }}
}}

@media (prefers-reduced-motion: reduce) {{
  *,
  *::before,
  *::after {{
    scroll-behavior: auto !important;
    transition-duration: .01ms !important;
    animation-duration: .01ms !important;
  }}
}}
"""
    script = f"""const config = {config_json};
const startForm = document.querySelector("#run-form");
const goalInput = document.querySelector("#run-goal");
const activeSection = document.querySelector("#active-run");
const activeGoal = document.querySelector("#active-goal");
const activeProgress = document.querySelector("#active-progress");
const stepList = document.querySelector("#step-list");
const outcome = document.querySelector("#run-outcome");
const operatorValue = document.querySelector("#run-value");
const frictionCode = document.querySelector("#run-friction");
const frictionSeverity = document.querySelector("#run-friction-severity");
const correctionCount = document.querySelector("#run-corrections");
const usualMinutes = document.querySelector("#run-usual-minutes");
const proof = document.querySelector("#run-proof");
const completeButton = document.querySelector("#complete-run");
const status = document.querySelector("#run-status");
const history = document.querySelector("#run-history");
const emptyHistory = document.querySelector("#empty-history");
const runCount = document.querySelector("#run-count");
const returnButton = document.querySelector("#return-button");
const exportButton = document.querySelector("#export-button");

function readRuns() {{
  try {{
    const parsed = JSON.parse(localStorage.getItem(config.storageKey) || "[]");
    return Array.isArray(parsed)
      ? parsed.filter(run =>
          run?.schema === "neyvia.capability-run/v2"
          && Array.isArray(run.steps)
        )
      : [];
  }} catch {{
    return [];
  }}
}}

let runs = readRuns();

function saveRuns() {{
  guardRuns();
  const serialized = JSON.stringify(runs);
  localStorage.setItem(config.storageKey, serialized);
  if (localStorage.getItem(config.storageKey) !== serialized) {{
    throw new Error("Contract a.factory-guided-ui: saved runs did not persist exactly.");
  }}
}}

function guardRuns() {{
  const ids = new Set();
  for (const run of runs) {{
    if (ids.has(run.runId) || run.schema !== "neyvia.capability-run/v2"
        || run.appFactoryJobId !== config.appFactoryJobId
        || run.handoffDigest !== config.handoffDigest
        || run.candidateDigest !== config.candidateDigest
        || run.candidateActivated !== false || run.transcriptsIncluded !== false
        || !Array.isArray(run.steps)
        || (run.status === "sealed" && (!/^[a-f0-9]{{64}}$/.test(run.receiptDigest || "")
          || !run.proofNote?.trim()
          || (run.outcome === "completed" && run.steps.some(step => step.complete !== true))))) {{
      throw new Error("Contract a.factory-guided-ui: run lost identity, proof or inactive boundary.");
    }}
    ids.add(run.runId);
  }}
}}

function canonicalJson(value) {{
  if (Array.isArray(value)) {{
    return `[${{value.map(item => canonicalJson(item)).join(",")}}]`;
  }}
  if (value && typeof value === "object") {{
    return `{{${{Object.keys(value)
      .sort()
      .map(key => `${{JSON.stringify(key)}}:${{canonicalJson(value[key])}}`)
      .join(",")}}}}`;
  }}
  return JSON.stringify(value);
}}

async function sha256(value) {{
  if (!globalThis.crypto?.subtle) {{
    throw new Error("This browser cannot seal a SHA-256 run receipt.");
  }}
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}}

function activeRun() {{
  return runs.find(run => run.status === "running") || null;
}}

function sealedRuns() {{
  return runs.filter(run => run.status === "sealed" && run.receiptDigest);
}}

function syncFrictionControls() {{
  const hasFriction = frictionCode.value !== "none";
  frictionSeverity.disabled = !hasFriction;
  correctionCount.disabled = !hasFriction;
  if (!hasFriction) {{
    frictionSeverity.value = "none";
    correctionCount.value = "0";
  }} else if (frictionSeverity.value === "none") {{
    frictionSeverity.value = "low";
  }}
}}

function renderActive() {{
  const run = activeRun();
  activeSection.hidden = !run;
  startForm.hidden = Boolean(run);
  if (!run) return;
  activeGoal.textContent = run.goal;
  outcome.value = run.outcome || "completed";
  operatorValue.value = run.operatorValue || "helpful";
  frictionCode.value = run.friction?.code || "none";
  frictionSeverity.value = run.friction?.severity || "none";
  correctionCount.value = String(run.friction?.correctionCount ?? 0);
  usualMinutes.value = run.friction?.usualMinutes ?? "";
  proof.value = run.proofNote || "";
  syncFrictionControls();
  const completeCount = run.steps.filter(step => step.complete).length;
  activeProgress.textContent = `${{completeCount}}/${{run.steps.length}} steps`;
  stepList.replaceChildren(...run.steps.map((step, index) => {{
    const row = document.createElement("li");
    row.className = "step";
    row.dataset.complete = step.complete ? "true" : "false";

    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = Boolean(step.complete);
    toggle.setAttribute("aria-label", `Complete step ${{index + 1}}`);
    toggle.addEventListener("change", () => {{
      step.complete = toggle.checked;
      step.updatedAt = new Date().toISOString();
      saveRuns();
      render();
    }});

    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = step.text;
    const note = document.createElement("textarea");
    note.maxLength = 800;
    note.placeholder = "Optional evidence or decision for this step…";
    note.value = step.note || "";
    note.setAttribute("aria-label", `Evidence note for step ${{index + 1}}`);
    note.addEventListener("input", () => {{
      step.note = note.value;
      saveRuns();
    }});
    content.append(title);
    row.append(toggle, content, note);
    return row;
  }}));
}}

function renderHistory() {{
  const completed = runs.filter(run => run.status !== "running");
  runCount.textContent = `${{runs.length}} saved ${{runs.length === 1 ? "run" : "runs"}}`;
  returnButton.disabled = sealedRuns().length === 0;
  exportButton.disabled = sealedRuns().length === 0;
  emptyHistory.hidden = completed.length > 0;
  history.replaceChildren(...completed.map(run => {{
    const row = document.createElement("li");
    const detail = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = run.goal;
    const note = document.createElement("small");
    const friction = run.friction?.code && run.friction.code !== "none"
      ? ` · friction: ${{run.friction.code.replaceAll("_", " ")}}`
      : "";
    note.textContent = `${{new Date(run.completedAt).toLocaleString()}} · ${{run.outcome}}${{friction}} · ${{run.proofNote}}`;
    const digest = document.createElement("code");
    digest.textContent = run.receiptDigest
      ? `SHA-256 ${{run.receiptDigest}}`
      : "Receipt digest unavailable";
    const state = document.createElement("em");
    state.textContent = run.outcome;
    detail.append(title, note, digest);
    row.append(detail, state);
    return row;
  }}));
}}

function render() {{
  renderActive();
  renderHistory();
}}

startForm.addEventListener("submit", event => {{
  event.preventDefault();
  const goal = goalInput.value.trim();
  if (!goal || activeRun()) return;
  runs.unshift({{
    schema: "neyvia.capability-run/v2",
    runId: globalThis.crypto?.randomUUID?.() || `${{Date.now()}}-${{Math.random().toString(16).slice(2)}}`,
    appFactoryJobId: config.appFactoryJobId,
    appId: config.appId,
    handoffId: config.handoffId,
    handoffDigest: config.handoffDigest,
    candidateDigest: config.candidateDigest,
    skillId: config.skillId,
    proofLease: config.proofLease,
    goal,
    status: "running",
    outcome: "completed",
    operatorValue: "helpful",
    friction: {{
      code: "none",
      severity: "none",
      correctionCount: 0,
      usualMinutes: null,
    }},
    proofNote: "",
    startedAt: new Date().toISOString(),
    completedAt: "",
    steps: config.workflowSteps.map(text => ({{
      text,
      complete: false,
      note: "",
      updatedAt: "",
    }})),
    candidateActivated: false,
    transcriptsIncluded: false,
  }});
  saveRuns();
  goalInput.value = "";
  render();
}});

proof.addEventListener("input", () => {{
  const run = activeRun();
  if (!run) return;
  run.proofNote = proof.value;
  saveRuns();
}});

outcome.addEventListener("change", () => {{
  const run = activeRun();
  if (!run) return;
  run.outcome = outcome.value;
  saveRuns();
}});

operatorValue.addEventListener("change", () => {{
  const run = activeRun();
  if (!run) return;
  run.operatorValue = operatorValue.value;
  saveRuns();
}});

frictionCode.addEventListener("change", () => {{
  const run = activeRun();
  if (!run) return;
  syncFrictionControls();
  run.friction.code = frictionCode.value;
  run.friction.severity = frictionSeverity.value;
  run.friction.correctionCount = Number(correctionCount.value);
  saveRuns();
}});

frictionSeverity.addEventListener("change", () => {{
  const run = activeRun();
  if (!run) return;
  run.friction.severity = frictionSeverity.value;
  saveRuns();
}});

correctionCount.addEventListener("input", () => {{
  const run = activeRun();
  if (!run) return;
  run.friction.correctionCount = Number(correctionCount.value);
  saveRuns();
}});

usualMinutes.addEventListener("input", () => {{
  const run = activeRun();
  if (!run) return;
  run.friction.usualMinutes = usualMinutes.value === ""
    ? null
    : Number(usualMinutes.value);
  saveRuns();
}});

completeButton.addEventListener("click", async () => {{
  const run = activeRun();
  if (!run) return;
  const incomplete = run.steps.filter(step => !step.complete).length;
  const proofNote = proof.value.trim();
  if (outcome.value === "completed" && incomplete) {{
    status.textContent = `${{incomplete}} workflow ${{incomplete === 1 ? "step remains" : "steps remain"}}.`;
    return;
  }}
  if (!proofNote) {{
    status.textContent = "Add a proof note before sealing the run receipt.";
    proof.focus();
    return;
  }}
  syncFrictionControls();
  const corrections = Number(correctionCount.value);
  const usual = usualMinutes.value === "" ? null : Number(usualMinutes.value);
  if (!Number.isInteger(corrections) || corrections < 0 || corrections > 100) {{
    status.textContent = "Corrections must be a whole number between 0 and 100.";
    correctionCount.focus();
    return;
  }}
  if (usual !== null && (!Number.isInteger(usual) || usual < 1 || usual > 10080)) {{
    status.textContent = "Usual-method minutes must be a whole number between 1 and 10080.";
    usualMinutes.focus();
    return;
  }}
  if (frictionCode.value !== "none" && frictionSeverity.value === "none") {{
    status.textContent = "Choose a severity for the reported friction.";
    frictionSeverity.focus();
    return;
  }}
  const completedAt = new Date().toISOString();
  const receipt = {{
    ...run,
    proofNote,
    outcome: outcome.value,
    operatorValue: operatorValue.value,
    friction: {{
      code: frictionCode.value,
      severity: frictionSeverity.value,
      correctionCount: corrections,
      usualMinutes: usual,
    }},
    status: "sealed",
    completedAt,
  }};
  delete receipt.receiptDigest;
  try {{
    Object.assign(run, receipt);
    run.receiptDigest = await sha256(receipt);
    saveRuns();
    status.textContent = "Run receipt sealed locally. Return it only when you choose.";
    render();
    goalInput.focus();
  }} catch (error) {{
    run.status = "running";
    run.completedAt = "";
    status.textContent = error instanceof Error ? error.message : String(error);
  }}
}});

function buildBundle() {{
  guardRuns();
  return {{
    schema: "neyvia.capability-run-bundle/v2",
    appFactoryJobId: config.appFactoryJobId,
    appId: config.appId,
    handoffId: config.handoffId,
    handoffDigest: config.handoffDigest,
    candidateDigest: config.candidateDigest,
    skillId: config.skillId,
    proofLease: config.proofLease,
    exportedAt: new Date().toISOString(),
    candidateActivated: false,
    transcriptsIncluded: false,
    runs: sealedRuns(),
  }};
}}

function downloadBundle(payload) {{
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }}));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${{config.appId.replaceAll(".", "-")}}-outcomes.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}}

returnButton.addEventListener("click", () => {{
  const payload = buildBundle();
  if (!payload.runs.length) return;
  if (window.parent !== window) {{
    window.parent.postMessage(
      {{ type: config.returnMessageType, bundle: payload }},
      window.location.origin,
    );
    status.textContent = "Typed outcomes sent to Neyvia for verification. Private run text will not be stored.";
    return;
  }}
  downloadBundle(payload);
  status.textContent = "Outcome bundle downloaded. Import it from Neyvia’s Compounding Loop.";
}});

exportButton.addEventListener("click", () => {{
  const payload = buildBundle();
  if (!payload.runs.length) return;
  downloadBundle(payload);
}});

render();
"""
    return {
        "src/index.html": index,
        "src/styles.css": css,
        "src/app.js": script,
    }


def _frontend_files(job: dict[str, Any]) -> dict[str, str]:
    spec = job["spec"]
    if spec["template"] == "capability":
        return _capability_frontend_files(job)
    name = spec["name"]
    brief = spec["brief"]
    template = spec["template"]
    copy = _starter_copy(template)
    theme = _theme_tokens(spec["theme"])
    config = {
        "schema": APP_FACTORY_CONFIG_SCHEMA,
        "appId": spec["appId"],
        "name": name,
        "brief": brief,
        "template": template,
        "revision": 1,
        "storageKey": f"neyvia.app-factory.{spec['appId']}.items.v1",
        **copy,
    }
    config_json = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    index = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="dark light" />
    <title>{html.escape(name)}</title>
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body data-neyvia-generated-app="{html.escape(spec['appId'])}">
    <main class="app-shell">
      <header class="app-intro">
        <div>
          <span class="eyebrow">LOCAL-FIRST · REVISION 1</span>
          <h1>{html.escape(name)}</h1>
          <p>{html.escape(brief)}</p>
        </div>
        <span class="local-state"><i></i> Saved on this device</span>
      </header>

      <section class="workbench" aria-labelledby="workspace-title">
        <div class="workbench-heading">
          <div>
            <span>FIRST USEFUL FLOW</span>
            <h2 id="workspace-title">{html.escape(copy['nounPlural'].title())}</h2>
          </div>
          <strong id="item-count">0 {html.escape(copy['nounPlural'])}</strong>
        </div>

        <form id="item-form" class="capture-row">
          <label for="item-input">{html.escape(copy['noun'].title())}</label>
          <div>
            <input id="item-input" maxlength="600" placeholder="{html.escape(copy['placeholder'])}" required />
            <button type="submit">{html.escape(copy['verb'])}</button>
          </div>
        </form>

        <div class="toolbar">
          <label for="item-search">Search saved {html.escape(copy['nounPlural'])}</label>
          <input id="item-search" type="search" placeholder="Filter locally…" />
          <button id="export-button" class="secondary" type="button">Export JSON</button>
        </div>

        <ol id="item-list" class="item-list" aria-live="polite"></ol>
        <div id="empty-state" class="empty-state">
          <strong>{html.escape(copy['emptyTitle'])}</strong>
          <p>{html.escape(copy['emptyDetail'])}</p>
        </div>
      </section>

      <footer>
        <span>Generated by Neyvia App Factory</span>
        <code>{html.escape(spec['appId'])}</code>
      </footer>
    </main>
    <script type="module" src="./app.js"></script>
  </body>
</html>
"""
    css = f"""* {{
  box-sizing: border-box;
}}

:root {{
  color: {theme['ink']};
  background: {theme['page']};
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-synthesis: none;
}}

body {{
  min-width: 320px;
  min-height: 100vh;
  margin: 0;
  background:
    radial-gradient(circle at 82% 0%, color-mix(in srgb, {theme['accent']} 17%, transparent), transparent 34rem),
    {theme['page']};
}}

button,
input {{
  font: inherit;
}}

button {{
  cursor: pointer;
}}

button:focus-visible,
input:focus-visible {{
  outline: 3px solid color-mix(in srgb, {theme['accent']} 54%, transparent);
  outline-offset: 2px;
}}

.app-shell {{
  width: min(980px, calc(100% - 40px));
  margin: 0 auto;
  padding: 72px 0 38px;
}}

.app-intro {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 32px;
  margin-bottom: 34px;
}}

.eyebrow,
.workbench-heading span {{
  color: {theme['accent']};
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .17em;
}}

h1 {{
  max-width: 760px;
  margin: 12px 0 10px;
  color: {theme['panelStrong']};
  font-size: clamp(42px, 8vw, 76px);
  line-height: .94;
  letter-spacing: -.065em;
}}

.app-intro p {{
  max-width: 670px;
  margin: 0;
  color: {theme['muted']};
  font-size: 17px;
  line-height: 1.6;
}}

.local-state {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: {theme['muted']};
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}}

.local-state i {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: {theme['accent']};
  box-shadow: 0 0 0 5px color-mix(in srgb, {theme['accent']} 12%, transparent);
}}

.workbench {{
  padding: clamp(22px, 5vw, 42px);
  border: 1px solid {theme['line']};
  border-radius: 28px;
  background: color-mix(in srgb, {theme['panel']} 95%, transparent);
  box-shadow: 0 28px 80px {theme['shadow']};
}}

.workbench-heading {{
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid {theme['line']};
}}

h2 {{
  margin: 6px 0 0;
  color: {theme['panelStrong']};
  font-size: 28px;
  letter-spacing: -.035em;
}}

.workbench-heading strong {{
  color: {theme['muted']};
  font-size: 12px;
}}

.capture-row {{
  margin-top: 28px;
}}

.capture-row > label,
.toolbar > label {{
  display: block;
  margin-bottom: 8px;
  color: {theme['muted']};
  font-size: 12px;
  font-weight: 750;
}}

.capture-row > div,
.toolbar {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}}

input {{
  width: 100%;
  min-height: 48px;
  padding: 0 15px;
  border: 1px solid {theme['line']};
  border-radius: 13px;
  color: {theme['ink']};
  background: color-mix(in srgb, {theme['page']} 58%, transparent);
}}

button {{
  min-height: 48px;
  padding: 0 18px;
  border: 0;
  border-radius: 13px;
  color: {theme['accentInk']};
  background: {theme['accent']};
  font-weight: 800;
}}

button.secondary {{
  border: 1px solid {theme['line']};
  color: {theme['ink']};
  background: transparent;
}}

.toolbar {{
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  margin-top: 20px;
}}

.toolbar label {{
  grid-column: 1 / -1;
  margin: 0;
}}

.item-list {{
  display: grid;
  gap: 10px;
  margin: 26px 0 0;
  padding: 0;
  list-style: none;
}}

.item {{
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 13px;
  padding: 14px;
  border: 1px solid {theme['line']};
  border-radius: 15px;
  background: color-mix(in srgb, {theme['page']} 45%, transparent);
}}

.item input {{
  width: 18px;
  min-height: 18px;
  accent-color: {theme['accent']};
}}

.item p {{
  margin: 0;
  line-height: 1.45;
  overflow-wrap: anywhere;
}}

.item[data-complete="true"] p {{
  color: {theme['muted']};
  text-decoration: line-through;
}}

.item button {{
  min-height: 34px;
  padding: 0 11px;
  border: 1px solid {theme['line']};
  color: {theme['muted']};
  background: transparent;
  font-size: 12px;
}}

.empty-state {{
  margin-top: 26px;
  padding: 38px 22px;
  border: 1px dashed {theme['line']};
  border-radius: 17px;
  text-align: center;
}}

.empty-state strong {{
  color: {theme['panelStrong']};
}}

.empty-state p {{
  max-width: 440px;
  margin: 8px auto 0;
  color: {theme['muted']};
  line-height: 1.5;
}}

footer {{
  display: flex;
  justify-content: space-between;
  gap: 18px;
  margin-top: 18px;
  color: {theme['muted']};
  font-size: 11px;
}}

footer code {{
  overflow-wrap: anywhere;
}}

@media (max-width: 680px) {{
  .app-shell {{
    width: min(100% - 24px, 980px);
    padding-top: 38px;
  }}

  .app-intro {{
    grid-template-columns: 1fr;
  }}

  .capture-row > div,
  .toolbar {{
    grid-template-columns: 1fr;
  }}

  footer {{
    flex-direction: column;
  }}
}}

@media (prefers-reduced-motion: reduce) {{
  *,
  *::before,
  *::after {{
    scroll-behavior: auto !important;
    transition-duration: .01ms !important;
    animation-duration: .01ms !important;
  }}
}}
"""
    script = f"""const config = {config_json};
const form = document.querySelector("#item-form");
const input = document.querySelector("#item-input");
const search = document.querySelector("#item-search");
const list = document.querySelector("#item-list");
const empty = document.querySelector("#empty-state");
const count = document.querySelector("#item-count");
const exportButton = document.querySelector("#export-button");

function readItems() {{
  try {{
    const value = JSON.parse(localStorage.getItem(config.storageKey) || "[]");
    return Array.isArray(value) ? value.filter(item => item && typeof item.text === "string") : [];
  }} catch {{
    return [];
  }}
}}

let items = readItems();

function saveItems() {{
  if (new Set(items.map(item => item.id)).size !== items.length
      || items.some(item => typeof item.text !== "string" || typeof item.complete !== "boolean")) {{
    throw new Error("Contract a.factory-notes-ui: saved entries lost unique identity or typed state.");
  }}
  const serialized = JSON.stringify(items);
  localStorage.setItem(config.storageKey, serialized);
  if (localStorage.getItem(config.storageKey) !== serialized) {{
    throw new Error("Contract a.factory-notes-ui: local entries did not persist exactly.");
  }}
}}

function render() {{
  const needle = String(search.value || "").trim().toLowerCase();
  const visible = items.filter(item => !needle || item.text.toLowerCase().includes(needle));
  list.replaceChildren(...visible.map(item => {{
    const row = document.createElement("li");
    row.className = "item";
    row.dataset.complete = item.complete ? "true" : "false";

    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = Boolean(item.complete);
    toggle.setAttribute("aria-label", `Mark ${{item.text}} complete`);
    toggle.addEventListener("change", () => {{
      item.complete = toggle.checked;
      item.updatedAt = new Date().toISOString();
      saveItems();
      render();
    }});

    const text = document.createElement("p");
    text.textContent = item.text;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {{
      items = items.filter(candidate => candidate.id !== item.id);
      saveItems();
      render();
    }});

    row.append(toggle, text, remove);
    return row;
  }}));

  empty.hidden = visible.length > 0;
  count.textContent = `${{items.length}} ${{items.length === 1 ? config.noun : config.nounPlural}}`;
  if (list.children.length !== visible.length || empty.hidden !== (visible.length > 0)) {{
    throw new Error("Contract a.factory-notes-ui: rendered search/count state disagrees with entries.");
  }}
}}

form.addEventListener("submit", event => {{
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  items.unshift({{
    id: globalThis.crypto?.randomUUID?.() || `${{Date.now()}}-${{Math.random().toString(16).slice(2)}}`,
    text,
    complete: false,
    createdAt: new Date().toISOString(),
  }});
  saveItems();
  input.value = "";
  render();
  input.focus();
}});

search.addEventListener("input", render);

exportButton.addEventListener("click", () => {{
  const payload = {{
    schema: "neyvia.local-app-export/v1",
    appId: config.appId,
    exportedAt: new Date().toISOString(),
    items,
  }};
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }}));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${{config.appId.replaceAll(".", "-")}}-export.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}});

render();
"""
    return {
        "src/index.html": index,
        "src/styles.css": css,
        "src/app.js": script,
    }


def _tauri_files(job: dict[str, Any]) -> dict[str, str | bytes]:
    spec = job["spec"]
    slug = spec["slug"]
    rust_name = _safe_rust_name(slug)
    identifier = f"local.neyvia.{slug.replace('-', '.')}"
    icon_png, icon_ico = _generated_app_icon(spec["theme"])
    config = {
        "$schema": "https://schema.tauri.app/config/2",
        "productName": spec["name"],
        "version": "0.1.0",
        "identifier": identifier,
        "build": {"frontendDist": "../dist"},
        "app": {
            "windows": [
                {
                    "label": "main",
                    "title": spec["name"],
                    "width": 1100,
                    "height": 760,
                    "minWidth": 720,
                    "minHeight": 520,
                    "resizable": True,
                    "center": True,
                }
            ],
            "security": {"csp": None},
        },
        "bundle": {"active": False},
    }
    cargo = f"""[package]
name = "{slug}"
version = "0.1.0"
description = "Local app generated by Neyvia App Factory"
authors = ["Neyvia App Factory"]
license = "MIT"
edition = "2021"

[build-dependencies]
tauri-build = {{ version = "=2.6.3", features = [] }}
tauri-codegen = {{ version = "=2.6.3" }}

[dependencies]
tauri = {{ version = "=2.11.5", features = [] }}
tauri-macros = {{ version = "=2.6.3" }}
tauri-runtime = {{ version = "=2.11.3" }}
tauri-runtime-wry = {{ version = "=2.11.4" }}

[[bin]]
name = "{slug}"
path = "src/main.rs"
"""
    main = f"""#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {{
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running {rust_name}");
}}
"""
    return {
        "src-tauri/Cargo.toml": cargo,
        "src-tauri/build.rs": "fn main() {\n    tauri_build::build()\n}\n",
        "src-tauri/src/main.rs": main,
        "src-tauri/tauri.conf.json": json.dumps(config, indent=2) + "\n",
        "src-tauri/capabilities/default.json": json.dumps(
            {
                "$schema": "../gen/schemas/desktop-schema.json",
                "identifier": "default",
                "description": "Default local window capability.",
                "windows": ["main"],
                "permissions": ["core:default"],
            },
            indent=2,
        )
        + "\n",
        "src-tauri/icons/icon.png": icon_png,
        "src-tauri/icons/icon.ico": icon_ico,
    }


def _project_metadata_files(job: dict[str, Any]) -> dict[str, str]:
    spec = job["spec"]
    preview_url = job["previewUrl"]
    handoff = (
        dict(job.get("capabilityHandoff") or {})
        if isinstance(job.get("capabilityHandoff"), dict)
        else {}
    )
    is_capability = spec["template"] == "capability"
    application_services = (
        ["shell-surfaces", "embedded-workspace"]
        if is_capability
        else [
            "tools",
            "artifacts",
            "evidence",
            "shell-surfaces",
            "embedded-workspace",
        ]
    )
    application_manifest = normalize_application_manifest(
        {
            "kind": "ecosystem-native",
            "applicationId": spec["appId"],
            "name": spec["name"],
            "summary": spec["brief"],
            "version": "0.1.0",
            "services": application_services,
            "provides": [
                {
                    "capabilityId": f"{spec['appId']}.open",
                    "label": f"Open {spec['name']}",
                }
            ],
            "permissions": [] if is_capability else ["workspace.read", "artifacts.write"],
            "surfaces": ["marketplace", "lab"],
            "presentations": ["fullscreen", "dock-right"],
            "entryPointUrl": preview_url,
            "marketplaceProposed": False,
            "provenance": {
                "publisher": "local.neyvia.app-factory",
                "origin": (
                    "neyvia-app-factory-capability-handoff"
                    if is_capability
                    else "neyvia-app-factory"
                ),
                "compatibility": "neyvia.application.contract.v1",
            },
        }
    )
    config = {
        "schema": APP_FACTORY_CONFIG_SCHEMA,
        "jobId": job["jobId"],
        "appId": spec["appId"],
        "name": spec["name"],
        "brief": spec["brief"],
        "target": spec["target"],
        "template": spec["template"],
        "theme": spec["theme"],
        "createdAt": job["createdAt"],
        "previewUrl": preview_url,
        "marketplace": {
            "state": "draft",
            "blockedBy": [
                "publisher-signature",
                "publisher-trust",
                "oci-attestation",
                "operator-activation",
            ],
        },
    }
    if is_capability:
        config["capabilityHandoff"] = {
            "handoffId": handoff.get("handoffId") or "",
            "handoffDigest": handoff.get("handoffDigest") or "",
            "appBindingDigest": handoff.get("appBindingDigest") or "",
            "materializationId": handoff.get("materializationId") or "",
            "approvedLineageId": handoff.get("approvedLineageId") or "",
            "parentLineageId": handoff.get("parentLineageId") or "",
            "skillId": handoff.get("skillId") or "",
            "candidateDigest": handoff.get("candidateDigest") or "",
            "proofLease": handoff.get("proofLease") or {},
            "candidateActivated": False,
            "appActivated": False,
        }
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "dataLicense": "CC0-1.0",
        "name": f"{spec['slug']}-app-factory-source",
        "documentNamespace": f"https://neyvia.local/app-factory/{job['jobId']}",
        "creationInfo": {
            "created": job["createdAt"],
            "creators": ["Tool: Neyvia App Factory"],
        },
        "packages": [],
    }
    readme_lines = [
        f"# {spec['name']}",
        "",
        spec["brief"],
        "",
        "Generated by Neyvia App Factory as a real local-first starter.",
        "",
        "## Preview",
        "",
        "Open the project through App Factory, or serve `dist/` with any local static server.",
        "",
    ]
    if is_capability:
        readme_lines.extend(
            [
                "## Verified capability source",
                "",
                f"- Skill: `{handoff.get('skillId') or ''}`",
                f"- Handoff: `{handoff.get('handoffId') or ''}`",
                f"- Handoff digest: `{handoff.get('handoffDigest') or ''}`",
                f"- Candidate digest: `{handoff.get('candidateDigest') or ''}`",
                "",
                "The exact sealed `SKILL.md` and `agents/openai.yaml` are retained under",
                "`source/skill/`. `neyvia.capability-lineage.json` binds those hashes to",
                "this app specification and its qualifying comparison evidence.",
                "",
                "## Guided-runner boundary",
                "",
                "This draft turns the skill's explicit workflow steps into a local guided runner.",
                "It stores completed runs in browser/WebView local storage, seals each completed",
                "run with canonical SHA-256 receipts, and returns outcomes only after an explicit",
                "operator action. Embedded previews send the sealed bundle to Neyvia for",
                "verification; standalone/native builds export the same JSON for manual import.",
                "Neyvia persists typed outcomes, timing, and friction, not the private goal, proof",
                "note, or step notes carried transiently in the receipt verification boundary.",
                "It does not invoke an agent or widen the tested skill's authority.",
                "",
            ]
        )
    else:
        readme_lines.extend(
            [
                "## Data",
                "",
                "The first useful flow saves its records in browser/WebView local storage and exports JSON.",
                "",
            ]
        )
    if spec["target"] == "desktop":
        readme_lines.extend(
            [
                "## Native desktop build",
                "",
                "```powershell",
                "cargo build --manifest-path src-tauri/Cargo.toml --release",
                "```",
                "",
                "Neyvia's Build native app action runs the same command and records the executable hash.",
                "",
            ]
        )
    readme_lines.extend(
        [
            "## Marketplace boundary",
            "",
            "This workspace is a local App Factory draft. Signing, publisher trust, OCI evidence,",
            "permission review, and activation remain separate Marketplace gates.",
            "",
        ]
    )
    context = {
        "schema": "neyvia.app-factory-context/v1",
        "summary": spec["brief"],
        "jobId": job["jobId"],
        "appId": spec["appId"],
    }
    result = {
        "neyvia.app-factory.json": json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        "neyvia.application.json": json.dumps(application_manifest, indent=2, ensure_ascii=False) + "\n",
        "context/index.json": "",
        "sbom.spdx.json": json.dumps(sbom, indent=2, ensure_ascii=False) + "\n",
        ".gitignore": "target/\nnode_modules/\n.neyvia/build/\n.env*\n",
        "README.md": "\n".join(readme_lines),
    }
    if is_capability:
        lineage = {
            "schema": "neyvia.capability-app-lineage/v1",
            "jobId": job["jobId"],
            "appId": spec["appId"],
            "handoffId": handoff.get("handoffId") or "",
            "handoffDigest": handoff.get("handoffDigest") or "",
            "appBindingDigest": handoff.get("appBindingDigest") or "",
            "materializationId": handoff.get("materializationId") or "",
            "trialId": handoff.get("trialId") or "",
            "approvedLineageId": handoff.get("approvedLineageId") or "",
            "parentLineageId": handoff.get("parentLineageId") or "",
            "skillId": handoff.get("skillId") or "",
            "candidateDigest": handoff.get("candidateDigest") or "",
            "source": {
                "skillPath": "source/skill/SKILL.md",
                "metadataPath": "source/skill/agents/openai.yaml",
                "skillSha256": handoff.get("skillSha256") or "",
                "metadataSha256": handoff.get("metadataSha256") or "",
            },
            "evidenceSummary": handoff.get("evidenceSummary") or {},
            "proofLease": handoff.get("proofLease") or {},
            "reviewBoundary": (handoff.get("review") or {}).get("boundary")
            if isinstance(handoff.get("review"), dict)
            else "",
            "candidateActivated": False,
            "appActivated": False,
            "transcriptsIncluded": False,
        }
        context["capabilityHandoff"] = {
            key: lineage[key]
            for key in (
                "handoffId",
                "handoffDigest",
                "appBindingDigest",
                "skillId",
                "candidateDigest",
                "proofLease",
                "candidateActivated",
                "appActivated",
                "transcriptsIncluded",
            )
        }
        result["neyvia.capability-lineage.json"] = (
            json.dumps(lineage, indent=2, ensure_ascii=False) + "\n"
        )
    result["context/index.json"] = (
        json.dumps(context, indent=2, ensure_ascii=False) + "\n"
    )
    return result


def _write_expected_file(path: Path, content: str | bytes) -> None:
    encoded = content.encode("utf-8") if isinstance(content, str) else content
    if path.exists():
        if not path.is_file() or path.read_bytes() != encoded:
            raise RuntimeError(
                f"Resume stopped because a generated file changed outside App Factory: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def _copy_expected_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"Generated source file is missing: {source}")
    content = source.read_bytes()
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != content:
            raise RuntimeError(
                f"Resume stopped because an assembled file changed outside App Factory: {destination}"
            )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def _deterministic_archive(project_root: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f"{output_path.name}.{uuid.uuid4().hex}.tmp")
    files = [
        path
        for path in project_root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.relative_to(project_root).as_posix() != "src-tauri/Cargo.lock"
        and path.relative_to(project_root).parts[:2] != ("src-tauri", "gen")
        and not any(part in _ARCHIVE_EXCLUDED_PARTS for part in path.relative_to(project_root).parts)
    ]
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(project_root).as_posix()):
            relative = path.relative_to(project_root).as_posix()
            info = ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    os.replace(temporary, output_path)
    return {
        "path": str(output_path),
        "sha256": _sha256(output_path),
        "bytes": output_path.stat().st_size,
        "mediaType": "application/vnd.neyvia.app-factory+zip",
        "fileCount": len(files),
    }


def _project_source_digest(project_root: Path) -> str:
    """Hash the editable project and assembled preview, excluding local build output."""
    digest = hashlib.sha256()
    if not project_root.is_dir():
        return digest.hexdigest()
    for path in sorted(
        (
            item
            for item in project_root.rglob("*")
            if item.is_file()
            and not item.is_symlink()
            and item.relative_to(project_root).as_posix() != "src-tauri/Cargo.lock"
            and item.relative_to(project_root).parts[:2] != ("src-tauri", "gen")
            and "dist" not in item.relative_to(project_root).parts
            and not any(
                part in _ARCHIVE_EXCLUDED_PARTS
                for part in item.relative_to(project_root).parts
            )
        ),
        key=lambda item: item.relative_to(project_root).as_posix(),
    ):
        relative = path.relative_to(project_root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _replace_generated_file(path: Path, content: bytes) -> None:
    """Atomically refresh derived output such as dist/ from the current source."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _stage_rows() -> list[dict[str, Any]]:
    labels = {
        "brief": "Brief",
        "scaffold": "Scaffold",
        "assemble": "Assemble",
        "verify": "Source/package checks",
        "register": "Register",
    }
    return [
        {
            "id": stage_id,
            "label": labels[stage_id],
            "state": "pending",
            "startedAt": "",
            "completedAt": "",
            "durationMs": None,
            "detail": "",
            "artifacts": [],
        }
        for stage_id in APP_FACTORY_STAGE_IDS
    ]


class AppFactory:
    """Create, resume, inspect, preview, and compile local application jobs."""

    def __init__(self, root: str | Path) -> None:
        self.root = _resolved_workspace(root)
        self.state_root = self.root / APP_FACTORY_ROOT
        self.jobs_root = self.root / APP_FACTORY_JOBS
        self.registry_path = self.root / APP_FACTORY_REGISTRY
        self.handoffs_root = self.root / APP_FACTORY_HANDOFFS
        configured_cargo_target = str(
            os.environ.get("NEYVIA_APP_FACTORY_CARGO_TARGET") or ""
        ).strip()
        self.cargo_target = (
            Path(configured_cargo_target).expanduser().resolve()
            if configured_cargo_target
            else self.root / APP_FACTORY_CARGO_TARGET
        )

    def _job_path(self, job_id: str) -> Path:
        value = str(job_id or "").strip()
        if not _SAFE_JOB_ID.fullmatch(value):
            raise RuntimeError("App Factory job id is invalid.")
        return self.jobs_root / f"{value}.json"

    def _save_job(self, job: dict[str, Any]) -> None:
        job["updatedAt"] = _utc_now()
        _atomic_json(self._job_path(job["jobId"]), job)

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        job = _read_json(path, {})
        if not isinstance(job, dict) or job.get("schema") != APP_FACTORY_JOB_SCHEMA:
            raise RuntimeError(f"App Factory job was not found: {job_id}")
        self._invalidate_stale_claims(job)
        return self._with_install_state(self._refresh_native_state(job))

    def list_jobs(self, *, limit: int = 40) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        if self.jobs_root.exists():
            for path in self.jobs_root.glob("*.json"):
                value = _read_json(path, {})
                if isinstance(value, dict) and value.get("schema") == APP_FACTORY_JOB_SCHEMA:
                    self._invalidate_stale_claims(value)
                    jobs.append(self._with_install_state(self._refresh_native_state(value)))
        jobs.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        return jobs[: max(1, min(int(limit or 40), 200))]

    @staticmethod
    def _with_install_state(job: dict[str, Any]) -> dict[str, Any]:
        if os.name == "nt":
            from .local_app_install import LocalAppInstall
            try:
                job["installation"] = LocalAppInstall().state(job)
            except (OSError, RuntimeError, ValueError) as exc:
                job["installation"] = {"state": "unavailable", "error": str(exc)}
        return job

    def install_native(self, job_id: str) -> dict[str, Any]:
        from .local_app_install import LocalAppInstall
        job = self.get_job(job_id)
        job["installation"] = LocalAppInstall().install(job)
        self._save_job(job)
        return job

    def rollback_native_install(self, job_id: str) -> dict[str, Any]:
        from .local_app_install import LocalAppInstall
        job = self.get_job(job_id)
        job["installation"] = LocalAppInstall().rollback(job)
        self._save_job(job)
        return job

    def _validate_capability_handoff(
        self,
        value: dict[str, Any],
    ) -> tuple[dict[str, Any], Path, Path]:
        capsule = dict(value or {})
        if capsule.get("schema") != APP_FACTORY_HANDOFF_SCHEMA:
            raise RuntimeError("The capability handoff schema is unsupported.")
        handoff_id = str(capsule.get("handoffId") or "")
        if not _SAFE_HANDOFF_ID.fullmatch(handoff_id):
            raise RuntimeError("The capability handoff id is invalid.")
        skill_id = str(capsule.get("skillId") or "")
        if not _SAFE_SKILL_ID.fullmatch(skill_id):
            raise RuntimeError("The capability handoff skill id is invalid.")
        handoff_digest = str(capsule.get("handoffDigest") or "")
        if (
            not _SAFE_SHA256.fullmatch(handoff_digest)
            or _canonical_digest(_stable_handoff_contract(capsule))
            != handoff_digest
        ):
            raise RuntimeError(
                "The capability handoff digest does not match its sealed lineage."
            )
        for field in (
            "candidateDigest",
            "skillSha256",
            "metadataSha256",
            "forgeDigest",
        ):
            if not _SAFE_SHA256.fullmatch(str(capsule.get(field) or "")):
                raise RuntimeError(
                    f"The capability handoff {field} is not a SHA-256 digest."
                )
        if (
            capsule.get("state") != "reviewed_for_local_draft"
            or capsule.get("candidateActivated") is not False
            or capsule.get("appActivated") is not False
            or capsule.get("transcriptsIncluded") is not False
        ):
            raise RuntimeError(
                "The capability handoff is not an inactive, reviewed local-draft source."
            )
        review = (
            dict(capsule.get("review") or {})
            if isinstance(capsule.get("review"), dict)
            else {}
        )
        if review.get("confirmed") is not True or not str(
            review.get("boundary") or ""
        ).strip():
            raise RuntimeError(
                "The capability handoff has no explicit operator review boundary."
            )
        workflow_steps = capsule.get("workflowSteps")
        if (
            not isinstance(workflow_steps, list)
            or not 1 <= len(workflow_steps) <= 12
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item.strip()) > 800
                for item in workflow_steps
            )
        ):
            raise RuntimeError(
                "The capability handoff has no bounded, explicit workflow."
            )
        authority = (
            dict(capsule.get("authorityComparison") or {})
            if isinstance(capsule.get("authorityComparison"), dict)
            else {}
        )
        if (
            authority.get("gatePassed") is not True
            or authority.get("status") not in {"unchanged", "reduced"}
        ):
            raise RuntimeError(
                "The capability handoff does not preserve the approved authority boundary."
            )
        proof_lease = (
            dict(capsule.get("proofLease") or {})
            if isinstance(capsule.get("proofLease"), dict)
            else {}
        )
        if proof_lease:
            if (
                proof_lease.get("schema")
                != "neyvia.capability_proof_lease.v1"
                or proof_lease.get("state") != "current"
                or proof_lease.get("materializationId")
                != capsule.get("materializationId")
                or proof_lease.get("candidateActivated") is not False
                or proof_lease.get("transcriptsIncluded") is not False
                or any(
                    not _SAFE_SHA256.fullmatch(
                        str(proof_lease.get(field) or "")
                    )
                    for field in (
                        "leaseDigest",
                        "goalDigest",
                        "proofRoutesDigest",
                        "dependenciesDigest",
                    )
                )
            ):
                raise RuntimeError(
                    "The capability handoff proof lease is incomplete or changed."
                )
        evidence = (
            dict(capsule.get("evidenceSummary") or {})
            if isinstance(capsule.get("evidenceSummary"), dict)
            else {}
        )
        comparison_runs = capsule.get("comparisonRuns")
        if (
            not isinstance(comparison_runs, list)
            or not comparison_runs
            or int(evidence.get("qualifyingRunCount") or 0)
            != len(comparison_runs)
            or evidence.get("transcriptsIncluded") is not False
            or any(
                not isinstance(item, dict)
                or item.get("candidatePackageDigest")
                != capsule.get("candidateDigest")
                or item.get("transcriptsIncluded") is not False
                or not _SAFE_SHA256.fullmatch(
                    str(item.get("receiptPairDigest") or "")
                )
                for item in comparison_runs
            )
        ):
            raise RuntimeError(
                "The capability handoff comparison evidence is incomplete or changed."
            )
        source = (
            dict(capsule.get("sourcePackage") or {})
            if isinstance(capsule.get("sourcePackage"), dict)
            else {}
        )
        skill_path = Path(str(source.get("skillPath") or "")).expanduser().resolve()
        metadata_path = (
            Path(str(source.get("metadataPath") or "")).expanduser().resolve()
        )
        if (
            not skill_path.is_file()
            or not metadata_path.is_file()
            or skill_path.is_symlink()
            or metadata_path.is_symlink()
            or _sha256(skill_path) != capsule["skillSha256"]
            or _sha256(metadata_path) != capsule["metadataSha256"]
        ):
            raise RuntimeError(
                "The exact materialized skill source is missing or changed."
            )
        return capsule, skill_path, metadata_path

    def _copy_capability_handoff(
        self,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        capsule, skill_path, metadata_path = self._validate_capability_handoff(
            value
        )
        handoff_id = str(capsule["handoffId"])
        skill_id = str(capsule["skillId"])
        handoff_root = self.handoffs_root / handoff_id
        copied_skill_root = handoff_root / "source" / skill_id
        copied_skill_path = copied_skill_root / "SKILL.md"
        copied_metadata_path = copied_skill_root / "agents" / "openai.yaml"
        receipt_path = handoff_root / "handoff.json"
        existing = _read_json(receipt_path, {})
        if handoff_root.exists():
            if (
                not isinstance(existing, dict)
                or existing.get("schema") != APP_FACTORY_HANDOFF_RECEIPT_SCHEMA
                or existing.get("handoffDigest")
                != capsule.get("handoffDigest")
                or not copied_skill_path.is_file()
                or not copied_metadata_path.is_file()
                or _sha256(copied_skill_path) != capsule["skillSha256"]
                or _sha256(copied_metadata_path)
                != capsule["metadataSha256"]
            ):
                raise RuntimeError(
                    "The App Factory handoff store conflicts with this sealed source."
                )
        else:
            self.handoffs_root.mkdir(parents=True, exist_ok=True)
            temporary_root = self.handoffs_root / (
                f".{handoff_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            )
            try:
                temporary_skill_root = (
                    temporary_root / "source" / skill_id
                )
                temporary_metadata_root = (
                    temporary_skill_root / "agents"
                )
                temporary_metadata_root.mkdir(parents=True, exist_ok=False)
                (temporary_skill_root / "SKILL.md").write_bytes(
                    skill_path.read_bytes()
                )
                (temporary_metadata_root / "openai.yaml").write_bytes(
                    metadata_path.read_bytes()
                )
                receipt = {
                    "schema": APP_FACTORY_HANDOFF_RECEIPT_SCHEMA,
                    "handoffId": handoff_id,
                    "handoffDigest": capsule["handoffDigest"],
                    "materializationId": capsule["materializationId"],
                    "trialId": capsule["trialId"],
                    "approvedLineageId": capsule["approvedLineageId"],
                    "parentLineageId": capsule["parentLineageId"],
                    "skillId": skill_id,
                    "candidateDigest": capsule["candidateDigest"],
                    "forgeId": capsule["forgeId"],
                    "forgeDigest": capsule["forgeDigest"],
                    "evidenceSummary": capsule["evidenceSummary"],
                    "review": capsule["review"],
                    "source": {
                        "skillPath": f"source/{skill_id}/SKILL.md",
                        "metadataPath": (
                            f"source/{skill_id}/agents/openai.yaml"
                        ),
                        "skillSha256": capsule["skillSha256"],
                        "metadataSha256": capsule["metadataSha256"],
                    },
                    "state": "source_copied",
                    "candidateActivated": False,
                    "appActivated": False,
                    "transcriptsIncluded": False,
                    "copiedAt": _utc_now(),
                    "jobId": "",
                }
                if isinstance(capsule.get("proofLease"), dict):
                    receipt["proofLease"] = dict(
                        capsule["proofLease"]
                    )
                _atomic_json(temporary_root / "handoff.json", receipt)
                os.replace(temporary_root, handoff_root)
            except Exception:
                if temporary_root.exists():
                    shutil.rmtree(temporary_root)
                raise
        return {
            **_stable_handoff_contract(capsule),
            "handoffDigest": capsule["handoffDigest"],
            "state": "reviewed_for_local_draft",
            "label": str(capsule.get("label") or skill_id),
            "description": str(capsule.get("description") or ""),
            "evidenceSummary": dict(capsule["evidenceSummary"]),
            "review": dict(capsule["review"]),
            "sourcePackage": {
                "path": str(copied_skill_root),
                "skillPath": str(copied_skill_path),
                "metadataPath": str(copied_metadata_path),
                "receiptPath": str(receipt_path),
                "skillSha256": capsule["skillSha256"],
                "metadataSha256": capsule["metadataSha256"],
            },
        }

    def _update_handoff_receipt(
        self,
        handoff: dict[str, Any],
        job: dict[str, Any] | None,
        *,
        error: str = "",
    ) -> None:
        updated_at = _utc_now()
        error_message = str(error or "").strip()
        source = (
            dict(handoff.get("sourcePackage") or {})
            if isinstance(handoff.get("sourcePackage"), dict)
            else {}
        )
        receipt_path = Path(str(source.get("receiptPath") or ""))
        receipt = _read_json(receipt_path, {})
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema") != APP_FACTORY_HANDOFF_RECEIPT_SCHEMA
            or receipt.get("handoffDigest") != handoff.get("handoffDigest")
        ):
            raise RuntimeError(
                "The App Factory handoff receipt is missing or changed."
            )
        if job:
            receipt.update(
                {
                    "state": (
                        "draft_ready"
                        if job.get("status") == "ready"
                        else (
                            "needs_attention"
                            if error
                            or job.get("status")
                            in {"failed", "needs_attention"}
                            else "building"
                        )
                    ),
                    "jobId": job.get("jobId") or "",
                    "appId": (job.get("spec") or {}).get("appId") or "",
                    "appBindingDigest": handoff.get("appBindingDigest") or "",
                    "jobStatus": job.get("status") or "",
                    "verification": job.get("verification") or {},
                    "package": job.get("package") or {},
                    "registration": job.get("registration") or {},
                    "candidateActivated": False,
                    "appActivated": False,
                    "updatedAt": updated_at,
                    "error": (
                        ""
                        if job.get("status") == "ready"
                        else error_message
                    ),
                }
            )
            if error_message and job.get("status") == "ready":
                receipt["lastRejectedRequest"] = {
                    "at": updated_at,
                    "reason": error_message,
                }
        else:
            receipt.update(
                {
                    "state": "needs_attention",
                    "updatedAt": updated_at,
                    "error": error_message,
                }
            )
        _atomic_json(receipt_path, receipt)

    def create_from_capability_handoff(
        self,
        handoff: dict[str, Any],
        *,
        name: object,
        brief: object,
        target: object = "neyvia",
        theme: object = "midnight",
        directory: object = "",
    ) -> dict[str, Any]:
        # The copied source, idempotent job lookup and receipt readback share
        # one capsule lease. Locking only the directory replacement allows
        # competing callers to create different jobs for the same handoff.
        from .harness_jobs import _exclusive_job_lock
        capsule, _, _ = self._validate_capability_handoff(handoff)
        self.handoffs_root.mkdir(parents=True, exist_ok=True)
        lease_path = self.handoffs_root / str(capsule["handoffId"])
        with _exclusive_job_lock(lease_path, timeout_seconds=30):
            return self._create_from_capability_handoff_locked(
                handoff, name=name, brief=brief, target=target,
                theme=theme, directory=directory,
            )

    @checked_action(check_factory_lineage)
    def _create_from_capability_handoff_locked(
        self,
        handoff: dict[str, Any],
        *,
        name: object,
        brief: object,
        target: object = "neyvia",
        theme: object = "midnight",
        directory: object = "",
    ) -> dict[str, Any]:
        copied = self._copy_capability_handoff(handoff)
        try:
            job = self.create(
                name=name,
                brief=brief,
                target=target,
                template="capability",
                theme=theme,
                directory=directory,
                capability_handoff=copied,
            )
        except Exception as exc:
            failed_job = next(
                (
                    item
                    for item in self.list_jobs(limit=200)
                    if (
                        (
                            item.get("capabilityHandoff")
                            if isinstance(
                                item.get("capabilityHandoff"),
                                dict,
                            )
                            else {}
                        ).get("handoffId")
                        == copied.get("handoffId")
                    )
                ),
                None,
            )
            self._update_handoff_receipt(
                (
                    dict(failed_job.get("capabilityHandoff") or {})
                    if isinstance(failed_job, dict)
                    and isinstance(
                        failed_job.get("capabilityHandoff"),
                        dict,
                    )
                    else copied
                ),
                failed_job,
                error=str(exc),
            )
            raise
        self._update_handoff_receipt(
            (
                dict(job.get("capabilityHandoff") or {})
                if isinstance(job.get("capabilityHandoff"), dict)
                else copied
            ),
            job,
        )
        return job

    def catalog(self) -> dict[str, Any]:
        jobs = self.list_jobs(limit=200)
        cargo = shutil.which("cargo")
        rustc = shutil.which("rustc")
        try:
            native_disk = shutil.disk_usage(
                self.cargo_target.anchor or self.cargo_target.parent
            )
            native_free_bytes = native_disk.free
        except OSError:
            native_free_bytes = 0
        native_disk_ready = native_free_bytes >= 2 * 1024 * 1024 * 1024
        return {
            "schema": APP_FACTORY_SCHEMA,
            "generatedAt": _utc_now(),
            "workspaceRoot": str(self.root),
            "jobs": jobs[:40],
            "summary": {
                "total": len(jobs),
                "ready": sum(item.get("status") == "ready" for item in jobs),
                "building": sum(
                    str((item.get("nativeBuild") or {}).get("state") or "")
                    in {"queued", "running"}
                    for item in jobs
                ),
                "needsAttention": sum(
                    item.get("status") in {"failed", "needs_attention"} for item in jobs
                ),
            },
            "targets": [
                {
                    "id": "desktop",
                    "label": "Native desktop",
                    "detail": "Dependency-free local frontend plus a Tauri 2 native shell.",
                    "available": bool(cargo and rustc and native_disk_ready),
                    "readiness": (
                        "Cargo, Rust, and native build-cache space are available."
                        if cargo and rustc and native_disk_ready
                        else (
                            "Cargo and Rust are available, but the native build cache "
                            "needs at least 2 GB free."
                        )
                        if cargo and rustc
                        else "Preview works, but native compilation needs Cargo and Rust."
                    ),
                    "cargoCacheRoot": str(self.cargo_target),
                    "cargoCacheFreeBytes": native_free_bytes,
                },
                {
                    "id": "neyvia",
                    "label": "Neyvia local app",
                    "detail": "Fast authenticated local preview and App Factory registration.",
                    "available": True,
                    "readiness": "Ready without installing project dependencies.",
                },
                {
                    "id": "ios-studio",
                    "label": "iPhone / iPad",
                    "detail": "Continue through the existing iOS Studio and its separate Apple proof gates.",
                    "available": True,
                    "readiness": "Authoring route available; native Apple proof remains separate.",
                },
            ],
            "pipeline": [
                {"id": "brief", "role": "planner", "parallelSafe": False},
                {"id": "scaffold", "role": "builder", "parallelSafe": False},
                {"id": "assemble", "role": "builder", "parallelSafe": True},
                {"id": "verify", "role": "verifier", "parallelSafe": True},
                {"id": "register", "role": "release-steward", "parallelSafe": False},
            ],
            "marketplaceBoundary": (
                "Factory registration enables a local draft preview. Marketplace publication "
                "still requires signing, publisher trust, OCI evidence, permission review, and activation."
            ),
        }

    @checked_action(check_factory_job)
    def create(
        self,
        *,
        name: object,
        brief: object,
        target: object = "desktop",
        template: object = "auto",
        theme: object = "midnight",
        directory: object = "",
        capability_handoff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        app_name = _clean_text(name, minimum=2, maximum=80, label="App name")
        app_brief = _clean_text(brief, minimum=12, maximum=900, label="App brief")
        target_id = str(target or "desktop").strip().lower()
        if target_id not in SUPPORTED_TARGETS:
            raise RuntimeError(f"Unsupported App Factory target: {target_id or '(blank)'}")
        theme_id = str(theme or "midnight").strip().lower()
        if theme_id not in SUPPORTED_THEMES:
            raise RuntimeError(f"Unsupported App Factory theme: {theme_id or '(blank)'}")
        template_id = _template_for(app_brief, str(template or "auto"))
        capability = (
            dict(capability_handoff)
            if isinstance(capability_handoff, dict)
            else {}
        )
        if template_id == "capability" and not capability:
            raise RuntimeError(
                "A guided capability app requires a reviewed lineage handoff."
            )
        if capability and template_id != "capability":
            raise RuntimeError(
                "A capability lineage handoff can only create the guided capability starter."
            )
        if capability:
            handoff_id = str(capability.get("handoffId") or "")
            if (
                not _SAFE_HANDOFF_ID.fullmatch(handoff_id)
                or capability.get("schema") != APP_FACTORY_HANDOFF_SCHEMA
            ):
                raise RuntimeError("The copied capability handoff is invalid.")
            source = (
                dict(capability.get("sourcePackage") or {})
                if isinstance(capability.get("sourcePackage"), dict)
                else {}
            )
            copied_root = (
                self.handoffs_root / handoff_id / "source"
            ).resolve()
            copied_skill_path = Path(
                str(source.get("skillPath") or "")
            ).resolve()
            copied_metadata_path = Path(
                str(source.get("metadataPath") or "")
            ).resolve()
            try:
                copied_skill_path.relative_to(copied_root)
                copied_metadata_path.relative_to(copied_root)
            except ValueError as exc:
                raise RuntimeError(
                    "The capability source is outside the App Factory handoff store."
                ) from exc
            if (
                capability.get("state") != "reviewed_for_local_draft"
                or capability.get("candidateActivated") is not False
                or capability.get("appActivated") is not False
                or capability.get("transcriptsIncluded") is not False
                or _canonical_digest(
                    _stable_handoff_contract(capability)
                )
                != capability.get("handoffDigest")
                or not copied_skill_path.is_file()
                or not copied_metadata_path.is_file()
                or _sha256(copied_skill_path)
                != capability.get("skillSha256")
                or _sha256(copied_metadata_path)
                != capability.get("metadataSha256")
            ):
                raise RuntimeError(
                    "The copied capability handoff is missing or changed."
                )
        slug = _slug(app_name)
        app_id = f"local.{slug.replace('-', '.')}"
        if not _SAFE_APP_ID.fullmatch(app_id):
            raise RuntimeError("The generated local application id is invalid.")
        requested_directory = str(directory or f"apps/{slug}").strip()
        project_root = _safe_child(self.root, requested_directory)
        relative_directory = str(project_root.relative_to(self.root)).replace(
            "\\", "/"
        )
        if capability:
            app_binding_digest = _capability_binding_digest(
                str(capability["handoffDigest"]),
                app_id=app_id,
                name=app_name,
                brief=app_brief,
                target=target_id,
                theme=theme_id,
                directory=relative_directory,
            )
            capability["appBindingDigest"] = app_binding_digest
            for existing in self.list_jobs(limit=200):
                existing_handoff = (
                    dict(existing.get("capabilityHandoff") or {})
                    if isinstance(existing.get("capabilityHandoff"), dict)
                    else {}
                )
                if existing_handoff.get("handoffId") != capability["handoffId"]:
                    continue
                if (
                    existing_handoff.get("appBindingDigest")
                    != app_binding_digest
                ):
                    raise RuntimeError(
                        "This sealed capability already has an App Factory draft "
                        "with a different app specification. Continue that draft "
                        "or withdraw it before changing the binding."
                    )
                return self.resume(str(existing["jobId"]))
        if project_root.exists() and any(project_root.iterdir()):
            raise RuntimeError(f"The target folder is not empty: {project_root}")
        for existing in self.list_jobs(limit=200):
            if (existing.get("spec") or {}).get("appId") == app_id:
                raise RuntimeError(
                    f"{app_name} already has an App Factory job. Open that job and continue it."
                )

        job_id = f"app-{_job_timestamp()}-{uuid.uuid4().hex[:8]}"
        preview_url = f"/api/app-factory/{job_id}/"
        now = _utc_now()
        job = {
            "schema": APP_FACTORY_JOB_SCHEMA,
            "jobId": job_id,
            "status": "draft",
            "currentStage": "brief",
            "createdAt": now,
            "updatedAt": now,
            "projectRoot": str(project_root),
            "previewUrl": preview_url,
            "spec": {
                "appId": app_id,
                "slug": slug,
                "name": app_name,
                "brief": app_brief,
                "target": target_id,
                "template": template_id,
                "theme": theme_id,
                "directory": relative_directory,
            },
            "stages": _stage_rows(),
            "artifacts": [],
            "verification": {
                "state": "pending",
                "checks": [],
                "verifiedAt": "",
            },
            "registration": {
                "state": "pending",
                "registryPath": str(self.registry_path),
            },
            "marketplace": {
                "state": "draft",
                "eligible": True,
                "blockedBy": [
                    "publisher-signature",
                    "publisher-trust",
                    "oci-attestation",
                    "operator-activation",
                ],
            },
            "nativeBuild": {
                "state": "not_applicable" if target_id != "desktop" else "not_started",
                "processId": None,
                "artifactPath": "",
                "sha256": "",
                "bytes": 0,
                "lockfilePath": "",
                "lockfileSha256": "",
                "logPath": str(self.state_root / "native-builds" / f"{job_id}.log"),
                "startedAt": "",
                "completedAt": "",
                "error": "",
            },
            "agentHandoff": {
                "state": "available",
                "roles": ["planner", "builder", "verifier", "release-steward"],
                "prompt": "",
            },
            "error": "",
        }
        if capability:
            job["capabilityHandoff"] = capability
        job["agentHandoff"]["prompt"] = self._agent_prompt(job)
        self._save_job(job)
        return self.resume(job_id)

    @checked_action(check_factory_job)
    def resume(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "brief": self._stage_brief,
            "scaffold": self._stage_scaffold,
            "assemble": self._stage_assemble,
            "verify": self._stage_verify,
            "register": self._stage_register,
        }
        job["error"] = ""
        for stage_id in APP_FACTORY_STAGE_IDS:
            stage = self._stage(job, stage_id)
            if stage["state"] == "completed":
                continue
            job["currentStage"] = stage_id
            job["status"] = "running"
            stage["state"] = "running"
            stage["startedAt"] = _utc_now()
            stage["completedAt"] = ""
            stage["detail"] = ""
            stage["artifacts"] = []
            started = time.perf_counter()
            self._save_job(job)
            try:
                result = handlers[stage_id](job)
            except Exception as exc:
                stage["state"] = "failed"
                stage["completedAt"] = _utc_now()
                stage["durationMs"] = int((time.perf_counter() - started) * 1000)
                stage["detail"] = str(exc)
                job["status"] = "failed"
                job["error"] = str(exc)
                self._save_job(job)
                raise
            stage["state"] = "completed"
            stage["completedAt"] = _utc_now()
            stage["durationMs"] = int((time.perf_counter() - started) * 1000)
            stage["detail"] = str(result.get("detail") or f"{stage['label']} completed.")
            stage["artifacts"] = list(result.get("artifacts") or [])
            if result.get("sourceSha256"):
                stage["sourceSha256"] = result["sourceSha256"]
            self._save_job(job)
        job["currentStage"] = "ready"
        job["status"] = "ready"
        job["agentHandoff"]["prompt"] = self._agent_prompt(job)
        self._save_job(job)
        return job

    def start_native_build(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if any(
            self._stage(job, stage_id).get("state") != "completed"
            for stage_id in APP_FACTORY_STAGE_IDS
        ):
            job = self.resume(job_id)
        if (job.get("spec") or {}).get("target") != "desktop":
            raise RuntimeError("Only desktop App Factory jobs have a native build.")
        build = job["nativeBuild"]
        current_source = _project_source_digest(Path(job["projectRoot"]))
        if (
            build.get("state") == "ready"
            and build.get("sourceSha256") == current_source
            and Path(str(build.get("artifactPath") or "")).is_file()
            and build.get("sha256") == _sha256(Path(str(build["artifactPath"])))
        ):
            return job
        if build.get("state") in {"queued", "running"} and self._pid_running(
            int(build.get("processId") or 0)
        ):
            return job
        if not shutil.which("cargo") or not shutil.which("rustc"):
            raise RuntimeError("Cargo and Rust are required to compile the native desktop app.")
        try:
            native_free_bytes = shutil.disk_usage(
                self.cargo_target.anchor or self.cargo_target.parent
            ).free
        except OSError:
            native_free_bytes = 0
        if native_free_bytes < 2 * 1024 * 1024 * 1024:
            raise RuntimeError(
                "The native build cache needs at least 2 GB free. "
                "Move the workspace or configure NEYVIA_APP_FACTORY_CARGO_TARGET "
                "on a roomier local drive."
            )

        build.update(
            {
                "state": "queued",
                "sourceSha256": current_source,
                "processId": None,
                "artifactPath": "",
                "sha256": "",
                "bytes": 0,
                "lockfilePath": "",
                "lockfileSha256": "",
                "startedAt": _utc_now(),
                "completedAt": "",
                "error": "",
            }
        )
        job["status"] = "building"
        job["currentStage"] = "native-build"
        self._save_job(job)

        log_path = Path(build["logPath"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "grant_agent.app_factory",
            "worker",
            "--root",
            str(self.root),
            "--job-id",
            job_id,
        ]
        kwargs: dict[str, Any] = hidden_windows_subprocess_kwargs()
        worker_env = os.environ.copy()
        module_root = str(Path(__file__).resolve().parents[1])
        worker_env["PYTHONPATH"] = os.pathsep.join(
            part for part in (module_root, worker_env.get("PYTHONPATH", "")) if part
        )
        kwargs.update(
            {
                "cwd": str(self.root),
                "stdin": subprocess.DEVNULL,
                "env": worker_env,
            }
        )
        with log_path.open("ab") as stream:
            process = subprocess.Popen(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                **kwargs,
            )
        build["processId"] = process.pid
        build["state"] = "running"
        self._save_job(job)
        return job

    def run_native_build(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if (job.get("spec") or {}).get("target") != "desktop":
            raise RuntimeError("Only desktop App Factory jobs have a native build.")
        build = job["nativeBuild"]
        source_sha256 = _project_source_digest(Path(job["projectRoot"]))
        verification = job.get("verification") if isinstance(job.get("verification"), dict) else {}
        if (
            verification.get("state") != "passed"
            or verification.get("sourceSha256") != source_sha256
            or build.get("sourceSha256") != source_sha256
        ):
            raise RuntimeError(
                "The native build source no longer matches its current static verification. Resume App Factory before compiling."
            )
        build["state"] = "running"
        build["processId"] = os.getpid()
        build["startedAt"] = build.get("startedAt") or _utc_now()
        build["error"] = ""
        job["status"] = "building"
        job["currentStage"] = "native-build"
        self._save_job(job)

        project_root = Path(job["projectRoot"])
        manifest = project_root / "src-tauri" / "Cargo.toml"
        if not manifest.is_file():
            raise RuntimeError("The generated Tauri Cargo manifest is missing.")
        log_path = Path(build["logPath"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cargo = shutil.which("cargo")
        if not cargo:
            raise RuntimeError("Cargo is unavailable.")
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(self.cargo_target)
        command = [cargo, "build", "--manifest-path", str(manifest), "--release", "--locked"]
        if not (project_root / "src-tauri" / "Cargo.lock").exists():
            command.remove("--locked")
        started = time.perf_counter()
        try:
            with log_path.open("ab") as stream:
                stream.write(
                    (
                        f"\n[{_utc_now()}] Native build started for {job_id}\n"
                        f"CARGO_TARGET_DIR={self.cargo_target}\n"
                    ).encode("utf-8")
                )
                completed = subprocess.run(
                    command,
                    cwd=str(project_root),
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=1800,
                    check=False,
                    **hidden_windows_subprocess_kwargs(),
                )
            if completed.returncode != 0:
                detail = self._tail_text(log_path, 2400)
                raise RuntimeError(
                    f"Native Cargo build failed with exit code {completed.returncode}: {detail}"
                )
            slug = job["spec"]["slug"]
            executable_name = f"{slug}.exe" if os.name == "nt" else slug
            compiled = self.cargo_target / "release" / executable_name
            if not compiled.is_file():
                raise RuntimeError(f"Cargo completed but the executable was not found: {compiled}")
            if _project_source_digest(project_root) != source_sha256:
                raise RuntimeError("Project source changed while the native build was running.")
            latest = _read_json(self._job_path(job_id), {})
            latest_build = latest.get("nativeBuild") if isinstance(latest, dict) else None
            if (
                not isinstance(latest, dict)
                or latest.get("schema") != APP_FACTORY_JOB_SCHEMA
                or not isinstance(latest_build, dict)
                or latest_build.get("sourceSha256") != source_sha256
                or latest_build.get("state") != "running"
            ):
                raise RuntimeError("This native build was superseded by a newer App Factory revision.")
            job = latest
            build = latest["nativeBuild"]
            output_dir = project_root / ".neyvia" / "build"
            output_dir.mkdir(parents=True, exist_ok=True)
            artifact = output_dir / f"{slug}-0.1.0{'.exe' if os.name == 'nt' else ''}"
            shutil.copy2(compiled, artifact)
            lockfile = project_root / "src-tauri" / "Cargo.lock"
            build.update(
                {
                    "state": "ready",
                    "sourceSha256": source_sha256,
                    "runtimeVerified": False,
                    "artifactPath": str(artifact),
                    "sha256": _sha256(artifact),
                    "bytes": artifact.stat().st_size,
                    "completedAt": _utc_now(),
                    "durationMs": int((time.perf_counter() - started) * 1000),
                    "lockfilePath": str(lockfile) if lockfile.is_file() else "",
                    "lockfileSha256": _sha256(lockfile) if lockfile.is_file() else "",
                    "error": "",
                }
            )
            job["status"] = "ready"
            job["currentStage"] = "ready"
            job["artifacts"] = [
                item for item in job.get("artifacts") or [] if item.get("kind") != "native-executable"
            ] + [
                {
                    "kind": "native-executable",
                    "path": str(artifact),
                    "sha256": build["sha256"],
                    "bytes": build["bytes"],
                }
            ]
            self._save_job(job)
            return job
        except Exception as exc:
            latest = _read_json(self._job_path(job_id), {})
            latest_build = latest.get("nativeBuild") if isinstance(latest, dict) else None
            if (
                isinstance(latest, dict)
                and isinstance(latest_build, dict)
                and latest_build.get("sourceSha256") == source_sha256
                and latest_build.get("state") == "running"
            ):
                latest_build.update(
                    {
                        "state": "failed",
                        "completedAt": _utc_now(),
                        "durationMs": int((time.perf_counter() - started) * 1000),
                        "error": str(exc),
                    }
                )
                latest["status"] = "needs_attention"
                latest["currentStage"] = "native-build"
                latest["error"] = str(exc)
                self._save_job(latest)
            raise

    @checked_action(check_preview_asset)
    def resolve_preview_asset(self, job_id: str, requested_path: str) -> tuple[Path, str]:
        job = self.get_job(job_id)
        verify = job.get("verification") if isinstance(job.get("verification"), dict) else {}
        if verify.get("state") != "passed":
            raise RuntimeError("App Factory preview is unavailable until verification passes.")
        project_root = Path(job["projectRoot"]).resolve()
        asset_root = (project_root / "dist").resolve()
        try:
            asset_root.relative_to(project_root)
        except ValueError as exc:
            raise RuntimeError("App Factory preview root is invalid.") from exc
        relative = str(requested_path or "").replace("\\", "/").lstrip("/")
        if not relative:
            candidate = asset_root / "index.html"
        else:
            parts = Path(relative).parts
            if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
                raise RuntimeError("App Factory preview path is invalid.")
            candidate = (asset_root / Path(*parts)).resolve()
        try:
            candidate.relative_to(asset_root)
        except ValueError as exc:
            raise RuntimeError("App Factory preview path escapes the generated app.") from exc
        content_type = _PREVIEW_MEDIA_TYPES.get(candidate.suffix.lower())
        if (
            not content_type
            or not candidate.is_file()
            or candidate.is_symlink()
            or candidate.stat().st_size > 16 * 1024 * 1024
        ):
            raise RuntimeError("App Factory preview asset is unavailable or unsupported.")
        return candidate, content_type

    def _stage(self, job: dict[str, Any], stage_id: str) -> dict[str, Any]:
        for stage in job.get("stages") or []:
            if stage.get("id") == stage_id:
                if stage_id == "verify":
                    stage["label"] = "Source/package checks"
                return stage
        raise RuntimeError(f"App Factory job is missing the {stage_id} stage.")

    def _job_capability_handoff(
        self,
        job: dict[str, Any],
    ) -> dict[str, Any]:
        spec = job.get("spec") if isinstance(job.get("spec"), dict) else {}
        handoff = (
            dict(job.get("capabilityHandoff") or {})
            if isinstance(job.get("capabilityHandoff"), dict)
            else {}
        )
        if spec.get("template") != "capability":
            if handoff:
                raise RuntimeError(
                    "A non-capability App Factory job cannot carry a lineage handoff."
                )
            return {}
        if (
            not handoff
            or handoff.get("schema") != APP_FACTORY_HANDOFF_SCHEMA
            or handoff.get("state") != "reviewed_for_local_draft"
            or handoff.get("candidateActivated") is not False
            or handoff.get("appActivated") is not False
            or handoff.get("transcriptsIncluded") is not False
            or _canonical_digest(_stable_handoff_contract(handoff))
            != handoff.get("handoffDigest")
        ):
            raise RuntimeError(
                "The saved capability lineage handoff is missing or changed."
            )
        expected_binding = _capability_binding_digest(
            str(handoff.get("handoffDigest") or ""),
            app_id=str(spec.get("appId") or ""),
            name=str(spec.get("name") or ""),
            brief=str(spec.get("brief") or ""),
            target=str(spec.get("target") or ""),
            theme=str(spec.get("theme") or ""),
            directory=str(spec.get("directory") or ""),
        )
        if handoff.get("appBindingDigest") != expected_binding:
            raise RuntimeError(
                "The app specification no longer matches its approved capability handoff."
            )
        source = (
            dict(handoff.get("sourcePackage") or {})
            if isinstance(handoff.get("sourcePackage"), dict)
            else {}
        )
        handoff_id = str(handoff.get("handoffId") or "")
        if not _SAFE_HANDOFF_ID.fullmatch(handoff_id):
            raise RuntimeError("The saved capability handoff id is invalid.")
        source_root = (self.handoffs_root / handoff_id / "source").resolve()
        skill_path = Path(str(source.get("skillPath") or "")).resolve()
        metadata_path = Path(str(source.get("metadataPath") or "")).resolve()
        try:
            skill_path.relative_to(source_root)
            metadata_path.relative_to(source_root)
        except ValueError as exc:
            raise RuntimeError(
                "The saved capability source escapes its handoff store."
            ) from exc
        if (
            not skill_path.is_file()
            or not metadata_path.is_file()
            or skill_path.is_symlink()
            or metadata_path.is_symlink()
            or _sha256(skill_path) != handoff.get("skillSha256")
            or _sha256(metadata_path) != handoff.get("metadataSha256")
        ):
            raise RuntimeError(
                "The stored exact capability source is missing or changed."
            )
        return handoff

    def _stage_brief(self, job: dict[str, Any]) -> dict[str, Any]:
        spec = job["spec"]
        _clean_text(spec.get("name"), minimum=2, maximum=80, label="App name")
        _clean_text(spec.get("brief"), minimum=12, maximum=900, label="App brief")
        if spec.get("target") not in SUPPORTED_TARGETS:
            raise RuntimeError("The saved App Factory target is unsupported.")
        handoff = self._job_capability_handoff(job)
        if handoff:
            return {
                "detail": (
                    f"Reviewed sealed capability {handoff['skillId']} bound to a "
                    f"{spec['target']} guided runner; both capability and app remain inactive."
                )
            }
        return {
            "detail": (
                f"{spec['template'].title()} starter selected for {spec['target']} output; "
                "Marketplace publication remains gated."
            )
        }

    def _stage_scaffold(self, job: dict[str, Any]) -> dict[str, Any]:
        project_root = Path(job["projectRoot"])
        project_root.mkdir(parents=True, exist_ok=True)
        files = {
            **_frontend_files(job),
            **_project_metadata_files(job),
        }
        if job["spec"]["target"] == "desktop":
            files.update(_tauri_files(job))
        written: list[str] = []
        for relative, content in files.items():
            destination = project_root / relative
            _write_expected_file(destination, content)
            written.append(str(destination))
        handoff = self._job_capability_handoff(job)
        if handoff:
            source = handoff["sourcePackage"]
            for source_path, relative in (
                (source["skillPath"], "source/skill/SKILL.md"),
                (
                    source["metadataPath"],
                    "source/skill/agents/openai.yaml",
                ),
            ):
                destination = project_root / relative
                _copy_expected_file(Path(str(source_path)), destination)
                written.append(str(destination))
        return {
            "detail": f"Wrote {len(written)} deterministic project files without installing dependencies.",
            "artifacts": written,
        }

    def _stage_assemble(self, job: dict[str, Any]) -> dict[str, Any]:
        project_root = Path(job["projectRoot"])
        dist = project_root / "dist"
        for source_name, destination_name in (
            ("index.html", "index.html"),
            ("styles.css", "styles.css"),
            ("app.js", "app.js"),
        ):
            source = project_root / "src" / source_name
            if not source.is_file():
                raise RuntimeError(f"App source file is missing: {source}")
            _replace_generated_file(dist / destination_name, source.read_bytes())
        archive = _deterministic_archive(
            project_root,
            self.state_root / "packages" / job["jobId"] / f"{job['spec']['slug']}-0.1.0.nyapp",
        )
        job["package"] = archive
        job["artifacts"] = [
            item for item in job.get("artifacts") or [] if item.get("kind") != "source-package"
        ] + [{"kind": "source-package", **archive}]
        return {
            "detail": (
                f"Assembled the preview and deterministic {archive['fileCount']}-file source package."
            ),
            "artifacts": [str(dist / "index.html"), archive["path"]],
            "sourceSha256": _project_source_digest(project_root),
        }

    def _stage_verify(self, job: dict[str, Any]) -> dict[str, Any]:
        project_root = Path(job["projectRoot"])
        checks: list[dict[str, Any]] = []

        def check(check_id: str, condition: bool, detail: str) -> None:
            checks.append(
                {
                    "id": check_id,
                    "state": "passed" if condition else "failed",
                    "detail": detail,
                }
            )

        dist = project_root / "dist"
        index = dist / "index.html"
        styles = dist / "styles.css"
        script = dist / "app.js"
        check("preview-index", index.is_file(), "dist/index.html exists.")
        check("preview-styles", styles.is_file(), "dist/styles.css exists.")
        check("preview-script", script.is_file(), "dist/app.js exists.")
        index_text = index.read_text(encoding="utf-8") if index.is_file() else ""
        script_text = script.read_text(encoding="utf-8") if script.is_file() else ""
        handoff = self._job_capability_handoff(job)
        if handoff:
            check(
                "guided-capability-workflow",
                all(
                    marker in script_text
                    for marker in (
                        "localStorage.setItem",
                        'schema: "neyvia.capability-run/v2"',
                        '"neyvia.capability-run-bundle/v2"',
                        "canonicalJson",
                        'digest("SHA-256"',
                        "window.parent.postMessage",
                        "config.appFactoryJobId",
                        "config.proofLease",
                    )
                )
                and "Return typed outcomes to Neyvia" in index_text
                and "stay out of its learning ledger" in index_text,
                "The guided runner seals bound canonical receipts and returns typed outcomes only on request.",
            )
            lineage = _read_json(
                project_root / "neyvia.capability-lineage.json",
                {},
            )
            check(
                "capability-lineage-binding",
                isinstance(lineage, dict)
                and lineage.get("schema")
                == "neyvia.capability-app-lineage/v1"
                and lineage.get("handoffDigest")
                == handoff.get("handoffDigest")
                and lineage.get("appBindingDigest")
                == handoff.get("appBindingDigest")
                and lineage.get("candidateDigest")
                == handoff.get("candidateDigest")
                and (
                    not isinstance(handoff.get("proofLease"), dict)
                    or lineage.get("proofLease")
                    == handoff.get("proofLease")
                )
                and lineage.get("candidateActivated") is False
                and lineage.get("appActivated") is False
                and lineage.get("transcriptsIncluded") is False,
                "The app specification is bound to the reviewed inactive lineage.",
            )
            copied_skill = project_root / "source" / "skill" / "SKILL.md"
            copied_metadata = (
                project_root
                / "source"
                / "skill"
                / "agents"
                / "openai.yaml"
            )
            check(
                "exact-skill-source",
                copied_skill.is_file()
                and copied_metadata.is_file()
                and _sha256(copied_skill) == handoff.get("skillSha256")
                and _sha256(copied_metadata)
                == handoff.get("metadataSha256"),
                "The exact sealed skill and metadata hashes are carried into the app package.",
            )
        else:
            check(
                "local-workflow",
                "localStorage.setItem" in script_text
                and "Export JSON" in index_text,
                "The generated app saves real local state and exposes a portable export.",
            )
        check(
            "no-remote-scripts",
            not re.search(r"<script[^>]+src=[\"']https?://", index_text, re.I),
            "The starter loads no remote script.",
        )
        application = _read_json(project_root / "neyvia.application.json", {})
        normalized = normalize_application_manifest(application if isinstance(application, dict) else {})
        check(
            "application-contract",
            normalized.get("valid") is True
            and normalized.get("applicationId") == job["spec"]["appId"]
            and (
                normalized.get("permissions") == []
                if handoff
                else True
            ),
            "The generated Neyvia application contract validates.",
        )
        package = job.get("package") if isinstance(job.get("package"), dict) else {}
        package_path = Path(str(package.get("path") or ""))
        source_sha256 = _project_source_digest(project_root)
        rebuilt_path = (
            package_path.with_name(f".{package_path.name}.{uuid.uuid4().hex}.check")
            if package_path.name
            else self.state_root / "temporary" / f"{job['jobId']}.{uuid.uuid4().hex}.check"
        )
        rebuilt = {}
        try:
            if package_path.is_file() and package_path.parent.exists():
                rebuilt = _deterministic_archive(project_root, rebuilt_path)
        finally:
            rebuilt_path.unlink(missing_ok=True)
        check(
            "package-integrity",
            package_path.is_file()
            and package.get("sha256") == _sha256(package_path)
            and int(package.get("bytes") or 0) == package_path.stat().st_size
            and rebuilt.get("sha256") == package.get("sha256"),
            "The package hash matches the exact current project files.",
        )
        if job["spec"]["target"] == "desktop":
            check(
                "tauri-shell",
                (project_root / "src-tauri" / "Cargo.toml").is_file()
                and (project_root / "src-tauri" / "tauri.conf.json").is_file(),
                "Tauri 2 shell files exist; native compilation remains an explicit proof step.",
            )
        failed = [item for item in checks if item["state"] != "passed"]
        job["verification"] = {
            "kind": "static-source-and-package",
            "runtimeVerified": False,
            "sourceSha256": source_sha256,
            "packageSha256": package.get("sha256") or "",
            "state": "failed" if failed else "passed",
            "checks": checks,
            "verifiedAt": _utc_now(),
            "summary": (
                f"{len(checks)} static source and package checks passed; runtime behavior was not tested."
                if not failed
                else f"{len(failed)} of {len(checks)} static source and package checks failed."
            ),
        }
        if failed:
            raise RuntimeError("; ".join(item["detail"] for item in failed))
        receipt_path = self.state_root / "receipts" / f"{job['jobId']}-verification.json"
        _atomic_json(
            receipt_path,
            {
                "schema": "neyvia.app-factory-verification-receipt/v1",
                "jobId": job["jobId"],
                "appId": job["spec"]["appId"],
                "verifiedAt": job["verification"]["verifiedAt"],
                "kind": job["verification"]["kind"],
                "runtimeVerified": False,
                "sourceSha256": source_sha256,
                "package": job["package"],
                "checks": checks,
                "capabilityHandoff": (
                    {
                        "handoffId": handoff.get("handoffId") or "",
                        "handoffDigest": handoff.get("handoffDigest") or "",
                        "appBindingDigest": handoff.get("appBindingDigest")
                        or "",
                        "materializationId": handoff.get(
                            "materializationId"
                        )
                        or "",
                        "skillId": handoff.get("skillId") or "",
                        "candidateDigest": handoff.get("candidateDigest")
                        or "",
                        "proofLease": handoff.get("proofLease") or {},
                        "candidateActivated": False,
                        "appActivated": False,
                    }
                    if handoff
                    else None
                ),
            },
        )
        job["verification"]["receiptPath"] = str(receipt_path)
        job["verification"]["receiptSha256"] = _sha256(receipt_path)
        return {
            "detail": job["verification"]["summary"],
            "artifacts": [str(receipt_path)],
            "sourceSha256": source_sha256,
        }

    def _stage_register(self, job: dict[str, Any]) -> dict[str, Any]:
        from .harness_jobs import _exclusive_job_lock

        # Registration is a read/modify/write of one shared catalog. The
        # atomic writer protects complete bytes; the mutation lease also
        # preserves applications registered by competing factory instances.
        with _exclusive_job_lock(self.registry_path, timeout_seconds=10):
            return self._stage_register_locked(job)

    def _stage_register_locked(self, job: dict[str, Any]) -> dict[str, Any]:
        registry = _read_json(
            self.registry_path,
            {"schema": APP_FACTORY_REGISTRY_SCHEMA, "applications": []},
        )
        if not isinstance(registry, dict):
            registry = {"schema": APP_FACTORY_REGISTRY_SCHEMA, "applications": []}
        applications = (
            list(registry.get("applications") or [])
            if isinstance(registry.get("applications"), list)
            else []
        )
        app_id = job["spec"]["appId"]
        entry = {
            "applicationId": app_id,
            "name": job["spec"]["name"],
            "summary": job["spec"]["brief"],
            "jobId": job["jobId"],
            "projectRoot": job["projectRoot"],
            "target": job["spec"]["target"],
            "previewUrl": job["previewUrl"],
            "state": "draft-ready",
            "sourceSha256": job["verification"].get("sourceSha256") or "",
            "packageSha256": job["package"]["sha256"],
            "verificationReceiptSha256": job["verification"].get("receiptSha256") or "",
            "runtimeVerified": False,
            "updatedAt": _utc_now(),
        }
        handoff = self._job_capability_handoff(job)
        if handoff:
            entry["capabilityHandoff"] = {
                "handoffId": handoff["handoffId"],
                "handoffDigest": handoff["handoffDigest"],
                "appBindingDigest": handoff["appBindingDigest"],
                "materializationId": handoff["materializationId"],
                "approvedLineageId": handoff["approvedLineageId"],
                "parentLineageId": handoff["parentLineageId"],
                "skillId": handoff["skillId"],
                "candidateDigest": handoff["candidateDigest"],
                "proofLease": handoff.get("proofLease") or {},
                "candidateActivated": False,
                "appActivated": False,
            }
        replaced = False
        for index, existing in enumerate(applications):
            if isinstance(existing, dict) and existing.get("applicationId") == app_id:
                applications[index] = entry
                replaced = True
                break
        if not replaced:
            applications.append(entry)
        registry = {
            "schema": APP_FACTORY_REGISTRY_SCHEMA,
            "updatedAt": _utc_now(),
            "applications": sorted(
                applications,
                key=lambda item: str((item or {}).get("updatedAt") or ""),
                reverse=True,
            ),
        }
        _atomic_json(self.registry_path, registry)
        # Record the same real source/build/proof state as a semantic Living
        # Application. This is local provenance only; it never publishes or
        # restarts the generated application.
        try:
            from .app_factory_semantics import register_app_factory_job

            register_app_factory_job(
                job,
                persist_path=self.state_root / "living-applications.json",
                permissions=job.get("permissions"),
            )
        except Exception as exc:
            raise RuntimeError(f"Living Application registration failed: {exc}") from exc
        job["registration"] = {
            "state": "draft-ready",
            "sourceSha256": job["verification"].get("sourceSha256") or "",
            "packageSha256": job["package"]["sha256"],
            "verificationReceiptSha256": job["verification"].get("receiptSha256") or "",
            "runtimeVerified": False,
            "registryPath": str(self.registry_path),
            "registeredAt": registry["updatedAt"],
            "detail": (
                "Registered as a local App Factory draft after static source and package checks; runtime behavior is not verified and Marketplace activation remains separate."
            ),
        }
        return {
            "detail": job["registration"]["detail"],
            "artifacts": [str(self.registry_path)],
        }

    def _agent_prompt(self, job: dict[str, Any]) -> str:
        verification = job.get("verification") if isinstance(job.get("verification"), dict) else {}
        lines = [
                f"Continue the Neyvia App Factory job {job['jobId']}.",
                f"Application: {job['spec']['name']} ({job['spec']['appId']})",
                f"Goal: {job['spec']['brief']}",
                f"Project: {job['projectRoot']}",
                f"Target: {job['spec']['target']} · starter: {job['spec']['template']}",
                f"Current state: {job.get('status')} · stage: {job.get('currentStage')}",
                f"Verification: {verification.get('state', 'pending')} — {verification.get('summary', 'No receipt yet.')}",
                "",
        ]
        handoff = (
            dict(job.get("capabilityHandoff") or {})
            if isinstance(job.get("capabilityHandoff"), dict)
            else {}
        )
        if handoff:
            lines.extend(
                [
                    "Verified capability source:",
                    f"- Skill: {handoff.get('skillId')}",
                    f"- Handoff: {handoff.get('handoffId')}",
                    f"- Handoff digest: {handoff.get('handoffDigest')}",
                    f"- App binding digest: {handoff.get('appBindingDigest')}",
                    f"- Candidate digest: {handoff.get('candidateDigest')}",
                    "- Exact source: source/skill/SKILL.md and source/skill/agents/openai.yaml",
                    "- Boundary: keep the skill inactive, the app local and unpublished, "
                    "and authority unchanged. The current runner guides a human through "
                    "the exact steps; it does not invoke an agent.",
                    "",
                ]
            )
        lines.extend(
            [
                "Work as a supervised app team:",
                "1. Planner: turn the brief into one narrow user journey and acceptance checks.",
                "2. Builder: improve the real generated files without replacing local persistence with mocks.",
                "3. Verifier: build, open, click through the journey in Chrome, and attach exact proof.",
                "4. Release steward: keep Marketplace signing, permission review, and activation separate.",
                "",
                "Resume from existing files and receipts. Do not overwrite unrelated workspace changes.",
                "After each source edit, resume this App Factory job to refresh the package and static checks. ",
                "Then run the authenticated App Factory test command for this job and inspect its journey receipt. ",
                "Repair a failed journey and repeat with a new run ID; stop after three bounded repair attempts ",
                "and report any remaining failure. A static pass or compiled executable is not runtime proof.",
            ]
        )
        return "\n".join(lines)

    def record_runtime_journey(self, job_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Bind a browser journey receipt to the exact current editable source."""
        job = self.get_job(job_id)
        verification = job.get("verification") or {}
        current_source = _project_source_digest(Path(job["projectRoot"]))
        if (
            verification.get("state") != "passed"
            or verification.get("sourceSha256") != current_source
            or receipt.get("sourceSha256") != current_source
        ):
            raise RuntimeError("The App Factory source changed during the browser journey; resume and test again.")
        run = receipt.get("run") if isinstance(receipt.get("run"), dict) else {}
        screenshot = Path(str(receipt.get("screenshotPath") or "")).resolve()
        proof_root = (self.root / ".agent_control" / "app_factory_tests" / job_id).resolve()
        try:
            screenshot.relative_to(proof_root)
        except ValueError as exc:
            raise RuntimeError("The browser screenshot is outside this App Factory job.") from exc
        if not screenshot.is_file() or _sha256(screenshot) != receipt.get("screenshotSha256"):
            raise RuntimeError("The browser screenshot receipt is missing or changed.")
        cleanup = receipt.get("cleanupRun") if isinstance(receipt.get("cleanupRun"), dict) else {}
        cleanup_screenshot = Path(str(receipt.get("cleanupScreenshotPath") or "")).resolve()
        if cleanup:
            try:
                cleanup_screenshot.relative_to(proof_root)
            except ValueError as exc:
                raise RuntimeError("The removal screenshot is outside this App Factory job.") from exc
            if not cleanup_screenshot.is_file() or _sha256(cleanup_screenshot) != receipt.get("cleanupScreenshotSha256"):
                raise RuntimeError("The removal screenshot receipt is missing or changed.")
        accepted = (run.get("accepted") is True and run.get("taskComplete") is True
                    and cleanup.get("accepted") is True and cleanup.get("taskComplete") is True)
        verification["runtimeVerified"] = accepted
        verification["runtimeCheckedAt"] = _utc_now()
        verification["runtimeProof"] = {
            "kind": "saved-browser-journey",
            "state": "passed" if accepted else "failed",
            "sourceSha256": current_source,
            "journeyId": str(run.get("journeyId") or ""),
            "runId": str(run.get("runId") or ""),
            "situationStatus": str(run.get("status") or ""),
            "acceptanceFrameId": str(run.get("acceptanceFrameId") or ""),
            "reloadFrameId": str(run.get("reloadFrameId") or ""),
            "cleanupJourneyId": str(cleanup.get("journeyId") or ""),
            "cleanupRunId": str(cleanup.get("runId") or ""),
            "cleanupStatus": str(cleanup.get("status") or "not_run"),
            "cleanupReloadFrameId": str(cleanup.get("reloadFrameId") or ""),
            "screenshotPath": str(screenshot),
            "screenshotSha256": receipt["screenshotSha256"],
            "cleanupScreenshotPath": str(cleanup_screenshot) if cleanup else "",
            "cleanupScreenshotSha256": str(receipt.get("cleanupScreenshotSha256") or ""),
        }
        job["verification"] = verification
        self._save_job(job)
        return job

    def _refresh_native_state(self, job: dict[str, Any]) -> dict[str, Any]:
        build = job.get("nativeBuild") if isinstance(job.get("nativeBuild"), dict) else {}
        if build.get("state") == "ready":
            artifact = Path(str(build.get("artifactPath") or ""))
            current_source = _project_source_digest(Path(str(job.get("projectRoot") or "")))
            if (
                not artifact.is_file()
                or build.get("sourceSha256") != current_source
                or build.get("sha256") != _sha256(artifact)
            ):
                build["staleArtifactPath"] = build.get("artifactPath") or ""
                build["staleSha256"] = build.get("sha256") or ""
                build.update(
                    {
                        "state": "stale",
                        "artifactPath": "",
                        "sha256": "",
                        "bytes": 0,
                        "error": "The native artifact does not match the current source revision.",
                    }
                )
                self._save_job(job)
        if build.get("state") in {"queued", "running"}:
            pid = int(build.get("processId") or 0)
            if pid and not self._pid_running(pid):
                artifact = Path(str(build.get("artifactPath") or ""))
                if not artifact.is_file():
                    build["state"] = "failed"
                    build["completedAt"] = _utc_now()
                    build["error"] = (
                        build.get("error")
                        or "The native build worker stopped before publishing an executable receipt."
                    )
                    job["status"] = "needs_attention"
                    job["error"] = build["error"]
                    self._save_job(job)
                elif (
                    build.get("sourceSha256")
                    != _project_source_digest(Path(str(job.get("projectRoot") or "")))
                    or build.get("sha256") != _sha256(artifact)
                ):
                    build["staleArtifactPath"] = str(artifact)
                    build["staleSha256"] = build.get("sha256") or ""
                    build.update(
                        {
                            "state": "stale",
                            "artifactPath": "",
                            "sha256": "",
                            "bytes": 0,
                            "error": "The native artifact does not match the current source revision.",
                        }
                    )
                    self._save_job(job)
        return job

    def _invalidate_stale_claims(self, job: dict[str, Any]) -> None:
        project_root = Path(str(job.get("projectRoot") or ""))
        if not project_root.is_dir():
            return
        current_source = _project_source_digest(project_root)
        assemble = self._stage(job, "assemble")
        verification = job.get("verification") if isinstance(job.get("verification"), dict) else {}
        package = job.get("package") if isinstance(job.get("package"), dict) else {}
        package_path = Path(str(package.get("path") or ""))
        assembled_source = str(assemble.get("sourceSha256") or "")
        verified_source = str(verification.get("sourceSha256") or "")
        package_is_current = bool(
            package_path.is_file()
            and package.get("sha256")
            and package.get("sha256") == _sha256(package_path)
            and int(package.get("bytes") or 0) == package_path.stat().st_size
        )
        source_changed = (
            assemble.get("state") == "completed"
            and assembled_source != current_source
        ) or (
            verification.get("state") == "passed"
            and verified_source != current_source
        ) or (
            verification.get("state") == "passed"
            and str(verification.get("packageSha256") or "")
            != str(package.get("sha256") or "")
        ) or (
            verification.get("state") == "passed" and not package_is_current
        ) or (
            verification.get("state") == "passed"
            and (
                not Path(str(verification.get("receiptPath") or "")).is_file()
                or verification.get("receiptSha256")
                != _sha256(Path(str(verification.get("receiptPath") or "")))
            )
        )
        if source_changed:
            for stage_id in ("assemble", "verify", "register"):
                stage = self._stage(job, stage_id)
                stage.update(
                    {
                        "state": "pending",
                        "startedAt": "",
                        "completedAt": "",
                        "durationMs": None,
                        "detail": "Invalidated because the project source changed.",
                        "artifacts": [],
                    }
                )
                stage.pop("sourceSha256", None)
            job["package"] = {}
            job["verification"] = {
                "kind": "static-source-and-package",
                "runtimeVerified": False,
                "state": "pending",
                "checks": [],
                "verifiedAt": "",
                "summary": "Source changed; source/package checks must be rerun.",
            }
            job["artifacts"] = [
                item
                for item in job.get("artifacts") or []
                if item.get("kind") not in {"source-package", "native-executable"}
            ]
            registration = job.get("registration") if isinstance(job.get("registration"), dict) else {}
            registration.update(
                {
                    "state": "stale",
                    "staleAt": _utc_now(),
                    "detail": "Registration was invalidated because its source changed.",
                }
            )
            native = job.get("nativeBuild") if isinstance(job.get("nativeBuild"), dict) else {}
            if native.get("state") in {"ready", "queued", "running"} and str(
                native.get("sourceSha256") or ""
            ) != current_source:
                native["staleArtifactPath"] = native.get("artifactPath") or ""
                native["staleSha256"] = native.get("sha256") or ""
                native.update(
                    {
                        "state": "stale",
                        "processId": None,
                        "artifactPath": "",
                        "sha256": "",
                        "bytes": 0,
                        "error": "Source changed after this native build was queued or completed.",
                    }
                )
                job["artifacts"] = [
                    item
                    for item in job.get("artifacts") or []
                    if item.get("kind") != "native-executable"
                ]
            self._mark_registry_stale(job)
            job["status"] = "needs_attention"
            job["currentStage"] = "assemble"
            job["error"] = "Project source changed; package and readiness claims were invalidated."
            self._save_job(job)
        native = job.get("nativeBuild") if isinstance(job.get("nativeBuild"), dict) else {}
        if native.get("state") == "ready" and str(native.get("sourceSha256") or "") != current_source:
            native["staleArtifactPath"] = native.get("artifactPath") or ""
            native["staleSha256"] = native.get("sha256") or ""
            native.update({"state": "stale", "artifactPath": "", "sha256": "", "bytes": 0})
            self._save_job(job)

    def _mark_registry_stale(self, job: dict[str, Any]) -> None:
        registry = _read_json(self.registry_path, {})
        applications = registry.get("applications") if isinstance(registry, dict) else None
        if not isinstance(applications, list):
            return
        changed = False
        for item in applications:
            if isinstance(item, dict) and item.get("jobId") == job.get("jobId"):
                item["state"] = "stale"
                item["staleAt"] = _utc_now()
                item["runtimeVerified"] = False
                changed = True
        if changed:
            registry["updatedAt"] = _utc_now()
            _atomic_json(self.registry_path, registry)

    @staticmethod
    def _pid_running(pid: int) -> bool:
        return process_is_alive(pid)

    @staticmethod
    def _tail_text(path: Path, limit: int) -> str:
        try:
            data = path.read_bytes()
        except OSError:
            return "No build log was available."
        return data[-max(256, limit) :].decode("utf-8", errors="replace").strip()


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(description="Neyvia App Factory worker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    worker = subparsers.add_parser("worker")
    worker.add_argument("--root", required=True)
    worker.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "worker":
        try:
            AppFactory(args.root).run_native_build(args.job_id)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
