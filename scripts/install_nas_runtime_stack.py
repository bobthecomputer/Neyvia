from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_ROOT = ROOT.parent / "runtime"
DEFAULT_NODE_VERSION = "22.23.1"
DEFAULT_HERMES_SOURCE_URL = "https://api.github.com/repos/NousResearch/hermes-agent/tarball/main"
DEFAULT_GROK_INSTALL_URL = "https://x.ai/cli/install.sh"


def node_platform_arch(machine: str | None = None) -> str:
    normalized = (machine or platform.machine()).strip().lower()
    # The architecture projection is the install plan, not an installation.
    mapping = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
    if normalized in {"x86_64", "amd64"}:
        result = "x64"
        if result != mapping[normalized]:
            raise ValueError("Contract d.runtime.nas-setup.node-plan: CPU architecture changed")
        return result
    if normalized in {"aarch64", "arm64"}:
        result = "arm64"
        if result != mapping[normalized]:
            raise ValueError("Contract d.runtime.nas-setup.node-plan: CPU architecture changed")
        return result
    if normalized.startswith("armv7"):
        return "armv7l"
    raise SystemExit(f"Unsupported NAS CPU architecture for packaged Node.js: {normalized}")


def node_dist_url(version: str, arch: str) -> str:
    clean_version = str(version or "").strip().lstrip("v")
    if not clean_version:
        raise SystemExit("Node.js version is required.")
    result = f"https://nodejs.org/dist/v{clean_version}/node-v{clean_version}-linux-{arch}.tar.xz"
    from urllib.parse import urlparse
    parsed = urlparse(result)
    if parsed.scheme != "https" or parsed.netloc != "nodejs.org" or parsed.path != f"/dist/v{clean_version}/node-v{clean_version}-linux-{arch}.tar.xz":
        raise ValueError("Contract d.runtime.nas-setup.node-plan: package URL lost version or architecture")
    return result


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=str(cwd), env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def download(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return target
    with urllib.request.urlopen(url, timeout=120) as response:
        target.write_bytes(response.read())
    return target


def unpack_node(tarball: Path, runtime_root: Path) -> Path:
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:xz") as archive:
        members = archive.getmembers()
        root_names = {member.name.split("/", 1)[0] for member in members if member.name}
        if len(root_names) != 1:
            raise SystemExit("Unexpected Node.js tarball layout.")
        node_root = runtime_root / next(iter(root_names))
        current_link = runtime_root / "node-current"
        if (node_root / "bin" / "node").exists():
            if current_link.exists() or current_link.is_symlink():
                if current_link.is_symlink() or current_link.is_file():
                    current_link.unlink()
                else:
                    shutil.rmtree(current_link)
            try:
                current_link.symlink_to(node_root.name, target_is_directory=True)
            except OSError:
                shutil.copytree(node_root, current_link)
            return current_link
        runtime_root_resolved = runtime_root.resolve()
        for member in members:
            target = (runtime_root / member.name).resolve()
            if not str(target).startswith(str(runtime_root_resolved)):
                raise SystemExit("Unsafe path found in Node.js tarball.")
        archive.extractall(runtime_root)
    current_link = runtime_root / "node-current"
    if current_link.exists() or current_link.is_symlink():
        if current_link.is_symlink() or current_link.is_file():
            current_link.unlink()
        else:
            shutil.rmtree(current_link)
    try:
        current_link.symlink_to(node_root.name, target_is_directory=True)
    except OSError:
        shutil.copytree(node_root, current_link)
    return current_link


def ensure_bin_shims(runtime_root: Path, node_root: Path) -> Path:
    bin_dir = runtime_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ["node", "npm", "npx"]:
        source = node_root / "bin" / name
        target = bin_dir / name
        if target.exists() or target.is_symlink():
            target.unlink()
        try:
            target.symlink_to(source)
        except OSError:
            shutil.copy2(source, target)
            target.chmod(target.stat().st_mode | 0o111)
    return bin_dir


def install_node_package(runtime_root: Path, bin_dir: Path, package: str) -> None:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")])
    env["NPM_CONFIG_PREFIX"] = str(runtime_root)
    runtime_home = runtime_root / "home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / ".npm").mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(runtime_home)
    env["NPM_CONFIG_CACHE"] = str(runtime_home / ".npm")
    run(["npm", "install", "-g", package], cwd=runtime_root, env=env)


def install_openclaw(runtime_root: Path, bin_dir: Path) -> None:
    install_node_package(runtime_root, bin_dir, "openclaw@latest")


def install_codex(runtime_root: Path, bin_dir: Path) -> None:
    install_node_package(runtime_root, bin_dir, "@openai/codex@latest")


def install_kimi_code(runtime_root: Path, bin_dir: Path) -> None:
    install_node_package(runtime_root, bin_dir, "@moonshot-ai/kimi-code@latest")


def install_claude_code(runtime_root: Path, bin_dir: Path) -> None:
    install_node_package(runtime_root, bin_dir, "@anthropic-ai/claude-code@latest")


def install_grok_build(
    runtime_root: Path,
    bin_dir: Path,
    install_url: str = DEFAULT_GROK_INSTALL_URL,
) -> None:
    installer = download(install_url, runtime_root / "downloads" / "grok-install.sh")
    installer_text = installer.read_text(encoding="utf-8", errors="replace")
    if "grok" not in installer_text.lower() or len(installer_text) < 100:
        raise SystemExit("The downloaded Grok Build installer is not a valid official installer script.")

    runtime_home = runtime_root / "home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")])
    env["HOME"] = str(runtime_home)
    env["GROK_BIN_DIR"] = str(bin_dir)
    run(["sh", str(installer)], cwd=runtime_root, env=env)
    grok_path = bin_dir / "grok"
    if not grok_path.exists():
        raise SystemExit(f"Grok Build installer completed but {grok_path} was not created.")


