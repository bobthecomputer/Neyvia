from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ContextEvent:
    role: str
    content: str
    tokens: int


@dataclass
class ContextWindowManager:
    max_tokens: int
    warn_threshold: float = 0.70
    rollover_threshold: float = 0.85
    hard_stop_threshold: float = 0.95
    events: list[ContextEvent] = field(default_factory=list)
    used_tokens: int = 0

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    @property
    def usage_ratio(self) -> float:
        if self.max_tokens <= 0:
            return 1.0
        return self.used_tokens / self.max_tokens

    def status(self) -> str:
        ratio = self.usage_ratio
        if ratio >= self.hard_stop_threshold:
            result = "hard_stop"
        elif ratio >= self.rollover_threshold:
            result = "rollover"
        elif ratio >= self.warn_threshold:
            result = "warn"
        else:
            result = "ok"
        from .proofs_a_control import check_context_status
        check_context_status(self, result)
        return result

    def record(self, role: str, content: str) -> str:
        tokens = self.estimate_tokens(content)
        self.events.append(ContextEvent(role=role, content=content, tokens=tokens))
        self.used_tokens += tokens
        return self.status()

    def compact_window(self) -> list[dict[str, str]]:
        user_messages = [e for e in self.events if e.role == "user"]
        non_user = [e for e in self.events if e.role != "user"]

        compacted: list[dict[str, str]] = []
        for event in user_messages:
            compacted.append({"role": event.role, "content": event.content})

        if non_user:
            token_total = sum(e.tokens for e in non_user)
            compacted.append(
                {
                    "role": "system",
                    "content": (
                        "[compacted_context] Preserved latent state for assistant/tool activity. "
                        f"events={len(non_user)}, tokens={token_total}."
                    ),
                }
            )
        from .proofs_a_control import check_context_compaction
        check_context_compaction(self.events, compacted)
        return compacted

    def reset_with_seed(self, seed_items: list[dict[str, str]]) -> None:
        self.events = []
        self.used_tokens = 0
        for item in seed_items:
            self.record(item["role"], item["content"])
