from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.web_backend import FluxioWebBackend  # noqa: E402


UI_SOURCE_PATHS = (
    Path("web/index.html"),
    Path("web/src"),
)


def _ui_source_prefixes() -> tuple[str, ...]:
    return tuple(path.as_posix().rstrip("/") for path in UI_SOURCE_PATHS)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        hashes[relative] = _sha256_file(path)
    return hashes


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            changed.append(path)
    return changed


def _is_ui_source_change(path: str) -> bool:
    if path in {"VISUAL_STATE_BRIEF.md", "REDESIGN_HANDOFF.md"}:
        return False
    for prefix in _ui_source_prefixes():
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def _expected_model_id(provider: str, model: str) -> str:
    provider_id = (provider or "opencode-go").strip().lower()
    model_id = (model or "glm-5.2").strip()
    normalized = model_id.lower()
    if provider_id == "opencode-go":
        for prefix in ("opencode-go/", "opencodego/"):
            if normalized.startswith(prefix):
                model_id = model_id[len(prefix) :]
                normalized = model_id.lower()
                break
        if normalized in {"openrouter/z-ai/glm-5", "z-ai/glm-5", "zai/glm-5"}:
            model_id = "glm-5"
        elif normalized in {"openrouter/z-ai/glm-5.2", "z-ai/glm-5.2", "zai/glm-5.2"}:
            model_id = "glm-5.2"
    if model_id.lower().startswith(f"{provider_id}/"):
        return model_id
    return f"{provider_id}/{model_id}"


def _route_matches(route: dict[str, Any], *, provider: str, model: str) -> bool:
    expected_provider = (provider or "opencode-go").strip().lower()
    provider_ok = str(route.get("provider") or "").strip().lower() == expected_provider
    route_model = str(route.get("model_id") or "").strip()
    if not route_model:
        raw_model = str(route.get("model") or "").strip()
        route_model = f"{expected_provider}/{raw_model}" if raw_model else ""
    return provider_ok and route_model == _expected_model_id(provider, model)


def _safe_reset_dir(path: Path, *, expected_parent: Path) -> None:
    resolved = path.resolve()
    parent = expected_parent.resolve()
    if parent not in resolved.parents and resolved != parent:
        raise RuntimeError(f"Refusing to reset unexpected path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def copy_ui_sources(project_root: Path, copy_root: Path) -> list[str]:
    copied: list[str] = []
    for relative in UI_SOURCE_PATHS:
        source = project_root / relative
        if not source.exists():
            continue
        target = copy_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns("dist", "node_modules", "__pycache__"),
            )
            for file_path in target.rglob("*"):
                if file_path.is_file():
                    copied.append(file_path.relative_to(copy_root).as_posix())
        else:
            shutil.copy2(source, target)
            copied.append(target.relative_to(copy_root).as_posix())
    if not copied:
        raise RuntimeError("No UI source files were copied.")
    return sorted(copied)


