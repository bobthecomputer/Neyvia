"""Run the requested release integration checks and retain bounded receipts on D:."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(r"D:\NeyviaRuns\INTN")


def frontend_sources():
    paths = [p for p in (ROOT / 'web/src').rglob('*') if p.is_file()]
    paths += [ROOT / name for name in ('web/index.html', 'vite.config.mjs', 'package.json',
              'package-lock.json', 'config/neyvia_apps.json', 'scripts/release-contracts.mjs') if (ROOT / name).is_file()]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument('--fast', action='store_true', help='P22 merge checks: only Vite build and CL artifact check; affected contracts run separately')
    args = parser.parse_args()
    if not args.label.replace("-", "").isalnum():
        parser.error("label must contain letters, numbers and hyphens")
    logs = OUT / "merges"
    logs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(OUT / "temp"), "TMP": str(OUT / "temp"),
           "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0",
           "TIKTOKEN_CACHE_DIR": str(OUT / 'python/tokenizer-rerun/tokenizer-cache')}
    Path(env["TEMP"]).mkdir(parents=True, exist_ok=True)
    commands = [
        ("compile", [sys.executable, str(ROOT / "scripts/cl_compile_manuals.py"), "--receipt", str(logs / (args.label + "-compile.json"))]),
        ("measured-context", [sys.executable, str(ROOT / "scripts/build_cl_context.py")]),
        ("measured-context-check", [sys.executable, str(ROOT / "scripts/build_cl_context.py"), "--check"]),
        ("manual-cache", [sys.executable, str(ROOT / "scripts/build_fixcl_manual_cache.py")]),
        ("manual-cache-check", [sys.executable, str(ROOT / "scripts/build_fixcl_manual_cache.py"), "--check"]),
        ("render", [sys.executable, str(ROOT / "scripts/render_manuals.py")]),
        ("plugin-skills", [sys.executable, str(ROOT / "scripts/build_claude_plugin_skills.py")]),
        ("plugin-skills-check", [sys.executable, str(ROOT / "scripts/build_claude_plugin_skills.py"), "--check"]),
        *([("module-map", [sys.executable, str(ROOT / "scripts/generate_module_map.py")])]
          if (ROOT / "scripts/generate_module_map.py").is_file() else []),
        ("cl-check", [sys.executable, str(ROOT / "scripts/cl_compile_manuals.py"), "--check", "--receipt", str(logs / (args.label + "-cl-check.json"))]),
        ("node", [shutil.which("node"), "--test", *map(str, sorted((ROOT / "web/src/neyvia/next").glob("*.test.js")))]),
        ("vite", [shutil.which("node"), str(ROOT / "node_modules/vite/bin/vite.js"), "build", "--configLoader", "runner", "--outDir", str(OUT / ("build-" + args.label))]),
    ]
    if args.fast:
        commands = [item for item in commands if item[0] in {'cl-check', 'vite'}]
    def run_check(item):
        name, command = item
        build_sources = frontend_sources() if name == 'vite' else None
        log = logs / f"{args.label}-{name}.log"
        start = time.monotonic()
        with log.open("wb") as stream:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        row = {"check": name, "exitCode": result.returncode, "seconds": round(time.monotonic() - start, 2), "receipt": str(log)}
        if name == 'vite' and not result.returncode:
            build = OUT / ('build-' + args.label)
            changed = build_sources != frontend_sources()
            proof = {'schema':'neyvia.intn.frontend-build.v1', 'ok':not changed,
                     'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                     'sourceHashes':build_sources, 'sourceChangedDuringBuild':changed,
                     'artifactHashes':{p.relative_to(build).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(build.rglob('*')) if p.is_file() and p.name != '.neyvia-build-receipt.json'}}
            (build / '.neyvia-build-receipt.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
            if changed:
                row['exitCode'] = 1
                row['failure'] = 'Frontend sources changed during build'
        print(json.dumps(row), flush=True)
        return row

    # These checks read the already merged frontend. The ordered generation
    # below touches manual/cache/documentation owners, never frontend sources.
    # The build receipt independently refuses frontend changes during its run.
    rows = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        frontends = {name: pool.submit(run_check, (name, command))
                     for name, command in commands if name in {'node', 'vite'}}
        for item in commands:
            if item[0] in frontends:
                continue
            row = run_check(item)
            rows.append(row)
            if row['exitCode']:
                break
        # Always collect both owned processes, including on generation failure;
        # no detached check or receipt is left running when the command returns.
        rows.extend(future.result() for future in frontends.values())
    receipt = {"schema": "neyvia.intn.merge-checks.v1", "label": args.label, 'mode': 'P22-fast' if args.fast else 'historical-full-merge-checks', "ok": len(rows) == len(commands) and all(row["exitCode"] == 0 for row in rows), "checks": rows}
    (logs / (args.label + "-checks.json")).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
