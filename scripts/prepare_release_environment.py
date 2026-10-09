"""Prepare a reusable, lock-bound NAS environment before release activation."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def prepare(base: Path, candidate: Path) -> dict:
    base, candidate = base.resolve(strict=True), candidate.resolve(strict=True)
    if candidate.parent != base / "releases":
        raise ValueError("Candidate must be a direct immutable release")
    digest = hashlib.sha256((candidate / "uv.lock").read_bytes()).hexdigest()
    environment = base / "runtime" / "neyvia-environments" / digest
    receipt = environment / ".neyvia-environment.json"
    if environment.exists():
        from resolve_release_python import resolve
        interpreter = resolve(base, candidate)
        subprocess.run([str(interpreter), "-B", "-c", "import agents,blake3,cryptography,ddgs,jsonschema,PIL"], check=True)
        return {**json.loads(receipt.read_text()), "environment": str(environment), "reused": True}
    environment.parent.mkdir(parents=True, exist_ok=True)
    environment.mkdir()  # Exclusive; an unfinished environment is never selected.
    uv = base / ".home" / ".local" / "bin" / "uv"
    interpreter = environment / "bin" / "python"
    env = {**os.environ, "UV_CACHE_DIR": str(base / ".home/.cache/uv"), "PYTHONDONTWRITEBYTECODE": "1"}
    def run(args):
        subprocess.run([str(item) for item in args], env=env, check=True, stdout=subprocess.DEVNULL)
    run([uv, "venv", "--python", base / ".venv/bin/python", environment])
    requirements = environment / "requirements.txt"
    run([uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--project", candidate, "--output-file", requirements])
    run([uv, "pip", "sync", "--python", interpreter, "--require-hashes", requirements])
    # Keep the final path from creation: relocating a venv breaks entry-point shebangs.
    probe = "import agents,blake3,cryptography,ddgs,jsonschema,PIL;import importlib.metadata,json;print(json.dumps({n:importlib.metadata.version(n) for n in ['openai-agents','blake3','cryptography','ddgs','jsonschema','pillow']}))"
    versions = json.loads(subprocess.check_output([str(interpreter), "-B", "-c", probe], env=env))
    ready = {"status": "ready", "lockSha256": digest, "versions": versions,
             "requirementsSha256": hashlib.sha256(requirements.read_bytes()).hexdigest()}
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(json.dumps(ready, indent=2), encoding="utf-8")
    temporary.replace(receipt)
    return {**ready, "environment": str(environment), "reused": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--base", type=Path, default=Path("/volume1/Saclay/projects/syntelos"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.base, args.candidate)))
