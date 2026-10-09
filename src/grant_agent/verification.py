from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .models import VerificationResult
from .safety import risk_level_for_command
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_e_sv import enforced


class VerificationRunner:
    def __init__(self, default_timeout_seconds: int = 120) -> None:
        self.default_timeout_seconds = default_timeout_seconds

    @enforced("sv.verification.result")
    def run(self, commands: list[str], workdir: Path) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        pytest_python = _resolve_pytest_python(workdir)
        for command in commands:
            normalized_command = _normalize_verification_command(command, pytest_python)
            risk_level = risk_level_for_command(normalized_command)
            if risk_level == "high":
                results.append(
                    VerificationResult(
                        command=normalized_command,
                        return_code=126,
                        stdout="",
                        stderr="Blocked high-risk command by safety policy.",
                        duration_ms=0,
                        status="blocked",
                        risk_level=risk_level,
                    )
                )
                continue

            start = time.monotonic()
            try:
                completed = subprocess.run(  # noqa: S603
                    normalized_command,
                    shell=True,
                    cwd=str(workdir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.default_timeout_seconds,
                    check=False,
                    **hidden_windows_subprocess_kwargs(),
                )
            except subprocess.TimeoutExpired as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
                stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
                timeout_note = f"Command timed out after {self.default_timeout_seconds} seconds."
                results.append(
                    VerificationResult(
                        command=normalized_command,
                        return_code=124,
                        stdout=stdout.strip(),
                        stderr=(f"{stderr.strip()}\n{timeout_note}".strip()),
                        duration_ms=duration_ms,
                        status="timeout",
                        risk_level=risk_level,
                    )
                )
                continue

            duration_ms = int((time.monotonic() - start) * 1000)
            results.append(
                VerificationResult(
                    command=normalized_command,
                    return_code=completed.returncode,
                    stdout=completed.stdout.strip(),
                    stderr=completed.stderr.strip(),
                    duration_ms=duration_ms,
                    status="executed",
                    risk_level=risk_level,
                )
            )
        return results


@enforced("sv.verification.normalize")
def _normalize_verification_command(command: str, pytest_python: str) -> str:
    text = str(command or "").strip()
    if not text:
        return text
    if text == "pytest" or text.startswith("pytest "):
        suffix = text[len("pytest") :].strip()
        return f'"{pytest_python}" -m pytest {suffix}'.strip()
    if text == "python -m pytest" or text.startswith("python -m pytest "):
        suffix = text[len("python -m pytest") :].strip()
        return f'"{pytest_python}" -m pytest {suffix}'.strip()
    return text


def _resolve_pytest_python(workdir: Path) -> str:
    candidates = [
        Path(sys.executable),
        workdir / ".venv" / "bin" / "python",
        workdir / "venv" / "bin" / "python",
        workdir.parent / "runtime" / "bin" / "python",
        workdir.parent / "syntelos" / "runtime" / "bin" / "python",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if not Path(candidate).exists():
            continue
        try:
            probe = subprocess.run(  # noqa: S603
                [str(candidate), "-c", "import pytest"],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return str(candidate)
    return sys.executable


@enforced("sv.verification.discovery")
def detect_default_verification_commands(workdir: Path, *, pytest_python: str | None = None) -> list[str]:
    commands: list[str] = []
    has_pyproject = (workdir / "pyproject.toml").exists()
    has_tests_dir = (workdir / "tests").exists()
    if has_pyproject and (workdir / "src").exists():
        commands.append("python -m compileall -q src")
    if has_pyproject and has_tests_dir:
        pytest_python = pytest_python or _resolve_pytest_python(workdir)
        pytest_available = False
        try:
            probe = subprocess.run(  # noqa: S603
                [pytest_python, "-c", "import pytest"],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            pytest_available = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pytest_available = False
        if pytest_available:
            commands.append("pytest tests -q")
        else:
            commands.append("python -m unittest discover -s tests")
    package_json_path = workdir / "package.json"
    if package_json_path.exists():
        try:
            package_payload = json.loads(package_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            package_payload = {}
        scripts = package_payload.get("scripts", {}) if isinstance(package_payload, dict) else {}
        if isinstance(scripts, dict):
            if "frontend:build" in scripts:
                commands.append("npm run frontend:build")
            elif "build" in scripts:
                commands.append("npm run build")
    return commands
