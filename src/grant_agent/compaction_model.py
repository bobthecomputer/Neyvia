"""Bookkeeping model calls, isolated from execution and fully accounted for."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace


async def summarize(provider, selected, compactor, previous, records):
    from agents import ModelSettings
    from agents.models.interface import ModelTracing
    from .neyvia_agent import _agent_reasoning_resolution
    from .model_usage import add_summary_usage
    from .session_compaction import SUMMARY_INSTRUCTIONS

    model = provider.get_model(selected.model)
    effort = _agent_reasoning_resolution(replace(selected, reasoning_effort="low")).get("wireEffort")
    extra = {"reasoning_effort": effort} if effort and selected.transport == "chat-completions" else {}
    if selected.transport == "chat-completions" and selected.provider_id == "opencode-go" and selected.model == "deepseek-v4.1-flash":
        extra = {"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}}
    response = None
    try:
        response = await asyncio.wait_for(model.get_response(
            system_instructions=SUMMARY_INSTRUCTIONS,
            input=json.dumps({"previous_checkpoint": previous, "new_records": records}, ensure_ascii=False),
            model_settings=ModelSettings(max_tokens=8192,
                reasoning={"effort": effort} if effort and selected.transport != "chat-completions" else None,
                extra_body=extra or None), tools=[], output_schema=None,
            handoffs=[], tracing=ModelTracing.DISABLED), timeout=240)
        return "\n".join(str(getattr(part, "text", "")) for item in response.output
                         if getattr(item, "type", "") == "message"
                         for part in getattr(item, "content", []) if getattr(part, "type", "") == "output_text")
    finally:
        add_summary_usage(compactor, getattr(response, "usage", None))
