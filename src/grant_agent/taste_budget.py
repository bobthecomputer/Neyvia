"""Admission reservations and measured accounting for a finite taste run.

Codex CLI reports usage after a turn; a reservation is not a provider token cap.
Any overrun or unknown usage closes admission, retaining the real spend evidence.
"""
from __future__ import annotations

import math


class BudgetExceeded(RuntimeError):
    pass


class TasteBudget:
    def __init__(self, *, max_rounds=4, max_tokens=100000, max_usd=0.45,
                 max_call_tokens=24000, max_call_usd=0.25):
        values = (max_rounds, max_tokens, max_usd, max_call_tokens, max_call_usd)
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError('Budgets must be finite positive numbers')
        self.limits = dict(maxRounds=int(max_rounds), maxTokens=int(max_tokens),
                           maxUsd=max_usd, maxCallTokens=int(max_call_tokens), maxCallUsd=max_call_usd)
        self.rounds = 0
        self.calls = []
        self.calibration = []  # prior receipts inform estimates, never current spend
        self.pending = None
        self.closed_reason = None
        self.capacity_rejections = 0
        self.retry_model = None
        self.protected_usd = 0

    def start_round(self):
        self._open()
        if self.rounds >= self.limits['maxRounds']:
            raise BudgetExceeded('Hard round budget exhausted')
        self.rounds += 1
        return self.rounds

    def _open(self):
        if self.closed_reason:
            raise BudgetExceeded(self.closed_reason)

    def admit(self, *, model, tokens, usd):
        self._open()
        if self.pending:
            raise BudgetExceeded('A call reservation is already pending')
        if self.retry_model is not None and model != self.retry_model:
            raise BudgetExceeded('Capacity retry must use the same explicit model')
        if not isinstance(tokens, int) or tokens <= 0 or not isinstance(usd, (int, float)) or not math.isfinite(usd) or usd <= 0:
            raise ValueError('A positive token and dollar reservation is required')
        totals = self.snapshot()
        if tokens > self.limits['maxCallTokens'] or usd > self.limits['maxCallUsd']:
            raise BudgetExceeded('Per-call reservation exceeds admission limit')
        if totals['totalTokens'] + tokens > self.limits['maxTokens'] or totals['costUsd'] + usd > self.limits['maxUsd'] - self.protected_usd:
            raise BudgetExceeded('Run budget cannot admit the next call reservation')
        self.pending = dict(model=model, reservedTokens=tokens, reservedUsd=usd)
        return dict(self.pending)

    def account(self, receipt):
        if not self.pending:
            raise RuntimeError('Measured call has no admission reservation')
        row = {**self.pending, **receipt}
        self.pending = None
        self.calls.append(row)
        if receipt.get('rejectedBeforeInference'):
            self.capacity_rejections += 1
            self.retry_model = row['model']
            if self.capacity_rejections > 1:
                self.closed_reason = 'Same-model capacity retry exhausted; future calls blocked'
        elif receipt.get('usageComplete'):
            self.retry_model = None
        if not receipt.get('usageComplete'):
            self.closed_reason = 'Missing or invalid provider token usage; future calls blocked'
        else:
            if row['usage']['total_tokens'] > row['reservedTokens'] or row['costUsd'] > row['reservedUsd']:
                self.closed_reason = 'Measured call exceeded its reservation; future calls blocked'
            totals = self.snapshot()
            if totals['totalTokens'] >= self.limits['maxTokens'] or totals['costUsd'] >= self.limits['maxUsd']:
                self.closed_reason = 'Measured run budget exhausted; future calls blocked'
        return self.snapshot()

    def snapshot(self):
        return {'limits': dict(self.limits), 'rounds': self.rounds, 'calls': len(self.calls),
                'totalTokens': sum(c.get('usage', {}).get('total_tokens', 0) for c in self.calls),
                'inputTokens': sum(c.get('usage', {}).get('input_tokens', 0) for c in self.calls),
                'cachedInputTokens': sum(c.get('usage', {}).get('cached_input_tokens', 0) for c in self.calls),
                'outputTokens': sum(c.get('usage', {}).get('output_tokens', 0) for c in self.calls),
                'costUsd': sum(c.get('costUsd', 0) or 0 for c in self.calls),
                'closedReason': self.closed_reason, 'pending': self.pending,
                'capacityRejections':self.capacity_rejections, 'retryModel':self.retry_model,
                'usageComplete': all(c.get('usageComplete', False) for c in self.calls),
                'enforcement': 'hard pre-call/round admission; post-turn usage with fail-closed overshoot; no provider hard token cap'}
