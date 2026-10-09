"""Shared validation and interface metadata for durable Codex skill packages."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SKILL_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SKILL_STEP_PATTERN = re.compile(
    r"^\s*(?:\d{1,3}[.)]|[-*+])\s+(?:\[[ xX]\]\s+)?(.+?)\s*$"
)
SKILL_WORKFLOW_HEADINGS = {
    "instructions",
    "procedure",
    "process",
    "steps",
    "workflow",
    "working method",
}


def normalize_skill_markdown(content: str) -> str:
    return str(content or "").rstrip() + "\n"


def validate_skill_markdown(content: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    normalized = normalize_skill_markdown(content)
    name = ""
    description = ""
    if not normalized.startswith("---\n"):
        errors.append("SKILL.md must start with YAML frontmatter.")
    else:
        parts = normalized.split("---", 2)
        if len(parts) < 3:
            errors.append("SKILL.md frontmatter is not closed.")
        else:
            for line in parts[1].splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                field = key.strip().lower()
                parsed = value.strip().strip("\"'")
                if field == "name":
                    name = parsed
                elif field == "description":
                    description = parsed
            if not name:
                errors.append("SKILL.md frontmatter requires a name.")
            elif len(name) > 64 or not SKILL_NAME_PATTERN.fullmatch(name):
                errors.append(
                    "Skill name must use 1-64 lowercase letters and digits separated by hyphens."
                )
            if not description:
                errors.append("SKILL.md frontmatter requires a description.")
            if not parts[2].strip():
                errors.append("SKILL.md requires instruction content after frontmatter.")
    line_count = len(normalized.splitlines())
    if line_count > 500:
        warnings.append(
            "SKILL.md is over 500 lines; move detailed material into references for progressive disclosure."
        )
    return {
        "schema": "fluxio.skill_validation.v1",
        "status": "passed" if not errors else "failed",
        "name": name,
        "description": description,
        "lineCount": line_count,
        "errors": errors,
        "warnings": warnings,
    }


def skill_interface_short_description(description: str) -> str:
    text = " ".join(str(description or "").split()).strip().rstrip(".")
    if len(text) < 25:
        text = f"{text} through a guided workflow"
    if len(text) <= 64:
        return text
    return text[:61].rstrip() + "..."


def _plain_skill_step(value: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(value or ""))
    text = re.sub(r"[*_`~]+", "", text)
    return " ".join(text.split()).strip()[:240]


def extract_skill_workflow_steps(
    content: str,
    *,
    limit: int = 12,
) -> list[str]:
    """Extract exact operator-visible workflow steps without inventing behavior."""

    normalized = normalize_skill_markdown(content)
    body = normalized.split("---", 2)[-1]
    lines = body.splitlines()
    section_steps: list[str] = []
    fallback_steps: list[str] = []
    in_workflow_section = False
    workflow_level = 0
    for line in lines:
        heading = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if heading:
            heading_level = len(heading.group(1))
            heading_name = " ".join(heading.group(2).casefold().split())
            if heading_name in SKILL_WORKFLOW_HEADINGS:
                in_workflow_section = True
                workflow_level = heading_level
            elif in_workflow_section and heading_level <= workflow_level:
                in_workflow_section = False
            continue
        matched = SKILL_STEP_PATTERN.match(line)
        if not matched:
            continue
        step = _plain_skill_step(matched.group(1))
        if not step:
            continue
        fallback_steps.append(step)
        if in_workflow_section:
            section_steps.append(step)

    selected = section_steps or fallback_steps
    steps: list[str] = []
    seen: set[str] = set()
    for step in selected:
        key = step.casefold()
        if key in seen:
            continue
        seen.add(key)
        steps.append(step)
        if len(steps) >= max(1, min(int(limit), 24)):
            break
    if not steps:
        raise ValueError(
            "The sealed skill needs at least one explicit numbered or bulleted "
            "workflow step before App Factory can preserve it."
        )
    return steps


def build_skill_interface_metadata(
    *,
    skill_id: str,
    display_name: str,
    description: str,
    default_prompt: str = "",
) -> str:
    normalized_skill_id = str(skill_id or "").strip()
    if (
        not normalized_skill_id
        or len(normalized_skill_id) > 64
        or not SKILL_NAME_PATTERN.fullmatch(normalized_skill_id)
    ):
        raise ValueError(
            "Skill name must use 1-64 lowercase letters and digits separated by hyphens."
        )
    normalized_description = " ".join(str(description or "").split()).strip()
    if not normalized_description:
        raise ValueError("Skill description is required.")
    normalized_display_name = (
        str(display_name or "").strip()
        or normalized_skill_id.replace("-", " ").title()
    )[:80]
    normalized_prompt = str(default_prompt or "").strip()
    if not normalized_prompt:
        sentence = (
            normalized_description[0].lower() + normalized_description[1:]
            if normalized_description
            else "complete the task"
        )
        normalized_prompt = (
            f"Use ${normalized_skill_id} to {sentence.rstrip('.')}."
        )
    if f"${normalized_skill_id}" not in normalized_prompt:
        raise ValueError(
            f"Default prompt must explicitly mention ${normalized_skill_id}."
        )
    return "\n".join(
        [
            "interface:",
            f"  display_name: {json.dumps(normalized_display_name, ensure_ascii=False)}",
            "  short_description: "
            + json.dumps(
                skill_interface_short_description(normalized_description),
                ensure_ascii=False,
            ),
            f"  default_prompt: {json.dumps(normalized_prompt, ensure_ascii=False)}",
            "",
        ]
    )


def build_validated_skill_package(
    skill_markdown: str,
    *,
    display_name: str = "",
    default_prompt: str = "",
) -> dict[str, Any]:
    normalized = normalize_skill_markdown(skill_markdown)
    validation = validate_skill_markdown(normalized)
    if validation["status"] != "passed":
        raise ValueError(
            "Skill validation failed: " + " ".join(validation["errors"])
        )
    metadata = build_skill_interface_metadata(
        skill_id=str(validation["name"]),
        display_name=display_name,
        description=str(validation["description"]),
        default_prompt=default_prompt,
    )
    skill_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    metadata_sha256 = hashlib.sha256(metadata.encode("utf-8")).hexdigest()
    package_sha256 = hashlib.sha256(
        (
            "neyvia.skill_package.v1\0"
            + skill_sha256
            + "\0"
            + metadata_sha256
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "neyvia.skill_package.v1",
        "skillId": validation["name"],
        "description": validation["description"],
        "skillMarkdown": normalized,
        "openaiYaml": metadata,
        "skillSha256": skill_sha256,
        "metadataSha256": metadata_sha256,
        "packageSha256": package_sha256,
        "validation": validation,
    }
