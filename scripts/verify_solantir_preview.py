from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOLANTIR_ROOT = Path("Y:/projects/solantir-mindtower-fusion/Solantir")
DEFAULT_OUT_DIR = ROOT / ".agent_control" / "solantir_preview_proofs"
DEFAULT_RSS_URL = "https://feeds.bbci.co.uk/news/world/rss.xml"
RSS_SAMPLE_NAMES = (
    "BBC World",
    "NPR News",
    "Guardian World",
    "France 24",
    "DW News",
    "CNBC",
    "Federal Reserve",
    "SEC",
)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from control_route_interaction_smoke import Cdp, DevToolsSocket, free_port, wait_for_devtools
from control_route_visual_smoke import find_browser, image_stats


def checked_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return "".join(char for char in checked_at() if char.isdigit())[:14]


def make_check(check_id: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"id": check_id, "passed": bool(passed), "detail": detail, **extra}


def tail(text: str, limit: int = 1800) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[-limit:]


def npm_binary() -> str:
    name = "npm.cmd" if os.name == "nt" else "npm"
    candidate = shutil.which(name) or shutil.which("npm")
    if not candidate:
        raise RuntimeError("npm is not available on PATH.")
    return candidate


def node_binary() -> str:
    name = "node.exe" if os.name == "nt" else "node"
    candidate = shutil.which(name) or shutil.which("node")
    if not candidate:
        raise RuntimeError("node is not available on PATH.")
    return candidate


def workspace_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return path.resolve()


def run_npm_script(terminal_root: Path, script_name: str, timeout: int) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            [npm_binary(), "run", script_name],
            cwd=terminal_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return make_check(f"solantir-{script_name}", False, str(exc), command=f"npm run {script_name}")

    elapsed_ms = round((time.time() - started) * 1000)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return make_check(
        f"solantir-{script_name}",
        completed.returncode == 0,
        f"npm run {script_name} exited {completed.returncode}.",
        command=f"npm run {script_name}",
        elapsedMs=elapsed_ms,
        outputPreview=tail(output),
    )


def request_text(url: str, timeout: float = 15.0) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return int(response.status), str(response.headers.get("Content-Type") or ""), body


def looks_like_feed_xml(body: str) -> bool:
    lowered = body.lower()
    return any(token in lowered for token in ("<rss", "<feed", "<item", "<entry"))


def count_feed_items(body: str) -> int:
    return len(re.findall(r"<(?:item|entry)(?:\s|>)", body, flags=re.IGNORECASE))


def extract_feed_sources(feeds_path: Path) -> list[dict[str, str]]:
    try:
        text = feeds_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    name_matches = list(re.finditer(r"name:\s*(['\"])(?P<name>.+?)\1", text))
    for index, match in enumerate(name_matches):
        name = match.group("name")
        next_start = name_matches[index + 1].start() if index + 1 < len(name_matches) else len(text)
        block = text[match.end():next_start]
        for call in re.finditer(r"\b(?P<helper>rss|railwayRss)\('(?P<url>https?://[^']+)'\)", block):
            url = call.group("url")
            key = (name, url)
            if key in seen:
                continue
            seen.add(key)
            sources.append({"name": name, "url": url, "helper": call.group("helper")})
    return sources


