"""Find frontend files exclusively reachable from retired shell entry points."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1] / "web/src"
IMPORT = re.compile(r'''(?:from\s*|import\s*\(?\s*|url\(\s*)["'](\.[^"']+)["']''')
def resolve(parent, value):
    path = parent / value
    for candidate in [path, *(Path(str(path) + ext) for ext in (".js", ".jsx", ".ts", ".tsx", ".css")), path / "index.js", path / "index.ts"]:
        if candidate.is_file():
            return candidate.resolve()

def reachable(entries):
    seen, queue = set(), list(entries)
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for value in IMPORT.findall(path.read_text(encoding="utf-8-sig")):
            dep = resolve(path.parent, value)
            if dep and dep not in seen and dep.is_relative_to(ROOT.resolve()):
                queue.append(dep)
    return seen

if __name__ == "__main__":
    old = reachable([(ROOT / "neyvia/NeyviaShell.jsx").resolve(), (ROOT / "neyvia/NeyviaReferenceShell.jsx").resolve()])
    new = reachable([(ROOT / "main.tsx").resolve()])
    result = {"retiredOnly": sorted(str(path.relative_to(ROOT)) for path in old - new), "retained": len(new), "oldReachable": len(old)}
    print(json.dumps(result, indent=2))
