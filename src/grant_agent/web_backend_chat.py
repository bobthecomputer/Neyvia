"""Chat routing, CLI transports and durable turn persistence.

Resolve public-facade collaborators at call time to preserve existing patch
seams; this owner changes responsibility boundaries without changing policy.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _backend_facade():
    from . import web_backend
    return web_backend


class WebBackendChatMixin:
    def _openclaw_provider_for_route(self, provider: object) -> str:
        _facade = _backend_facade()
        normalized = str(provider or "").strip().lower()
        if normalized == "openai":
            return "openai-codex"
        if normalized == "minimax":
            presence = _facade._provider_presence(
                ["minimax", "minimax-portal"],
                session_secrets=self.provider_secrets,
            )
            if presence.get("minimax-portal") and not presence.get("minimax"):
                return "minimax-portal"
            return "minimax"
        aliases = {
            "openai-codex": "openai-codex",
            "minimax-portal": "minimax-portal",
            "minimax-cn": "minimax",
            "anthropic": "anthropic",
            "openrouter": "openrouter",
            "opencon": "openrouter",
            "opencon-pro": "openrouter",
            "openconpro": "openrouter",
            "deepseek": "openrouter",
            "opencode-go": "opencode-go",
            "opencodego": "opencode-go",
            "gemini": "gemini",
            "huggingface": "huggingface",
            "zai": "zai",
            "kimi-coding": "kimi-coding",
            "kimi-coding-cn": "kimi-coding-cn",
            "kimi-code": "kimi-code",
            "claude-code": "claude-code",
            "grok-build": "grok-build",
        }
        return aliases.get(normalized, normalized)


    def _chat_route(self, payload: dict[str, Any]) -> dict[str, str]:
        _facade = _backend_facade()
        route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
        runtime = str(payload.get("runtime") or payload.get("runtimeId") or route.get("runtimeId") or "").strip().lower()
        open_code = runtime in {"opencode", "open-code", "opencode-native", "opencode-go"}
        requested_provider = str(route.get("provider") or payload.get("provider") or "openai-codex").strip()
        provider = requested_provider if open_code else self._openclaw_provider_for_route(requested_provider)
        model = _facade._normalize_chat_model(
            provider,
            str(route.get("model") or payload.get("model") or _facade.OPENAI_CODEX_DEFAULT_MODEL).strip(),
        )
        if not open_code and provider in {"minimax", "minimax-cn", "minimax-portal"} and model.lower() in {
            "minimax-m2.7",
            "minimax-m2.7-highspeed",
            "minimax/m2.7",
            "minimax/minimax-m2.7",
            "minimax/minimax-m2.7-highspeed",
        }:
            model = "MiniMax-M3"
        effort = str(route.get("effort") or payload.get("effort") or "high").strip().lower()
        role = str(route.get("role") or payload.get("role") or "executor").strip().lower()
        model_id = _facade._chat_model_id(provider, model)
        if open_code and model:
            # Catalog models may themselves contain a slash (for example a
            # vendor/model name). OpenCode still needs its selected provider
            # prefix, and saved prompt scopes use the unprefixed model ID.
            if model.startswith(provider + "/"):
                model = model[len(provider) + 1:]
            model_id = f"{provider}/{model}"
        output = {
            "provider": provider,
            "model": model,
            "model_id": model_id,
            "effort": effort if effort and effort != "default" else "high",
            "role": role,
        }
        from .proofs_e_wz import check_chat_route
        check_chat_route(payload, output)
        return output


    def _openclaw_agent_id(self, session_id: str, model_id: str) -> str:
        _facade = _backend_facade()
        digest = _facade.hashlib.sha1((model_id or session_id).encode("utf-8")).hexdigest()[:8]
        return _facade._safe_identifier(f"neyvia_chat_{session_id}_{digest}", "neyvia_chat_agent")[:64]


    def _prepare_openclaw_agent(
        self,
        *,
        command: str,
        workspace_path: Path,
        session_id: str,
        model_id: str,
        env: dict[str, str],
    ) -> tuple[str, list[dict[str, str]]]:
        _facade = _backend_facade()
        if not model_id:
            return "", []
        agent_id = self._openclaw_agent_id(session_id, model_id)
        setup_events: list[dict[str, str]] = []
        add_args = [
            command,
            "agents",
            "add",
            agent_id,
            "--workspace",
            str(workspace_path),
            "--model",
            model_id,
            "--non-interactive",
            "--json",
        ]
        set_args = [command, "models", "--agent", agent_id, "set", model_id]
        try:
            _facade._run_process(
                add_args,
                cwd=workspace_path,
                timeout=_facade.AGENT_CHAT_SETUP_TIMEOUT_SECONDS,
                extra_env=env,
            )
            setup_events.append(
                {
                    "kind": "runtime.agent_config",
                    "summary": f"OpenClaw agent {agent_id} configured for {model_id}.",
                    "status": "completed",
                }
            )
            return agent_id, setup_events
        except Exception as add_exc:  # noqa: BLE001 - fallback to existing agent model set
            setup_events.append(
                {
                    "kind": "runtime.agent_config",
                    "summary": f"OpenClaw agent add did not complete: {str(add_exc)[:180]}",
                    "status": "fallback",
                }
            )
        try:
            _facade._run_process(
                set_args,
                cwd=workspace_path,
                timeout=_facade.AGENT_CHAT_SETUP_TIMEOUT_SECONDS,
                extra_env=env,
            )
            setup_events.append(
                {
                    "kind": "runtime.agent_config",
                    "summary": f"OpenClaw existing agent {agent_id} set to {model_id}.",
                    "status": "completed",
                }
            )
            return agent_id, setup_events
        except Exception as set_exc:  # noqa: BLE001
            setup_events.append(
                {
                    "kind": "runtime.agent_config",
                    "summary": f"OpenClaw model setup failed: {str(set_exc)[:180]}",
                    "status": "failed",
                }
            )
            return "", setup_events


    def _run_openclaw_infer_chat(
        self,
        *,
        command: str,
        prompt: str,
        route: dict[str, str],
        workspace_path: Path,
        session_id: str,
        env: dict[str, str],
        timeout: int | None,
    ) -> dict[str, Any]:
        _facade = _backend_facade()
        model_id = route["model_id"]
        args = [
            command,
            "infer",
            "model",
            "run",
            "--local",
            "--json",
            "--prompt",
            prompt,
        ]
        if model_id:
            args.extend(["--model", model_id])
        display_command = self._display_command(args)
        result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
            args,
            cwd=workspace_path,
            timeout=timeout,
            extra_env=env,
        )
        reply = _facade._extract_model_reply(result)
        if not reply:
            raise RuntimeError("OpenClaw finished without a readable model reply.")
        now = _facade._utc_now()
        tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
            result,
            stdout=stdout,
            now=now,
            elapsed_ms=elapsed_ms,
        )
        return {
            "reply": reply,
            "runtime": "openclaw",
            "sessionId": session_id,
            "route": {**route, "openclawMode": "infer"},
            "raw": result,
            "elapsedMs": elapsed_ms,
            "command": display_command,
            "toolTimeline": tool_timeline,
            "filesChanged": files_changed,
            "changeEvidenceAvailable": change_evidence_available,
        }


    def _run_openclaw_agent_chat(
        self,
        *,
        command: str,
        prompt: str,
        route: dict[str, str],
        workspace_path: Path,
        session_id: str,
        env: dict[str, str],
        timeout: int | None,
    ) -> dict[str, Any]:
        _facade = _backend_facade()
        model_id = route["model_id"]
        agent_id, setup_events = self._prepare_openclaw_agent(
            command=command,
            workspace_path=workspace_path,
            session_id=session_id,
            model_id=model_id,
            env=env,
        )
        thinking = route.get("effort") or "high"
        args = [
            command,
            "agent",
            "--session-id",
            session_id,
            "--message",
            prompt,
            "--thinking",
            thinking,
            "--json",
        ]
        local_mode = str(
            _facade.os.environ.get("NEYVIA_OPENCLAW_AGENT_MODE")
            or _facade.os.environ.get("SYNTELOS_OPENCLAW_AGENT_MODE")
            or ""
        ).strip().lower()
        if local_mode == "local":
            args.append("--local")
        if agent_id:
            args[2:2] = ["--agent", agent_id]
        elif model_id:
            setup_summary = "; ".join(item["summary"] for item in setup_events[-2:])
            raise RuntimeError(
                f"OpenClaw model setup failed before chat execution for {model_id}. {setup_summary}"
            )
        display_command = self._display_command(args)
        result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
            args,
            cwd=workspace_path,
            timeout=timeout,
            extra_env=env,
        )
        reply = _facade._extract_model_reply(result)
        if not reply:
            raise RuntimeError("OpenClaw finished without a readable model reply.")
        now = _facade._utc_now()
        tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
            result,
            stdout=stdout,
            now=now,
            elapsed_ms=elapsed_ms,
        )
        setup_timeline = [
            {
                "kind": item["kind"],
                "at": now,
                "summary": item["summary"],
                "status": item["status"],
            }
            for item in setup_events
        ]
        return {
            "reply": reply,
            "runtime": "openclaw",
            "sessionId": session_id,
            "route": {**route, "openclawMode": "agent", "agentId": agent_id},
            "raw": result,
            "elapsedMs": elapsed_ms,
            "command": display_command,
            "toolTimeline": [*setup_timeline, *tool_timeline][-24:],
            "filesChanged": files_changed,
            "changeEvidenceAvailable": change_evidence_available,
        }


    def _run_openclaw_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        _facade = _backend_facade()
        prompt = _facade._chat_prompt(payload)
        env = self._provider_env()
        command = _facade.shutil.which("openclaw", path=env.get("PATH") or _facade.os.environ.get("PATH"))
        if not command:
            raise RuntimeError("OpenClaw CLI was not found on PATH.")
        route = self._chat_route(payload)
        timeout = _facade._agent_chat_runtime_timeout_seconds(payload, route)
        workspace_path = _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser()
        if not workspace_path.exists():
            workspace_path = self.root
        workspace_id = _facade._safe_identifier(payload.get("workspaceId") or workspace_path.name, "workspace")
        session_id = _facade._safe_identifier(payload.get("sessionId") or f"neyvia_chat_{workspace_id}", "neyvia_chat")
        mode = str(
            payload.get("openclawMode")
            or payload.get("openclaw_mode")
            or _facade.os.environ.get("FLUXIO_OPENCLAW_CHAT_MODE")
            or "agent"
        ).strip().lower()
        if mode in {"infer", "model", "model-run"}:
            return self._run_openclaw_infer_chat(
                command=command,
                prompt=prompt,
                route=route,
                workspace_path=workspace_path,
                session_id=session_id,
                env=env,
                timeout=timeout,
            )
        return self._run_openclaw_agent_chat(
            command=command,
            prompt=prompt,
            route=route,
            workspace_path=workspace_path,
            session_id=session_id,
            env=env,
            timeout=timeout,
        )


    def _run_neyvia_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        _facade = _backend_facade()
        workspace_path = _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser()
        if not workspace_path.exists():
            workspace_path = self.root
        runtime_workspace = _facade.Path(
            str(payload.get("_profileWorkspacePath") or workspace_path)
        ).expanduser()
        if not runtime_workspace.exists():
            runtime_workspace = self.root
        # Native execution shares this backend's verified interpreter and active
        # source. A launcher on PATH may belong to an older dependency environment.
        launcher = [_facade.sys.executable, "-m", "grant_agent.neyvia_agent_cli"]
        route = self._chat_route(payload)
        route["effort"] = str((payload.get("route") or {}).get("effort") or "default")
        runtime_timeout_seconds = _facade._agent_chat_runtime_timeout_seconds(payload, route)
        max_turns = _facade._agent_chat_max_turns(payload)
        model = str(route.get("model") or "").strip()
        if model.lower() in {"", "auto", "provider-selected", "route-selected", "codex"}:
            model = _facade.OPENAI_CODEX_DEFAULT_MODEL
        session_id = _facade._safe_identifier(
            payload.get("sessionId")
            or f"neyvia-ui-{_facade.uuid.uuid4().hex[:12]}",
            "neyvia-ui",
        )
        prompt = _facade._chat_prompt({**payload, "_roleInstructionsInSystem": True,
                               "_durableNativeHistory": _facade._native_session_has_history(runtime_workspace, session_id)})
        from .agent_questions import answer_pending_question
        answer_pending_question(runtime_workspace, session_id, str(payload.get("message") or ""))
        from .agent_prompt_library import compiled_role_prompt, ROLES
        role = str(payload.get("agentRole") or "chat")
        role = role if role in ROLES else "chat"
        instructions = str(payload.get("_systemInstructions") or compiled_role_prompt(runtime_workspace, role, **_facade._chat_prompt_scope({**payload, "route": route})))
        instructions = instructions.replace("\r\n", "\n").replace("\r", "\n")
        instruction_hash = _facade.hashlib.sha256(instructions.encode()).hexdigest()
        instruction_path = runtime_workspace / ".agent_control" / "neyvia_agent" / "instructions" / f"{instruction_hash}.txt"
        instruction_path.parent.mkdir(parents=True, exist_ok=True)
        if not instruction_path.exists():
            instruction_path.write_text(instructions, encoding="utf-8", newline="\n")
        args = [
            *launcher,
            prompt,
            "--root",
            str(workspace_path),
            "--session-id",
            session_id,
            "--model",
            model,
            "--provider-id", str(route.get("provider") or ""),
            "--reasoning-effort",
            route["effort"],
            "--control-root",
            str(runtime_workspace),
            "--max-turns",
            str(max_turns),
            "--json",
            "--agent-role", role,
            "--permission-mode", str(payload.get("_permissionMode") or "read-only"),
            "--instructions-file", str(instruction_path),
        ]
        if runtime_timeout_seconds is not None:
            # Leave time inside the caller-requested outer deadline to clean up
            # the runtime child and write its durable receipt.
            args.extend(["--timeout-seconds", str(max(1, runtime_timeout_seconds - 30))])
        if payload.get("goalMode") is True:
            args.append("--goal-mode")
        if role != "chat" or not payload.get("enableSpecialists"):
            args.append("--no-specialists")
        if payload.get("maxOutputTokens"):
            args.extend(["--max-output-tokens", str(int(payload["maxOutputTokens"]))])
        profile_id = str(
            payload.get("harnessProfileId") or payload.get("harness_profile_id") or ""
        ).strip()
        profile = _facade.resolve_harness_profile(runtime_workspace, "neyvia-agent", profile_id)
        selected_provider = str(route.get("provider") or "").lower()
        if profile and selected_provider and str(profile.get("providerId") or "").lower() != selected_provider:
            if profile_id:
                raise RuntimeError("The selected native connection profile does not match the requested provider.")
            profile = None
        profile_env = _facade.harness_gateway_environment(
            runtime_workspace,
            "neyvia-agent",
            profile_id,
            self._provider_env(),
        ) if profile else {}
        if profile:
            base_url = str(profile.get("baseUrl") or "").strip()
            credential_env = str(profile.get("credentialEnv") or "").strip()
            compatibility = str(profile.get("compatibilityMode") or "").strip().lower()
            if base_url:
                args.extend(["--base-url", base_url])
            if credential_env:
                args.extend(["--api-key-env", credential_env])
            if compatibility == "openai-compatible":
                args.extend(["--transport", "chat-completions"])
        if not profile:
            provider = str(route.get("provider") or "").lower()
            if provider in {"opencode-go", "opencodego"}:
                args.extend(_facade.native_go_transport_args(model))
            elif provider not in {"", "openai", "openai-codex", "responses-compatible"}:
                raise RuntimeError(f"Configure a Neyvia Native connection profile for provider '{provider}' in Connection settings.")
        if bool(payload.get("_allowMutation")):
            args.append("--allow-mutations")
        for tool in payload.get("_nativeMutationTools") or []:
            args.extend(["--native-mutation-tool", str(tool)])
        display_args = list(args)
        display_args[len(launcher)] = "<prompt>"
        env = _facade.runtime_subprocess_env(runtime_workspace)
        env.update(self._provider_env())
        env.update(profile_env)
        stream_turn_id = str(payload.get("assistantTurnId") or "")
        if stream_turn_id:
            env["NEYVIA_STREAM_EVENTS"] = "1"
        # Proof belongs to the parent conversation, even when execution uses a
        # separate workspace and a runtime-specific session identifier.
        proof_conversation = str(payload.get("parentSessionId") or payload.get("conversationId") or "")
        try:
            self.neyvia_mcp.conversations.get_conversation(proof_conversation)
        except KeyError:
            proof_conversation = ""
        env["NEYVIA_PROOF_CONVERSATION_ID"] = proof_conversation
        from .neyvia_memory_tools import chat_context, launcher_scope
        env['NEYVIA_MEMORY_SCOPE'] = launcher_scope(chat_context(self.root, self.username, workspace_path,
            str(payload.get('message') or ''), str(payload.get('userTurnId') or stream_turn_id)))
        env['NEYVIA_MEMORY_HOST_ROOT'] = str(self.root.resolve())
        env["NEYVIA_PROOF_ROOT"] = str(self.root) if proof_conversation else ""
        # Keep the stable launcher bound to the active backend candidate. A
        # workspace checkout can lag behind a just-published release, and must
        # not silently supply an older CLI parser for newly selected transports.
        active_package_root = str(_facade.Path(__file__).resolve().parents[1])
        # Workspace sessions keep their own history; model metadata/preferences
        # belong to the app's catalog root and must travel to the native child.
        env["NEYVIA_CONTEXT_CATALOG_ROOT"] = str(self.root)
        existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
        env["PYTHONPATH"] = _facade.os.pathsep.join(
            item for item in (active_package_root, existing_pythonpath) if item
        )
        from .chat_stream import append_chat_stream
        result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
            args,
            cwd=workspace_path,
            timeout=runtime_timeout_seconds,
            extra_env=env,
            on_event=(lambda event: append_chat_stream(self.root, stream_turn_id, event)) if stream_turn_id else None,
        )
        reply = str(result.get("output") or "").strip()
        if not reply:
            raise RuntimeError("Neyvia Agent finished without a readable model reply.")
        now = _facade._utc_now()
        tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
            result,
            stdout=stdout,
            now=now,
            elapsed_ms=elapsed_ms,
        )
        return {
            "reply": reply,
            "runtime": "neyvia-agent",
            "status": result.get("status") or "completed",
            "pendingQuestions": result.get("pendingQuestions") or [],
            "goalLoop": result.get("goalLoop"),
            "promptHash": result.get("promptHash") or instruction_hash,
            "sessionId": session_id,
            "externalRuntimeSessionId": str(
                result.get("externalRuntimeSessionId") or ""
            ),
            "route": {
                **route,
                "provider": str(
                    (profile or {}).get("providerId")
                    or route.get("provider")
                    or (result.get("provider") or {}).get("kind")
                    or "responses-compatible"
                ),
                "model": model,
                "model_id": model,
                "transport": str(
                    (result.get("provider") or {}).get("transport") or "auto"
                ),
            },
            "raw": result,
            "elapsedMs": elapsed_ms,
            "runtimeTimeoutSeconds": runtime_timeout_seconds,
            "maxTurns": max_turns,
            "command": self._display_command(display_args),
            "toolTimeline": tool_timeline,
            "filesChanged": files_changed,
            "changeEvidenceAvailable": change_evidence_available,
            "receiptPath": str(result.get("receiptPath") or ""),
        }


    def _run_codex_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        _facade = _backend_facade()
        prompt_root = _facade.Path(str(payload.get("_profileWorkspacePath") or payload.get("workspacePath") or self.root))
        prompt_role = str(payload.get("agentRole") or "chat")
        from .agent_prompt_library import compiled_role_prompt, has_authored_prompt, ROLES
        prompt_role = prompt_role if prompt_role in ROLES else "chat"
        base_instructions = str(payload.get("_systemInstructions") or "")
        if not base_instructions and has_authored_prompt(prompt_root, prompt_role, **_facade._chat_prompt_scope(payload)):
            base_instructions = compiled_role_prompt(prompt_root, prompt_role, **_facade._chat_prompt_scope(payload))
        prompt = _facade._chat_prompt({**payload, "_roleInstructionsInSystem": True}) if base_instructions else _facade._chat_prompt(payload)
        env = self._provider_env()
        command = _facade._resolve_codex_cli()
        if not command:
            raise RuntimeError("Codex CLI was not found on PATH. Install @openai/codex in the packaged runtime.")
        codex_home = _facade._codex_home_path()
        env["CODEX_HOME"] = str(codex_home)
        route = self._chat_route(payload)
        requested_model = str(route.get("model") or "").strip()
        codex_model = (
            _facade.OPENAI_CODEX_DEFAULT_MODEL
            if requested_model.lower() in {"", "codex", "openai-codex"}
            else requested_model
        )
        route = {**route, "model": codex_model}
        runtime_timeout_seconds = _facade._agent_chat_runtime_timeout_seconds(payload, route)
        workspace_path = _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser()
        if not workspace_path.exists():
            workspace_path = self.root
        tmp_dir = self.root / ".agent_control" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with _facade.tempfile.NamedTemporaryFile(prefix="codex-chat-", suffix=".txt", dir=str(tmp_dir), delete=False) as output_file:
            output_path = _facade.Path(output_file.name)
        try:
            args = [
                command,
                "exec",
                "--model",
                codex_model,
                "--config",
                f'model_reasoning_effort="{route["effort"]}"',
                "--skip-git-repo-check",
                "--output-last-message",
                str(output_path),
                "--json",
                "-",
            ]
            if base_instructions:
                canonical_instructions = base_instructions.replace("\r\n", "\n").replace("\r", "\n")
                args[args.index("-", args.index("--json")):] = [
                    "--config", "base_instructions=" + _facade.json.dumps(canonical_instructions),
                    "--config", 'developer_instructions=""',
                    "-",
                ]
            permission_mode = str(payload.get("_permissionMode") or "read-only")
            prompt_index = args.index("-", args.index("--json"))
            if permission_mode == "full-access":
                # This flag intentionally removes Codex's host sandbox and all
                # command approval prompts. It is used only after the operator
                # explicitly selected full access for this chat.
                args.insert(prompt_index, "--dangerously-bypass-approvals-and-sandbox")
            else:
                sandbox_args = ["--sandbox", "workspace-write" if permission_mode == "workspace" else "read-only"]
                args[prompt_index:prompt_index] = sandbox_args
            if payload.get("_onRuntimeEvent"):
                from .neyvia_agent import _codex_neyvia_mcp_args
                parent_conversation = str(payload.get("parentSessionId") or "")
                try:
                    self.neyvia_mcp.conversations.get_conversation(parent_conversation)
                except KeyError:
                    parent_conversation = ""
                args = args[:-1] + _codex_neyvia_mcp_args(
                    workspace_path, read_only=not bool(payload.get("_allowMutation")),
                    session_id=str(payload.get("sessionId") or ""),
                    proof_root=self.root if parent_conversation else None,
                    proof_conversation_id=parent_conversation,
                ) + ["-"]
            broker_binding = _facade._codex_loopback_broker_binding()
            if broker_binding is not None:
                prompt_stdin = args.pop()
                args.extend(
                    [
                        "--config",
                        f'model_providers.neyvia_cliproxy.name={_facade.json.dumps("Neyvia CLIProxy")}',
                        "--config",
                        f'model_providers.neyvia_cliproxy.base_url={_facade.json.dumps(broker_binding["base_url"])}',
                        "--config",
                        f'model_providers.neyvia_cliproxy.env_key={_facade.json.dumps(broker_binding["credential_env"])}',
                        "--config",
                        'model_providers.neyvia_cliproxy.wire_api="responses"',
                        "--config",
                        'model_provider="neyvia_cliproxy"',
                    ]
                )
                args.append(prompt_stdin)
            display_command = self._display_command(args[:-1] + ["<prompt:stdin>"])
            runtime_observation = {}
            def observe_codex(event):
                data = event.get("data") or {}
                if data.get("processId"):
                    runtime_observation["processId"] = data["processId"]
                if data.get("externalRuntimeSessionId"):
                    runtime_observation["externalRuntimeSessionId"] = data["externalRuntimeSessionId"]
                if event.get("kind") == "runtime.error":
                    runtime_observation["error"] = event.get("message")
                if payload.get("_onRuntimeEvent"):
                    payload["_onRuntimeEvent"](event)
            result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
                args,
                cwd=workspace_path,
                timeout=runtime_timeout_seconds,
                extra_env=env,
                stdin_text=prompt,
                on_event=observe_codex,
                event_format="codex",
            )
            if runtime_observation.get("error"):
                raise RuntimeError(str(runtime_observation["error"]))
            reply = ""
            try:
                reply = output_path.read_text(encoding="utf-8").strip()
            except OSError:
                reply = ""
            if not reply:
                reply = _facade._extract_model_reply(result)
            if not reply:
                raise RuntimeError("Codex finished without a readable model reply.")
            now = _facade._utc_now()
            tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
                result,
                stdout=stdout,
                now=now,
                elapsed_ms=elapsed_ms,
            )
            return {
                "reply": reply,
                "runtime": "codex",
                "externalRuntimeSessionId": runtime_observation.get("externalRuntimeSessionId"),
                "processId": runtime_observation.get("processId"),
                "sessionId": _facade._safe_identifier(payload.get("sessionId") or "neyvia_chat"),
                "route": route,
                "raw": result,
                "elapsedMs": elapsed_ms,
                "runtimeTimeoutSeconds": runtime_timeout_seconds,
                "command": display_command,
                "toolTimeline": tool_timeline,
                "filesChanged": files_changed,
                "changeEvidenceAvailable": change_evidence_available,
            }
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass


    def _run_hermes_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        _facade = _backend_facade()
        from .hermes_subscription_route import PROVIDER as subscription_provider, require_subscription_route
        from .agent_prompt_library import compiled_role_prompt, has_authored_prompt, ROLES
        from .hermes_integration import hermes_python
        prompt_root = _facade.Path(str(payload.get("_profileWorkspacePath") or payload.get("workspacePath") or self.root))
        role = str(payload.get("agentRole") or "chat")
        role = role if role in ROLES else "chat"
        instructions = str(payload.get("_systemInstructions") or "")
        if not instructions and has_authored_prompt(prompt_root, role, **_facade._chat_prompt_scope(payload)):
            instructions = compiled_role_prompt(prompt_root, role, **_facade._chat_prompt_scope(payload))
        instructions = instructions.replace("\r\n", "\n").replace("\r", "\n")
        prompt = _facade._chat_prompt({**payload, "_roleInstructionsInSystem": True}) if instructions else _facade._chat_prompt(payload)
        env = self._provider_env()
        command = _facade.shutil.which("hermes", path=env.get("PATH") or _facade.os.environ.get("PATH"))
        route = self._chat_route(payload)
        raw_route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
        routed_model = str(route.get("model") or "").strip()
        explicit_model = str(raw_route.get("model") or payload.get("model") or "").strip()
        hermes_model = routed_model or explicit_model
        explicit_provider = str(raw_route.get("provider") or payload.get("provider") or "").strip()
        hermes_provider = str(route.get("provider") or "").strip()
        if hermes_provider.lower() in _facade.HERMES_RUNTIME_PROVIDER_ALIASES:
            hermes_provider = str(
                _facade.os.environ.get("FLUXIO_HERMES_DEFAULT_PROVIDER") or "openai-codex"
            ).strip() or "openai-codex"
        if hermes_provider == "minimax-portal":
            hermes_provider = "minimax-oauth"
        if hermes_provider == subscription_provider:
            from .hermes_subscription_route import subscription_environment
            env = {**subscription_environment(self.root), **env}
            require_subscription_route(self.root, payload, env)
            from .runtimes.base import runtime_which
            command = runtime_which("hermes", self.root)
        native_args = ["hermes", "chat", "-q", prompt, "-Q"]
        if hermes_model:
            native_args.extend(["--model", hermes_model])
        if (explicit_provider or hermes_provider == subscription_provider) and hermes_provider:
            native_args.extend(["--provider", hermes_provider])
        if str(payload.get("_permissionMode") or "read-only") == "full-access":
            # Hermes otherwise prompts before dangerous shell actions, which
            # cannot be answered by Neyvia's non-interactive process runner.
            native_args.append("--yolo")
        if command:
            args = [command, *native_args[1:]]
            if instructions:
                instruction_hash = _facade.hashlib.sha256(instructions.encode("utf-8")).hexdigest()
                instruction_path = prompt_root / ".agent_control" / "neyvia_agent" / "instructions" / f"{instruction_hash}.txt"
                instruction_path.parent.mkdir(parents=True, exist_ok=True)
                if not instruction_path.exists():
                    instruction_path.write_text(instructions, encoding="utf-8", newline="\n")
                # The managed shim normally selects this home. Direct Python
                # launch must preserve it so plugins/auth use the same profile.
                command_home = _facade.Path(command).resolve().parent.parent
                if not (env.get("HERMES_HOME") or _facade.os.environ.get("HERMES_HOME")) and command_home.name == ".hermes":
                    env = {**env, "HERMES_HOME": str(command_home)}
                args = [str(hermes_python(command, env)),
                        str(_facade.Path(__file__).with_name("hermes_prompt_bridge.py")),
                        str(instruction_path), instruction_hash, *native_args[1:]]
        elif _facade._wsl_has_command("hermes"):
            if instructions:
                raise RuntimeError("Hermes system prompt delivery requires a native Hermes Python runtime; WSL task-context fallback is disabled.")
            wsl_command = f'export PATH="$HOME/.local/bin:$PATH"; {_facade.shlex.join(native_args)}'
            args = [
                _facade.shutil.which("wsl") or "wsl",
                "bash",
                "-lc",
                wsl_command,
            ]
        else:
            raise RuntimeError("Hermes CLI was not found on PATH (native or WSL).")
        display_command = self._display_command(args)
        workspace_path = _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser()
        if not workspace_path.exists():
            workspace_path = self.root
        result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
            args,
            cwd=workspace_path,
            timeout=_facade._agent_chat_runtime_timeout_seconds(payload, route),
            extra_env=env,
        )
        reply = _facade._extract_model_reply(result)
        if not reply:
            raise RuntimeError("Hermes finished without a readable model reply.")
        now = _facade._utc_now()
        tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
            result,
            stdout=stdout,
            now=now,
            elapsed_ms=elapsed_ms,
        )
        result_payload = {
            "reply": reply,
            "runtime": "hermes",
            "promptDelivery": {
                "channel": "system_overlay" if instructions else "runtime_default",
                "replacesBase": False,
                "sha256": _facade.hashlib.sha256(instructions.encode("utf-8")).hexdigest() if instructions else None,
            },
            "sessionId": _facade._safe_identifier(payload.get("sessionId") or "neyvia_chat"),
            "route": {
                **route,
                "provider": hermes_provider or route["provider"],
                "model": hermes_model,
                "model_id": f"{hermes_provider or route['provider']}/{hermes_model}" if hermes_model else hermes_provider or route["provider"],
            },
            "raw": result,
            "elapsedMs": elapsed_ms,
            "command": display_command,
            "toolTimeline": tool_timeline,
            "filesChanged": files_changed,
            "changeEvidenceAvailable": change_evidence_available,
        }
        self._record_runtime_route_proof(payload, result_payload, root=self.root)
        return result_payload


    def _run_opencode_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        _facade = _backend_facade()
        from .agent_prompt_library import compiled_role_prompt, has_authored_prompt, ROLES
        prompt_root = _facade.Path(str(payload.get("_profileWorkspacePath") or payload.get("workspacePath") or self.root))
        role = str(payload.get("agentRole") or "chat")
        role = role if role in ROLES else "chat"
        instructions = str(payload.get("_systemInstructions") or "")
        if not instructions and has_authored_prompt(prompt_root, role, **_facade._chat_prompt_scope(payload)):
            instructions = compiled_role_prompt(prompt_root, role, **_facade._chat_prompt_scope(payload))
        prompt = _facade._chat_prompt({**payload, "_roleInstructionsInSystem": True}) if instructions else _facade._chat_prompt(payload)
        env = self._provider_env()
        command = _facade.shutil.which("opencode", path=env.get("PATH") or _facade.os.environ.get("PATH"))
        if not command:
            raise RuntimeError("OpenCode CLI was not found on PATH.")
        route = self._chat_route(payload)
        raw_route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
        if (
            str(raw_route.get("provider") or "").strip().lower() == "opencode"
            and "model" in raw_route
            and not str(raw_route.get("model") or "").strip()
        ):
            route = {**route, "model": "", "model_id": ""}
        workspace_path = _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser()
        if not workspace_path.exists():
            workspace_path = self.root
        workspace_id = _facade._safe_identifier(payload.get("workspaceId") or workspace_path.name, "workspace")
        session_id = _facade._safe_identifier(payload.get("sessionId") or f"neyvia_chat_{workspace_id}", "neyvia_chat")
        args = [
            _facade.sys.executable,
            "-m",
            "grant_agent.opencode_bridge",
            "--opencode-command",
            command,
            "--mode",
            "mission" if payload.get("_allowMutation") else "chat",
            "--prompt-stdin",
            "--max-steps",
            str(_facade._agent_chat_max_turns(payload)),
        ]
        if instructions:
            instruction_hash = _facade.hashlib.sha256(instructions.encode("utf-8")).hexdigest()
            instruction_path = prompt_root / ".agent_control" / "neyvia_agent" / "instructions" / f"{instruction_hash}.txt"
            instruction_path.parent.mkdir(parents=True, exist_ok=True)
            if not instruction_path.exists():
                instruction_path.write_text(instructions, encoding="utf-8", newline="\n")
            args.extend(["--instructions-file", str(instruction_path)])
        if route.get("model_id"):
            args.extend(["--model", route["model_id"]])
        if session_id:
            args.extend(["--title", session_id[:80]])
        if payload.get("_allowMutation"):
            for directory in payload.get("_authorizedExternalDirectories") or []:
                args.extend(["--external-directory", str(directory)])
            if payload.get("_resumeExternalRuntimeSessionId"):
                args.extend(["--resume-session", str(payload["_resumeExternalRuntimeSessionId"])])
        variant = route.get("effort") or ""
        if str(raw_route.get("effort") or "").lower() == "default":
            variant = ""
            route = {**route, "effort": "default"}
        if variant in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "thinking"}:
            args.extend(["--variant", variant])
        display_command = self._display_command(args)
        result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
            args,
            cwd=workspace_path,
            timeout=_facade._agent_chat_runtime_timeout_seconds(payload, route),
            extra_env=env,
            on_event=payload.get("_onRuntimeEvent"),
            stdin_text=prompt,
        )
        reply = _facade._extract_model_reply(result)
        if not reply:
            reply = _facade._extract_fluxio_event_reply(stdout)
        if not reply:
            raise RuntimeError("OpenCode finished without a readable model reply.")
        now = _facade._utc_now()
        tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
            result,
            stdout=stdout,
            now=now,
            elapsed_ms=elapsed_ms,
        )
        events = _facade._parse_json_objects_from_text(stdout)
        external_session = next((event.get("data", {}).get("externalRuntimeSessionId")
                                 for event in reversed(events)
                                 if event.get("data", {}).get("externalRuntimeSessionId")), None)
        return {
            "reply": reply,
            "runtime": "opencode",
            "sessionId": session_id,
            "externalRuntimeSessionId": external_session,
            "route": route,
            "raw": result,
            "elapsedMs": elapsed_ms,
            "command": display_command,
            "toolTimeline": tool_timeline,
            "filesChanged": files_changed,
            "changeEvidenceAvailable": change_evidence_available,
        }


    def _run_managed_cli_chat(
        self,
        payload: dict[str, Any],
        *,
        runtime_id: str,
    ) -> dict[str, Any]:
        _facade = _backend_facade()
        spec = _facade.MANAGED_CLI_SPECS[runtime_id]
        prompt = ""
        system_prompt_file = ""
        instructions = ""
        profile_id = str(
            payload.get("harnessProfileId") or payload.get("harness_profile_id") or ""
        ).strip()
        profile_workspace = _facade.Path(
            str(payload.get("_profileWorkspacePath") or payload.get("workspacePath") or self.root)
        ).expanduser()
        env = _facade.runtime_subprocess_env(profile_workspace)
        env.update(self._provider_env())
        env.update(_facade.harness_gateway_environment(profile_workspace, runtime_id, profile_id, env))
        command = _facade.shutil.which(
            spec.command_name,
            path=env.get("PATH") or _facade.os.environ.get("PATH"),
        )
        if not command:
            raise RuntimeError(
                f"{spec.label} CLI (`{spec.command_name}`) was not found on PATH."
            )
        raw_route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
        try:
            model = _facade.normalize_managed_cli_model(
                runtime_id,
                str(
                    raw_route.get("model")
                    or payload.get("model")
                    or env.get("FLUXIO_HARNESS_MODEL")
                    or ""
                ),
                allow_custom=bool(profile_id)
                or runtime_id
                in {
                    "grok-build",
                    "prime-agent",
                    "pi",
                    "gptme",
                    "deepseek-harness",
                    "wallbreaker",
                    "rook",
                },
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        effort = str(raw_route.get("effort") or payload.get("effort") or "high").strip().lower()
        role = str(raw_route.get("role") or payload.get("role") or "executor").strip().lower()
        operation_mode = (
            "mission"
            if role == "executor" and bool(payload.get("_allowMutation"))
            else "chat"
        )
        if spec.security_only:
            if role != "executor" or operation_mode != "mission":
                raise RuntimeError(
                    f"{spec.label} can run only as the executor of an orchestration."
                )
            if payload.get("authorizedSecurity") is not True:
                raise RuntimeError(
                    f"{spec.label} requires an explicit authorized-security acknowledgement."
                )
        route = {
            "provider": runtime_id,
            "model": model,
            "model_id": model,
            "effort": effort if effort and effort != "default" else "high",
            "role": role,
            "transport": spec.headless_transport,
            "harnessProfileId": profile_id,
            "authPreference": (
                "authorized-security-profiles"
                if spec.security_only
                else "api-key-or-provider-login"
            ),
            "operationMode": operation_mode,
        }
        if runtime_id == "claude-code":
            from .agent_prompt_library import compiled_role_prompt, has_authored_prompt, ROLES
            prompt_root = profile_workspace
            prompt_role = str(
                payload.get("agentRole")
                or payload.get("_promptRole")
                or raw_route.get("promptRole")
                or "chat"
            ).strip().lower()
            prompt_role = prompt_role if prompt_role in ROLES else "chat"
            prompt_scope = {
                "runtime": runtime_id,
                "provider": str(raw_route.get("provider") or payload.get("provider") or runtime_id),
                "model": model,
            }
            instructions = str(payload.get("_systemInstructions") or "")
            if not instructions and has_authored_prompt(prompt_root, prompt_role, **prompt_scope):
                instructions = compiled_role_prompt(prompt_root, prompt_role, **prompt_scope)
            if instructions:
                prompt_hash = _facade.hashlib.sha256(instructions.encode("utf-8")).hexdigest()
                instruction_path = prompt_root / ".agent_control" / "neyvia_agent" / "instructions" / f"{prompt_hash}.txt"
                instruction_path.parent.mkdir(parents=True, exist_ok=True)
                if not instruction_path.exists():
                    instruction_path.write_text(instructions, encoding="utf-8", newline="\n")
                system_prompt_file = str(instruction_path)
                prompt = _facade._chat_prompt({
                    **payload,
                    "agentRole": prompt_role,
                    "_systemInstructions": instructions,
                    "_roleInstructionsInSystem": True,
                })
        if not prompt:
            prompt = _facade._chat_prompt(payload)
        runtime_timeout_seconds = _facade._agent_chat_runtime_timeout_seconds(payload, route)
        workspace_path = _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser()
        if not workspace_path.exists():
            workspace_path = self.root
        workspace_id = _facade._safe_identifier(
            payload.get("workspaceId") or workspace_path.name,
            "workspace",
        )
        logical_session_id = _facade._safe_identifier(
            payload.get("sessionId") or f"neyvia_chat_{workspace_id}",
            "neyvia_chat",
        )
        external_session_id = str(
            _facade.uuid.uuid5(_facade.uuid.NAMESPACE_URL, f"fluxio:{runtime_id}:chat:{logical_session_id}")
        )
        args = [
            _facade.sys.executable,
            "-m",
            "grant_agent.external_cli_bridge",
            "--runtime",
            runtime_id,
            "--command",
            command,
            "--prompt",
            prompt,
            "--mode",
            operation_mode,
            "--permission-mode",
            str(payload.get("_permissionMode") or "read-only"),
            "--session-id",
            external_session_id,
            "--workspace-root",
            str(workspace_path),
        ]
        if model:
            args.extend(["--model", model])
        if route["effort"]:
            args.extend(["--effort", route["effort"]])
        if profile_id:
            args.extend(["--harness-profile", profile_id])
        if system_prompt_file:
            args.extend(["--system-prompt-file", system_prompt_file])
        display_args = list(args)
        prompt_index = display_args.index("--prompt") + 1
        display_args[prompt_index] = "<prompt>"
        display_command = self._display_command(display_args)
        result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
            args,
            cwd=workspace_path,
            timeout=runtime_timeout_seconds,
            extra_env=env,
        )
        reply = _facade._extract_model_reply(result) or _facade._extract_fluxio_event_reply(stdout)
        if not reply:
            raise RuntimeError(f"{spec.label} finished without a readable model reply.")
        now = _facade._utc_now()
        tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
            result,
            stdout=stdout,
            now=now,
            elapsed_ms=elapsed_ms,
        )
        result_payload = {
            "reply": reply,
            "runtime": runtime_id,
            "sessionId": logical_session_id,
            "externalRuntimeSessionId": external_session_id,
            "route": route,
            "raw": result,
            "elapsedMs": elapsed_ms,
            "runtimeTimeoutSeconds": runtime_timeout_seconds,
            "command": display_command,
            "toolTimeline": tool_timeline,
            "filesChanged": files_changed,
            "changeEvidenceAvailable": change_evidence_available,
        }
        self._record_runtime_route_proof(payload, result_payload, root=self.root)
        return result_payload


    def _run_cursor_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        _facade = _backend_facade()
        prompt = _facade._chat_prompt(payload)
        env = self._provider_env()
        command = (
            _facade.shutil.which("cursor-agent", path=env.get("PATH") or _facade.os.environ.get("PATH"))
            or _facade.shutil.which("cursor", path=env.get("PATH") or _facade.os.environ.get("PATH"))
        )
        if not command:
            raise RuntimeError("Cursor Agent CLI was not found on PATH.")
        route = self._chat_route(payload)
        workspace_path = _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser()
        args = [command, "agent", "--print", "--output-format", "json"]
        if route.get("model"):
            args.extend(["--model", route["model"]])
        if bool(payload.get("_allowMutation")):
            args.append("--force")
        args.append(prompt)
        result, stdout, _stderr, elapsed_ms = _facade._run_process_capture(
            args,
            cwd=workspace_path,
            timeout=_facade._agent_chat_runtime_timeout_seconds(payload, self._chat_route(payload)),
            extra_env=env,
        )
        reply = _facade._extract_model_reply(result) or _facade._extract_fluxio_event_reply(stdout)
        if not reply:
            raise RuntimeError("Cursor Agent finished without a readable model reply.")
        tool_timeline, files_changed, change_evidence_available = _facade._chat_runtime_evidence_from_process(
            result,
            stdout=stdout,
            now=_facade._utc_now(),
            elapsed_ms=elapsed_ms,
        )
        return {
            "reply": reply,
            "runtime": "cursor",
            "sessionId": _facade._safe_identifier(payload.get("sessionId") or "neyvia_chat"),
            "route": {**route, "provider": "cursor"},
            "raw": result,
            "elapsedMs": elapsed_ms,
            "command": self._display_command(args[:-1] + ["<prompt>"]),
            "toolTimeline": tool_timeline,
            "filesChanged": files_changed,
            "changeEvidenceAvailable": change_evidence_available,
        }


    def _image_playground_readiness(self) -> dict[str, Any]:
        _facade = _backend_facade()
        env = self._provider_env()
        has_openai_api_key = bool(
            str(env.get("OPENAI_API_KEY") or "").strip()
            or str(self.provider_secrets.get("openai") or "").strip()
        )
        fluxio_gpt_image_command = str(
            env.get("FLUXIO_GPT_IMAGE2_COMMAND")
            or _facade.os.environ.get("FLUXIO_GPT_IMAGE2_COMMAND")
            or ""
        ).strip()
        codex_auth = _facade._openai_codex_oauth_status(
            session_secrets=self.provider_secrets
        )
        from .neyvia_image_generate import codex_cli_status, list_jobs, sweep_stale_jobs

        codex_cli = codex_cli_status(env)
        sweep_stale_jobs(self.root)
        provider_route_ready = bool(codex_cli.get("ready"))
        return {
            "schema": "fluxio.image_playground_readiness.v1",
            "providerId": _facade.IMAGE_PROVIDER_CODEX_SUBSCRIPTION_ID,
            "model": _facade.IMAGE_PROVIDER_CODEX_EXPECTED_MODEL,
            "legacyCommandModel": "gpt-image-1",
            "hasOpenAiApiKey": has_openai_api_key,
            "hasFluxioGptImageCommand": bool(fluxio_gpt_image_command),
            "providerRouteReady": provider_route_ready,
            "codexSubscriptionReady": bool(codex_cli.get("ready")),
            "codexCli": {k: v for k, v in codex_cli.items() if k != "path"},
            "recentJobs": list_jobs(self.root, 5),
            "authSource": codex_auth.get("source"),
        }


    @staticmethod
    def _agent_chat_persistence_ids(
        payload: dict[str, Any],
    ) -> tuple[str, str, str] | None:
        _facade = _backend_facade()
        raw = (
            str(
                payload.get("conversationId")
                or payload.get("conversation_id")
                or ""
            ).strip(),
            str(
                payload.get("userTurnId")
                or payload.get("user_turn_id")
                or ""
            ).strip(),
            str(
                payload.get("assistantTurnId")
                or payload.get("assistant_turn_id")
                or ""
            ).strip(),
        )
        if not all(raw):
            return None
        normalized = tuple(_facade._safe_identifier(value, "") for value in raw)
        if normalized != raw:
            raise RuntimeError(
                "Conversation and turn IDs must use letters, digits, dot, "
                "underscore, or hyphen and be at most 80 characters."
            )
        return normalized


    def _agent_chat_replay(
        self,
        ids: tuple[str, str, str],
    ) -> dict[str, Any] | None:
        _facade = _backend_facade()
        conversation_id, _, assistant_turn_id = ids
        try:
            turn = self.neyvia_mcp.conversations.get_turn(assistant_turn_id)
        except KeyError:
            return None
        if turn.get("conversationId") != conversation_id:
            raise RuntimeError(
                f"conversation turn id conflict: {assistant_turn_id}"
            )
        metadata = turn.get("metadata")
        runtime_result = (
            metadata.get("runtimeResult")
            if isinstance(metadata, dict)
            else None
        )
        if not isinstance(runtime_result, dict):
            raise RuntimeError(
                "Persisted assistant turn is missing replay metadata"
            )
        replay = _facade.copy.deepcopy(runtime_result)
        replay["conversationPersistence"] = {
            "status": "replayed",
            "conversationId": conversation_id,
            "turnId": assistant_turn_id,
            "storage": "sqlite",
        }
        return replay


    def _begin_agent_chat_persistence(
        self,
        payload: dict[str, Any],
    ) -> tuple[tuple[str, str, str] | None, dict[str, Any] | None]:
        _facade = _backend_facade()
        ids = self._agent_chat_persistence_ids(payload)
        if ids is None:
            return None, None
        key = ids[2]
        with self._agent_chat_persistence_lock:
            while True:
                replay = self._agent_chat_replay(ids)
                if replay is not None:
                    return None, replay
                condition = self._agent_chat_persistence_inflight.get(key)
                if condition is None:
                    condition = _facade.threading.Condition(
                        self._agent_chat_persistence_lock
                    )
                    self._agent_chat_persistence_inflight[key] = condition
                    try:
                        self._ensure_agent_chat_user_turn(payload, ids)
                    except Exception:
                        self._agent_chat_persistence_inflight.pop(
                            key,
                            None,
                        )
                        condition.notify_all()
                        raise
                    return ids, None
                condition.wait(timeout=1.0)


    def _ensure_agent_chat_user_turn(
        self,
        payload: dict[str, Any],
        ids: tuple[str, str, str],
    ) -> None:
        conversation_id, user_turn_id, _ = ids
        message = str(payload.get("message") or "").strip()
        if not message:
            raise RuntimeError("Chat message is required.")
        try:
            self.neyvia_mcp.conversations.get_conversation(conversation_id)
        except KeyError:
            self.neyvia_mcp.conversations.create_conversation(
                workspace_id=str(
                    payload.get("workspaceId")
                    or payload.get("workspace_id")
                    or ""
                ),
                kind="chat",
                title=message,
                metadata={
                    "source": "agent-chat-runtime",
                    "sessionId": str(payload.get("sessionId") or ""),
                    "goalMode": payload.get("goalMode") is True,
                    "workspacePath": str(payload.get("workspacePath") or self.root),
                },
                conversation_id=conversation_id,
                now=str(payload.get("requestStartedAt") or "") or None,
            )
        if isinstance(payload.get("goalMode"), bool):
            existing = self.neyvia_mcp.conversations.get_conversation(conversation_id)
            if (existing.get("metadata") or {}).get("goalMode", False) != payload["goalMode"]:
                self.neyvia_mcp.conversations.set_goal_mode(conversation_id, payload["goalMode"])
        self.neyvia_mcp.conversations.append_turn(
            conversation_id,
            role="user",
            content=message,
            source="operator-submitted",
            metadata={
                "runtime": str(
                    payload.get("runtime")
                    or payload.get("runtimeId")
                    or "codex"
                ),
                "requestStartedAt": str(
                    payload.get("requestStartedAt") or ""
                ),
                "attachments": [
                    {
                        "name": item["name"],
                        "mime": item["mime"],
                        "size": item["size"],
                        "sha256": item["sha256"],
                    }
                    for item in payload.get("_validatedChatAttachments") or []
                ],
            },
            turn_id=user_turn_id,
            idempotent=True,
            now=str(payload.get("requestStartedAt") or "") or None,
        )


    @staticmethod
    def _compact_agent_chat_result(
        result: dict[str, Any],
    ) -> dict[str, Any]:
        _facade = _backend_facade()
        allowed = (
            "reply",
            "runtime",
            "sessionId",
            "externalRuntimeSessionId",
            "route",
            "status",
            "error",
            "elapsedMs",
            "command",
            "toolTimeline",
            "filesChanged",
            "changeEvidenceAvailable",
            "readOnly",
            "compartment",
            "pendingQuestions",
            "promptHash",
            "goalLoop",
        )
        return {
            key: _facade.copy.deepcopy(result[key])
            for key in allowed
            if key in result
        }


    def _persist_agent_chat_result(
        self,
        payload: dict[str, Any],
        ids: tuple[str, str, str],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        conversation_id, _, assistant_turn_id = ids
        reply = str(result.get("reply") or "").strip()
        visible_content = reply or str(
            result.get("error") or "Runtime failed without a readable reply."
        )
        source = (
            "backend-runtime-reply"
            if reply
            else "backend-runtime-error"
        )
        compact = self._compact_agent_chat_result(result)
        if isinstance(compact.get("compartment"), dict):
            # Store the turn's own messages and a reference, not the session window.
            compact["compartment"] = self.neyvia_mcp.conversations.compartment_for_storage(
                conversation_id,
                compact["compartment"],
            )
        self.neyvia_mcp.conversations.append_turn(
            conversation_id,
            role="assistant",
            content=visible_content,
            source=source,
            metadata={
                "runtimeResult": compact,
                "requestStartedAt": str(
                    payload.get("requestStartedAt") or ""
                ),
            },
            turn_id=assistant_turn_id,
            idempotent=True,
        )
        result["conversationPersistence"] = {
            "status": "persisted",
            "conversationId": conversation_id,
            "turnId": assistant_turn_id,
            "storage": "sqlite",
        }
        return result


    def _finish_agent_chat_persistence(
        self,
        ids: tuple[str, str, str],
    ) -> None:
        key = ids[2]
        with self._agent_chat_persistence_lock:
            condition = self._agent_chat_persistence_inflight.pop(key, None)
            if condition is not None:
                condition.notify_all()


    def _resolve_chat_runtime_delegation(
        self,
        payload: dict[str, Any],
        runtime: str,
    ) -> dict[str, Any] | None:
        """Verify a claimed ecosystem override against the durable registry.

        The client states which runtime it believes owns the conversation loop.
        That claim is only echoed back as a receipt when a matching open
        invocation actually exists, so a delegation shown in the UI always
        corresponds to a recorded one.
        """

        claim = payload.get("runtimeDelegation") or payload.get("runtime_delegation")
        if not isinstance(claim, dict):
            return None
        invocation_id = str(claim.get("invocationId") or claim.get("invocation_id") or "").strip()
        responsibility = str(claim.get("responsibility") or "").strip()
        if not invocation_id or not responsibility:
            return None
        try:
            from . import neyvia_runtime_invocation as runtime_invocation

            registry = runtime_invocation.load_registry(self.root)
        except Exception:  # pragma: no cover - depends on local workspace state
            return None
        record = next(
            (
                item
                for item in registry.get("invocations") or []
                if item.get("invocationId") == invocation_id
            ),
            None,
        )
        if record is None or responsibility not in (record.get("delegated") or []):
            return {
                "verified": False,
                "responsibility": responsibility,
                "claimedRuntime": str(claim.get("runtime") or ""),
                "detail": "No open invocation delegates this responsibility. The turn ran on the Neyvia route.",
            }
        return {
            "verified": True,
            "responsibility": responsibility,
            "runtime": record.get("runtime"),
            "mode": record.get("mode"),
            "invocationId": invocation_id,
            "effectiveRuntime": runtime,
            "retained": record.get("retained") or [],
            "detail": (
                f"Neyvia remains the ecosystem; {record.get('runtime')} powered "
                f"{responsibility} for this turn."
            ),
        }


    def _run_agent_chat(
        self,
        payload: dict[str, Any],
        *,
        allow_mutation: bool | None = None,
    ) -> dict[str, Any]:
        # Resolve defaults before looking up saved instructions, so the prompt
        # key is the route that actually executes, including on resumed chats.
        _facade = _backend_facade()
        payload = {**payload, "_promptRoute": self._chat_route(payload)}
        if "goalMode" not in payload:
            conversation_id = str(payload.get("conversationId") or payload.get("sessionId") or "")
            try:
                saved = self.neyvia_mcp.conversations.get_conversation(conversation_id)
                payload["goalMode"] = (saved.get("metadata") or {}).get("goalMode") is True
            except KeyError:
                payload["goalMode"] = False
        mutation_allowed = (
            bool(payload.get("_allowMutation"))
            if allow_mutation is None
            else bool(allow_mutation)
        )
        source_workspace = _facade.Path(
            str(payload.get("workspacePath") or self.root)
        ).expanduser().resolve()
        if not mutation_allowed:
            runtime_id = str(payload.get("runtime") or payload.get("runtimeId") or "").strip().lower()
            route_provider = str((payload.get("route") or {}).get("provider") or "").strip().lower()
            # The Codex app-server enforces read-only access itself. Copying an
            # entire source checkout before every short chat adds seconds to
            # first feedback; keep the mirror for every other runtime/transport.
            codex_read_only = (
                runtime_id in {"neyvia-agent", "neyvia", "own"}
                and route_provider == "openai-codex"
                and not (payload.get("harnessProfileId") or payload.get("harness_profile_id"))
                and not self._provider_env().get("OPENAI_API_KEY")
                and bool(_facade._resolve_codex_cli())
                and source_workspace.is_dir()
            )
            if codex_read_only:
                result = self._run_agent_chat(payload, allow_mutation=True)
                result["readOnly"] = {
                    "enforced": True,
                    "sourceWorkspace": str(source_workspace),
                    "executionWorkspace": str(source_workspace),
                    "mechanism": "codex-app-server-read-only",
                }
                return result
            # The restricted Windows runtime must be able to use the mirror as
            # its process working directory. Keep disposable state under the
            # already-authorized source ACL; .agent_control is excluded from
            # the mirror itself, so this cannot recurse.
            state_root = (
                source_workspace
                if _facade.os.name == "nt"
                else _facade._read_only_chat_state_root(self.root)
            )
            with _facade.isolated_read_only_workspace(
                source_workspace,
                state_root=state_root,
                include_paths=payload.get("readOnlyIncludePaths"),
            ) as mirror:
                isolated_payload = {
                    **payload,
                    "workspacePath": str(mirror),
                    "_profileWorkspacePath": str(source_workspace),
                    "_allowMutation": False,
                }
                result = self._run_agent_chat(
                    isolated_payload,
                    allow_mutation=True,
                )
                result["readOnly"] = {
                    "enforced": True,
                    "sourceWorkspace": str(source_workspace),
                    "executionWorkspace": str(mirror),
                }
                return result
        persistence_ids, replay = self._begin_agent_chat_persistence(
            payload
        )
        if replay is not None:
            return replay
        # All chat harnesses receive the same canonical task decisions. Native
        # renders this in its system instructions; external harnesses receive
        # it through _chat_prompt. Never trust a caller-supplied prompt fragment.
        from .collaboration_prompt import collaboration_instructions
        canonical_id = str(payload.get("parentSessionId") or payload.get("conversationId") or payload.get("sessionId") or "")
        try:
            self.neyvia_mcp.conversations.get_conversation(canonical_id)
        except KeyError:
            canonical_id = ""
        payload = {**payload, "_collaborationInstructions": collaboration_instructions(
            self.root, canonical_id, question_root=_facade.Path(str(payload.get("_profileWorkspacePath") or self.root)),
            session_id=str(payload.get("sessionId") or canonical_id), conversation_id=canonical_id,
            task_query=str(payload.get("message") or ""),
        ) if canonical_id else ""}
        staged_context = ""
        attachment_stage = _facade._staged_chat_attachments(
            _facade.Path(str(payload.get("workspacePath") or self.root)).expanduser().resolve(),
            payload.get("_validatedChatAttachments") if isinstance(payload.get("_validatedChatAttachments"), list) else [],
        )
        try:
            staged_context = attachment_stage.__enter__()
        except Exception:
            if persistence_ids is not None:
                self._finish_agent_chat_persistence(persistence_ids)
            raise
        payload = {**payload, "_chatAttachmentContext": staged_context}
        storage_payload = {
            key: value for key, value in payload.items()
            if key not in {"attachments", "_validatedChatAttachments", "_chatAttachmentContext"}
        }
        runtime = str(payload.get("runtime") or payload.get("runtimeId") or "codex").strip().lower()
        runtime_started = _facade.time.perf_counter()
        runtime_started_at = _facade._utc_now()
        cancellation_exc = None
        try:
            try:
                from .hermes_subscription_route import PROVIDER as subscription_provider
                if self._chat_route(payload).get("provider") == subscription_provider:
                    payload = {**payload, "exactRoute": True, "allowRuntimeFallback": False}
                    if runtime != "hermes":
                        raise RuntimeError("The Claude subscription plugin requires the Hermes runtime. No alternate runtime was started.")
                if runtime == "hermes":
                    result = self._run_hermes_chat(payload)
                elif runtime in {"neyvia-agent", "neyvia", "own"}:
                    result = self._run_neyvia_chat(payload)
                elif runtime in {"openclaw", "openclaw-local"}:
                    result = self._run_openclaw_chat(payload)
                elif runtime in {"opencode", "open-code", "opencode-native", "opencode-go"}:
                    result = self._run_opencode_chat(payload)
                elif runtime in _facade.MANAGED_CLI_SPECS:
                    result = self._run_managed_cli_chat(
                        payload,
                        runtime_id=runtime,
                    )
                elif runtime == "codex":
                    result = self._run_codex_chat(payload)
                elif runtime in {"cursor", "cursor-agent"}:
                    result = self._run_cursor_chat(payload)
                else:
                    raise RuntimeError(
                        f"Unsupported chat runtime: {runtime}"
                    )
            except Exception as exc:
                from .chat_run_control import ChatRunCancelled
                if isinstance(exc, ChatRunCancelled):
                    cancellation_exc = exc
                    route = self._chat_route(payload)
                    process_stopped = bool(getattr(exc, "process_tree_stopped", False))
                    process_reaped = bool(getattr(exc, "process_reaped", False))
                    cancellation_confirmed = process_stopped and process_reaped
                    result = {
                        "reply": "Stopped by you." if cancellation_confirmed else "Stop was requested, but runtime process termination could not be confirmed.",
                        "runtime": runtime or "unknown",
                        "sessionId": _facade._safe_identifier(payload.get("sessionId") or "neyvia_chat"),
                        "route": route,
                        "requestedRoute": {
                            "runtime": runtime or "unknown",
                            "provider": route.get("provider") or "",
                            "model": route.get("model") or route.get("model_id") or "",
                            "effort": route.get("effort") or "",
                        },
                        "status": "cancelled" if cancellation_confirmed else "stop_unconfirmed",
                        "error": str(exc) if cancellation_confirmed else "Stop was requested, but runtime process termination could not be confirmed.",
                        "recovery": {**exc.recovery,
                                     "processTreeStopped": process_stopped,
                                     "processReaped": process_reaped},
                        "processId": getattr(exc, "process_id", None),
                        "startedAt": str(getattr(exc, "started_at", "") or runtime_started_at),
                        "endedAt": str(getattr(exc, "ended_at", "") or _facade._utc_now()),
                        "processStopped": cancellation_confirmed,
                        "elapsedMs": int(getattr(exc, "elapsed_ms", 0) or (_facade.time.perf_counter() - runtime_started) * 1000),
                        "toolTimeline": [{
                            "kind": "runtime.cancelled" if cancellation_confirmed else "runtime.cancel_failed",
                            "at": _facade._utc_now(),
                            "summary": "Stopped by you." if cancellation_confirmed else "Stop was requested, but process termination is unconfirmed.",
                            "status": "cancelled" if cancellation_confirmed else "failed",
                        }],
                        "filesChanged": [],
                    }
                elif not isinstance(exc, RuntimeError):
                    raise
                else:
                    route = self._chat_route(payload)
                    exact_route = bool(
                        payload.get("exactRoute")
                        or str(payload.get("routePolicy") or "").strip().lower() == "exact"
                        or payload.get("allowRuntimeFallback") is not True
                    )
                    codex_status = (
                        _facade._codex_cli_login_status()
                        if not exact_route and runtime != "codex" and route.get("provider") == "openai-codex"
                        else {"authenticated": False}
                    )
                    if codex_status.get("authenticated") and not exact_route:
                        failed_at = _facade._utc_now()
                        fallback = self._run_codex_chat(payload)
                        fallback["requestedRuntime"] = runtime
                        fallback["runtimeFallback"] = {
                            "from": runtime,
                            "to": "codex",
                            "reason": str(exc),
                            "at": failed_at,
                        }
                        fallback["toolTimeline"] = [
                            {
                                "kind": "runtime.fallback",
                                "at": failed_at,
                                "summary": (
                                    f"{runtime or 'requested runtime'} failed; "
                                    "continued through authenticated Codex CLI."
                                ),
                                "status": "completed",
                            },
                            *list(fallback.get("toolTimeline") or []),
                        ]
                        result = fallback
                    else:
                        elapsed_ms = int(
                            getattr(exc, "elapsed_ms", 0)
                            or (_facade.time.perf_counter() - runtime_started) * 1000
                        )
                        result = {
                            "reply": "",
                            "runtime": runtime or "unknown",
                            "sessionId": _facade._safe_identifier(
                                payload.get("sessionId") or "neyvia_chat"
                            ),
                            "route": route,
                            "requestedRoute": {
                                "runtime": runtime or "unknown",
                                "provider": route.get("provider") or "",
                                "model": route.get("model") or route.get("model_id") or "",
                                "effort": route.get("effort") or "",
                            },
                            "exactRoute": exact_route,
                            "status": "failed",
                            "error": str(exc),
                            "elapsedMs": elapsed_ms,
                            "startedAt": str(getattr(exc, "started_at", "") or runtime_started_at),
                            "endedAt": str(getattr(exc, "ended_at", "") or _facade._utc_now()),
                            "processId": getattr(exc, "process_id", None),
                            "command": (
                                "Not launched"
                                if "not found" in str(exc).lower()
                                else "Runtime failed before a readable reply"
                            ),
                            "toolTimeline": [
                                {
                                    "kind": "runtime.error",
                                    "at": _facade._utc_now(),
                                    "summary": str(exc)[:240],
                                    "status": "failed",
                                }
                            ],
                            "filesChanged": [],
                        }
            if not str(result.get("status") or "").strip():
                result["status"] = "completed" if str(result.get("reply") or "").strip() else "failed"
            effective_runtime = str(result.get("runtime") or runtime)
            delegation = self._resolve_chat_runtime_delegation(
                payload,
                effective_runtime,
            )
            if delegation is not None:
                result["runtimeDelegation"] = delegation
            from .neyvia_ecosystem import infer_task_prompt_profile
            requested_profile = str(
                payload.get("systemPromptProfile")
                or payload.get("system_prompt_profile")
                or payload.get("taskProfile")
                or ""
            ).strip().lower()
            result["promptProfile"] = infer_task_prompt_profile(
                str(payload.get("message") or ""),
                requested_profile=requested_profile if requested_profile and requested_profile != "auto" else None,
            )
            result = _facade._redact_chat_attachment_paths(result, staged_context)
            result["compartment"] = self._save_chat_compartment(
                storage_payload,
                result,
            )
            if persistence_ids is not None:
                result = self._persist_agent_chat_result(
                    storage_payload,
                    persistence_ids,
                    result,
                )
            if cancellation_exc is not None:
                cancellation_exc.cancelled_result = result
                raise cancellation_exc
            return result
        finally:
            attachment_stage.__exit__(None, None, None)
            if persistence_ids is not None:
                self._finish_agent_chat_persistence(persistence_ids)


    def _persist_runtime_handback(
        self,
        invocation: dict[str, Any],
    ) -> dict[str, Any]:
        """Carry a runtime return into the durable parent conversation."""
        _facade = _backend_facade()

        from . import runtime_handback

        parent_session_id = str(invocation.get("parentSessionId") or "").strip()
        if not parent_session_id:
            return {
                "schema": "neyvia.runtime.handback/1",
                "invocationId": invocation.get("invocationId"),
                "runtime": invocation.get("runtime") or "unknown",
                "persistence": {
                    "status": "deferred",
                    "reason": "The invocation has no parent conversation.",
                },
            }

        try:
            parent = self.neyvia_mcp.conversations.get_conversation(
                parent_session_id,
                include_turns=True,
            )
        except KeyError:
            return {
                "schema": "neyvia.runtime.handback/1",
                "invocationId": invocation.get("invocationId"),
                "runtime": invocation.get("runtime") or "unknown",
                "parentSessionId": parent_session_id,
                "persistence": {
                    "status": "deferred",
                    "reason": "The parent conversation is not available yet.",
                },
            }

        already_carried: set[str] = set()
        for turn in parent.get("turns") or []:
            metadata = turn.get("metadata") if isinstance(turn, dict) else None
            if not isinstance(metadata, dict):
                continue
            digest = str(metadata.get("handbackDigest") or "").strip()
            if digest:
                already_carried.add(digest)
            already_carried.update(
                str(item).strip()
                for item in metadata.get("handbackDigests") or []
                if str(item).strip()
            )

        handback = runtime_handback.build_handback(
            invocation,
            already_carried=already_carried,
        )
        if handback["carriedCount"] == 0:
            return {
                **handback,
                "persistence": {
                    "status": "empty" if handback["empty"] else "already-carried",
                    "conversationId": parent_session_id,
                    "turnCount": 0,
                },
            }

        carried = handback["carried"]
        changed_files = [row["item"] for row in carried.get("changes") or []]
        proof_artifacts = [row["item"] for row in carried.get("artifacts") or []]
        receipts = [row["item"] for row in carried.get("receipts") or []]
        new_digests = [
            row["digest"]
            for kind in runtime_handback.CARRIED_KINDS
            for row in carried.get(kind) or []
        ]
        transcript_rows = runtime_handback.handback_messages(handback)
        if not transcript_rows:
            transcript_rows = [
                {
                    "role": "assistant",
                    "author": handback["runtime"],
                    "content": handback["summary"],
                    "source": "runtime-handback",
                    "origin": {
                        "runtime": handback["runtime"],
                        "invocationId": handback["invocationId"],
                        "kind": "summary",
                    },
                    "digest": new_digests[0],
                }
            ]

        inserted: list[str] = []
        for index, row in enumerate(transcript_rows):
            is_last = index == len(transcript_rows) - 1
            turn_receipt = None
            if is_last and (changed_files or proof_artifacts or receipts):
                latest_receipt = receipts[-1] if receipts and isinstance(receipts[-1], dict) else {}
                turn_receipt = {
                    **latest_receipt,
                    "status": latest_receipt.get("status") or invocation.get("state") or "returned",
                    "runtime": invocation.get("runtime"),
                    "model": invocation.get("model"),
                    "changedFiles": changed_files,
                    "proofArtifacts": proof_artifacts,
                }
            digest = str(row.get("digest") or new_digests[0])
            turn_id = _facade._safe_identifier(
                f"handback_{invocation.get('invocationId')}_{digest}",
                "handback",
            )
            self.neyvia_mcp.conversations.append_turn(
                parent_session_id,
                role=str(row.get("role") or "assistant"),
                content=str(row.get("content") or handback["summary"]),
                detail=handback["summary"] if is_last else "",
                source="runtime-handback",
                turn_kind="runtime-handback",
                metadata={
                    "author": row.get("author") or handback["runtime"],
                    "runtime": handback["runtime"],
                    "invocationId": handback["invocationId"],
                    "origin": row.get("origin") or {},
                    "handbackDigest": digest,
                    "handbackDigests": new_digests if is_last else [digest],
                    "turnReceipt": turn_receipt,
                    "chips": ["Runtime hand-back"],
                },
                turn_id=turn_id,
                idempotent=True,
            )
            inserted.append(turn_id)

        return {
            **handback,
            "persistence": {
                "status": "persisted",
                "conversationId": parent_session_id,
                "turnCount": len(inserted),
                "turnIds": inserted,
            },
        }