def write_visual_state_brief(copy_root: Path, *, provider: str, model: str) -> Path:
    brief = copy_root / "VISUAL_STATE_BRIEF.md"
    brief.write_text(
        "\n".join(
            [
                "# Fluxio UI Redesign Brief",
                "",
                "This is an isolated copy of the UI source. Do not modify the original project tree.",
                "",
                "## Route To Prove",
                f"- Provider: `{provider}`",
                f"- Model: `{model}`",
                "- Expected behavior: the selected route must control this normal Agent Live chat turn.",
                "",
                "## Current State",
                "- The app has an Agent Live composer, runtime lane board, and proof/artifact panels.",
                "- The earlier smoke path proved GLM could answer once, but did not prove autonomous copied-file UI work.",
                "- The redesign should make route proof, copied-file work, and returned artifacts visible without hiding the model answer in trace-only rows.",
                "",
                "## Required Output",
                "- Modify copied UI files in this folder only.",
                "- Keep the proof bounded: change one or two UI files, preferably `web/src/neyvia/RuntimeOperationsPanel.jsx` and/or `web/src/neyvia/styles.css`.",
                "- Make the change visibly about route proof, copied-file work, and returned artifacts.",
                "- Create `REDESIGN_HANDOFF.md` in this folder.",
                "- In the handoff, list changed files, the visual design intent, and how the operator can verify the result.",
                "- Preserve maintainable React/CSS patterns and avoid placeholder or mock-only behavior.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return brief


def run_glm_ui_redesign_proof(
    project_root: Path,
    *,
    runtime: str = "openclaw",
    provider: str = "opencode-go",
    model: str = "opencode-go/glm-5.2",
    effort: str = "high",
    proof_id: str | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    proof_id = proof_id or f"glm-ui-redesign-{_utc_stamp()}"
    proof_root = project_root / ".agent_control" / "glm_ui_redesign_proofs" / proof_id
    copy_root = proof_root / "ui-copy"
    _safe_reset_dir(proof_root, expected_parent=project_root / ".agent_control" / "glm_ui_redesign_proofs")
    copy_root.mkdir(parents=True, exist_ok=True)

    copied_files = copy_ui_sources(project_root, copy_root)
    brief_path = write_visual_state_brief(copy_root, provider=provider, model=model)
    before_hashes = _file_hashes(copy_root)

    backend = FluxioWebBackend(project_root, project_root / "web" / "dist")
    message = (
        "Prove the GLM copied-UI redesign workflow. Work only inside this copied folder: "
        f"{copy_root}. Read VISUAL_STATE_BRIEF.md, redesign the copied UI files, and create "
        "REDESIGN_HANDOFF.md with changed files, visual intent, and verification notes. "
        "Do not edit the original project root."
    )
    payload = {
        "message": message,
        "runtime": runtime,
        "workspaceId": proof_id,
        "workspacePath": str(copy_root),
        "sessionId": proof_id,
        "openclawMode": "agent",
        "route": {
            "role": "executor",
            "provider": provider,
            "model": model,
            "effort": effort,
        },
        "systemContext": (
            "This is a proof run for a controlled local/NAS UI redesign workflow. "
            "The only acceptable success condition is real file changes inside the copied UI folder."
        ),
    }
    try:
        result = backend._run_agent_chat(payload)
    except Exception as exc:  # noqa: BLE001 - proof must record hard runtime failures.
        result = {
            "reply": "",
            "runtime": runtime,
            "sessionId": proof_id,
            "route": backend._chat_route(payload),
            "status": "failed",
            "error": str(exc),
        }
    after_hashes = _file_hashes(copy_root)
    changed_files = [
        path
        for path in _changed_files(before_hashes, after_hashes)
        if path != "VISUAL_STATE_BRIEF.md"
    ]
    changed_ui_files = [path for path in changed_files if _is_ui_source_change(path)]
    handoff_path = copy_root / "REDESIGN_HANDOFF.md"
    handoff_text = ""
    if handoff_path.exists():
        try:
            handoff_text = handoff_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            handoff_text = ""
    route = result.get("route") if isinstance(result.get("route"), dict) else {}
    route_matches = _route_matches(route, provider=provider, model=model)
    runtime_status = str(result.get("status") or "").strip().lower()
    error_text = str(result.get("error") or result.get("errorMessage") or "")
    reply_text = str(result.get("reply") or "").strip()
    artifact_complete_no_reply = (
        not reply_text
        and bool(handoff_text)
        and bool(changed_ui_files)
        and "without a readable model reply" in error_text
    )
    effective_reply = reply_text or (handoff_text[:4000] if artifact_complete_no_reply else "")
    status = (
        "passed"
        if changed_ui_files
        and handoff_path.exists()
        and effective_reply
        and route_matches
        and (runtime_status != "failed" or artifact_complete_no_reply)
        else "failed"
    )
    receipt = {
        "schema": "fluxio.glm_ui_redesign_proof.v1",
        "proofId": proof_id,
        "status": status,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "projectRoot": str(project_root),
        "copyRoot": str(copy_root),
        "briefPath": str(brief_path),
        "handoffPath": str(handoff_path),
        "copiedFileCount": len(copied_files),
        "changedFiles": changed_files,
        "changedUiFiles": changed_ui_files,
        "runtime": result.get("runtime") or runtime,
        "route": route,
        "routeMatches": route_matches,
        "expectedRoute": {"runtime": runtime, "provider": provider, "model": model, "effort": effort},
        "expectedModelId": _expected_model_id(provider, model),
        "reply": effective_reply,
        "artifactCompleteNoReply": artifact_complete_no_reply,
        "error": error_text,
        "compartmentPath": str(project_root / ".agent_control" / "runtime_compartments" / f"{proof_id}.json"),
    }
    receipt_path = proof_root / "proof_receipt.json"
    receipt["receiptPath"] = str(receipt_path)
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove the copied-UI OpenCodeGo/GLM redesign workflow.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--runtime", default="openclaw")
    parser.add_argument("--provider", default="opencode-go")
    parser.add_argument("--model", default="opencode-go/glm-5.2")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--proof-id", default="")
    args = parser.parse_args(argv)

    receipt = run_glm_ui_redesign_proof(
        Path(args.root),
        runtime=args.runtime,
        provider=args.provider,
        model=args.model,
        effort=args.effort,
        proof_id=args.proof_id or None,
    )
    print(json.dumps(receipt, indent=2))
    return 0 if receipt.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
