"""Normalize conflicted text and reconcile manual data for the release integrator."""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(r"D:\NeyviaRuns\INTN\merges")
MISSING = object()


def merge(base, ours, theirs, path=""):
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    if isinstance(ours, dict) and isinstance(theirs, dict):
        result = {}
        old = base if isinstance(base, dict) else {}
        for key in dict.fromkeys([*ours, *theirs]):
            value = merge(old.get(key, MISSING), ours.get(key, MISSING), theirs.get(key, MISSING), path + "/" + key)
            if value is not MISSING:
                result[key] = value
        return result
    if isinstance(ours, list) and isinstance(theirs, list):
        old = base if isinstance(base, list) else []
        identity = next((key for key in ("id", "name") if all(isinstance(row, dict) and key in row for row in [*ours, *theirs, *old])), None)
        if identity:
            maps = [{row[identity]: row for row in rows} for rows in (old, ours, theirs)]
            return list(merge(*maps, path).values())
        # Preserve independent additions and one-sided removals in unkeyed sets.
        return [row for row in ours if row not in old or row in theirs] + [row for row in theirs if row not in ours and row not in old]
    raise ValueError(f"Manual conflict needs review: {path}: {base!r} -> {ours!r} / {theirs!r}")


def stage(name, number):
    result = subprocess.run(["git", "show", f":{number}:{name}"], cwd=ROOT, capture_output=True)
    if result.returncode and number == 1:
        # Independently added files have no common ancestor in the index.
        return b""
    result.check_returncode()
    return result.stdout.replace(b"\r\n", b"\n")


def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "src"))
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    names = sys.argv[1:] or subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=U"], cwd=ROOT, text=True).splitlines()
    for name in names:
        target = (ROOT / name).resolve()
        target.relative_to(ROOT)
        values = [stage(name, n) for n in (1, 2, 3)]
        if name.endswith(".json") or name.endswith(".cl"):
            decode = cl_to_manual if name.endswith(".cl") else json.loads
            value = merge(*(decode(data.decode("utf-8-sig")) for data in values))
            if name.endswith(".cl"):
                metadata = []
                for data in values:
                    header = next(line for line in data.decode("utf-8-sig").splitlines() if line.startswith("-- @manual "))
                    metadata.append(json.loads(header[len("-- @manual "):]).get("tool_metadata", {}))
                output = manual_to_cl(value, tool_metadata=merge(*metadata))
            else:
                output = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            target.write_text(output, encoding="utf-8", newline="\n")
            code = 0
        else:
            inputs = []
            for n in (2, 1, 3):
                temp = SCRATCH / (name.replace("/", "_") + f".{n}")
                temp.write_bytes(values[n - 1])
                inputs.append(str(temp))
            result = subprocess.run(["git", "merge-file", "-p", "-L", "ours", "-L", "base", "-L", "theirs", *inputs], cwd=ROOT, capture_output=True)
            code = result.returncode
            if not 0 <= code < 128:
                raise RuntimeError(result.stderr.decode(errors="replace"))
            target.write_bytes(result.stdout)
        print(name, "resolved" if code == 0 else f"{code} conflict blocks", flush=True)
        if code == 0:
            subprocess.run(["git", "add", "--", name], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
