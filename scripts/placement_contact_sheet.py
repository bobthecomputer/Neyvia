"""Contact sheet for docs/evidence/placement-shots: index.html from receipt.json (no network, no scripts)."""
from __future__ import annotations

import html
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/evidence/placement-shots"
COLUMNS = [
    ("main", "desktop", "Beside the chat"), ("side", "desktop", "Side panel"), ("full", "desktop", "Full screen"),
    ("bubble", "desktop", "Bubble"), ("bubble-peek", "desktop", "Bubble, peeking"), ("bubble-peek-isolated", "desktop", "Peek (shell hidden)"),
    ("side", "phone", "Phone: split"), ("bubble-peek", "phone", "Phone: bubble peek"),
]


def main():
    # Runs go side by side (placement_shots.py --tag): merge their receipts, in app order.
    parts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(OUT.glob("receipt-*.json"))]
    # Summary first: a reader (or the manual's bounded workspace.read, 20000 characters) sees the verdict
    # and every whole-round-trip check before the 130 KB of per-shot detail. Derived from the checks below.
    all_checks = [check for part in parts for check in part["checks"]]
    summary = {"ok": bool(all_checks) and all(part.get("ok") for part in parts) and all(check["ok"] for check in all_checks),
               "checks": len(all_checks), "passed": sum(1 for check in all_checks if check["ok"]),
               "failed": [check["label"] for check in all_checks if not check["ok"]],
               "roundTrip": [check["label"] for check in all_checks if "state kept after the whole round trip" in check["label"]]}
    receipt = {"schema": "neyvia.placement-shots.v1", "summary": summary, "runs": [{k: part.get(k) for k in ("at", "ports", "ok", "failure", "engine", "errors")} for part in parts],
               "shots": [shot for part in parts for shot in part["shots"]], "checks": [check for part in parts for check in part["checks"]],
               "marks": {k: v for part in parts for k, v in part.get("marks", {}).items()}}
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2, default=str) + chr(10), encoding="utf-8")
    files = {path.name for path in OUT.glob("*.png")}
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from placement_shots import APPS
    shot_apps = {shot["app"] for shot in receipt["shots"]}
    apps = [app for app, *_ in APPS if app in shot_apps]
    checks = receipt["checks"]
    passed = sum(1 for check in checks if check["ok"])
    failed = [check for check in checks if not check["ok"]]

    def cell(app, placement, viewport):
        name = f"{app}-{placement}" + ("-phone" if viewport == "phone" else "") + ".png"
        if placement == "bubble-peek-isolated":
            name = f"{app}-bubble-peek-isolated.png"
        if name not in files:
            return '<td class="missing">no shot</td>'
        return f'<td><a href="{html.escape(name)}"><img loading="lazy" src="{html.escape(name)}" alt="{html.escape(app)} {html.escape(placement)} {viewport}" class="{viewport}"></a></td>'

    rows = []
    for app in apps:
        app_checks = [check for check in checks if check["label"].startswith(app)]
        ok = all(check["ok"] for check in app_checks)
        rows.append(f'<tr><th scope="row"><strong>{html.escape(app)}</strong><span class="{"ok" if ok else "bad"}">{sum(c["ok"] for c in app_checks)}/{len(app_checks)} checks</span></th>'
                    + "".join(cell(app, placement, viewport) for placement, viewport, _ in COLUMNS) + "</tr>")
    extra = [shot for shot in receipt["shots"] if shot["placement"] in ("dragging", "side-left")]
    extra_html = "".join(f'<figure><a href="{html.escape(s["file"])}"><img src="{html.escape(s["file"])}" alt="{html.escape(s["note"])}"></a><figcaption>{html.escape(s["note"] or s["placement"])}</figcaption></figure>' for s in extra)
    fail_html = "".join(f"<li>{html.escape(check['label'])}</li>" for check in failed) or "<li>None</li>"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Placement proof</title>
<style>
:root {{ --bg:#0b100d; --panel:#121a15; --line:#24312a; --text:#e6efe9; --muted:#9db0a4; --ok:#5fcf8f; --bad:#ff7a6b; color-scheme: dark; }}
@media (prefers-color-scheme: light) {{ :root:not([data-theme="dark"]) {{ --bg:#f5f1e6; --panel:#fffdf8; --line:#ddd5c4; --text:#1d2420; --muted:#5d6a62; --ok:#1f8a4c; --bad:#b4372b; color-scheme: light; }} }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif; }}
main {{ max-width: 1900px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }} h2 {{ font-size: 16px; margin: 28px 0 10px; }}
p {{ color: var(--muted); margin: 4px 0; max-width: 1000px; }}
.wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }}
table {{ border-collapse: collapse; }}
th, td {{ padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }}
thead th {{ position: sticky; top: 0; background: var(--panel); font-size: 12px; color: var(--muted); font-weight: 600; white-space: nowrap; }}
tbody th {{ white-space: nowrap; }} tbody th span {{ display:block; font-size:12px; font-weight:600; }}
.ok {{ color: var(--ok); }} .bad {{ color: var(--bad); }}
img {{ display:block; width: 220px; border-radius: 6px; border: 1px solid var(--line); }}
img.phone {{ width: 104px; }}
.missing {{ color: var(--muted); font-size: 12px; }}
.extra {{ display:flex; gap:16px; flex-wrap:wrap; }} .extra img {{ width: 420px; max-width: 100%; }}
figure {{ margin:0; }} figcaption {{ font-size:12px; color:var(--muted); margin-top:4px; max-width:420px; }}
</style></head>
<body><main>
<h1>Every app in every placement</h1>
<p>Rendered in Neyvia's own Obscura engine at 1440×900 and 390×844 against the production build, by <code>scripts/placement_shots.py</code>.
Each app was opened from the launcher and moved with its own placement buttons, Esc, the bubble's keys and (3D Studio) a title-bar drag.
<span class="{'ok' if not failed else 'bad'}">{passed} of {len(checks)} checks passed.</span>
"State kept" checks prove no remount: a mark on the window's body, a value typed in its first text field and a mark on its iframe's window all survive every move.</p>
<p>Engine limits, not product faults: Obscura does not paint iframe contents and has no WebGL, so the 3D scene, web pages and app previews show empty frames
(the 3D iframe's live document is still proven kept); and it paints lower layers' text through floating layers, so "Peek (shell hidden)" repeats the same moment
with the shell under the peek hidden for that shot only.</p>
<h2>Matrix</h2>
<div class="wrap"><table><thead><tr><th>App</th>{''.join(f'<th>{html.escape(label)}</th>' for *_, label in COLUMNS)}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>Moved by the user: drag to another place</h2>
<div class="extra">{extra_html}</div>
<h2>Failed checks</h2><ul>{fail_html}</ul>
</main></body></html>
"""
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(f"index.html: {len(apps)} apps, {passed}/{len(checks)} checks")


if __name__ == "__main__":
    main()
