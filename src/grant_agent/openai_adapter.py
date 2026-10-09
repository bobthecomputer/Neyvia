from __future__ import annotations

from .proofs_c_models import checked

from dataclasses import asdict, dataclass
from typing import Any

from .skills import Skill


@dataclass
class OpenAIRequestPlan:
    model: str
    input: list[dict]
    tools: list[dict]
    previous_response_id: str | None = None
    conversation: str | None = None
    instructions: str | None = None
    tool_choice: str | None = None
    store: bool = False

    def as_dict(self) -> dict:
        payload = asdict(self)
        if self.previous_response_id is None:
            payload.pop("previous_response_id")
        if self.conversation is None:
            payload.pop("conversation")
        if self.instructions is None:
            payload.pop("instructions")
        if self.tool_choice is None:
            payload.pop("tool_choice")
        # Apply cache-control / prompt_cache_key onto the wire payload.
        apply_attached_cache_control(payload, getattr(self, "_cache_control", None))
        return payload

    def to_provider_payload(self) -> dict:
        """Wire payload for OpenAI Responses API (includes prompt_cache_key when set)."""
        return self.as_dict()


def apply_attached_cache_control(payload: dict[str, Any], cache_control: Any) -> dict[str, Any]:
    """Mutate payload with route-neutral + provider wire cache fields."""
    if not isinstance(cache_control, dict):
        return payload
    payload["cache_control"] = cache_control
    if cache_control.get("cache_key"):
        payload["cache_key"] = cache_control.get("cache_key")
    if cache_control.get("stable_prefix_cache_key"):
        payload["stable_prefix_cache_key"] = cache_control.get("stable_prefix_cache_key")
    provider_fields = dict(cache_control.get("provider_fields") or {})
    # OpenAI Responses / Chat Completions prompt caching.
    if provider_fields.get("prompt_cache_key"):
        payload["prompt_cache_key"] = provider_fields["prompt_cache_key"]
    # Anthropic-style block cache_control (kept nested for content adapters).
    if provider_fields.get("cache_control") and "anthropic_cache_control" not in payload:
        payload["anthropic_cache_control"] = provider_fields["cache_control"]
    for key, value in provider_fields.items():
        if key in {"prompt_cache_key", "cache_control"}:
            continue
        if key not in payload:
            payload[key] = value
    from .proofs_a_control import check_cache_wire
    check_cache_wire(payload, cache_control)
    return payload


@dataclass
class CodeExecutionConfig:
    enabled: bool = False
    memory_limit: str = "4g"
    container_id: str | None = None
    file_ids: list[str] | None = None
    required: bool = False

    def tool_payload(self) -> dict:
        if self.container_id:
            return {
                "type": "code_interpreter",
                "container": self.container_id,
            }
        container: dict[str, object] = {
            "type": "auto",
            "memory_limit": self.memory_limit or "4g",
        }
        if self.file_ids:
            container["file_ids"] = list(self.file_ids)
        return {
            "type": "code_interpreter",
            "container": container,
        }


def tools_from_skills(
    skills: list[Skill],
    *,
    code_execution: CodeExecutionConfig | None = None,
) -> list[dict]:
    tools: list[dict] = []
    for skill in skills:
        tools.append(
            {
                "type": "function",
                "name": skill.name,
                "description": skill.description,
                "parameters": skill.schema or {"type": "object", "properties": {}},
                "strict": True,
            }
        )
    if code_execution and code_execution.enabled:
        tools.append(code_execution.tool_payload())
    return tools


def build_responses_request(
    objective: str,
    model: str,
    tools: list[dict],
    previous_response_id: str | None = None,
    conversation: str | None = None,
    instructions: str | None = None,
    tool_choice: str | None = None,
    *,
    stable_prefix_cache_key: str | None = None,
    cache_key: str | None = None,
    provider: str = "openai",
) -> OpenAIRequestPlan:
    plan = OpenAIRequestPlan(
        model=model,
        input=[{"role": "user", "content": objective}],
        tools=tools,
        previous_response_id=previous_response_id,
        conversation=conversation,
        instructions=instructions,
        tool_choice=tool_choice,
        store=False,
    )
    # Attach route-neutral cache scaffolding when a durable context key is present.
    if stable_prefix_cache_key or cache_key:
        from .context_microkernel import emit_prompt_cache_control

        plan._cache_control = emit_prompt_cache_control(  # type: ignore[attr-defined]
            stable_prefix_cache_key=str(stable_prefix_cache_key or ""),
            cache_key=str(cache_key or ""),
            provider=provider,
        )
    return plan


def apply_cache_control_to_payload(
    payload: dict,
    *,
    stable_prefix_cache_key: str = "",
    cache_key: str = "",
    provider: str = "openai",
) -> dict:
    """Emit provider cache fields onto an assembled request payload (on the wire)."""
    from .context_microkernel import emit_prompt_cache_control

    cache = emit_prompt_cache_control(
        stable_prefix_cache_key=stable_prefix_cache_key,
        cache_key=cache_key,
        provider=provider,
    )
    enriched = dict(payload)
    return apply_attached_cache_control(enriched, cache)


def build_compaction_request(model: str, items: list[dict], instructions: str | None = None) -> dict:
    payload: dict = {
        "model": model,
        "input": items,
    }
    if instructions:
        payload["instructions"] = instructions
    return payload


@checked("provider-request")
def build_responses_request_from_tool_compiler(
    objective: str,
    model: str,
    compiler: dict[str, Any],
    *,
    previous_response_id: str | None = None,
    conversation: str | None = None,
    instructions: str | None = None,
    stable_prefix_cache_key: str | None = None,
    cache_key: str | None = None,
) -> OpenAIRequestPlan:
    """Build a Responses request from a N-E-Y-V-I-A model-tool compiler result.

    The compiler's call map is intentionally not placed on the provider wire.
    Keep it beside the request and use ``resolve_compiled_tool_call`` when the
    provider returns a function call.
    """

    if str(compiler.get("schema") or "") != "neyvia.openai_tool_compiler.v1":
        raise ValueError("Expected neyvia.openai_tool_compiler.v1")
    tools = compiler.get("tools")
    if not isinstance(tools, list):
        raise ValueError("Tool compiler result is missing tools")
    return build_responses_request(
        objective,
        model,
        list(tools),
        previous_response_id=previous_response_id,
        conversation=conversation,
        instructions=instructions,
        stable_prefix_cache_key=stable_prefix_cache_key,
        cache_key=cache_key,
        provider="openai",
    )


def resolve_compiled_tool_call(
    compiler: dict[str, Any],
    call: dict[str, Any],
) -> dict[str, Any]:
    """Resolve an OpenAI function call back to its immutable native target."""

    from .model_tool_intelligence import ModelToolIntelligence

    arguments = call.get("arguments")
    if isinstance(arguments, str):
        import json

        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("OpenAI tool-call arguments are not valid JSON") from exc
    if not isinstance(arguments, dict):
        arguments = {}
    return ModelToolIntelligence.resolve_openai_call(
        compiler,
        name=str(call.get("name") or ""),
        namespace=str(call.get("namespace") or ""),
        arguments=arguments,
    )


from .proofs_d_runtime import checked as _checked
tools_from_skills = _checked("d.runtime.openai.tools", tools_from_skills)
OpenAIRequestPlan.as_dict = _checked("d.runtime.openai.request", OpenAIRequestPlan.as_dict)