def ensure_uv(runtime_root: Path, bin_dir: Path) -> Path:
    uv_path = bin_dir / "uv"
    if uv_path.exists():
        return uv_path
    env = dict(os.environ)
    runtime_home = runtime_root / "home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(runtime_home)
    env["UV_INSTALL_DIR"] = str(bin_dir)
    run(["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"], cwd=runtime_root, env=env)
    if not uv_path.exists():
        raise SystemExit(f"uv installer completed but {uv_path} was not created.")
    return uv_path


def unpack_single_root_tarball(tarball: Path, target: Path) -> None:
    tmp_target = target.with_name(f"{target.name}.tmp")
    backup_target = target.with_name(f"{target.name}.previous")
    if tmp_target.exists():
        shutil.rmtree(tmp_target)
    tmp_target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as archive:
        members = archive.getmembers()
        root_names = {member.name.split("/", 1)[0] for member in members if member.name}
        if len(root_names) != 1:
            raise SystemExit("Unexpected Hermes source tarball layout.")
        tmp_resolved = tmp_target.resolve()
        for member in members:
            member_target = (tmp_target / member.name).resolve()
            if not str(member_target).startswith(str(tmp_resolved)):
                raise SystemExit("Unsafe path found in Hermes source tarball.")
        archive.extractall(tmp_target)
        extracted = tmp_target / next(iter(root_names))
    if backup_target.exists():
        shutil.rmtree(backup_target)
    if target.exists():
        target.rename(backup_target)
    extracted.rename(target)
    shutil.rmtree(tmp_target, ignore_errors=True)


