from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ChatReceiptDependencies:
    """Current facade policy and callbacks, supplied explicitly at each operation."""

    openai_codex_default_model: str
    safe_identifier: Callable[..., Any]
    utc_now: Callable[..., Any]
    history_marker: Callable[..., Any]


class ChatReceiptMixin:
    """Owns receipts behavior; the backend supplies state and external callbacks."""

    def _chat_compartment_path(self, session_id: str) -> Path:
        deps = self._receipts_dependencies()
        return self.root / ".agent_control" / "runtime_compartments" / f"{deps.safe_identifier(session_id, 'neyvia_chat')}.json"

    def _display_command(self, args: list[object], *, prompt_marker: str = "<prompt>") -> str:
        safe_args: list[str] = []
        skip_next_prompt = False
        for item in args:
            value = str(item)
            if skip_next_prompt:
                safe_args.append(prompt_marker)
                skip_next_prompt = False
                continue
            safe_args.append(value)
            if value in {"--prompt", "-q"}:
                skip_next_prompt = True
        try:
            return subprocess.list2cmdline(safe_args)
        except (TypeError, ValueError):
            return shlex.join(safe_args)

    def _normalize_receipt_assistant_message(self, candidates: list[Any], command: str = "") -> str:
        command_text = " ".join(str(command or "").split())
        for candidate in candidates:
            text = str(candidate or "").replace("\r\n", "\n").strip()
            if not text:
                continue
            text = re.sub(r"[ \t]+\n", "\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            collapsed = " ".join(text.split())
            if command_text and collapsed == command_text:
                continue
            if re.search(r"^(command|feedback|response|reply)\s*:?\s+(\/volume\d+\/|[A-Z]:\\|wsl\s+|python\s+-m\s+|node\s+|npm\s+|pnpm\s+|yarn\s+|hermes\s+|opencode\s+|openclaw\s+|codex\s+)", collapsed, re.I):
                continue
            if re.search(r"^(\/volume\d+\/|[A-Z]:\\|wsl\s+|python\s+-m\s+|node\s+|npm\s+|pnpm\s+|yarn\s+|hermes\s+|opencode\s+|openclaw\s+|codex\s+)", collapsed, re.I):
                continue
            if re.search(r"\b(mission one-shot|execute model mission|--objective|--mission-id|--provider|--model)\b", collapsed, re.I):
                continue
            if re.search(
                r"\b(delegated runtime lane launched|delegated lane launched|file mutation completed|workspace search completed|approval required before|waiting for operator approval|lane action routed)\b",
                collapsed,
                re.I,
            ):
                continue
            selected = self._assistant_message_from_runtime_output(text) or text
            from .proofs_e_wz import check_model_message
            check_model_message(selected, command)
            return selected
        return ""

    def _assistant_message_from_runtime_output(self, text: str) -> str:
        cleaned = re.sub(
            r"^\s*(?:runtime output|raw action output)\s*:\s*",
            "",
            str(text or "").strip(),
            flags=re.I,
        )
        cleaned = re.sub(
            r"^\s*Mission\s+\S+\s+live runtime output\s*\([^)]+\)\s*",
            "",
            cleaned,
            flags=re.I,
        ).strip()
        if re.search(r"^OpenRuntime returned a real result for this mission\b", cleaned, re.I):
            return cleaned
        if not cleaned or not re.search(r"(^|\n)\s*(artifact|preview url|route)\s*:", cleaned, re.I):
            return ""
        lines = [
            re.sub(r"^[-*]\s*", "", line).strip()
            for line in cleaned.splitlines()
            if line.strip()
        ]

        def is_artifact_line(line: str) -> bool:
            return bool(
                re.search(r"^(artifact|preview url|route|command|status)\s*:", line, re.I)
                or re.search(r"^/volume\d+/", line, re.I)
                or re.search(r"^https?://", line, re.I)
                or re.search(r"^/api/artifact\b", line, re.I)
            )

        headline = next((line for line in lines if not is_artifact_line(line)), "")
        route = next((line for line in lines if re.search(r"^route\s*:", line, re.I)), "")
        facts = [line for line in lines if line != headline and not is_artifact_line(line)][:4]
        parts = [
            (
                f"OpenRuntime returned a real result for this mission: {headline}."
                if headline
                else "OpenRuntime returned a real result for this mission."
            )
        ]
        if facts:
            parts.append(f"Key output: {' '.join(facts)}")
        if route:
            parts.append(route)
        output = "\n".join(parts).strip()
        from .proofs_e_wz import check_humanized_message
        check_humanized_message(lines, headline, facts, route, output)
        return output

    def _turn_receipt_from_chat_result(
        self,
        payload: dict[str, Any],
        result: dict[str, Any],
        *,
        session_id: str,
        route: dict[str, Any],
        changed_files: list[str],
        timeline: list[dict[str, Any]],
        ended_at: str,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        existing = result.get("turnReceipt")
        if isinstance(existing, dict):
            receipt = dict(existing)
        else:
            receipt = {}
        command = (
            receipt.get("command")
            or result.get("command")
            or result.get("launchCommand")
            or result.get("launch_command")
            or ""
        )
        if not command:
            for item in reversed(timeline):
                if not isinstance(item, dict):
                    continue
                if str(item.get("kind") or "").lower() in {"command.execution", "command"}:
                    command = str(item.get("summary") or "")
                    break
        status = receipt.get("status") or result.get("status") or ("completed" if str(result.get("reply") or "").strip() else "completed_no_reply")
        source_type = str(payload.get("sourceType") or payload.get("source_type") or "chat").strip() or "chat"
        assistant_message = self._normalize_receipt_assistant_message(
            [
                receipt.get("assistantMessage"),
                receipt.get("modelMessage"),
                receipt.get("openRuntimeMessage"),
                receipt.get("agentMessage"),
                receipt.get("finalMessage"),
                result.get("assistantMessage"),
                result.get("modelMessage"),
                result.get("openRuntimeMessage"),
                result.get("runtimeMessage"),
                result.get("agentMessage"),
                result.get("finalMessage"),
                result.get("reply"),
                result.get("message"),
            ],
            command,
        )
        run_summary = str(
            receipt.get("runSummary")
            or result.get("result_summary")
            or result.get("resultSummary")
            or ""
        ).strip()
        proof_artifacts: list[dict[str, Any]] = []
        for candidate in (
            receipt.get("proofArtifacts"),
            result.get("proofArtifacts"),
            payload.get("proofArtifacts"),
        ):
            if not isinstance(candidate, list):
                continue
            for item in candidate:
                if isinstance(item, dict):
                    proof_artifacts.append(dict(item))
        for key, kind in (
            ("previewUrl", "preview"),
            ("artifactUrl", "artifact"),
            ("outputArtifactPath", "output_artifact"),
            ("manifestPath", "manifest"),
            ("reportPath", "report"),
            ("proofPath", "proof"),
        ):
            value = str(result.get(key) or payload.get(key) or "").strip()
            if value:
                proof_artifacts.append({"kind": kind, "path" if not value.startswith(("http://", "https://", "/api/")) else "url": value})
        deduped_proof_artifacts: list[dict[str, Any]] = []
        seen_proof_artifacts: set[tuple[str, str, str]] = set()
        for item in proof_artifacts:
            key = (
                str(item.get("kind") or ""),
                str(item.get("path") or ""),
                str(item.get("url") or item.get("previewUrl") or ""),
            )
            if key in seen_proof_artifacts:
                continue
            seen_proof_artifacts.add(key)
            deduped_proof_artifacts.append(item)
        raw_permission_summary = next(
            (
                dict(item)
                for item in (
                    receipt.get("permissionSummary"),
                    result.get("permissionSummary"),
                    payload.get("permissionSummary"),
                )
                if isinstance(item, dict)
            ),
            {},
        )

        def permission_names(key: str) -> list[str]:
            values = raw_permission_summary.get(key)
            if not isinstance(values, list):
                return []
            names: list[str] = []
            for value in values:
                name = str(value or "").strip().lower()[:120]
                if name and name not in names:
                    names.append(name)
            return sorted(names)[:40]

        permission_summary = (
            {
                "allowed": permission_names("allowed"),
                "approvalRequired": permission_names("approvalRequired"),
                "denied": permission_names("denied"),
            }
            if raw_permission_summary
            else {}
        )
        from .model_usage import runtime_usage
        return {
            "schema": "fluxio.turn_receipt.v1",
            "usage": runtime_usage(result),
            "sessionId": receipt.get("sessionId") or session_id,
            "missionId": receipt.get("missionId") or str(payload.get("missionId") or payload.get("mission_id") or ""),
            "sourceType": receipt.get("sourceType") or source_type,
            "sourceMessageId": receipt.get("sourceMessageId") or str(payload.get("sourceMessageId") or ""),
            "sourceZone": receipt.get("sourceZone") or str(payload.get("sourceZone") or ""),
            "commentText": receipt.get("commentText") or str(payload.get("commentText") or ""),
            "command": command or "Not reported",
            "runtime": receipt.get("runtime") or str(result.get("runtime") or payload.get("runtime") or "Not reported"),
            "provider": receipt.get("provider") or str(result.get("provider") or payload.get("provider") or route.get("provider") or "Not reported"),
            "model": receipt.get("model") or str(result.get("model") or result.get("model_id") or payload.get("model") or route.get("model_id") or route.get("model") or "Not reported"),
            "effort": receipt.get("effort") or str(result.get("effort") or payload.get("effort") or route.get("effort") or "Not reported"),
            "status": str(status),
            "exitCode": receipt.get("exitCode", result.get("exitCode", result.get("exit_code", ""))),
            "startedAt": receipt.get("startedAt") or str(payload.get("requestStartedAt") or ""),
            "endedAt": receipt.get("endedAt") or ended_at,
            "durationMs": receipt.get("durationMs", elapsed_ms),
            "toolTimeline": receipt.get("toolTimeline") if isinstance(receipt.get("toolTimeline"), list) else timeline[-30:],
            # The receipt is derived from the validated evidence supplied by
            # the runtime adapter. Never copy a nested/model-generated list
            # back into the authoritative receipt.
            "changedFiles": changed_files[:30],
            "assistantMessage": assistant_message,
            "finalMessage": assistant_message,
            "modelMessageSource": receipt.get("modelMessageSource") or str(result.get("modelMessageSource") or ""),
            "modelMessageSourceLabel": receipt.get("modelMessageSourceLabel") or str(result.get("modelMessageSourceLabel") or ""),
            "modelMessageSourceTitle": receipt.get("modelMessageSourceTitle") or str(result.get("modelMessageSourceTitle") or ""),
            "modelMessageSourceId": receipt.get("modelMessageSourceId") or str(result.get("modelMessageSourceId") or ""),
            "transcriptSessionId": receipt.get("transcriptSessionId") or str(result.get("transcriptSessionId") or ""),
            "runSummary": run_summary,
            "proofArtifacts": deduped_proof_artifacts[:30],
            "permissionSummary": permission_summary,
            "goalLoop": receipt.get("goalLoop") or result.get("goalLoop") or (
                result.get("raw", {}).get("goalLoop") if isinstance(result.get("raw"), dict) else None),
        }

    def _save_chat_compartment(self, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        deps = self._receipts_dependencies()
        session_id = deps.safe_identifier(result.get("sessionId") or payload.get("sessionId") or "neyvia_chat")
        route = result.get("route") if isinstance(result.get("route"), dict) else self._chat_route(payload)
        workspace_path = str(Path(str(payload.get("workspacePath") or self.root)).expanduser())
        workspace_root = Path(workspace_path).expanduser()
        textual_files, textual_proof_artifacts = self._chat_textual_artifact_evidence(
            result,
            workspace_path=workspace_root,
        )
        if textual_files or textual_proof_artifacts:
            enriched_result = dict(result)
            current_files = result.get("filesChanged") if isinstance(result.get("filesChanged"), list) else []
            current_artifacts = result.get("proofArtifacts") if isinstance(result.get("proofArtifacts"), list) else []
            enriched_result["filesChanged"] = [*current_files, *textual_files]
            enriched_result["proofArtifacts"] = [*current_artifacts, *textual_proof_artifacts]
            result = enriched_result
        path = self._chat_compartment_path(session_id)
        previous: dict[str, Any] = {}
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
        timeline = previous.get("timeline") if isinstance(previous.get("timeline"), list) else []
        now = deps.utc_now()
        elapsed_ms_raw = result.get("elapsedMs")
        try:
            elapsed_ms = int(elapsed_ms_raw) if elapsed_ms_raw is not None else 0
        except (TypeError, ValueError):
            elapsed_ms = 0
        runtime_tool_timeline = result.get("toolTimeline") if isinstance(result.get("toolTimeline"), list) else []
        timeline.extend(
            [
                {
                    "kind": "operator.message",
                    "at": now,
                    "summary": str(payload.get("message") or "").strip()[:240],
                },
            ]
        )
        if elapsed_ms > 0:
            timeline.append(
                {
                    "kind": "runtime.roundtrip",
                    "at": now,
                    "summary": f"CLI roundtrip completed in {elapsed_ms} ms.",
                    "status": "completed",
                }
            )
        for item in runtime_tool_timeline[-48:]:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or item.get("message") or "").strip()
            if not summary:
                continue
            timeline.append(
                {
                    "kind": str(item.get("kind") or item.get("type") or "runtime.event"),
                    "at": str(item.get("at") or now),
                    "summary": summary[:240],
                    "status": str(item.get("status") or "recorded"),
                    **{
                        key: str(item[key])[:12000]
                        for key in ("tool", "command", "code", "input", "output", "error", "goal", "callId", "itemId", "toolStatus")
                        if item.get(key)
                    },
                }
            )
        previous_files = previous.get("filesChanged") if isinstance(previous.get("filesChanged"), list) else []
        changed_files: list[str] = []
        seen_files: set[str] = set()
        for candidate in [*previous_files, *(result.get("filesChanged") if isinstance(result.get("filesChanged"), list) else [])]:
            if isinstance(candidate, dict):
                candidate = candidate.get("path") or candidate.get("file") or candidate.get("name")
            validated = self._validated_chat_changed_file(
                candidate,
                workspace_path=workspace_root,
            )
            if validated is None:
                continue
            value = validated[0]
            if value in seen_files:
                continue
            seen_files.add(value)
            changed_files.append(value)
        active_role = str(route.get("role") or payload.get("role") or "executor").strip().lower() or "executor"
        lanes = []
        for role in ("planner", "executor", "verifier"):
            lanes.append(
                {
                    "role": role,
                    "phase": "plan" if role == "planner" else ("verify" if role == "verifier" else "execute"),
                    "provider": route.get("provider") or "openai-codex",
                    "model": route.get("model") or deps.openai_codex_default_model,
                    "effort": route.get("effort") or "high",
                    "health": "ready",
                    "active": role == active_role,
                    "authPath": "OpenAI Codex OAuth" if route.get("provider") == "openai-codex" else "provider route",
                    "blocker": "",
                }
            )
        turn_receipt = self._turn_receipt_from_chat_result(
            payload,
            result,
            session_id=session_id,
            route=route,
            changed_files=changed_files,
            timeline=timeline,
            ended_at=now,
            elapsed_ms=elapsed_ms,
        )
        model_reply = str(turn_receipt.get("assistantMessage") or "").strip()
        raw_runtime_reply = str(result.get("reply") or result.get("message") or "").strip()
        if model_reply:
            timeline.append(
                {
                    "kind": "runtime.model_message",
                    "at": now,
                    "summary": model_reply[:240],
                    "status": "recorded",
                }
            )
        elif raw_runtime_reply:
            timeline.append(
                {
                    "kind": "runtime.trace_only_reply",
                    "at": now,
                    "summary": raw_runtime_reply[:240],
                    "status": "trace_only",
                }
            )
        # A reply owns only its own calls; the compartment below retains the
        # conversation-wide activity separately.
        turn_receipt["toolTimeline"] = runtime_tool_timeline
        turn_receipt["reasoningSummary"] = "\n\n".join(
            str(item.get("output") or "") for item in runtime_tool_timeline
            if item.get("kind") == "runtime.reasoning_summary"
        )
        turn_receipt["activitySegments"] = [
            ({"kind": "thinking_text" if item.get("kind") == "runtime.thinking" else "reasoning_summary",
              "id": f"thinking-{index}", "text": str(item.get("output") or ""),
              **({"source": "provider.reasoning_content"} if item.get("kind") == "runtime.thinking" else {})}
             if item.get("kind") in {"runtime.reasoning_summary", "runtime.thinking"} else
             {"kind": "tool", "callId": item.get("callId") or item.get("itemId") or f"tool-{index}",
              "tool": item.get("tool") or "tool", "status": item.get("toolStatus") or item.get("status"),
              "input": item.get("input") or "", "output": item.get("output") or "",
              "error": item.get("error") or "", "eventType": item.get("kind")})
            for index, item in enumerate(runtime_tool_timeline)
            if item.get("kind") in {"runtime.reasoning_summary", "runtime.thinking", "runtime.tool"}
        ]
        proof_artifacts = turn_receipt.get("proofArtifacts") if isinstance(turn_receipt.get("proofArtifacts"), list) else []
        result_status = str(result.get("status") or turn_receipt.get("status") or "completed").strip().lower()
        result_error = str(result.get("error") or result.get("errorMessage") or "").strip()
        if proof_artifacts:
            timeline.append(
                {
                    "kind": "proof.artifact_attached",
                    "at": now,
                    "summary": f"Attached {len(proof_artifacts)} proof artifact(s) to this turn receipt.",
                    "status": "recorded",
                }
            )
            turn_receipt["toolTimeline"] = [*runtime_tool_timeline, timeline[-1]]
        messages = previous.get("messages") if isinstance(previous.get("messages"), list) else []
        previous_receipts = previous.get("turnReceipts") if isinstance(previous.get("turnReceipts"), list) else []
        previous_window = (list(messages), list(previous_receipts))
        operator_message = str(payload.get("message") or "").strip()
        if operator_message:
            messages.append({
                "turnId": str(payload.get("userTurnId") or payload.get("user_turn_id") or ""),
                "role": "operator", "text": operator_message,
                "at": str(payload.get("requestStartedAt") or now), "source": "operator-submitted",
            })
        if model_reply:
            messages.append({
                "turnId": str(payload.get("assistantTurnId") or payload.get("assistant_turn_id") or ""),
                "role": "assistant", "text": model_reply, "at": now,
                "source": "backend-model-message", "turnReceipt": turn_receipt,
                "activitySegments": turn_receipt.get("activitySegments", []),
            })
        message_window = messages[-40:]
        receipt_window = [*previous_receipts, turn_receipt][-20:]
        compartment = {
            "sessionId": session_id,
            "missionId": str(payload.get("missionId") or payload.get("mission_id") or ""),
            "runtime": result.get("runtime") or payload.get("runtime") or "openclaw",
            "cwd": workspace_path,
            "route": route,
            "host": os.environ.get("COMPUTERNAME") or (os.uname().nodename if hasattr(os, "uname") else ""),
            "state": "failed" if result_status in {"failed", "error", "timeout"} else "ready",
            "streaming": "failed" if result_status in {"failed", "error", "timeout"} else "recorded",
            "messages": message_window,
            "toolTimeline": timeline[-30:],
            "lanes": lanes,
            "filesChanged": changed_files[:30],
            "proofArtifacts": proof_artifacts[:30],
            "turnReceipt": turn_receipt,
            "turnReceipts": receipt_window,
            "approvals": [],
            "blockers": [result_error] if result_error else [],
            "errors": [result_error] if result_error else [],
            "actions": ["resume-chat", "open-proof", "restart"],
            "restartControls": {
                "canRestart": True,
                "canResume": True,
            },
            "lastRoundtripMs": elapsed_ms,
            "updatedAt": now,
            # Lets the persisted turn store only what it added to the windows.
            "history": deps.history_marker(
                turn_id=str(payload.get("assistantTurnId") or payload.get("assistant_turn_id") or ""),
                previous=previous,
                previous_messages=previous_window[0],
                previous_receipts=previous_window[1],
                messages=message_window,
                receipts=receipt_window,
                appended_messages=len(messages) - len(previous_window[0]),
            ),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(compartment, indent=2), encoding="utf-8")
        from .proofs_e_wz import check_chat_compartment
        check_chat_compartment(compartment, payload, result, previous_window[0], path)
        return compartment
