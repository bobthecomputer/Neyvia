from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import tarfile
import time
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs


WINDOWS_IOS_SCHEMA = "neyvia.windows_ios.v1"
WINDOWS_IOS_CONFIG = Path(".agent_control") / "windows_ios.json"
WINDOWS_IOS_BUILDS = Path(".agent_control") / "windows_ios_builds"
DEFAULT_WSL_DISTRO = "default"
DEFAULT_MINIMUM_IOS = "16.0"
DEFAULT_LINK_SDK_VERSION = "18.0"
DEFAULT_ENGINE = "auto"
DIRECT_ENGINE = "win32"
WSL_ENGINE = "wsl2"
SUPPORTED_ENGINES = {DEFAULT_ENGINE, DIRECT_ENGINE, WSL_ENGINE}
LLVM_VERSION = "22.1.6"
LLVM_ARCHIVE_NAME = f"clang+llvm-{LLVM_VERSION}-x86_64-pc-windows-msvc.tar.xz"
LLVM_ARCHIVE_URL = (
    f"https://github.com/llvm/llvm-project/releases/download/llvmorg-{LLVM_VERSION}/{LLVM_ARCHIVE_NAME}"
)
LLVM_ARCHIVE_SHA256 = "657343edf361ca463bd642e39c74b251c6338b96cdbd55ff277555298b027696"
ZSIGN_TAG = "v1.0.8"
ZSIGN_COMMIT = "09486af36b0bdfda8f8ffc24c45c1e255530c2f8"
ZSIGN_VERSION = ZSIGN_TAG.removeprefix("v")
ZSIGN_ARCHIVE_NAME = "zsign-windows-x64.zip"
ZSIGN_ARCHIVE_URL = f"https://github.com/zhlynn/zsign/releases/download/{ZSIGN_TAG}/{ZSIGN_ARCHIVE_NAME}"
ZSIGN_ARCHIVE_SHA256 = "e4bb82d87ad88ade4839ddf1ee6ef3cf5188704b3d5c3dac9283b9e45b8d30fb"
DIRECT_TOOLCHAIN_ENV = "NEYVIA_WINDOWS_IOS_TOOLCHAIN_ROOT"

_BUNDLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+){2,}$")
_VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){1,2}$")
_DISTRO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PROBE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_source() -> Path:
    path = _repo_root() / "native" / "ios" / "neyvia_runtime.c"
    if not path.exists():
        raise RuntimeError(f"Neyvia native iOS runtime is missing: {path}")
    return path


def _stub_root() -> Path:
    path = _repo_root() / "native" / "ios" / "stubs"
    if not path.exists():
        raise RuntimeError(f"Neyvia clean-room iOS stubs are missing: {path}")
    return path


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    from .durability import atomic_write_text
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _clean_error(value: str, fallback: str) -> str:
    normalized = _ANSI_PATTERN.sub("", str(value or fallback)).strip()
    return normalized[-2400:] or fallback


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    raw_completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        input=(input_text.replace("\r\n", "\n").encode("utf-8") if input_text is not None else None),
        text=False,
        timeout=timeout,
        **hidden_windows_subprocess_kwargs(),
    )
    completed = subprocess.CompletedProcess(
        raw_completed.args,
        raw_completed.returncode,
        (raw_completed.stdout or b"").decode("utf-8", errors="replace"),
        (raw_completed.stderr or b"").decode("utf-8", errors="replace"),
    )
    if check and completed.returncode != 0:
        detail = _clean_error(completed.stderr or completed.stdout, "Command failed without output.")
        raise RuntimeError(f"{Path(command[0]).name} failed: {detail}")
    return completed


def _wsl_executable() -> str:
    executable = shutil.which("wsl") or shutil.which("wsl.exe")
    if not executable:
        raise RuntimeError("WSL2 is not installed on this Windows machine.")
    return executable


def _validate_engine(engine: str) -> str:
    normalized = str(engine or DEFAULT_ENGINE).strip().lower()
    if normalized not in SUPPORTED_ENGINES:
        choices = ", ".join(sorted(SUPPORTED_ENGINES))
        raise RuntimeError(f"Windows iOS compiler engine must be one of: {choices}.")
    return normalized


def _direct_toolchain_root() -> Path:
    override = str(os.environ.get(DIRECT_TOOLCHAIN_ENV) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data).expanduser().resolve() / "Neyvia" / "toolchains" / "ios-win32"