def install_hermes(runtime_root: Path, bin_dir: Path, source_url: str = DEFAULT_HERMES_SOURCE_URL) -> None:
    uv_path = ensure_uv(runtime_root, bin_dir)
    tarball = download(source_url, runtime_root / "downloads" / "hermes-agent-main.tgz")
    install_dir = runtime_root / "hermes-agent"
    unpack_single_root_tarball(tarball, install_dir)

    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")])
    runtime_home = runtime_root / "home"
    hermes_home = runtime_home / ".hermes"
    runtime_home.mkdir(parents=True, exist_ok=True)
    hermes_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(runtime_home)
    env["HERMES_HOME"] = str(hermes_home)

    run([str(uv_path), "python", "install", "3.11"], cwd=install_dir, env=env)
    run([str(uv_path), "venv", "venv", "--python", "3.11"], cwd=install_dir, env=env)
    env["VIRTUAL_ENV"] = str(install_dir / "venv")
    run([str(uv_path), "pip", "install", "-e", "."], cwd=install_dir, env=env)

    for name in [
        "cron",
        "sessions",
        "logs",
        "pairing",
        "hooks",
        "image_cache",
        "audio_cache",
        "memories",
        "skills",
    ]:
        (hermes_home / name).mkdir(parents=True, exist_ok=True)
    (hermes_home / ".env").touch(exist_ok=True)
    config_template = install_dir / "cli-config.yaml.example"
    config_path = hermes_home / "config.yaml"
    if config_template.exists() and not config_path.exists():
        shutil.copy2(config_template, config_path)

    shim = bin_dir / "hermes"
    shim.write_text(
        "#!/bin/sh\n"
        f"RUNTIME={runtime_root}\n"
        'export HOME="$RUNTIME/home"\n'
        'export HERMES_HOME="$RUNTIME/home/.hermes"\n'
        'export PATH="$RUNTIME/bin:$PATH"\n'
        'exec "$RUNTIME/hermes-agent/venv/bin/hermes" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | 0o111)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the packaged Syntelos NAS runtime stack.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--node-version", default=DEFAULT_NODE_VERSION)
    parser.add_argument("--node-url", default="", help="Override the Node.js Linux tarball URL.")
    parser.add_argument("--install-openclaw", action="store_true")
    parser.add_argument("--install-codex", action="store_true")
    parser.add_argument("--install-kimi-code", action="store_true")
    parser.add_argument("--install-claude-code", action="store_true")
    parser.add_argument("--install-grok-build", action="store_true")
    parser.add_argument("--grok-install-url", default=DEFAULT_GROK_INSTALL_URL)
    parser.add_argument("--install-hermes", action="store_true")
    parser.add_argument("--hermes-source-url", default=DEFAULT_HERMES_SOURCE_URL)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    arch = node_platform_arch()
    url = args.node_url or node_dist_url(args.node_version, arch)
    tarball = args.runtime_root / "downloads" / Path(url).name
    downloaded = download(url, tarball)
    node_root = unpack_node(downloaded, args.runtime_root)
    bin_dir = ensure_bin_shims(args.runtime_root, node_root)
    if args.install_openclaw:
        install_openclaw(args.runtime_root, bin_dir)
    install_codex_requested = bool(args.install_codex or args.install_openclaw)
    if install_codex_requested:
        install_codex(args.runtime_root, bin_dir)
    if args.install_kimi_code:
        install_kimi_code(args.runtime_root, bin_dir)
    if args.install_claude_code:
        install_claude_code(args.runtime_root, bin_dir)
    if args.install_grok_build:
        install_grok_build(args.runtime_root, bin_dir, args.grok_install_url)
    if args.install_hermes:
        install_hermes(args.runtime_root, bin_dir, args.hermes_source_url)

    payload = {
        "runtimeRoot": str(args.runtime_root),
        "runtimeBinDir": str(bin_dir),
        "nodeRoot": str(node_root),
        "nodeUrl": url,
        "openclawInstalled": bool(args.install_openclaw),
        "codexInstalled": install_codex_requested,
        "kimiCodeInstalled": bool(args.install_kimi_code),
        "claudeCodeInstalled": bool(args.install_claude_code),
        "grokBuildInstalled": bool(args.install_grok_build),
        "hermesInstalled": bool(args.install_hermes),
        "backendEnvironment": f"SYNTELOS_RUNTIME_BIN_DIR={bin_dir}",
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("Syntelos NAS runtime installed.")
        print(f"Runtime bin: {bin_dir}")
        print(f"Backend environment: SYNTELOS_RUNTIME_BIN_DIR={bin_dir}")
        if not args.install_openclaw:
            print("OpenClaw was not installed. Re-run with --install-openclaw when ready.")
        if not install_codex_requested:
            print("Codex was not installed. Re-run with --install-codex for ChatGPT-account chat.")
        if not args.install_kimi_code:
            print("Kimi Code was not installed. Re-run with --install-kimi-code for Kimi K3 routes.")
        if not args.install_claude_code:
            print("Claude Code was not installed. Re-run with --install-claude-code for Claude harness routes.")
        if not args.install_grok_build:
            print("Grok Build was not installed. Re-run with --install-grok-build for Grok harness routes.")
        if not args.install_hermes:
            print("Hermes was not installed. Re-run with --install-hermes for Hermes mission lanes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
