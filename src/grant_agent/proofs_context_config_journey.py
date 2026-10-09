"""Outcome contract for route context policy at the Native agent boundary."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import time
import uuid
from pathlib import Path


CONTRACT = "context.config.runtime-budget"
_STATE_BASE = Path("D:/NeyviaRuns/P22/measurements/context-config-journey")
_ROUTE = "openai/context-budget-journey"


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {CONTRACT}: {detail}")


def _stage(path: Path, run_id: str, started: float, name: str, **details) -> None:
    """Append bounded timing breadcrumbs outside the source worktree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"run": run_id, "stage": name,
           "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
           **details}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
        stream.flush()


def _policy_file(root: Path, *, mode: str = "capacity") -> Path:
    path = root / "config" / "neyvia_context_policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "neyvia.context-policy.v1",
        "mode": mode,
        "routes": {_ROUTE: {"contextTokens": 12000, "inputLimitTokens": 7000}},
    }, indent=2) + "\n", encoding="utf-8")
    return path


def _provider(requests: list[dict]):
    """Build the production SDK provider over a finite local Responses boundary."""
    import httpx
    from agents import OpenAIProvider
    from openai import AsyncOpenAI

    def respond(request):
        body = json.loads(request.content or b"{}")
        requests.append({"method": request.method, "path": request.url.path, "body": body})
        return httpx.Response(200, json={
            "id": "resp-context-budget-journey",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "model": body.get("model", "context-budget-journey"),
            "output": [{
                "id": "msg-context-budget-journey",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The bounded context policy was applied.", "annotations": []}],
            }],
            "usage": {"input_tokens": 4500, "output_tokens": 100, "total_tokens": 4600,
                      "input_tokens_details": {"cached_tokens": 0}},
        }, request=request)

    client = AsyncOpenAI(
        api_key="context-contract-no-send",
        base_url="http://127.0.0.1:49086/v1",
        max_retries=0,
        timeout=2.0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    return OpenAIProvider(openai_client=client), client


def _build(root: Path, provider, mark):
    mark("neyvia-agent.import.begin")
    from . import neyvia_agent
    mark("neyvia-agent.import.end")

    config = neyvia_agent.NeyviaAgentConfig(
        root=root,
        control_root=root,
        session_id="context-budget-journey",
        provider_id="openai",
        model="context-budget-journey",
        transport="responses",
        max_turns=1,
        enable_specialists=False,
        situation_interface=False,
    )
    original = neyvia_agent._command_capability_summary

    def measured_environment_summary(selected, gateway):
        mark("runtime-environment.inspect.begin")
        try:
            return original(selected, gateway)
        finally:
            mark("runtime-environment.inspect.end")

    neyvia_agent._command_capability_summary = measured_environment_summary
    try:
        mark("neyvia-agent.build.begin")
        built = neyvia_agent.build_neyvia_agent(
            config, provider=provider, instructions="Bounded context policy journey.")
        mark("neyvia-agent.build.end")
        return built
    finally:
        neyvia_agent._command_capability_summary = original


async def _run_session(agent, run_config, mark) -> tuple[str, dict]:
    output = io.StringIO()
    old_stream = os.environ.get("NEYVIA_STREAM_EVENTS")
    os.environ["NEYVIA_STREAM_EVENTS"] = "1"
    try:
        with contextlib.redirect_stdout(output):
            mark("sdk.runner-import.begin")
            from agents import Runner
            mark("sdk.runner-import.end")
            mark("sdk.run.begin")
            result = await Runner.run(
                agent, "Use the bounded context policy for this short request.",
                run_config=run_config, max_turns=1,
            )
            mark("sdk.run.end")
    finally:
        if old_stream is None:
            os.environ.pop("NEYVIA_STREAM_EVENTS", None)
        else:
            os.environ["NEYVIA_STREAM_EVENTS"] = old_stream
    events = [json.loads(line[len("FLUXIO_EVENT:"):]) for line in output.getvalue().splitlines()
              if line.startswith("FLUXIO_EVENT:")]
    observed = next((event.get("data") for event in events
                     if event.get("data", {}).get("eventType") == "context.usage"), None)
    _require(isinstance(observed, dict), "agent did not emit its observed context usage event")
    return str(result.final_output or ""), observed


async def _oversized_request(compactor, mark) -> dict:
    mark("session-compaction.import.begin")
    from .session_compaction import CompactionError
    mark("session-compaction.import.end")

    async def local_checkpoint(_previous, _rows):
        # Only the summarizer boundary is local and deterministic. The actual
        # SessionCompactor and policy-aware replay/refusal remain production code.
        return json.dumps({
            "goals": ["retain the current user request"], "constraints": [], "decisions": [],
            "completed_actions": [], "pending_work": [], "failures": [],
            "important_files": [], "next_steps": [],
        })

    compactor.summarize = local_checkpoint
    compactor.path.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {"role": "user", "content": "Earlier bounded request."},
        {"role": "assistant", "content": "Earlier response."},
        {"role": "user", "content": "Current authored request " + ("context " * 7000)},
    ]
    try:
        mark("compactor.oversize.begin", chars=len(items[-1]["content"]))
        await compactor.compact(items)
    except CompactionError as error:
        mark("compactor.oversize.refused", state=compactor.stats.get("status"),
             summaryCalls=compactor.stats.get("summaryCalls"))
        cause = error.__cause__
        _require(str(error) == "Automatic compaction could not finish. Your full history and last valid checkpoint are preserved; retry to resume.",
                 "oversized current request did not return the bounded user-facing refusal")
        _require(isinstance(cause, CompactionError)
                 and str(cause) == "The current user message exceeds the remaining context budget",
                 "oversized request failure did not identify the context-budget boundary")
        return {"visibleRefusal": str(error), "boundary": str(cause),
                "status": compactor.stats.get("status"), "summaryCalls": compactor.stats.get("summaryCalls")}
    raise ValueError(f"Contract {CONTRACT}: oversized current request was not refused")