def select_feed_sample(sources: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    used_urls: set[str] = set()
    by_name: dict[str, list[dict[str, str]]] = {}
    for source in sources:
        by_name.setdefault(source["name"], []).append(source)

    for name in RSS_SAMPLE_NAMES:
        for source in by_name.get(name, []):
            if source["url"] not in used_urls:
                selected.append(source)
                used_urls.add(source["url"])
                break
        if len(selected) >= limit:
            return selected

    for source in sources:
        if source["url"] in used_urls:
            continue
        selected.append(source)
        used_urls.add(source["url"])
        if len(selected) >= limit:
            break
    return selected


def verify_rss_sample(base_url: str, terminal_root: Path, limit: int, timeout: float) -> dict[str, Any]:
    feeds_path = terminal_root / "src" / "config" / "feeds.ts"
    sources = extract_feed_sources(feeds_path)
    sample = select_feed_sample(sources, max(1, limit))
    results: list[dict[str, Any]] = []
    for source in sample:
        proxy_url = f"{base_url}api/rss-proxy?{urllib.parse.urlencode({'url': source['url']})}"
        started = time.time()
        observed_at = checked_at()
        try:
            status, content_type, body = request_text(proxy_url, timeout=timeout)
            item_count = count_feed_items(body)
            xml_like = looks_like_feed_xml(body)
            passed = status == 200 and xml_like and item_count > 0
            failure_reason = None
            if not passed:
                failure_reason = f"status={status}; xmlLike={xml_like}; itemCount={item_count}"
            results.append(
                {
                    "name": source["name"],
                    "sourceUrl": source["url"],
                    "helper": source["helper"],
                    "checkedAt": observed_at,
                    "passed": passed,
                    "status": status,
                    "contentType": content_type,
                    "itemCount": item_count,
                    "failureReason": failure_reason,
                    "elapsedMs": round((time.time() - started) * 1000),
                    "bodyPreview": tail(body, 500),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "name": source["name"],
                    "sourceUrl": source["url"],
                    "helper": source["helper"],
                    "checkedAt": observed_at,
                    "passed": False,
                    "failureReason": str(exc),
                    "elapsedMs": round((time.time() - started) * 1000),
                }
            )

    failed = [item for item in results if not item.get("passed")]
    return make_check(
        "rss-proxy-sampled-feeds",
        bool(sample) and not failed,
        (
            f"{len(results)}/{len(results)} sampled RSS feeds returned feed XML."
            if sample and not failed
            else f"{len(results) - len(failed)}/{len(results)} sampled RSS feeds returned feed XML."
        ),
        feedsPath=str(feeds_path),
        configuredFeedCount=len(sources),
        sampledFeeds=results,
    )


def wait_for_http(url: str, timeout: float = 25.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            status, content_type, body = request_text(url, timeout=3.0)
            if status < 500:
                return {"status": status, "contentType": content_type, "bodyPreview": tail(body, 600)}
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.35)
    raise RuntimeError(last_error or f"Timed out waiting for {url}")


def start_preview(terminal_root: Path, port: int, variant: str) -> subprocess.Popen[str]:
    vite_bin = terminal_root / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_bin.exists():
        raise RuntimeError(f"Missing Vite binary: {vite_bin}")
    env = {**os.environ, "VITE_VARIANT": variant}
    return subprocess.Popen(
        [
            node_binary(),
            str(vite_bin),
            "preview",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=terminal_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop_process(process: subprocess.Popen[str]) -> str:
    output = ""
    if process.poll() is None:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
    else:
        stdout, stderr = process.communicate(timeout=2)
    output = "\n".join(part for part in (stdout, stderr) if part)
    return tail(output)


def eval_wait(cdp: Cdp, expression: str, timeout: float = 12.0) -> Any:
    deadline = time.time() + timeout
    last_value: Any = None
    while time.time() < deadline:
        last_value = cdp.eval(expression)
        if last_value:
            return last_value
        time.sleep(0.25)
    return last_value


def capture_screenshot(cdp: Cdp, path: Path) -> dict[str, Any]:
    result = cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    encoded = result.get("data") if isinstance(result, dict) else None
    if not isinstance(encoded, str):
        raise RuntimeError("CDP did not return screenshot data.")
    path.write_bytes(base64.b64decode(encoded))
    stats = image_stats(path)
    return {"path": str(path), **stats}


def verify_browser(base_url: str, out_dir: Path, browser: str, browser_path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}
    debug_port = free_port()
    executable = find_browser(browser, browser_path)
    profile = tempfile.TemporaryDirectory(prefix="solantir-preview-browser-")
    process = subprocess.Popen(
        [
            executable,
            "--headless",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-sandbox",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile.name}",
            "--window-size=1440,1200",
            "about:blank",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ws: DevToolsSocket | None = None
    try:
        tabs = wait_for_devtools(debug_port)
        ws = DevToolsSocket(str(tabs[0]["webSocketDebuggerUrl"]))
        cdp = Cdp(ws)
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Page.navigate", {"url": base_url})
        rendered = eval_wait(
            cdp,
            """
(() => {
  const body = document.body ? document.body.innerText : "";
  return document.readyState === "complete"
    && body.length > 100
    && Boolean(document.querySelector('[data-panel="live-news"]'));
})()
""",
            timeout=18,
        )
        snapshot = cdp.eval(
            """
(() => {
  const panelInfo = selector => {
    const node = document.querySelector(selector);
    if (!node) return { found: false };
    const rect = node.getBoundingClientRect();
    return { found: true, width: Math.round(rect.width), height: Math.round(rect.height), text: node.innerText.slice(0, 500) };
  };
            return {
    title: document.title,
    textLength: document.body ? document.body.innerText.length : 0,
    liveNews: panelInfo('[data-panel="live-news"]'),
    liveWebcams: panelInfo('[data-panel="live-webcams"]'),
    liveNewsFrames: Array.from(document.querySelectorAll('[data-panel="live-news"] iframe')).map(frame => frame.src),
    webcamCells: document.querySelectorAll('[data-panel="live-webcams"] .webcam-cell').length,
  };
})()
"""
        )
        checks.append(make_check("browser-preview-rendered", bool(rendered), "Solantir preview renders the live-news panel.", snapshot=snapshot))

        live_news_text = ""
        if isinstance(snapshot, dict) and isinstance(snapshot.get("liveNews"), dict):
            live_news_text = str(snapshot["liveNews"].get("text") or "")
        live_news_error = any(
            fragment in live_news_text.lower()
            for fragment in (
                "cannot be embedded",
                "ne peut pas être intégré",
                "n'est pas disponible",
                "not available",
                "video unavailable",
            )
        )
        live_news_ready = isinstance(snapshot, dict) and bool(snapshot.get("liveNews", {}).get("found")) and not live_news_error
        checks.append(
            make_check(
                "live-news-panel-visible",
                live_news_ready,
                "Live news panel is present without a visible YouTube embed error.",
                liveNewsTextPreview=live_news_text[:700],
            )
        )

        webcam_probe = cdp.eval(
            """
(() => {
  const panel = document.querySelector('[data-panel="live-webcams"]');
  if (!panel) return { clicked: false, reason: 'live-webcams panel missing' };
  panel.scrollIntoView({ block: 'center', inline: 'center' });
  const firstCell = panel.querySelector('.webcam-cell');
  if (!firstCell) return { clicked: false, reason: 'webcam grid cell missing', text: panel.innerText.slice(0, 300) };
  firstCell.click();
  return { clicked: true, text: firstCell.innerText.slice(0, 300) };
})()
"""
        )
        time.sleep(1.0)
        webcam_iframe = eval_wait(
            cdp,
            """
(() => {
  const frame = document.querySelector('[data-panel="live-webcams"] iframe.webcam-iframe');
  if (!frame) return null;
  const status = document.querySelector('[data-panel="live-webcams"] .webcam-feed-status');
  const rect = frame.getBoundingClientRect();
  return {
    src: frame.getAttribute('src') || '',
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    visible: rect.width > 200 && rect.height > 120,
    source: frame.dataset.videoSource || '',
    videoId: frame.dataset.videoId || '',
    channelHandle: frame.dataset.channelHandle || '',
    statusFound: Boolean(status),
    statusSource: status?.dataset?.videoSource || '',
    statusText: status?.innerText?.replace(/\\s+/g, ' ').trim() || '',
    sandbox: frame.getAttribute('sandbox') || '',
  };
})()
""",
            timeout=8,
        )
        webcam_status_honest = (
            isinstance(webcam_iframe, dict)
            and bool(webcam_iframe.get("visible"))
            and bool(webcam_iframe.get("statusFound"))
            and str(webcam_iframe.get("source") or "") in {"live", "fallback"}
            and str(webcam_iframe.get("statusSource") or "") == str(webcam_iframe.get("source") or "")
            and bool(str(webcam_iframe.get("statusText") or "").strip())
        )
        checks.append(
            make_check(
                "live-webcam-source-status-visible",
                bool(webcam_status_honest),
                "Webcam single view exposes whether the iframe uses a live lookup or a fallback video ID.",
                clickProbe=webcam_probe,
                iframe=webcam_iframe,
            )
        )
        webcam_ready = (
            isinstance(webcam_probe, dict)
            and webcam_probe.get("clicked")
            and isinstance(webcam_iframe, dict)
            and webcam_iframe.get("visible")
            and webcam_iframe.get("source") == "live"
            and (
                "youtube-nocookie.com/embed" in str(webcam_iframe.get("src") or "")
                or "/api/youtube/embed" in str(webcam_iframe.get("src") or "")
            )
        )
        checks.append(
            make_check(
                "live-webcam-embed-visible",
                bool(webcam_ready),
                "Clicking a webcam opens a visible stream only when the current channel live lookup resolves.",
                clickProbe=webcam_probe,
                iframe=webcam_iframe,
            )
        )
        if webcam_ready:
            time.sleep(5.0)

        screenshot = capture_screenshot(cdp, out_dir / f"{stamp()}_solantir_preview.png")
        artifacts["screenshot"] = screenshot
        checks.append(
            make_check(
                "browser-screenshot-nonblank",
                bool(screenshot.get("nonBlank")),
                "Preview screenshot is nonblank and large enough for operator inspection.",
                screenshot=screenshot,
            )
        )
    except Exception as exc:
        checks.append(make_check("browser-preview-exception", False, str(exc)))
    finally:
        if ws is not None:
            ws.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        profile.cleanup()
    return checks, artifacts


def verify_preview(
    terminal_root: Path,
    out_dir: Path,
    variant: str,
    rss_url: str,
    browser: str,
    browser_path: str,
    rss_sample_limit: int,
    rss_sample_timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}
    port = free_port()
    base_url = f"http://127.0.0.1:{port}/"
    process: subprocess.Popen[str] | None = None
    try:
        process = start_preview(terminal_root, port, variant)
        index_probe = wait_for_http(base_url)
        checks.append(
            make_check(
                "vite-preview-http-ready",
                int(index_probe.get("status") or 0) == 200,
                "Vite preview served the Solantir app.",
                url=base_url,
                response=index_probe,
            )
        )

        proxy_url = f"{base_url}api/rss-proxy?{urllib.parse.urlencode({'url': rss_url})}"
        try:
            status, content_type, body = request_text(proxy_url, timeout=20.0)
            item_count = count_feed_items(body)
            xml_like = looks_like_feed_xml(body)
            rss_ok = status == 200 and xml_like and item_count > 0
            failure_reason = None
            if not rss_ok:
                failure_reason = f"status={status}; xmlLike={xml_like}; itemCount={item_count}"
            checks.append(
                make_check(
                    "rss-proxy-live-fetch",
                    rss_ok,
                    "RSS proxy returned feed XML with sourced items." if rss_ok else "RSS proxy did not return feed XML with sourced items.",
                    url=proxy_url,
                    checkedAt=checked_at(),
                    status=status,
                    contentType=content_type,
                    itemCount=item_count,
                    failureReason=failure_reason,
                    bodyPreview=tail(body, 900),
                )
            )
        except Exception as exc:
            checks.append(make_check("rss-proxy-live-fetch", False, str(exc), url=proxy_url, checkedAt=checked_at(), failureReason=str(exc)))

        checks.append(verify_rss_sample(base_url, terminal_root, rss_sample_limit, rss_sample_timeout))

        browser_checks, browser_artifacts = verify_browser(base_url, out_dir, browser, browser_path)
        checks.extend(browser_checks)
        artifacts.update(browser_artifacts)
    except Exception as exc:
        checks.append(make_check("vite-preview-start", False, str(exc), url=base_url))
    finally:
        if process is not None:
            artifacts["previewLog"] = stop_process(process)
    artifacts["baseUrl"] = base_url
    return checks, artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Solantir NAS fusion preview, RSS proxy, and camera/browser surfaces.")
    parser.add_argument("--solantir-root", default=str(DEFAULT_SOLANTIR_ROOT))
    parser.add_argument("--terminal-root", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--variant", default="full", choices=["full", "tech", "finance"])
    parser.add_argument("--rss-url", default=DEFAULT_RSS_URL)
    parser.add_argument("--browser", default="auto", choices=["auto", "chrome", "chromium", "edge", "zen"])
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--rss-sample-limit", type=int, default=8)
    parser.add_argument("--rss-sample-timeout", type=float, default=15.0)
    parser.add_argument("--skip-source-checks", action="store_true")
    parser.add_argument("--source-timeout", type=int, default=45)
    args = parser.parse_args()

    solantir_root = workspace_path(args.solantir_root)
    terminal_root = workspace_path(args.terminal_root) if args.terminal_root else solantir_root / "apps" / "terminal"
    out_dir = workspace_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}
    checks.append(make_check("solantir-terminal-root-present", terminal_root.exists(), f"Terminal root: {terminal_root}"))
    checks.append(make_check("solantir-dist-present", (terminal_root / "dist" / "index.html").exists(), "Preview dist/index.html is present."))

    if terminal_root.exists() and not args.skip_source_checks:
        for script_name in ("test:data", "test:sidecar", "typecheck"):
            checks.append(run_npm_script(terminal_root, script_name, args.source_timeout))

    if terminal_root.exists():
        preview_checks, preview_artifacts = verify_preview(
            terminal_root,
            out_dir,
            args.variant,
            args.rss_url,
            args.browser,
            args.browser_path,
            args.rss_sample_limit,
            args.rss_sample_timeout,
        )
        checks.extend(preview_checks)
        artifacts.update(preview_artifacts)

    passed = all(check.get("passed") for check in checks)
    report = {
        "schema": "fluxio.solantir.preview_verification.v1",
        "status": "passed" if passed else "failed",
        "checkedAt": checked_at(),
        "solantirRoot": str(solantir_root),
        "terminalRoot": str(terminal_root),
        "variant": args.variant,
        "rssUrl": args.rss_url,
        "summary": f"{sum(1 for check in checks if check.get('passed'))}/{len(checks)} Solantir preview checks passed.",
        "checks": checks,
        "artifacts": artifacts,
    }
    report_path = out_dir / f"{stamp()}_solantir_preview_proof.json"
    report["proofPath"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path = out_dir / "latest.json"
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary": report["summary"], "proofPath": str(report_path)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
