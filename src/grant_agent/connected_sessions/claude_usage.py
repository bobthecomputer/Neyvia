"""Incremental per-turn Claude token spend, using the Usage pane's transcript interpretation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..usage_report import claude_usage_entry
from .claude_transcript import LineFollower


class ClaudeTranscriptUsage:
    def __init__(self, began_at: datetime, ended_at: datetime | None = None):
        self.began_at = began_at
        self.ended_at = ended_at
        self.followers = {}
        self.messages = {}
        self.last = None

    def poll(self, path: Path):
        # Usage includes child agent transcripts as well as the owning session.
        for source in [path, *sorted((path.with_suffix("") / "subagents").glob("*.jsonl"))]:
            follower = self.followers.setdefault(source, LineFollower(source))
            for offset, record in follower.poll():
                parsed = claude_usage_entry(record, fallback_id=f"{source}:{offset}", timestamps=True)
                if not parsed:
                    continue
                identity, row = parsed
                try:
                    stamp = datetime.fromisoformat(row[7].replace("Z", "+00:00"))
                except ValueError:
                    continue
                stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
                if stamp >= self.began_at and (self.ended_at is None or stamp <= self.ended_at):
                    # Stream fragments and copied records count once by provider message id.
                    self.messages[identity] = row
        if not self.messages:
            return None  # Missing measurements must stay unknown.
        rows = self.messages.values()
        inp = sum(row[2] for row in rows)
        out = sum(row[4] for row in rows)
        usage = {"inputTokens": inp, "outputTokens": out, "cachedInputTokens": sum(row[3] for row in rows),
                 "cacheCreationInputTokens": sum(row[5] + row[6] for row in rows), "totalTokens": inp + out,
                 "reportedByTransport": True, "coverage": "reported", "source": "claude-transcript",
                 "requests": len(self.messages)}
        if usage == self.last:
            return None
        self.last = usage
        return usage
