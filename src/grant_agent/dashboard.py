from __future__ import annotations

import json
from pathlib import Path
from .proofs_b_desktop import checked


def _safe_read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_proof_bundles(bundle_root: Path) -> list[dict]:
    if not bundle_root.exists():
        return []

    bundles: list[dict] = []
    for folder in sorted(
        [item for item in bundle_root.glob("bundle_*") if item.is_dir()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        payload_path = folder / "proof_payload.json"
        payload = _safe_read_json(payload_path)
        if not payload:
            continue

        preset = payload.get("preset", {})
        before = payload.get("training_before", {})
        after = payload.get("training_after", {})
        comparison = payload.get("training_comparison", {})
        probe = payload.get("probe", {})

        bundles.append(
            {
                "id": folder.name,
                "generated_at": payload.get("generated_at", ""),
                "preset": preset.get("name", "unknown"),
                "description": preset.get("description", ""),
                "before_score": before.get("completion_score", 0),
                "after_score": after.get("completion_score", 0),
                "score_delta": comparison.get("score_delta", 0),
                "probe_status": probe.get("status", "unknown"),
                "resistance_score": probe.get("resistance_score", 0),
                "top_findings": payload.get("top_findings", []),
                "bundle_path": str(folder),
                "proof_panel_path": str(folder / "proof_report_panel.html"),
                "proof_report_path": str(folder / "proof_report.md"),
                "payload_path": str(payload_path),
            }
        )

    return bundles


def _stats(bundles: list[dict]) -> dict:
    count = len(bundles)
    if count == 0:
        return {
            "count": 0,
            "avg_delta": 0,
            "avg_resistance": 0,
            "pass_rate": 0,
        }

    avg_delta = round(sum(int(item.get("score_delta", 0)) for item in bundles) / count, 2)
    avg_resistance = round(sum(int(item.get("resistance_score", 0)) for item in bundles) / count, 2)
    passed = len([item for item in bundles if item.get("probe_status") == "pass"])
    pass_rate = round((passed / count) * 100, 1)
    return {
        "count": count,
        "avg_delta": avg_delta,
        "avg_resistance": avg_resistance,
        "pass_rate": pass_rate,
    }


@checked("desktop.dashboard.artifact")
def write_proof_dashboard(bundle_root: Path, output_path: Path) -> Path:
    bundles = load_proof_bundles(bundle_root)
    stats = _stats(bundles)

    bundles_json = json.dumps(bundles)

    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Proof Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f5f7fb; color: #1c2433; }}
    .header {{ padding: 16px 20px; background: #11284f; color: #eaf0ff; }}
    .header h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
    .stats {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .stat {{ background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.2); padding: 8px 10px; border-radius: 8px; }}
    .layout {{ display: grid; grid-template-columns: 360px 1fr; min-height: calc(100vh - 120px); }}
    .sidebar {{ border-right: 1px solid #d5deef; background: #ffffff; overflow: auto; }}
    .controls {{ padding: 12px; border-bottom: 1px solid #e4ebf9; position: sticky; top: 0; background: #fff; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    .list {{ padding: 8px; }}
    .item {{ border: 1px solid #dde5f5; border-radius: 10px; padding: 10px; margin-bottom: 8px; cursor: pointer; background: #fbfdff; }}
    .item.active {{ border-color: #3d67b1; box-shadow: 0 0 0 2px rgba(61,103,177,0.15); }}
    .main {{ padding: 16px; overflow: auto; }}
    .panel {{ background: #fff; border: 1px solid #dde5f5; border-radius: 12px; padding: 14px; margin-bottom: 12px; }}
    .row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .metric {{ flex: 1; min-width: 180px; border: 1px solid #e4ebf9; border-radius: 10px; padding: 10px; background: #fbfdff; }}
    .big {{ font-size: 28px; font-weight: 700; color: #1f4c98; }}
    .muted {{ color: #5a6578; font-size: 13px; }}
    .legend {{ display: flex; gap: 12px; margin-top: 8px; }}
    .tag {{ display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 99px; display: inline-block; }}
    .comparator {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .mini {{ font-size: 12px; color: #4f5b73; }}
    .compare-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-top: 10px; }}
    .compare-box {{ border: 1px solid #e4ebf9; border-radius: 8px; padding: 8px; background: #fbfdff; }}
    svg {{ width: 100%; height: 220px; border: 1px solid #e4ebf9; border-radius: 10px; background: #fbfdff; }}
    ul {{ margin: 8px 0 0 18px; }}
    a {{ color: #1d4ea3; text-decoration: none; }}
  </style>
</head>
<body>
  <div class=\"header\">
    <h1>Proof Report Dashboard</h1>
    <div class=\"stats\">
      <div class=\"stat\">Bundles: {stats['count']}</div>
      <div class=\"stat\">Avg score delta: {stats['avg_delta']}</div>
      <div class=\"stat\">Avg resistance: {stats['avg_resistance']}</div>
      <div class=\"stat\">Probe pass rate: {stats['pass_rate']}%</div>
    </div>
  </div>

  <div class=\"layout\">
    <div class=\"sidebar\">
      <div class=\"controls\">
        <label for=\"presetFilter\">Filter preset:</label>
        <select id=\"presetFilter\"><option value=\"all\">all</option></select>
      </div>
      <div id=\"bundleList\" class=\"list\"></div>
    </div>

    <div class=\"main\">
      <div id=\"overviewPanel\"></div>
      <div id=\"selectedPanel\"></div>
    </div>
  </div>

  <script>
    const bundles = {bundles_json};
    const listEl = document.getElementById('bundleList');
    const overviewEl = document.getElementById('overviewPanel');
    const selectedEl = document.getElementById('selectedPanel');
    const filterEl = document.getElementById('presetFilter');
    let selectedId = bundles.length ? bundles[0].id : null;
    let compareAId = bundles.length ? bundles[0].id : null;
    let compareBId = bundles.length > 1 ? bundles[1].id : (bundles.length ? bundles[0].id : null);

    function presetOptions() {{
      const set = new Set(bundles.map(item => item.preset));
      [...set].sort().forEach(name => {{
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        filterEl.appendChild(opt);
      }});
    }}

    function filtered() {{
      const current = filterEl.value;
      if (current === 'all') return bundles;
      return bundles.filter(item => item.preset === current);
    }}

    function plotPoints(values, width, height, pad) {{
      if (!values.length) return '';
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = Math.max(1, max - min);
      const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;
      return values.map((v, i) => {{
        const x = pad + i * step;
        const y = height - pad - ((v - min) / span) * (height - pad * 2);
        return `${{x.toFixed(1)}},${{y.toFixed(1)}}`;
      }}).join(' ');
    }}

    function renderOverview() {{
      const rows = filtered();
      if (!rows.length) {{
        overviewEl.innerHTML = '<div class="panel">No bundles to summarize.</div>';
        return;
      }}

      if (!rows.find(item => item.id === compareAId)) compareAId = rows[0].id;
      if (!rows.find(item => item.id === compareBId)) compareBId = rows.length > 1 ? rows[1].id : rows[0].id;

      const width = 800;
      const height = 220;
      const pad = 22;

      const deltas = rows.map(item => Number(item.score_delta || 0));
      const resistance = rows.map(item => Number(item.resistance_score || 0));
      const deltaPoints = plotPoints(deltas, width, height, pad);
      const resistancePoints = plotPoints(resistance, width, height, pad);

      const options = rows.map(item => `<option value="${{item.id}}">${{item.id}} (${{item.preset}})</option>`).join('');
      const itemA = rows.find(item => item.id === compareAId) || rows[0];
      const itemB = rows.find(item => item.id === compareBId) || rows[0];
      const deltaGap = Number(itemB.score_delta || 0) - Number(itemA.score_delta || 0);
      const resistanceGap = Number(itemB.resistance_score || 0) - Number(itemA.resistance_score || 0);

      overviewEl.innerHTML = `
        <div class="panel" id="trendPanel">
          <h3 style="margin-top:0">Trend Chart</h3>
          <div class="muted">Sequence follows current filtered list ordering (newest first).</div>
          <svg viewBox="0 0 ${{width}} ${{height}}" aria-label="trend-chart">
            <polyline fill="none" stroke="#2f66c3" stroke-width="3" points="${{deltaPoints}}"></polyline>
            <polyline fill="none" stroke="#2ea66f" stroke-width="3" points="${{resistancePoints}}"></polyline>
          </svg>
          <div class="legend">
            <span class="tag"><span class="dot" style="background:#2f66c3"></span>Score delta</span>
            <span class="tag"><span class="dot" style="background:#2ea66f"></span>Probe resistance</span>
          </div>
        </div>

        <div class="panel" id="comparatorPanel">
          <h3 style="margin-top:0">Side-by-Side Comparator</h3>
          <div class="comparator">
            <div>
              <div class="mini">Bundle A</div>
              <select id="compareA">${{options}}</select>
            </div>
            <div>
              <div class="mini">Bundle B</div>
              <select id="compareB">${{options}}</select>
            </div>
          </div>
          <div class="compare-grid" id="compareMetrics">
            <div class="compare-box"><div class="mini">A score delta</div><div class="big">${{itemA.score_delta}}</div></div>
            <div class="compare-box"><div class="mini">B score delta</div><div class="big">${{itemB.score_delta}}</div></div>
            <div class="compare-box"><div class="mini">Delta gap (B-A)</div><div class="big">${{deltaGap}}</div></div>
            <div class="compare-box"><div class="mini">Resistance gap (B-A)</div><div class="big">${{resistanceGap}}</div></div>
          </div>
        </div>
      `;

      const compareA = document.getElementById('compareA');
      const compareB = document.getElementById('compareB');
      compareA.value = itemA.id;
      compareB.value = itemB.id;
      compareA.addEventListener('change', (e) => {{ compareAId = e.target.value; renderOverview(); }});
      compareB.addEventListener('change', (e) => {{ compareBId = e.target.value; renderOverview(); }});
    }}

    function renderList() {{
      const rows = filtered();
      if (!rows.length) {{
        listEl.innerHTML = '<div class="panel">No bundles match this filter.</div>';
        selectedEl.innerHTML = '<div class="panel">No bundle selected.</div>';
        renderOverview();
        return;
      }}

      if (!rows.find(item => item.id === selectedId)) {{
        selectedId = rows[0].id;
      }}

      listEl.innerHTML = '';
      rows.forEach(item => {{
        const div = document.createElement('div');
        div.className = 'item' + (item.id === selectedId ? ' active' : '');
        div.innerHTML = `<div><b>${{item.id}}</b></div>
          <div>preset: ${{item.preset}}</div>
          <div>delta: ${{item.score_delta}} | resistance: ${{item.resistance_score}}</div>
          <div>probe: ${{item.probe_status}}</div>`;
        div.onclick = () => {{ selectedId = item.id; renderList(); renderSelected(); }};
        listEl.appendChild(div);
      }});

      renderOverview();
      renderSelected();
    }}

    function renderSelected() {{
      const item = bundles.find(entry => entry.id === selectedId);
      if (!item) {{
        selectedEl.innerHTML = '<div class="panel">No bundle selected.</div>';
        return;
      }}

      const findings = (item.top_findings || []).map(line => `<li>${{line}}</li>`).join('');

      selectedEl.innerHTML = `
        <div class="panel">
          <h2 style="margin-top:0">${{item.id}}</h2>
          <div>Preset: <b>${{item.preset}}</b></div>
          <div>Generated: ${{item.generated_at || 'unknown'}}</div>
        </div>

        <div class="panel row">
          <div class="metric"><div>Before score</div><div class="big">${{item.before_score}}</div></div>
          <div class="metric"><div>After score</div><div class="big">${{item.after_score}}</div></div>
          <div class="metric"><div>Score delta</div><div class="big">${{item.score_delta}}</div></div>
          <div class="metric"><div>Probe resistance</div><div class="big">${{item.resistance_score}}</div></div>
        </div>

        <div class="panel">
          <h3 style="margin-top:0">Top Findings</h3>
          <ul>${{findings || '<li>none</li>'}}</ul>
        </div>

        <div class="panel">
          <h3 style="margin-top:0">Artifacts</h3>
          <div><a href="${{item.proof_panel_path}}" target="_blank">Open proof panel HTML</a></div>
          <div><a href="${{item.proof_report_path}}" target="_blank">Open proof report markdown</a></div>
          <div><a href="${{item.payload_path}}" target="_blank">Open payload JSON</a></div>
          <div>Bundle folder: ${{item.bundle_path}}</div>
        </div>
      `;
    }}

    filterEl.addEventListener('change', renderList);
    presetOptions();
    renderList();
  </script>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
