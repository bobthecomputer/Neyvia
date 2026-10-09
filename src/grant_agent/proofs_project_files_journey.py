"""Outcome journey for registered Project Files browsing and export policy."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
import zipfile
from pathlib import Path

CONTRACTS = ("p22.files.registered-project-export-outcome",)
INITIAL = "# Café notes 🧭\n\nNested project export keeps exact UTF-8 text: naïve résumé.\n"
ROOT_REPORT = "# P22 export receipt\n\nThe root file remains byte-exact.\n"
SECRET = "do-not-export-P22-secret-sentinel\n"


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError("Contract p22.files.registered-project-export-outcome: " + detail)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _refused(call, *, status: int, contains: str) -> dict:
    from .project_files import ProjectFilesError

    try:
        call()
    except ProjectFilesError as error:
        require(error.status_code == status, f"refusal status should be {status}, got {error.status_code}: {error}")
        require(contains.casefold() in str(error).casefold(), f"refusal should explain {contains!r}, got {error}")
        return {"status": error.status_code, "message": str(error)}
    raise ValueError(f"Expected project-files refusal ({status}: {contains})")


def self_check(root=None):
    """Exercise the production registered-project file functions in a disposable local workspace."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    allowed = Path("D:/NeyviaRuns/P22").resolve()
    supplied = Path(root or allowed / "project-files-journey").expanduser().resolve()
    require(_under(supplied, allowed), "scratch root must stay under D:/NeyviaRuns/P22")
    run_root = supplied / uuid.uuid4().hex
    run_root.mkdir(parents=True, exist_ok=False)
    project = run_root / "project"
    nested = project / "nested" / "Δ dossier"
    nested.mkdir(parents=True)
    nested_file = nested / "naïve résumé.md"
    root_file = project / "report.md"
    env_file = project / ".env"
    git_config = project / ".git" / "config"
    dependency = project / "node_modules" / "package.txt"
    git_config.parent.mkdir(parents=True)
    dependency.parent.mkdir(parents=True)
    nested_bytes = INITIAL.encode("utf-8")
    root_bytes = ROOT_REPORT.encode("utf-8")
    nested_file.write_bytes(nested_bytes)
    root_file.write_bytes(root_bytes)
    env_file.write_text(SECRET, encoding="utf-8")
    git_config.write_text("[remote \"private\"]\nurl = do-not-export\n", encoding="utf-8")
    dependency.write_text("generated dependency sentinel\n", encoding="utf-8")

    workspace_id = "p22-project-files-" + uuid.uuid4().hex
    workspace_name = "P22 Unicode project"
    control = run_root / ".agent_control"
    control.mkdir()
    (control / "workspaces.json").write_text(json.dumps({"workspaces": [{
        "workspace_id": workspace_id, "name": workspace_name, "root_path": str(project), "enabled": True,
    }]}), encoding="utf-8")

    from .project_files import (
        ProjectFilesError,
        create_project_archive,
        list_project_entries,
        open_project_download,
        preview_project_file,
    )

    try:
        root_listing = list_project_entries(run_root, workspace_id)
        root_names = [entry["name"] for entry in root_listing["entries"]]
        require(root_listing["workspace"] == {"id": workspace_id, "name": workspace_name},
                "listing must resolve the registered project identity")
        require(root_listing["path"] == "" and root_listing["parentPath"] == "" and root_listing["total"] == 2
                and root_names == ["nested", "report.md"],
                f"root listing must show only visible folders/files in stable folders-first order, got {root_listing}")
        require(not any(name in root_names for name in (".env", ".git", "node_modules")),
                "secret, VCS metadata, and dependency folders must be filtered from visible entries")

        nested_listing = list_project_entries(run_root, workspace_id, "nested/Δ dossier")
        nested_rows = nested_listing["entries"]
        require(nested_listing["path"] == "nested/Δ dossier" and nested_listing["parentPath"] == "nested"
                and len(nested_rows) == 1 and nested_rows[0]["name"] == nested_file.name
                and nested_rows[0]["path"] == "nested/Δ dossier/naïve résumé.md"
                and nested_rows[0]["type"] == "file" and nested_rows[0]["previewable"] is True,
                f"nested Unicode file selection must retain the exact relative path and readable name, got {nested_listing}")

        preview = preview_project_file(run_root, workspace_id, nested_rows[0]["path"])
        require(preview["name"] == nested_file.name and preview["path"] == nested_rows[0]["path"]
                and preview["content"] == INITIAL and preview["truncated"] is False and preview["encoding"] == "utf-8",
                "preview must return the exact full Unicode text and its registered-project relative path")

        download = open_project_download(run_root, workspace_id, nested_rows[0]["path"])
        try:
            download_bytes = download.file.read()
            require(download.filename == nested_file.name and download.size == len(nested_bytes)
                    and download_bytes == nested_bytes,
                    "download descriptor must return the exact saved UTF-8 bytes under the Unicode basename")
        finally:
            download.close()
        require(download.file.closed, "download descriptor must close its owned file handle")

        archive = create_project_archive(run_root, workspace_id)
        try:
            with zipfile.ZipFile(archive.path, "r") as opened:
                names = sorted(opened.namelist())
                expected_visible = ["nested/Δ dossier/naïve résumé.md", "report.md"]
                require(names == sorted(expected_visible + [archive.manifest["policy"]["manifestPath"]]),
                        f"archive must include only visible project files and its manifest, got {names}")
                require(opened.read("nested/Δ dossier/naïve résumé.md") == nested_bytes
                        and opened.read("report.md") == root_bytes,
                        "archived members must retain each source file's exact saved bytes")
                manifest = json.loads(opened.read(archive.manifest["policy"]["manifestPath"]).decode("utf-8"))
                require(manifest["workspaceId"] == workspace_id and manifest["workspaceName"] == workspace_name
                        and manifest["filesIncluded"] == 2 and manifest["sourceBytes"] == len(nested_bytes) + len(root_bytes),
                        "archive manifest must describe this registered project and exact included byte count")
                require(manifest["skipped"]["credential_or_secret"] >= 1
                        and manifest["skipped"]["protected_metadata"] >= 1
                        and manifest["skipped"]["generated_dependency_or_cache"] >= 1,
                        "archive must report each filtered secret, metadata and dependency category")
        finally:
            archive.cleanup()
        require(not archive.path.exists(), "archive cleanup must remove the generated ZIP scratch artifact")

        outside = run_root / "outside.txt"
        outside_bytes = b"outside sentinel must never be read\n"
        outside.write_bytes(outside_bytes)
        traversal = _refused(lambda: preview_project_file(run_root, workspace_id, "../outside.txt"),
                             status=400, contains="relative")
        secret = _refused(lambda: preview_project_file(run_root, workspace_id, ".env"),
                          status=403, contains="excluded")
        metadata = _refused(lambda: open_project_download(run_root, workspace_id, ".git/config"),
                            status=403, contains="excluded")
        unknown = _refused(lambda: list_project_entries(run_root, "not-registered"),
                           status=404, contains="Unknown registered workspace ID")
        require(outside.read_bytes() == outside_bytes, "a rejected traversal must leave outside bytes unchanged")

        after_nested = nested_file.read_bytes()
        after_root = root_file.read_bytes()
        require(after_nested == nested_bytes and after_root == root_bytes,
                "listing, preview, download and archive must preserve the exact original project bytes")
        require(_sha(after_nested) == _sha(nested_bytes) and _sha(after_root) == _sha(root_bytes),
                "independent byte readback must match the saved source digests")

        case = {
            "id": "registered-project-export",
            "contracts": list(CONTRACTS),
            "ok": True,
            "visibleRootEntries": root_names,
            "nestedRelativePath": nested_rows[0]["path"],
            "previewExactText": preview["content"] == INITIAL,
            "downloadExactBytes": download_bytes == nested_bytes,
            "archiveVisibleMembers": expected_visible,
            "sourceBytesPreserved": True,
            "refusals": {"traversal": traversal, "secret": secret, "metadata": metadata, "unknownWorkspace": unknown},
        }
        return {
            "ok": True,
            "contracts": list(CONTRACTS),
            "cases": [case],
            "failures": [],
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "scratchRoot": str(run_root),
            "frontier": "Exercises the registered-project functions in src/grant_agent/project_files.py. It does not exercise HTTP authentication, HttpServingMixin.serve_project_files, or browser rendering; the files CL manual's neyvia.files.* actions are a separate API.",
        }
    except Exception as error:
        return {
            "ok": False,
            "contracts": list(CONTRACTS),
            "cases": [{"id": "registered-project-export", "contracts": list(CONTRACTS), "ok": False, "error": str(error)}],
            "failures": [str(error)],
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "scratchRoot": str(run_root),
        }
