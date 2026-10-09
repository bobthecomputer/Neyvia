"""Generate Markdown views from authored CL manuals and their JSON contracts."""
from __future__ import annotations
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.neyvia_manuals import document, records, render

def main():
    check = "--check" in sys.argv
    stale = []
    for row in records():
        data = document(row)[1]
        source = row.get("clSource", row["path"])
        text = "<!-- Generated from " + source + "; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->\n# " + row["id"] + "\n\n"
        for name, chapter in data["chapters"].items():
            view = render(chapter, data["schemas"], data.get("proofs"), layer=row["id"],
                          source_version="1.1" if row.get("clSource") else "1.0")
            text += "## " + name + "\n" + view + "\n"
        path = REPO / "docs/manuals" / (row["id"] + ".md")
        text = text.rstrip() + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(row["id"])
            if not check:
                path.write_text(text, encoding="utf-8")
    print("Stale: " + ", ".join(stale) if check and stale else "Manual views current")
    return int(check and bool(stale))

if __name__ == "__main__":
    raise SystemExit(main())