def _direct_tool_paths() -> dict[str, Path]:
    root = _direct_toolchain_root()
    llvm = root / f"llvm-{LLVM_VERSION}"
    # Explicit portable tool paths, scoped to this process; never rewrite PATH.
    llvm_bin = Path(os.environ.get("NEYVIA_WINDOWS_IOS_LLVM_BIN") or llvm / "bin")
    signer = root / f"zsign-{ZSIGN_VERSION}"
    return {
        "root": root,
        "llvmRoot": llvm,
        "signerRoot": signer,
        "clang": llvm_bin / "clang.exe",
        "linker": llvm_bin / "ld64.lld.exe",
        "objdump": llvm_bin / "llvm-objdump.exe",
        "zsign": Path(os.environ.get("NEYVIA_WINDOWS_IOS_ZSIGN") or signer / "zsign.exe"),
        "manifest": root / "manifest.json",
    }


def _validate_distro(distro: str) -> str:
    normalized = str(distro or DEFAULT_WSL_DISTRO).strip()
    if not _DISTRO_PATTERN.fullmatch(normalized):
        raise RuntimeError("WSL distribution name contains unsupported characters.")
    return normalized


def _wsl(
    distro: str,
    script: str,
    *,
    timeout: int = 120,
    root: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    normalized_distro = _validate_distro(distro)
    command = [_wsl_executable()]
    if normalized_distro != "default":
        command.extend(["-d", normalized_distro])
    if root:
        command.extend(["-u", "root"])
    command.extend(["--", "bash", "-s"])
    return _run(command, input_text=f"{script}\n", timeout=timeout, check=check)


def _wsl_path(path: Path, distro: str) -> str:
    completed = _wsl(
        distro,
        f"wslpath -a -- {shlex.quote(str(path.resolve()))}",
        timeout=30,
    )
    value = completed.stdout.strip()
    if not value.startswith("/"):
        raise RuntimeError(f"WSL could not map Windows path: {path}")
    return value


def load_windows_ios_config(root: str | Path) -> dict[str, Any]:
    resolved = Path(root).expanduser().resolve()
    payload = _read_json(resolved / WINDOWS_IOS_CONFIG, {})
    return {
        "schema": WINDOWS_IOS_SCHEMA,
        "engine": _validate_engine(str(payload.get("engine") or DEFAULT_ENGINE)),
        "distro": str(payload.get("distro") or DEFAULT_WSL_DISTRO),
        "minimumIos": str(payload.get("minimumIos") or DEFAULT_MINIMUM_IOS),
        "identityFile": str(payload.get("identityFile") or ""),
        "certificateFile": str(payload.get("certificateFile") or ""),
        "provisioningProfile": str(payload.get("provisioningProfile") or ""),
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def _save_windows_ios_config_locked(
    root: str | Path,
    *,
    engine: str = DEFAULT_ENGINE,
    distro: str = DEFAULT_WSL_DISTRO,
    minimum_ios: str = DEFAULT_MINIMUM_IOS,
    identity_file: str = "",
    certificate_file: str = "",
    provisioning_profile: str = "",
) -> dict[str, Any]:
    resolved = Path(root).expanduser().resolve()
    normalized_engine = _validate_engine(engine)
    normalized_distro = _validate_distro(distro)
    normalized_version = str(minimum_ios or DEFAULT_MINIMUM_IOS).strip()
    if not _VERSION_PATTERN.fullmatch(normalized_version):
        raise RuntimeError("Minimum iOS version must look like 16.0 or 17.2.")
    payload = {
        "schema": WINDOWS_IOS_SCHEMA,
        "engine": normalized_engine,
        "distro": normalized_distro,
        "minimumIos": normalized_version,
        "identityFile": str(identity_file or "").strip(),
        "certificateFile": str(certificate_file or "").strip(),
        "provisioningProfile": str(provisioning_profile or "").strip(),
        "updatedAt": _utc_now(),
    }
    _write_json(resolved / WINDOWS_IOS_CONFIG, payload)
    from .proofs_c_mobile import check_config
    check_config(resolved / WINDOWS_IOS_CONFIG, payload, "proofs-c.mobile.compiler-config")
    _PROBE_CACHE.clear()
    return payload


def save_windows_ios_config(
    root: str | Path,
    *,
    engine: str = DEFAULT_ENGINE,
    distro: str = DEFAULT_WSL_DISTRO,
    minimum_ios: str = DEFAULT_MINIMUM_IOS,
    identity_file: str = "",
    certificate_file: str = "",
    provisioning_profile: str = "",
) -> dict[str, Any]:
    """Hold the existing process lease through publication and durable check."""
    from .harness_jobs import _exclusive_job_lock
    resolved = Path(root).expanduser().resolve()
    target = resolved / WINDOWS_IOS_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_job_lock(target, timeout_seconds=120):
        return _save_windows_ios_config_locked(
            resolved, engine=engine, distro=distro, minimum_ios=minimum_ios,
            identity_file=identity_file, certificate_file=certificate_file,
            provisioning_profile=provisioning_profile,
        )


def _probe_script() -> str:
    return r'''
set +e
resolve_tool() {
  name="$1"
  shift
  for candidate in "$name" "$@"; do
    path="$(command -v "$candidate" 2>/dev/null)"
    if [ -n "$path" ]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}
printf 'clang=%s\n' "$(resolve_tool clang clang-22 clang-21 clang-20 clang-19)"
printf 'linker=%s\n' "$(resolve_tool ld64.lld ld64.lld-22 ld64.lld-21 ld64.lld-20 ld64.lld-19)"
printf 'objdump=%s\n' "$(resolve_tool llvm-objdump llvm-objdump-22 llvm-objdump-21 llvm-objdump-20 llvm-objdump-19)"
printf 'zsign=%s\n' "$(resolve_tool zsign)"
printf 'zip=%s\n' "$(resolve_tool zip)"
printf 'clangVersion=%s\n' "$(clang --version 2>/dev/null | head -n 1)"
'''.strip()


def _inspect_direct_windows_toolchain() -> dict[str, Any]:
    paths = _direct_tool_paths()
    tools = {
        key: str(paths[key])
        for key in ("clang", "linker", "objdump", "zsign")
        if paths[key].is_file()
    }
    result: dict[str, Any] = {
        "engine": DIRECT_ENGINE,
        "host": "windows-native",
        "nativeProcess": True,
        "toolchainRoot": str(paths["root"]),
        "ready": bool(tools.get("clang") and tools.get("linker") and tools.get("objdump")),
        "signerReady": bool(tools.get("zsign")),
        "tools": tools,
        "summary": "Direct Windows iOS compiler is not installed yet.",
    }
    if not result["ready"]:
        return result
    try:
        version = _run([tools["clang"], "--version"], timeout=30).stdout.splitlines()[0].strip()
        tools["clangVersion"] = version
        if result["signerReady"]:
            signer_version = _run([tools["zsign"], "-v"], timeout=30).stdout.strip()
            tools["zsignVersion"] = signer_version
            result["summary"] = "Direct Win32 LLVM and signer are ready; WSL is not required."
        else:
            result["summary"] = "Direct Win32 LLVM is ready; install zsign for signed IPA output."
    except Exception as exc:
        result.update(
            {
                "ready": False,
                "error": str(exc),
                "summary": f"Direct Windows toolchain could not run: {exc}",
            }
        )
    return result


def _inspect_wsl_toolchain(distro: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "engine": WSL_ENGINE,
        "host": "windows-wsl2",
        "nativeProcess": False,
        "distro": distro,
        "ready": False,
        "signerReady": False,
        "tools": {},
        "summary": "WSL2 compatibility compiler is not installed yet.",
    }
    try:
        completed = _wsl(distro, _probe_script(), timeout=30)
        tools: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                tools[key.strip()] = value.strip()
        result["tools"] = tools
        result["ready"] = bool(tools.get("clang") and tools.get("linker") and tools.get("objdump"))
        result["signerReady"] = bool(tools.get("zsign"))
        if result["ready"] and result["signerReady"]:
            result["summary"] = "WSL2 LLVM Mach-O compiler and signer are ready as a compatibility path."
        elif result["ready"]:
            result["summary"] = "WSL2 LLVM can compile iOS Mach-O; install the signer for signed IPAs."
    except Exception as exc:
        result["error"] = str(exc)
        result["summary"] = str(exc)
    return result


def inspect_windows_ios_toolchain(
    root: str | Path,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    config = load_windows_ios_config(root)
    distro = _validate_distro(config["distro"])
    configured_engine = _validate_engine(config["engine"])
    cache_key = f"{configured_engine}:{distro}:{_direct_toolchain_root()}"
    cached = _PROBE_CACHE.get(cache_key)
    if not refresh and cached and time.monotonic() - cached[0] < 5:
        return dict(cached[1])
    direct = _inspect_direct_windows_toolchain()
    wsl = (
        _inspect_wsl_toolchain(distro)
        if configured_engine in {DEFAULT_ENGINE, WSL_ENGINE} and not (configured_engine == DEFAULT_ENGINE and direct["ready"])
        else {
            "engine": WSL_ENGINE,
            "host": "windows-wsl2",
            "nativeProcess": False,
            "distro": distro,
            "ready": False,
            "signerReady": False,
            "tools": {},
            "notProbed": True,
            "summary": "WSL2 fallback was not needed.",
        }
    )
    active = direct if configured_engine == DIRECT_ENGINE else wsl if configured_engine == WSL_ENGINE else direct if direct["ready"] else wsl
    result: dict[str, Any] = {
        "schema": WINDOWS_IOS_SCHEMA,
        "host": active["host"],
        "engine": configured_engine,
        "activeEngine": active["engine"],
        "nativeProcess": active["nativeProcess"],
        "distro": distro,
        "ready": bool(active["ready"]),
        "signerReady": bool(active["signerReady"]),
        "tools": active["tools"],
        "minimumIos": config["minimumIos"],
        "signingConfigured": bool(config["identityFile"] and config["provisioningProfile"]),
        "config": config,
        "directWindows": direct,
        "wsl2": wsl,
        "summary": active["summary"],
    }
    if active.get("error"):
        result["error"] = active["error"]
    _PROBE_CACHE[cache_key] = (time.monotonic(), dict(result))
    return result


def _download_verified(url: str, destination: Path, expected_sha256: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    from .harness_jobs import _exclusive_job_lock
    # A cooperating reader hashing the cached destination can hold an open
    # Windows handle while another writer promotes its replacement. Serialize
    # the cache check and promotion together with the existing crash-safe guard.
    with _exclusive_job_lock(destination, timeout_seconds=120):
        return _download_verified_locked(url, destination, expected_sha256)


def _download_verified_locked(url: str, destination: Path, expected_sha256: str) -> Path:
    if destination.is_file() and _file_sha256(destination) == expected_sha256:
        return destination
    partial = destination.with_name(f"{destination.name}.part-{uuid.uuid4().hex}")
    request = urllib.request.Request(url, headers={"User-Agent": "Neyvia-Windows-iOS-Toolchain/1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        actual_sha256 = _file_sha256(partial)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"Downloaded toolchain checksum mismatch for {destination.name}: {actual_sha256}."
            )
        partial.replace(destination)
    finally:
        if partial.exists():
            partial.unlink()
    return destination


def _safe_archive_destination(base: Path, member_name: str) -> Path:
    destination = (base / member_name).resolve()
    try:
        destination.relative_to(base.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Toolchain archive contains an unsafe path: {member_name}") from exc
    return destination


def _extract_llvm_archive(archive_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive_path, "r:xz") as archive:
        members = archive.getmembers()
        for member in members:
            _safe_archive_destination(destination, member.name)
        archive.extractall(destination, members=members, filter="data")
    matches = sorted(destination.rglob("bin/clang.exe"))
    roots = [match.parent.parent for match in matches if (match.parent / "ld64.lld.exe").is_file()]
    if not roots:
        raise RuntimeError("The verified LLVM archive did not contain clang.exe and ld64.lld.exe.")
    return roots[0]


def _extract_zsign_archive(archive_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            _safe_archive_destination(destination, member.filename)
        archive.extractall(destination)
    matches = sorted(destination.rglob("zsign.exe"))
    if not matches:
        raise RuntimeError("The verified zsign archive did not contain zsign.exe.")
    return matches[0]


def _install_direct_windows_toolchain() -> None:
    if os.name != "nt":
        raise RuntimeError("The direct Win32 iOS compiler can only be installed on Windows.")
    paths = _direct_tool_paths()
    paths["root"].mkdir(parents=True, exist_ok=True)
    downloads = paths["root"] / "downloads"
    llvm_archive = _download_verified(
        LLVM_ARCHIVE_URL,
        downloads / LLVM_ARCHIVE_NAME,
        LLVM_ARCHIVE_SHA256,
    )
    zsign_archive = _download_verified(
        ZSIGN_ARCHIVE_URL,
        downloads / ZSIGN_ARCHIVE_NAME,
        ZSIGN_ARCHIVE_SHA256,
    )
    if not paths["clang"].is_file() or not paths["linker"].is_file() or not paths["objdump"].is_file():
        if paths["llvmRoot"].exists():
            raise RuntimeError(f"Refusing to replace an incomplete LLVM toolchain: {paths['llvmRoot']}")
        staging = paths["root"] / f".llvm-install-{uuid.uuid4().hex}"
        extracted_root = _extract_llvm_archive(llvm_archive, staging)
        shutil.move(str(extracted_root), str(paths["llvmRoot"]))
        shutil.rmtree(staging, ignore_errors=True)
    if not paths["zsign"].is_file():
        if paths["signerRoot"].exists():
            raise RuntimeError(f"Refusing to replace an incomplete zsign toolchain: {paths['signerRoot']}")
        staging = paths["root"] / f".zsign-install-{uuid.uuid4().hex}"
        extracted_zsign = _extract_zsign_archive(zsign_archive, staging)
        paths["signerRoot"].mkdir(parents=True, exist_ok=False)
        shutil.copy2(extracted_zsign, paths["zsign"])
        shutil.rmtree(staging, ignore_errors=True)
    manifest = {
        "schema": "neyvia.windows_ios_toolchain.v1",
        "installedAt": _utc_now(),
        "engine": DIRECT_ENGINE,
        "llvm": {
            "version": LLVM_VERSION,
            "url": LLVM_ARCHIVE_URL,
            "sha256": LLVM_ARCHIVE_SHA256,
        },
        "zsign": {
            "version": ZSIGN_VERSION,
            "url": ZSIGN_ARCHIVE_URL,
            "sha256": ZSIGN_ARCHIVE_SHA256,
        },
        "globalPathModified": False,
    }
    _write_json(paths["manifest"], manifest)


def _install_wsl_toolchain(distro: str) -> None:
    apt_script = "\n".join(
        [
            "set -eu",
            "export DEBIAN_FRONTEND=noninteractive",
            "if ! command -v clang >/dev/null || ! command -v ld64.lld >/dev/null || ! command -v llvm-objdump >/dev/null \\",
            "  || ! command -v g++ >/dev/null || ! command -v make >/dev/null || ! command -v git >/dev/null \\",
            "  || ! command -v pkg-config >/dev/null || ! command -v zip >/dev/null || ! command -v unzip >/dev/null \\",
            "  || ! pkg-config --exists openssl; then",
            "  apt-get update",
            "  apt-get install -y clang lld llvm build-essential git pkg-config libssl-dev zip unzip",
            "fi",
        ]
    )
    _wsl(distro, apt_script, root=True, timeout=1800)
    signer_script = f"""
set -eu
root=/opt/neyvia-ios-toolchain
src="$root/zsign-{ZSIGN_TAG}"
mkdir -p "$root"
if [ ! -d "$src/.git" ]; then
  test ! -e "$src" || {{ echo "Refusing to replace unexpected path: $src" >&2; exit 1; }}
  git clone --depth 1 --branch {shlex.quote(ZSIGN_TAG)} https://github.com/zhlynn/zsign.git "$src"
fi
test "$(git -C "$src" rev-parse HEAD)" = {shlex.quote(ZSIGN_COMMIT)}
make -C "$src/build/linux"
install -m 0755 "$src/bin/zsign" /usr/local/bin/zsign
""".strip()
    _wsl(distro, signer_script, root=True, timeout=1200)


def install_windows_ios_toolchain(
    root: str | Path,
    *,
    engine: str = DEFAULT_ENGINE,
    distro: str = DEFAULT_WSL_DISTRO,
) -> dict[str, Any]:
    resolved = Path(root).expanduser().resolve()
    config = load_windows_ios_config(resolved)
    normalized_engine = _validate_engine(engine or config["engine"])
    normalized_distro = _validate_distro(distro or config["distro"])
    save_windows_ios_config(
        resolved,
        engine=normalized_engine,
        distro=normalized_distro,
        minimum_ios=config["minimumIos"],
        identity_file=config["identityFile"],
        certificate_file=config["certificateFile"],
        provisioning_profile=config["provisioningProfile"],
    )
    installed_engine = WSL_ENGINE if normalized_engine == WSL_ENGINE else DIRECT_ENGINE
    if installed_engine == DIRECT_ENGINE:
        _install_direct_windows_toolchain()
    else:
        _install_wsl_toolchain(normalized_distro)
    _PROBE_CACHE.clear()
    probe = inspect_windows_ios_toolchain(resolved, refresh=True)
    if not probe["ready"] or not probe["signerReady"]:
        raise RuntimeError(probe["summary"])
    return {
        "schema": WINDOWS_IOS_SCHEMA,
        "installed": True,
        "installedAt": _utc_now(),
        "installedEngine": installed_engine,
        "toolchain": probe,
    }


def _safe_copy_web_assets(project_root: Path, build_dir: Path, app_dir: Path) -> Path:
    candidates = [
        project_root / "dist",
        project_root / "web-build",
        project_root / "build" / "web",
        project_root / "www",  # plain web apps and Capacitor projects (Mobile Studio starters)
    ]
    source = next((path for path in candidates if (path / "index.html").exists()), None)
    export_dir = build_dir / "web-export"
    if source is None:
        package = project_root / "package.json"
        if not package.exists():
            raise RuntimeError("Windows Native needs a web export or an Expo package.json project.")
        if not (project_root / "node_modules").exists():
            raise RuntimeError("Install project dependencies before creating the Windows-local iOS build.")
        completed = _run(
            [
                "npx",
                "expo",
                "export",
                "--platform",
                "web",
                "--output-dir",
                str(export_dir),
                "--clear",
            ],
            cwd=project_root,
            timeout=900,
            check=False,
        )
        if completed.returncode != 0 or not (export_dir / "index.html").exists():
            detail = (completed.stderr or completed.stdout or "Expo web export failed.").strip()
            raise RuntimeError(f"Could not export the app UI for the native container: {detail[-1600:]}")
        source = export_dir
    destination = app_dir / "www"
    if destination.exists():
        raise RuntimeError(f"Refusing to replace an existing build staging directory: {destination}")
    for directory, dirs, files in os.walk(source, followlinks=False):
        if any((Path(directory) / name).is_symlink() for name in [*dirs, *files]):
            raise RuntimeError("Web export contains a symlink; export real assets before bundling.")
    shutil.copytree(source, destination, symlinks=False)
    index_path = destination / "index.html"
    content = index_path.read_text(encoding="utf-8")
    original_content = content
    content = re.sub(r'''(?P<attr>\b(?:src|href)=['"])/(?!/)''', r"\g<attr>./", content)
    index_path.write_text(content, encoding="utf-8")
    from .proofs_c_mobile import check_web_assets
    check_web_assets(destination, original_content)
    return destination


def _write_info_plist(
    app_dir: Path,
    *,
    executable: str,
    app_name: str,
    bundle_identifier: str,
    minimum_ios: str,
    target: str = "ios",
) -> Path:
    payload = {
        "BuildMachineOSBuild": "Neyvia-Windows",
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": app_name,
        "CFBundleExecutable": executable,
        "CFBundleIdentifier": bundle_identifier,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": app_name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleSupportedPlatforms": ["iPhoneOS"],
        "CFBundleVersion": "1",
        "LSRequiresIPhoneOS": True,
        "MinimumOSVersion": minimum_ios,
        "UIDeviceFamily": [2] if target == "ipados" else [1, 2],
        "UIRequiresFullScreen": False,
        "UISupportedInterfaceOrientations~ipad": [
            "UIInterfaceOrientationPortrait", "UIInterfaceOrientationPortraitUpsideDown",
            "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight",
        ],
        "UILaunchScreen": {},
        "UIRequiredDeviceCapabilities": ["arm64"],
        "UISupportedInterfaceOrientations": [
            "UIInterfaceOrientationPortrait",
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight",
        ],
    }
    path = app_dir / "Info.plist"
    path.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_BINARY, sort_keys=True))
    from .proofs_c_mobile import check_plist
    check_plist(path, payload)
    return path


def _zip_payload(app_dir: Path, ipa_path: Path) -> None:
    with zipfile.ZipFile(ipa_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(app_dir.rglob("*")):
            if path.is_dir() or path.is_symlink():
                continue
            relative = Path("Payload") / app_dir.name / path.relative_to(app_dir)
            archive.write(path, relative.as_posix())
    from .proofs_c_mobile import check_package
    check_package(app_dir, ipa_path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_project_metadata(project_root: Path) -> tuple[str, str]:
    package = _read_json(project_root / "package.json", {})
    app_config = _read_json(project_root / "app.json", {})
    expo = app_config.get("expo") if isinstance(app_config.get("expo"), dict) else {}
    cap = _read_json(project_root / "capacitor.config.json", {})
    native = _read_json(project_root / "neyvia.app.json", {})
    app_name = str(expo.get("name") or cap.get("appName") or package.get("displayName") or native.get("name") or package.get("name") or project_root.name).strip()
    ios = expo.get("ios") if isinstance(expo.get("ios"), dict) else {}
    bundle_identifier = str(ios.get("bundleIdentifier") or cap.get("appId") or native.get("bundleIdentifier") or "").strip()
    if not bundle_identifier and native.get("instance"):
        bundle_identifier = "com.neyvia." + re.sub(r"[^A-Za-z0-9]", "", str(native["instance"]))
    if not _BUNDLE_PATTERN.fullmatch(bundle_identifier):
        raise RuntimeError("A valid reverse-domain iOS bundle identifier is required in app.json.")
    return app_name, bundle_identifier


def build_windows_ios_app(root: str | Path, *, timeout_seconds: int = 1800, target: str = "ios") -> dict[str, Any]:
    if target not in {"ios", "ipados"}:
        raise ValueError("This UIKit engine supports ios or ipados")
    project_root = Path(root).expanduser().resolve()
    config = load_windows_ios_config(project_root)
    toolchain = inspect_windows_ios_toolchain(project_root, refresh=True)
    if not toolchain["ready"]:
        raise RuntimeError("Install the Windows Native LLVM toolchain before compiling an iOS app locally.")
    app_name, bundle_identifier = _resolve_project_metadata(project_root)
    job_id = f"win_ios_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    build_dir = project_root / WINDOWS_IOS_BUILDS / job_id
    app_dir = build_dir / "app" / f"{re.sub(r'[^A-Za-z0-9]', '', app_name)[:32] or 'NeyviaApp'}.app"
    executable_name = "NeyviaApp"
    executable_path = app_dir / executable_name
    receipt_path = build_dir / "receipt.json"
    build_dir.mkdir(parents=True, exist_ok=False)
    app_dir.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema": "neyvia.windows_ios_build_receipt.v1",
        "jobId": job_id,
        "mode": "windows-native",
        "platform": target,
        "status": "running",
        "createdAt": _utc_now(),
        "updatedAt": _utc_now(),
        "projectRoot": str(project_root),
        "appName": app_name,
        "bundleIdentifier": bundle_identifier,
        "host": toolchain["host"],
        "engine": toolchain["activeEngine"],
        "nativeProcess": bool(toolchain["nativeProcess"]),
        "wslInvoked": toolchain["activeEngine"] == WSL_ENGINE,
        "receiptPath": str(receipt_path),
    }
    if toolchain["activeEngine"] == WSL_ENGINE:
        receipt["distro"] = config["distro"]
    _write_json(receipt_path, receipt)
    try:
        web_assets = _safe_copy_web_assets(project_root, build_dir, app_dir)
        _write_info_plist(
            app_dir,
            executable=executable_name,
            app_name=app_name,
            bundle_identifier=bundle_identifier,
            minimum_ios=config["minimumIos"],
            target=target,
        )
        tools = toolchain["tools"]
        engine = toolchain["activeEngine"]
        object_path = build_dir / "neyvia_runtime.o"
        if engine == DIRECT_ENGINE:
            compile_parts = [
                tools["clang"],
                "-target",
                f"arm64-apple-ios{config['minimumIos']}",
                "-O2",
                "-fno-stack-protector",
                "-fno-builtin",
                "-fvisibility=hidden",
                "-ffreestanding",
                "-c",
                str(_runtime_source()),
                "-o",
                str(object_path),
            ]
            link_parts = [
                tools["linker"],
                "-arch",
                "arm64",
                "-platform_version",
                "ios",
                config["minimumIos"],
                DEFAULT_LINK_SDK_VERSION,
                "-o",
                str(executable_path),
                str(object_path),
                "-L",
                str(_stub_root()),
                "-lSystem",
                "-lobjc",
                "-F",
                str(_stub_root() / "Frameworks"),
                "-framework",
                "UIKit",
                "-e",
                "_main",
                "-dead_strip",
            ]
            compiled = _run(compile_parts, timeout=max(300, timeout_seconds), check=False)
            linked = (
                _run(link_parts, timeout=max(300, timeout_seconds), check=False)
                if compiled.returncode == 0
                else subprocess.CompletedProcess(link_parts, 1, "", "Link skipped because compilation failed.")
            )
            compile_command = subprocess.list2cmdline(compile_parts)
            link_command = subprocess.list2cmdline(link_parts)
            compile_output = f"{compiled.stdout}\n{compiled.stderr}\n{linked.stdout}\n{linked.stderr}"
            compile_returncode = compiled.returncode or linked.returncode
        else:
            source_wsl = _wsl_path(_runtime_source(), config["distro"])
            stubs_wsl = _wsl_path(_stub_root(), config["distro"])
            build_wsl = _wsl_path(build_dir, config["distro"])
            executable_wsl = _wsl_path(executable_path, config["distro"])
            object_wsl = f"{build_wsl}/neyvia_runtime.o"
            compile_parts = [
                tools["clang"],
                "-target",
                f"arm64-apple-ios{config['minimumIos']}",
                "-O2",
                "-fno-stack-protector",
                "-fno-builtin",
                "-fvisibility=hidden",
                "-ffreestanding",
                "-c",
                source_wsl,
                "-o",
                object_wsl,
            ]
            link_parts = [
                tools["linker"],
                "-arch",
                "arm64",
                "-platform_version",
                "ios",
                config["minimumIos"],
                DEFAULT_LINK_SDK_VERSION,
                "-o",
                executable_wsl,
                object_wsl,
                "-L",
                stubs_wsl,
                "-lSystem",
                "-lobjc",
                "-F",
                f"{stubs_wsl}/Frameworks",
                "-framework",
                "UIKit",
                "-e",
                "_main",
                "-dead_strip",
            ]
            compile_command = " ".join(shlex.quote(part) for part in compile_parts)
            link_command = " ".join(shlex.quote(part) for part in link_parts)
            build_script = f"set -eu\n{compile_command}\n{link_command}\nchmod 0755 {shlex.quote(executable_wsl)}"
            completed = _wsl(config["distro"], build_script, timeout=max(300, timeout_seconds), check=False)
            compile_output = f"{completed.stdout}\n{completed.stderr}"
            compile_returncode = completed.returncode
        (build_dir / "compile.log").write_text(
            f"$ {compile_command}\n$ {link_command}\n\n{compile_output}",
            encoding="utf-8",
        )
        if compile_returncode != 0 or not executable_path.exists():
            raise RuntimeError(_clean_error(compile_output, "LLVM iOS compilation failed."))
        magic = executable_path.read_bytes()[:4].hex()
        if magic != "cffaedfe":
            raise RuntimeError(f"Compiler output is not a 64-bit Mach-O executable (magic={magic}).")
        inspection_path = build_dir / "macho-inspection.txt"

        unsigned_ipa = build_dir / f"{app_dir.stem}-windows-native-unsigned.ipa"
        _zip_payload(app_dir, unsigned_ipa)
        artifact_path = unsigned_ipa
        signature_kind = "unsigned"
        signing_detail = "Native Mach-O compiled locally; no signing identity was configured."
        if toolchain["signerReady"]:
            signed_ipa = build_dir / f"{app_dir.stem}-windows-native.ipa"
            signer_parts = [tools["zsign"]]
            identity = str(config["identityFile"] or "").strip()
            provision = str(config["provisioningProfile"] or "").strip()
            certificate = str(config["certificateFile"] or "").strip()
            if identity and provision:
                identity_path = Path(identity).expanduser().resolve()
                provision_path = Path(provision).expanduser().resolve()
                if not identity_path.exists() or not provision_path.exists():
                    raise RuntimeError("Configured Windows iOS signing identity or provisioning profile does not exist.")
                signer_parts.extend(
                    ["-k", str(identity_path) if engine == DIRECT_ENGINE else _wsl_path(identity_path, config["distro"])]
                )
                if certificate:
                    certificate_path = Path(certificate).expanduser().resolve()
                    if not certificate_path.exists():
                        raise RuntimeError("Configured signing certificate does not exist.")
                    signer_parts.extend(
                        [
                            "-c",
                            str(certificate_path)
                            if engine == DIRECT_ENGINE
                            else _wsl_path(certificate_path, config["distro"]),
                        ]
                    )
                signer_parts.extend(
                    ["-m", str(provision_path) if engine == DIRECT_ENGINE else _wsl_path(provision_path, config["distro"])]
                )
                password = os.environ.get("NEYVIA_IOS_SIGNING_PASSWORD", "")
                if password:
                    signer_parts.extend(["-p", password])
                signature_kind = "development"
                signing_detail = "Signed locally with the configured identity and provisioning profile."
            else:
                signer_parts.append("-a")
                signature_kind = "adhoc"
                signing_detail = "Ad-hoc signed locally for Mach-O/IPA verification."
            signer_parts.append(str(app_dir) if engine == DIRECT_ENGINE else _wsl_path(app_dir, config["distro"]))
            if engine == DIRECT_ENGINE:
                signed = _run(signer_parts, cwd=build_dir, timeout=300, check=False)
            else:
                signer_command = " ".join(shlex.quote(part) for part in signer_parts)
                signed = _wsl(config["distro"], signer_command, timeout=300, check=False)
            (build_dir / "signing.log").write_text(
                f"{signed.stdout}\n{signed.stderr}",
                encoding="utf-8",
            )
            if signed.returncode != 0 or not (app_dir / "_CodeSignature" / "CodeResources").exists():
                raise RuntimeError(_clean_error(signed.stderr or signed.stdout, "Windows-local IPA signing failed."))
            _zip_payload(app_dir, signed_ipa)
            artifact_path = signed_ipa

        if engine == DIRECT_ENGINE:
            inspection = _run(
                [tools["objdump"], "--macho", "--private-headers", str(executable_path)],
                timeout=60,
            )
        else:
            inspect_script = " ".join(
                [
                    shlex.quote(tools["objdump"]),
                    "--macho",
                    "--private-headers",
                    shlex.quote(executable_wsl),
                ]
            )
            inspection = _wsl(config["distro"], inspect_script, timeout=60)
        inspection_path.write_text(inspection.stdout, encoding="utf-8")

        if signature_kind != "unsigned":
            from .apple_bundle import verify_bundle
            receipt["verification"] = verify_bundle(app_dir, target)
        receipt["nativeExecutionVerified"] = False
        receipt.update(
            {
                "status": "completed",
                "updatedAt": _utc_now(),
                "artifactPath": str(artifact_path),
                "artifactBytes": artifact_path.stat().st_size,
                "artifactSha256": _file_sha256(artifact_path),
                "executablePath": str(executable_path),
                "executableBytes": executable_path.stat().st_size,
                "executableSha256": _file_sha256(executable_path),
                "machoMagic": magic,
                "architecture": "arm64",
                "target": f"arm64-apple-ios{config['minimumIos']}",
                "compiler": tools.get("clangVersion") or tools.get("clang"),
                "linker": tools.get("linker"),
                "codeSignatureLoadCommand": "LC_CODE_SIGNATURE" in inspection.stdout,
                "linkedAppleRuntime": [
                    "/usr/lib/libSystem.B.dylib",
                    "/usr/lib/libobjc.A.dylib",
                    "/System/Library/Frameworks/UIKit.framework/UIKit",
                ],
                "signatureKind": signature_kind,
                "signingDetail": signing_detail,
                "webAssetsPath": str(web_assets),
                "compileLogPath": str(build_dir / "compile.log"),
                "inspectionPath": str(inspection_path),
            }
        )
    except Exception as exc:
        receipt.update({"status": "failed", "updatedAt": _utc_now(), "error": str(exc)})
    _write_json(receipt_path, receipt)
    return receipt
