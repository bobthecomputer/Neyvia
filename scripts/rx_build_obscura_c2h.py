"""Rebuild the source-admitted C2h Obscura engine on D and stage it durably.

The C2h admission (scripts/evidence/C2h-engine-admission.json) named binaries inside a
deleted worktree. This rebuilds the same recorded inputs: tag v0.2.4 source archive
(sha256 from C2f-engine-source-audit.json), the fetch-retention, C2g and C2h patches
(admission hashes, LF-normalized), the admitted rusty_v8 simdutf archive and libclang
wheel. Cargo runs --offline --locked against the locked vendor directory, with a dead
loopback proxy so nothing can leave the machine. No stealth feature, no system install,
no download over 200 MB.

Usage: python scripts/rx_build_obscura_c2h.py [--jobs 2]

Work tree:  D:/NeyviaRuns/rx-browser/build      (source, inputs, cargo home, log)
Scratch:    ~/.rx-browser-vendor, ~/.rx-browser-target on the local NVMe, removed after a build
Engine:     D:/NeyviaRuns/engines/obscura-c2h/<engine12>-<worker12>/obscura(.exe|-worker.exe)
Receipt:    scripts/evidence/RX-browser-engine-build.json
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "scripts/evidence"
WORK = Path(r"D:\NeyviaRuns\rx-browser\build")
ENGINES = Path(r"D:\NeyviaRuns\engines\obscura-c2h")
INTN = Path(r"D:\NeyviaRuns\INTN\obscura-recovery")
LIMIT = 200_000_000
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TOOLCHAIN = Path(r"C:\Users\user\.rustup\toolchains\1.91.0-x86_64-pc-windows-msvc\bin")
VC = "C:/Program Files/Microsoft Visual Studio/18/Insiders/VC/Tools/MSVC/14.50.35503"
CMAKE = "C:/Program Files/Microsoft Visual Studio/18/Insiders/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin"
SDK, SDK_VERSION = "C:/Program Files (x86)/Windows Kits/10", "10.0.26100.0"
PATCHES = ["obscura-v024-fetch-retention.patch", "obscura-v024-C2g-capabilities.patch",
           "obscura-v024-C2g-fragment-render-key.patch", "obscura-v024-C2h-opacity-cull.patch",
           "obscura-v024-C2h-websocket.patch"]
DEAD_PROXY = "http://127.0.0.1:49029"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def download(url, target, expected):
    if not target.exists():
        part = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=90) as response, part.open("wb") as stream:
            size = 0
            while chunk := response.read(1 << 20):
                size += len(chunk)
                if size > LIMIT:
                    raise SystemExit("Download exceeds the 200 MB limit: " + url)
                stream.write(chunk)
        part.replace(target)
    actual = sha256(target)
    if actual != expected:
        raise SystemExit(f"{target.name} differs from the admitted sha256 ({actual})")
    return {"url": url, "path": str(target), "bytes": target.stat().st_size, "sha256": actual}


def local_or_download(name, local_dir, url, expected, target_dir):
    target = target_dir / name
    if not target.exists() and (local_dir / name).is_file() and sha256(local_dir / name) == expected:
        shutil.copy2(local_dir / name, target)
        return {"source": str(local_dir / name), "path": str(target), "bytes": target.stat().st_size, "sha256": expected}
    return download(url, target, expected)


def stage_vendor(lock_path, vendor):
    """Unpack every locked registry crate whose archive matches its Cargo.lock checksum."""
    import tomllib
    from concurrent.futures import ThreadPoolExecutor
    cache = Path.home() / ".cargo/registry/cache/index.crates.io-1949cf8c6b5b557f"
    vendor.mkdir(parents=True, exist_ok=True)

    def one(package):
        if not package.get("source", "").startswith("registry+"):
            return
        identity = package["name"] + "-" + package["version"]
        if (vendor / identity / ".cargo-checksum.json").is_file():
            return
        archive = next((p for p in (cache / (identity + ".crate"), INTN / (identity + ".crate")) if p.is_file()), None)
        if archive is None or sha256(archive) != package["checksum"]:
            raise SystemExit("No locked archive with the recorded checksum for " + identity)
        with tarfile.open(archive) as packed:
            packed.extractall(vendor, filter="data")
        files = {p.relative_to(vendor / identity).as_posix(): sha256(p) for p in (vendor / identity).rglob("*") if p.is_file()}
        (vendor / identity / ".cargo-checksum.json").write_text(json.dumps({"package": package["checksum"], "files": files}))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, tomllib.loads(Path(lock_path).read_text(encoding="utf-8"))["package"]))


def main():
    jobs = sys.argv[sys.argv.index("--jobs") + 1] if "--jobs" in sys.argv else "2"
    # rustc on the D: USB disk sat I/O bound (51 crates in 15 min), so the intermediate target
    # and temp live on the local NVMe (RX_TARGET) and are removed once the engine is staged on D:.
    target = Path(os.environ.get("RX_TARGET", str(Path.home() / ".rx-browser-target")))
    (target / "tmp").mkdir(parents=True, exist_ok=True)
    for sub in ("inputs", "src", "cargo-home"):
        (WORK / sub).mkdir(parents=True, exist_ok=True)
    inputs = WORK / "inputs"
    receipt_path = EVIDENCE / "RX-browser-engine-build.json"
    admission = json.loads((EVIDENCE / "C2h-engine-admission.json").read_text(encoding="utf-8"))
    audit = json.loads((EVIDENCE / "C2f-engine-source-audit.json").read_text(encoding="utf-8"))
    v8 = json.loads((EVIDENCE / "C2f-v8-simdutf-admission.json").read_text(encoding="utf-8"))
    clang = json.loads((EVIDENCE / "C2f-libclang-admission.json").read_text(encoding="utf-8"))
    report = {"schema": "neyvia.rx-browser.engine-rebuild@1", "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "reason": "C2h admission binaries lived in a deleted worktree; rebuild from the recorded inputs",
              "admission": "scripts/evidence/C2h-engine-admission.json", "stealth": False, "cargoNetwork": False,
              "systemInstall": False, "inputs": []}

    # 1. Tag source archive, exactly the audited bytes.
    archive = audit["archive"]
    report["inputs"].append(download("https://codeload.github.com/h4ckf0r0day/obscura/tar.gz/refs/tags/v0.2.4",
                                     inputs / "obscura-v0.2.4.tar.gz", archive["sha256"]))
    source = WORK / "src/obscura-0.2.4"
    marker = WORK / "src/patches-applied.json"
    if not marker.exists():
        if source.exists():
            shutil.rmtree(source)
        with tarfile.open(inputs / "obscura-v0.2.4.tar.gz") as packed:
            packed.extractall(WORK / "src", filter="data")
        if not source.is_dir():
            raise SystemExit("Archive did not unpack to obscura-0.2.4")
        applied = []
        for name in PATCHES:
            owned = inputs / name
            owned.write_bytes((REPO / "scripts" / name).read_bytes().replace(b"\r\n", b"\n"))
            subprocess.run(["git", "apply", "--check", str(owned)], cwd=source, check=True, creationflags=HIDDEN)
            subprocess.run(["git", "apply", str(owned)], cwd=source, check=True, creationflags=HIDDEN)
            applied.append({"path": "scripts/" + name, "lfSha256": sha256(owned)})
        marker.write_text(json.dumps(applied, indent=2), encoding="utf-8")
    report["patches"] = json.loads(marker.read_text(encoding="utf-8"))
    admitted = {Path(p["path"]).name: p["sha256"] for p in admission["patches"]}
    for row in report["patches"]:
        expected = admitted.get(Path(row["path"]).name)
        row["matchesAdmission"] = None if expected is None else expected == row["lfSha256"]
    if any(row["matchesAdmission"] is False for row in report["patches"]):
        raise SystemExit("A patch differs from the C2h admission")
    receipt = json.loads((EVIDENCE / admission["buildReceipt"].split("/")[-1]).read_text(encoding="utf-8"))
    report["sourceHashes"] = {name: {"sha256": sha256(source / name), "receipt": value, "match": sha256(source / name) == value}
                              for name, value in receipt["sourceHashes"].items()}

    # 2. Admitted V8 archive/binding and libclang DLL.
    for asset in v8["assets"]:
        report["inputs"].append(local_or_download(Path(asset["path"]).name, INTN, asset["source"], asset["sha256"], inputs))
    report["inputs"].append(download(clang["asset"], inputs / Path(clang["path"]).name, clang["sha256"]))
    clang_dir = inputs / "libclang18"
    if not (clang_dir / "clang/native/libclang.dll").is_file():
        with zipfile.ZipFile(inputs / Path(clang["path"]).name) as wheel:
            for member in wheel.namelist():
                if member.startswith("clang/native/"):
                    wheel.extract(member, clang_dir)

    # 3. Locked vendor directory, staged from checksum-verified .crate archives. D: is a
    # USB disk where cargo's per-file checksum walk of ~38k vendored files stalls for
    # over an hour, so the vendor tree goes on the local NVMe (RX_VENDOR) and is
    # deleted after the build.
    vendor = Path(os.environ.get("RX_VENDOR", str(Path.home() / ".rx-browser-vendor")))
    stage_vendor(source / "Cargo.lock", vendor)
    (WORK / "cargo-home/config.toml").write_text(
        '[source.crates-io]\nreplace-with = "rx-vendor"\n[source.rx-vendor]\ndirectory = ' + json.dumps(str(vendor)) + "\n"
        '[net]\noffline = true\n', encoding="utf-8")
    report["vendor"] = str(vendor)

    env = {**os.environ,
           "CARGO_HOME": str(WORK / "cargo-home"), "CARGO_TARGET_DIR": str(target), "CARGO_NET_OFFLINE": "true",
           "RUSTY_V8_ARCHIVE": str(inputs / "rusty_v8_simdutf_release_x86_64-pc-windows-msvc.lib.gz"),
           "RUSTY_V8_SRC_BINDING_PATH": str(inputs / "src_binding_simdutf_release_x86_64-pc-windows-msvc.rs"),
           "LIBCLANG_PATH": str(clang_dir / "clang/native"),
           "HTTP_PROXY": DEAD_PROXY, "HTTPS_PROXY": DEAD_PROXY, "ALL_PROXY": DEAD_PROXY,
           "TEMP": str(target / "tmp"), "TMP": str(target / "tmp"),
           "PATH": ";".join([str(TOOLCHAIN), VC + "/bin/Hostx64/x64", SDK + "/bin/" + SDK_VERSION + "/x64", CMAKE, os.environ["PATH"]]),
           "INCLUDE": ";".join([VC + "/include"] + [f"{SDK}/Include/{SDK_VERSION}/{p}" for p in ("ucrt", "shared", "um", "winrt")]),
           "LIB": ";".join([VC + "/lib/x64", f"{SDK}/Lib/{SDK_VERSION}/ucrt/x64", f"{SDK}/Lib/{SDK_VERSION}/um/x64"]),
           "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER": VC + "/bin/Hostx64/x64/link.exe",
           "RUSTC": str(TOOLCHAIN / "rustc.exe"), "VCToolsInstallDir": VC + "/", "WindowsSdkDir": SDK + "/",
           "WindowsSDKVersion": SDK_VERSION + "/"}
    args = ["build", "--offline", "--locked", "--release", "-p", "obscura-cli", "--features", "render", "-j", jobs]
    report["command"] = "cargo " + " ".join(args)
    report["toolchain"] = {tool: subprocess.run([str(TOOLCHAIN / (tool + ".exe")), "--version"], capture_output=True, text=True,
                                                creationflags=HIDDEN).stdout.strip() for tool in ("cargo", "rustc")}
    log = WORK / "cargo-build.log"
    report["log"] = str(log)
    receipt_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    started = time.time()
    with log.open("ab") as stream:
        code = subprocess.run([str(TOOLCHAIN / "cargo.exe"), *args], cwd=source, env=env, stdout=stream, stderr=stream,
                              stdin=subprocess.DEVNULL, creationflags=HIDDEN).returncode
    report.update(exitCode=code, seconds=round(time.time() - started), finishedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if code == 0:
        built = [target / "release" / name for name in ("obscura.exe", "obscura-worker.exe")]
        hashes = [sha256(path) for path in built]
        home = ENGINES / f"{hashes[0][:12]}-{hashes[1][:12]}"
        home.mkdir(parents=True, exist_ok=True)
        report["artifacts"] = []
        for path, digest in zip(built, hashes):
            shutil.copy2(path, home / path.name)
            if sha256(home / path.name) != digest:
                raise SystemExit("Staged engine changed during copy")
            report["artifacts"].append({"path": str(home / path.name), "bytes": path.stat().st_size, "sha256": digest})
        report["engineVersion"] = subprocess.run([str(home / "obscura.exe"), "--version"], capture_output=True, text=True,
                                                 creationflags=HIDDEN).stdout.strip()
        report["matchesAdmittedHashes"] = hashes == [admission["engineBinary"]["sha256"], admission["workerBinary"]["sha256"]]
        shutil.rmtree(vendor, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)
        report["intermediatesRemovedAfterBuild"] = not vendor.exists() and not target.exists()
    receipt_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"exitCode": code, "artifacts": report.get("artifacts"), "receipt": str(receipt_path)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
