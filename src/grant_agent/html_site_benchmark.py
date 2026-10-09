"""Frozen, route-honest HTML site benchmark for Neyvia harnesses."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from .proofs_b_adapters import checked as _proofs_b_checked


PROTOCOL_ID = "neyvia-html-site-v1"
SCHEMA = "neyvia.html-site-benchmark/v1"
FROZEN_PROMPT = """Build a polished, responsive single-page product site called Lumen Notes.

Write the finished artifact to index.html in the current working directory. Use only HTML, CSS, and vanilla JavaScript inside that one file: no external fonts, images, packages, CDNs, or network requests.

The page must include:
- semantic header, nav, main, and footer landmarks;
- exactly one h1 and a clear hero action;
- a feature grid and a demo notes section;
- three filter buttons labelled All, Ideas, and Tasks; clicking them must update the visible note cards and aria-pressed state;
- a theme toggle that updates an accessible label and a visible light/dark state;
- keyboard-visible focus, meaningful button types and labels, reduced-motion support, and sufficient contrast;
- a mobile layout at 390px with no horizontal overflow and a desktop layout at 1440px.

Make the visual hierarchy deliberate and original. Complete the file and verify the interactions. Do not substitute a framework or return only an explanation."""


STATIC_MAX = 80
BROWSER_MAX = 20


def _check(checks: list[dict[str, Any]], key: str, passed: bool, points: int, detail: str) -> None:
    checks.append({"id": key, "passed": bool(passed), "points": points if passed else 0, "maximum": points, "detail": detail})


@_proofs_b_checked("html")
def grade_html(path: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if not path.is_file():
        return {"score": 0, "maximum": STATIC_MAX, "checks": [], "status": "missing"}
    source = path.read_text(encoding="utf-8", errors="replace")
    lower = source.casefold()
    _check(checks, "artifact", len(source) >= 2500, 10, "A substantial single-file artifact exists.")
    _check(checks, "landmarks", all(f"<{tag}" in lower for tag in ("header", "nav", "main", "footer")), 10, "Semantic page landmarks are present.")
    h1_count = len(re.findall(r"<h1\b", lower))
    _check(checks, "heading", h1_count == 1, 5, f"Expected one h1; found {h1_count}.")
    buttons = re.findall(r"<button\b[^>]*>", source, re.IGNORECASE)
    typed_buttons = [button for button in buttons if re.search(r"\btype\s*=", button, re.IGNORECASE)]
    _check(checks, "button-types", len(buttons) >= 4 and len(typed_buttons) == len(buttons), 5, "Interactive buttons declare their type.")
    _check(checks, "filter-labels", all(re.search(rf">\s*{label}\s*<", source, re.IGNORECASE) for label in ("All", "Ideas", "Tasks")), 8, "All frozen filter labels are visible.")
    _check(checks, "aria-pressed", "aria-pressed" in lower, 7, "Filter state exposes aria-pressed.")
    _check(checks, "theme-accessibility", "theme" in lower and ("aria-label" in lower or "aria-labelledby" in lower), 5, "Theme control has an accessible name.")
    _check(checks, "responsive", bool(re.search(r"@media\s*\([^)]*(max-width|max-width\s*:|width\s*<)", source, re.IGNORECASE)), 8, "A narrow-layout media query exists.")
    _check(checks, "focus", ":focus-visible" in lower, 5, "Keyboard focus is visibly styled.")
    _check(checks, "reduced-motion", "prefers-reduced-motion" in lower, 5, "Reduced-motion preference is handled.")
    _check(checks, "interaction-code", "addEventListener" in source and ("data-category" in lower or "dataset" in source), 7, "Vanilla JavaScript binds the requested interaction.")
    external = re.findall(r"(?:src|href)\s*=\s*[\"'](?:https?:)?//", source, re.IGNORECASE)
    _check(checks, "offline", not external and "fetch(" not in source and "XMLHttpRequest" not in source, 5, "No external dependency or network request is present.")
    score = sum(item["points"] for item in checks)
    return {"score": score, "maximum": STATIC_MAX, "checks": checks, "status": "graded", "bytes": len(source.encode("utf-8"))}


@_proofs_b_checked("html-combined")
def combine_score(static: dict[str, Any], browser: dict[str, Any]) -> dict[str, Any]:
    browser_score = int(browser.get("score") or 0)
    total = int(static.get("score") or 0) + browser_score
    return {
        "score": total,
        "maximum": STATIC_MAX + BROWSER_MAX,
        "static": static,
        "browser": browser,
        "passed": total >= 75 and browser_score >= 12,
    }
