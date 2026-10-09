"""Keep authored instructions intact across SDK tool rounds and session replay."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from .context_window import bounded_history
from .chat_context import normalize_replay_context


class PromptContractError(RuntimeError):
    """A safe, content-free diagnostic for a blocked model request."""


class PromptContract:
    def __init__(self, transform=None):
        self.transform = transform
        self._agents = {}
        self.calls = 0
        self.rejected = 0
        self.omitted_history_records = 0
        self.compactor = None
        self.compaction_agent = None
        self.memory_provider = None
        self.memory_generation = None
        self.memory_tokens = 0

    def register(self, agent):
        if not isinstance(agent.instructions, str) or not agent.instructions.strip():
            raise ValueError("Native prompt contracts require frozen, non-empty instructions")
        self._agents[id(agent)] = (agent, agent.instructions)

    def __call__(self, data):
        registered = self._agents.get(id(data.agent))
        expected = registered[1] if registered else None
        model_data = self.transform(data) if self.transform else data.model_data
        if expected is None or model_data.instructions != expected:
            self.rejected += 1
            raise PromptContractError("Native system prompt contract changed before model call; request blocked")
        if any(isinstance(item, dict) and item.get("role") in {"system", "developer"}
               for item in model_data.input):
            self.rejected += 1
            raise PromptContractError("Native session history contains competing system/developer instructions; request blocked")
        self.calls += 1
        if self.memory_provider is not None:
            packet = self.memory_provider()
            generation = packet.get('generation')
            if self.memory_generation is not None and generation != self.memory_generation:
                self.rejected += 1
                raise PromptContractError('Memory changed during this run; start a fresh chat before another model request')
            self.memory_generation = generation
            self.memory_tokens += packet.get('tokens', 0)
            if packet.get('section'):
                # Ephemeral request input: the SDK durable session is untouched.
                model_data = replace(model_data, input=[{'role': 'user', 'content': packet['section']}, *model_data.input])
        if self.compactor is not None and id(data.agent) == self.compaction_agent:
            return self._compact(model_data)
        bounded, omitted = bounded_history(model_data.input)
        self.omitted_history_records = max(self.omitted_history_records, omitted)
        return replace(model_data, input=normalize_replay_context(bounded))

    async def _compact(self, model_data):
        compacted = await self.compactor.compact(model_data.input)
        return replace(model_data, input=normalize_replay_context(compacted))

    def receipt(self):
        return {
            "mode": "exact_instructions_each_call",
            "boundary": "sdk_model_input",
            "validatedCalls": self.calls,
            "rejectedCalls": self.rejected,
            "omittedHistoryRecords": self.omitted_history_records,
            "durableHistoryPreserved": True,
            "compaction": dict(self.compactor.stats) if self.compactor else {"status": "not_configured"},
            "instructionHashes": sorted({hashlib.sha256(text.encode("utf-8")).hexdigest()
                                         for _, text in self._agents.values()}),
            "remoteProviderInstructionsObservable": False,
            "memoryTokens": self.memory_tokens,
        }
