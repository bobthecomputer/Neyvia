from __future__ import annotations


HIGH_RISK_PATTERNS = [
    "rm -rf",
    "del /f /s /q",
    "format ",
    "mkfs",
    "shutdown",
    "reboot",
    "git reset --hard",
]

MEDIUM_RISK_PATTERNS = [
    "git clean -fd",
    "drop database",
    "truncate table",
]


def risk_level_for_command(command: str) -> str:
    lowered = command.lower()
    for pattern in HIGH_RISK_PATTERNS:
        if pattern in lowered:
            return "high"
    for pattern in MEDIUM_RISK_PATTERNS:
        if pattern in lowered:
            return "medium"
    return "low"
