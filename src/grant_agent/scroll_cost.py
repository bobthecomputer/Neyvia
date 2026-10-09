"""Observed generation usage, with explicitly supplied USD-per-million prices only."""
from __future__ import annotations


def derive_stats(rows, cards, review=None, prices=None):
    """prices[model] = {input, output, cached} in USD per million tokens.

    inTokens includes cached input tokens (provider usage convention). Missing
    provider usage or prices yields null dollar totals, never an estimated zero.
    """
    prices = prices or {}
    tiers = {key: {'input': 0, 'output': 0, 'cached': 0, 'tokens': 0, 'calls': 0, 'usd': 0.0, 'unknownCalls': 0} for key in ('script', 'memory', 'cache', 'small', 'big')}
    stages, unknown = {}, set()
    for row in rows:
        tier = row.get('tier', 'script')
        if tier not in tiers:
            continue
        bucket = tiers[tier]
        # Script/memory/cache hits have zero usage, but real provider calls must
        # explicitly report their usage including an observed zero.
        usage_missing = tier in {'small', 'big'} and (row.get('usageKnown') is False or any(row.get(key) is None for key in ('inTokens', 'outTokens', 'cachedTokens')))
        incoming = max(0, int(row.get('inTokens') or 0))
        outgoing = max(0, int(row.get('outTokens') or 0))
        cached = min(incoming, max(0, int(row.get('cachedTokens') or 0)))
        bucket['input'] += incoming
        bucket['output'] += outgoing
        bucket['cached'] += cached
        bucket['tokens'] += incoming + outgoing
        bucket['calls'] += 1
        stage = stages.setdefault(row.get('stage', 'unknown'), {'calls': 0, 'escalations': 0})
        stage['calls'] += 1
        stage['escalations'] += bool(row.get('escalatedFrom'))
        price = prices.get(row.get('model'))
        requires_price = tier in {'small', 'big'} or incoming + outgoing > 0
        if usage_missing or (requires_price and (not isinstance(price, dict) or any(price.get(key) is None for key in ('input', 'output', 'cached')))):
            bucket['unknownCalls'] += 1
            unknown.add(row.get('model') or 'unspecified-model')
        elif requires_price:
            bucket['usd'] += ((incoming - cached) * price['input'] + outgoing * price['output'] + cached * price['cached']) / 1_000_000
    for bucket in tiers.values():
        if bucket['unknownCalls']:
            bucket['usd'] = None
    count = len(cards)
    seconds = sum(float(card.get('seconds', 0)) for card in cards)
    total_tokens = sum(bucket['tokens'] for bucket in tiers.values())
    total_usd = None if unknown else sum(bucket['usd'] for bucket in tiers.values())
    measured_ms = sum(float(row.get('ms') or 0) for row in rows)
    per_card = {'tokens': total_tokens / count if count else None, 'usd': total_usd / count if count and total_usd is not None else None,
                'ms': measured_ms / count if count else None}
    hour_scale = 3600 / seconds if seconds > 0 else None
    if isinstance(review, dict) and 'decisions' not in review:
        decisions = [{'cardId': cid, 'action': {'approved': 'approve', 'dropped': 'drop'}.get(value.get('status'), value.get('status')), 'edited': value.get('edited', False)} for cid, value in review.items() if isinstance(value, dict)]
    else:
        decisions = (review or {}).get('decisions', []) if isinstance(review, dict) else (review or [])
    # Latest decision per card avoids repeated approvals inflating the rate.
    latest = {decision['cardId']: decision for decision in decisions if isinstance(decision, dict) and decision.get('cardId')}
    approved = sum(decision.get('action') == 'approve' for decision in latest.values())
    edited = {decision.get('cardId') for decision in decisions if isinstance(decision, dict) and (decision.get('action') == 'edit' or decision.get('edited'))}
    unchanged = sum(decision.get('action') == 'approve' and cid not in edited for cid, decision in latest.items())
    return {
        'cards': count, 'studySeconds': seconds, 'tiers': tiers,
        'measuredMs': measured_ms,
        'tokens': {**{tier: value['tokens'] for tier, value in tiers.items()}, 'cached': sum(value['cached'] for value in tiers.values())},
        'calls': {tier: value['calls'] for tier, value in tiers.items()},
        'totalUsd': total_usd, 'unknownPriceOrUsageModels': sorted(unknown),
        'costPerCard': per_card, 'perCard': per_card,
        'costPerStudyHour': {'tokens': total_tokens * hour_scale if hour_scale else None, 'usd': total_usd * hour_scale if hour_scale and total_usd is not None else None, 'newCards': count * hour_scale if hour_scale else None, 'reviewCost': 0, 'basis': '3600 / sum(new-card seconds); reviews cost zero'},
        'perStudyHour': total_usd * hour_scale if hour_scale and total_usd is not None else None,
        'escalationRate': {stage: value['escalations'] / value['calls'] for stage, value in stages.items()},
        'approveWithoutEditRate': unchanged / len(latest) if latest else None,
        'reviewedCards': len(latest), 'approvedCards': approved,
        'smallCallsPerCard': tiers['small']['calls'] / count if count else None,
        'bigCallsPerCard': tiers['big']['calls'] / count if count else None,
    }