async def _execute(agent, run_config, compactor, client, mark) -> tuple[str, dict, dict]:
    try:
        final_output, observed = await _run_session(agent, run_config, mark)
        mark("sdk.usage.observed", inputTokens=observed.get("inputTokens"),
             contextTokens=observed.get("contextTokens"), triggerTokens=observed.get("triggerTokens"))
        oversized = await _oversized_request(compactor, mark)
        return final_output, observed, oversized
    finally:
        await client.close()


def _journey(state: Path, mark) -> dict:
    state.mkdir(parents=True, exist_ok=True)
    (state / ".agent_control").mkdir(exist_ok=True)
    mark("scratch.ready")
    _policy_file(state)
    mark("policy.written")
    requests: list[dict] = []
    mark("provider.construct.begin")
    provider, client = _provider(requests)
    mark("provider.construct.end")
    client_closed = False
    old_catalog = os.environ.get("NEYVIA_CONTEXT_CATALOG_ROOT")
    os.environ["NEYVIA_CONTEXT_CATALOG_ROOT"] = str(state)
    gateway = None
    try:
        mark("agent.build.begin")
        agent, run_config, gateway = _build(state, provider, mark)
        mark("agent.build.end")
        prompt_contract = run_config.call_model_input_filter
        compactor = prompt_contract.compactor
        policy = compactor.policy
        _require(agent.model_settings.max_tokens == 4096
                 and policy.output_reserve == 4096,
                 "route policy did not set the exact SDK output reservation")
        _require(run_config.tracing_disabled is True,
                 "offline contract must not export unrelated SDK traces")
        _require((policy.context_tokens, policy.input_limit, policy.trigger, policy.target)
                 == (12000, 7000, 7000, 4550),
                 "selected route limits did not reach the agent compactor")

        final_output, observed, oversized = asyncio.run(
            _execute(agent, run_config, compactor, client, mark))
        client_closed = True
        _require(final_output == "The bounded context policy was applied.",
                 "the real Native agent session did not return the controlled Responses result")
        _require(len(requests) == 1 and requests[0]["path"].rstrip("/").endswith("/responses"),
                 "the Native SDK did not make exactly one request through the isolated Responses boundary")
        request_body = requests[0]["body"]
        _require(request_body.get("max_output_tokens") == 4096,
                 "route policy did not allocate the exact output budget on the actual SDK request")
        _require((observed.get("inputTokens"), observed.get("contextTokens"), observed.get("triggerTokens"))
                 == (4500, 12000, 7000),
                 "observed usage event did not use the selected route's limits")

        _require(oversized["status"] == "failed" and oversized["summaryCalls"] > 0,
                 "production compactor did not run its bounded summary/replay path before refusal")
        _require(len(requests) == 1, "unexpected provider request count before invalid-policy check")

        _policy_file(state, mode="not-a-context-policy")
        mark("invalid-policy.build.begin")
        try:
            _build(state, provider, mark)
        except ValueError as error:
            mark("invalid-policy.refused", errorType=type(error).__name__)
            _require(str(error) == "Compaction mode must be capacity or avoid-price-increase",
                     "invalid policy returned an unexpected refusal")
        else:
            raise ValueError(f"Contract {CONTRACT}: invalid policy was admitted")
        _require(len(requests) == 1, "invalid policy was refused only after another provider request")
        return {
            "route": _ROUTE,
            "allocation": {"sdkMaxOutputTokens": agent.model_settings.max_tokens,
                           "contextTokens": policy.context_tokens,
                           "inputLimitTokens": policy.input_limit,
                           "triggerTokens": policy.trigger,
                           "targetTokens": policy.target,
                           "requestMaxOutputTokens": request_body["max_output_tokens"]},
            "observedUsage": observed,
            "oversizedRequest": oversized,
            "invalidPolicy": "refused before provider work",
            "providerRequests": len(requests),
            "boundary": "Production Native agent builder, SDK request, usage event and session compactor; one deterministic Responses reply is served by an in-process HTTP transport, with no external provider or network call.",
        }
    finally:
        if gateway is not None:
            plugins = getattr(gateway.native, "_codex_plugins", None)
            if plugins is not None:
                plugins.close()
        if old_catalog is None:
            os.environ.pop("NEYVIA_CONTEXT_CATALOG_ROOT", None)
        else:
            os.environ["NEYVIA_CONTEXT_CATALOG_ROOT"] = old_catalog
        if not client_closed:
            asyncio.run(client.close())


def self_check(root: str | Path | None = None, selected: list[str] | None = None) -> dict:
    """Run the selected route-policy outcome using only P22 SSD scratch."""
    if selected is not None and CONTRACT not in selected:
        return {"area": "context-config-journey", "ok": True, "outcomes": [], "unselected": [CONTRACT]}
    state = _STATE_BASE / uuid.uuid4().hex
    started = time.perf_counter()
    run_id = uuid.uuid4().hex
    mark = lambda name, **details: _stage(state / "stages.jsonl", run_id, started, name, **details)
    mark("self-check.entered")
    try:
        outcome = _journey(state, mark)
        mark("journey.passed")
        result = {"id": CONTRACT, "status": "PASS", "observed": outcome}
    except Exception as error:
        mark("journey.failed", errorType=type(error).__name__)
        result = {"id": CONTRACT, "status": "FAIL", "error": f"{type(error).__name__}: {error}"}
    result["durationMs"] = round((time.perf_counter() - started) * 1000, 2)
    result["runtimeState"] = str(state)
    return {"area": "context-config-journey", "ok": result["status"] == "PASS", "outcomes": [result]}
