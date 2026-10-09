from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.video_tools import VideoEvidenceBuilder


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def record_real_ui(base_url: str, output_dir: Path) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment gate
        raise RuntimeError("Python Playwright is required for real Neyvia video proof.") from exc

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(raw_dir),
            record_video_size={"width": 1280, "height": 888},
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.goto(base_url, wait_until="networkidle", timeout=45_000)
        page.get_by_role("region", name="Neyvia command composer").wait_for(state="visible")
        page.wait_for_timeout(600)

        page.get_by_role("button", name="Add context or action", exact=True).click()
        page.get_by_role("menuitem", name="Feature tour Open quick walkthrough", exact=True).click()
        page.get_by_role("dialog", name="Welcome to Neyvia").wait_for(state="visible")
        page.wait_for_timeout(700)
        page.get_by_role("button", name="Next", exact=True).click()
        page.wait_for_timeout(650)
        page.get_by_role("button", name="Next", exact=True).click()
        page.wait_for_timeout(650)
        page.get_by_role("button", name="Skip tour", exact=True).click()

        page.get_by_label("Open Builder", exact=True).click()
        page.wait_for_timeout(900)
        page.get_by_label("Open Agent", exact=True).click()
        page.wait_for_timeout(900)

        video = page.video
        context.close()
        browser.close()
        if video is None:
            raise RuntimeError("Playwright did not expose a recorded video artifact.")
        recorded = Path(video.path())

    final_video = output_dir / "neyvia-real-ui.webm"
    shutil.copy2(recorded, final_video)
    return final_video


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a real Neyvia workflow and build model-readable video proof.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--base-url", default="http://127.0.0.1:1420/control?preview-control=1&mode=builder")
    parser.add_argument("--max-frames", type=int, default=12)
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    output_dir = root / ".agent_control" / "mission_artifacts" / "native_tools" / "video" / f"neyvia-real-ui-{_stamp()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = record_real_ui(args.base_url, output_dir)
    digest = VideoEvidenceBuilder(root).digest(
        {
            "path": str(video_path),
            "outputDir": str(output_dir / "digest"),
            "maxFrames": max(6, min(args.max_frames, 24)),
            "maxSceneFrames": 12,
            "sceneThreshold": 0.18,
            "extractAudio": False,
            "transcribe": "none",
        }
    )
    report = {
        "schema": "neyvia.real_ui_video_proof.v1",
        "baseUrl": args.base_url,
        "videoPath": str(video_path),
        "digest": digest,
        "reducedMotion": True,
        "recordedWorkflow": ["agent composer", "feature tour", "tutorial steps", "builder", "agent"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    report_path = output_dir / "real-ui-video-proof.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**report, "reportPath": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
