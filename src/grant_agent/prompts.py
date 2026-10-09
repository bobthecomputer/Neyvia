from __future__ import annotations

from .models import PersonaProfile, PromptStack


def default_step_policy() -> str:
    return (
        "For each step: read docs first, propose action, execute smallest safe change, "
        "run verification, then record decision and next action."
    )


def build_prompt_stack(
    constitution_text: str,
    project_profile: str,
    persona: PersonaProfile,
    task_brief: str,
    step_policy: str | None = None,
) -> PromptStack:
    return PromptStack(
        base_constitution=constitution_text,
        project_profile=project_profile,
        persona=persona,
        task_brief=task_brief,
        step_policy=step_policy or default_step_policy(),
    )


def render_system_prompt(stack: PromptStack) -> str:
    return (
        f"{stack.base_constitution}\n\n"
        f"Project Profile:\n{stack.project_profile}\n\n"
        f"Persona:\n"
        f"- Name: {stack.persona.name}\n"
        f"- Tone: {stack.persona.tone}\n"
        f"- Risk tolerance: {stack.persona.risk_tolerance}\n"
        f"- Creativity: {stack.persona.creativity_level}\n"
        f"- Coding style: {stack.persona.coding_style}\n"
        f"- Verbosity: {stack.persona.verbosity}\n\n"
        f"Task Brief:\n{stack.task_brief}\n\n"
        f"Step Policy:\n{stack.step_policy}\n"
    )
