"""DEPRECATED as a product UI gate.

Product chrome / landmark coverage moved to CU acceptance (structured ui.*):

    npm run verify:cu

See ``.agent_control/mission_artifacts/cu_acceptance/MATRIX.md``
(``control_room`` / ``surface_navigation`` cover structured landmarks).

This module remains for ad-hoc screenshot capture and as a helper import
(``find_browser``, ``image_stats``) used by specialized runtime proofs.
Pixel / viewport visual regression is **partial** — not fully replaced by CU.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
except Exception as exc:  # pragma: no cover - environment guard
    Image = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[1]
_CU_DEPRECATION = (
    "DEPRECATED product gate: prefer `npm run verify:cu` "
    "(see .agent_control/mission_artifacts/cu_acceptance/MATRIX.md). "
    "Continuing as ad-hoc visual capture only."
)
DEFAULT_URL = "http://127.0.0.1:1420/control?preview-control=1&fixture=live_review&mode=builder&surface=workbench"
DEFAULT_OUT_DIR = ROOT / "docs" / "cleanup" / "before-after" / "2026-05-20"


def find_browser(preference: str = "auto", browser_path: str = "") -> str:
    if browser_path:
        if Path(browser_path).exists():
            return browser_path
        raise RuntimeError(f"Browser path does not exist: {browser_path}")
    zen_candidates = [
        r"C:\Program Files\Zen Browser\zen.exe",
        r"C:\Program Files\Zen\zen.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "Zen Browser" / "zen.exe"),
        str(Path.home() / "AppData" / "Local" / "zen" / "zen.exe"),
        shutil.which("zen"),
    ]
    chromium_candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    if preference == "zen":
        candidates = zen_candidates
    elif preference in {"chrome", "chromium", "edge"}:
        candidates = chromium_candidates
    else:
        candidates = chromium_candidates + zen_candidates
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise RuntimeError("No Chrome, Chromium, Edge, or Zen executable found for visual smoke capture.")


def playwright_managed_browser_candidates() -> list[str]:
    """Find Playwright-managed Chromium executables across platforms."""
    roots: list[Path] = []
    env_root = str(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if env_root:
        roots.append(Path(env_root))
    home = Path.home()
    roots.extend(
        [
            home / "AppData" / "Local" / "ms-playwright",  # Windows default
            home / ".cache" / "ms-playwright",  # Linux default
            home / "Library" / "Caches" / "ms-playwright",  # macOS default
        ]
    )
    patterns = (
        "chromium-*/chrome-win/chrome.exe",
        "chromium-*/chrome-win64/chrome.exe",
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-linux64/chrome",
        "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    )
    found: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            for candidate in sorted(root.glob(pattern), reverse=True):
                key = str(candidate)
                if key not in seen and candidate.is_file():
                    seen.add(key)
                    found.append(key)
    return found


def find_browser_or_playwright_managed(preference: str = "auto", browser_path: str = "") -> str:
    """Return a system browser if available, otherwise a Playwright-managed Chromium."""
    try:
        return find_browser(preference, browser_path)
    except RuntimeError:
        managed = playwright_managed_browser_candidates()
        if managed:
            return managed[0]
        raise RuntimeError(
            "No Chrome, Chromium, Edge, Zen, or Playwright-managed browser executable was found. "
            "Install a browser or run `python -m playwright install chromium`."
        )


def browser_family(browser: str) -> str:
    lowered = browser.lower()
    if "zen" in lowered:
        return "zen"
    if "firefox" in lowered:
        return "firefox"
    return "chromium"


def run_browser(browser: str, args: list[str], timeout: int = 45) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [browser, "--headless", "--disable-gpu", "--no-sandbox", *args],
        check=False,
        cwd=ROOT,
        capture_output=True,
        timeout=timeout,
    )


def decode_output(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")


def image_stats(path: Path) -> dict[str, object]:
    if Image is None:
        raise RuntimeError(f"Pillow is required for pixel checks: {PIL_IMPORT_ERROR}")
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        step_x = max(1, width // 90)
        step_y = max(1, height // 90)
        samples = []
        for y in range(0, height, step_y):
            for x in range(0, width, step_x):
                samples.append(rgb.getpixel((x, y)))
        unique = len(set(samples))
        average_luma = sum((0.2126 * r + 0.7152 * g + 0.0722 * b) for r, g, b in samples) / max(len(samples), 1)
        return {
            "width": width,
            "height": height,
            "sampleCount": len(samples),
            "uniqueSampleColors": unique,
            "averageLuma": round(average_luma, 2),
            "nonBlank": unique >= 24 and width >= 1000 and height >= 700,
        }


def main() -> int:
    print(_CU_DEPRECATION, file=sys.stderr)
    parser = argparse.ArgumentParser(description="Capture and verify the rendered control route.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--name", default="runtime-workbench-visual-proof")
    parser.add_argument("--browser", choices=["auto", "chrome", "chromium", "edge", "zen"], default="auto")
    parser.add_argument("--browser-path", default="")
    parser.add_argument(
        "--expect",
        action="append",
        default=None,
        help="Rendered DOM text that must be present. May be passed multiple times.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = out_dir / f"{args.name}.png"
    dom_path = out_dir / f"{args.name}.html"
    report_path = out_dir / f"{args.name}-check.json"

    browser = find_browser(args.browser, args.browser_path)
    family = browser_family(browser)
    if family in {"zen", "firefox"}:
        profile_dir = ROOT / "tmp-ui-checks" / f"{family}-visual-smoke-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        screenshot_args = [
            "--no-remote",
            "--profile",
            str(profile_dir),
            "--window-size=1440,1200",
            "--screenshot",
            str(screenshot_path),
            args.url,
        ]
    else:
        screenshot_args = [
            "--hide-scrollbars",
            "--window-size=1440,1200",
            "--virtual-time-budget=5000",
            f"--screenshot={screenshot_path}",
            args.url,
        ]
    screenshot = run_browser(browser, screenshot_args)
    if screenshot.returncode not in (0, None) and not screenshot_path.exists():
        raise RuntimeError(
            decode_output(screenshot.stderr).strip()
            or decode_output(screenshot.stdout).strip()
            or "Browser screenshot failed."
        )
    if not screenshot_path.exists():
        raise RuntimeError("Browser did not create a screenshot.")

    dom_text = ""
    dom_supported = family == "chromium"
    if dom_supported:
        dom = run_browser(browser, ["--virtual-time-budget=5000", "--dump-dom", args.url])
        if dom.returncode not in (0, None):
            raise RuntimeError(
                decode_output(dom.stderr).strip()
                or decode_output(dom.stdout).strip()
                or "Browser DOM dump failed."
            )
        dom_text = decode_output(dom.stdout)
    dom_path.write_text(dom_text, encoding="utf-8")

    expected = args.expect or ["Runtime operations", "Automatic verify", "OpenClaw", "Hermes"]
    missing = [] if not dom_supported else [fragment for fragment in expected if fragment not in dom_text]
    stats = image_stats(screenshot_path)
    passed = not missing and bool(stats["nonBlank"])
    report = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "browser": browser,
        "browserFamily": family,
        "domSupported": dom_supported,
        "screenshotPath": str(screenshot_path),
        "domPath": str(dom_path),
        "expectedFragments": expected,
        "missingFragments": missing,
        "image": stats,
        "passed": passed,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not passed:
        print(json.dumps(report, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
