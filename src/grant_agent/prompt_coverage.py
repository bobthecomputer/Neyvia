"""Lossless, script-only prompt checklist and independently checked coverage.

Offsets are Python/Unicode character offsets into the unchanged original. Unknown
clauses are retained, not silently classified as noise. This is a conservative
reading aid, never an authority or an executable plan.
"""
from __future__ import annotations

import re

from .paul_manual import profile
from .prompt_references import resolve_references

BOUNDARY = re.compile(r"[.!?]+(?=\s|$)|\n+")
ACTION = (r"(?:please\s+)?(?:can you|could you|you (?:should|must|need)|I (?:want|need)|"
          r"make|build|fix|check|test|verify|explain|tell|show|give|read|inspect|research|"
          r"remove|delete|keep|preserve|use|run|add|improve|redesign|continue|do|don't|never|"
          r"commit|push|merge|send|publish|deploy|wait|plan|launch|spawn)\b")
CLAUSE = re.compile(r"(?:;\s*|,\s*(?=(?:and\s+|also\s+)?" + ACTION + r")|"
                    r"\s+(?:and|also|plus)\s+(?=" + ACTION + r")|"
                    r"\s+(?=I\s+(?:still|also)\s+(?:don't|don’t|do not|want|need|have)\b)|"
                    r",\s*(?=(?:one|another)\s+to\s+(?:attach|compact|add|open|save)\b)|"
                    r"\s+and\s+(?=(?:a|another)\s+(?:\+\s+)?button\b))", re.I)
CHATTER = re.compile(r"[\s.,!?]*(?:(?:uh|um|ah|oh|yeah|yes|ok|okay|well|please|"
                     r"thank you|thanks|merci|bonjour|hello|hi|sorry)[\s.,!?]*)+", re.I)
REFERENCE = re.compile(r"\b(?:that|those|it|the (?:thing|stuff|app)(?: from before)?)\b", re.I)
RISK = re.compile(r"\b(?:delete|remove|publish|deploy|send|push|merge|overwrite|purchase|buy)\b", re.I)
NEGATIVE = re.compile(r"\b(?:never|don't|do not|must not|not allowed|only|at most|without|"
                      r"plan only|wait|later|pause|hold|permission|approval)\b", re.I)
CORRECTION = re.compile(r"\b(?:instead|actually|forget what I said|scratch that|"
                        r"not .{1,40} but|I meant|I said|just make a plan)\b", re.I)


def _trim(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def sentences(text):
    """Return every nonblank sentence, including trailing unpunctuated text."""
    rows, start = [], 0
    for match in BOUNDARY.finditer(text):
        end = match.end()
        # Decimal values, paths and abbreviations within tokens are not breaks.
        left, right = _trim(text, start, end)
        if left < right:
            rows.append([left, right])
        start = end
    left, right = _trim(text, start, len(text))
    if left < right:
        rows.append([left, right])
    return rows


def _clauses(text, span):
    start, end = span
    result, cursor = [], start
    for match in CLAUSE.finditer(text, start, end):
        # Include conjunctions/separators in a span so no punctuation disappears.
        left, right = _trim(text, cursor, match.start())
        if left < right:
            result.append([left, right])
        cursor = match.start()
    left, right = _trim(text, cursor, end)
    if left < right:
        result.append([left, right])
    return result


def _reading(quote, rules):
    """Apply only explicit name aliases; preserve code, paths and numbers."""
    hints, reading = [], quote
    def replace(alias, canonical, rule):
        nonlocal reading
        pattern = re.compile(r'(?<![\w/\\`.-])' + re.escape(alias) + r'(?![\w/\\`-]|\.\w)', re.I)
        if pattern.search(reading):
            hints.append({'heard': alias, 'reading': canonical, 'rule': rule})
            reading = pattern.sub(lambda _: canonical, reading)
    for row in rules:
        rule = row['rule']
        if row['category'] != 'vocab' or row['p'] < .85:
            continue
        if rule.startswith('Any odd word ending in VIA'):
            # Explicit aliases only; no arbitrary word/name similarity guessing.
            for alias in rule.partition('(')[2].partition(')')[0].split(','):
                if not alias.strip().startswith('any '):
                    replace(alias.strip(), 'Neyvia', rule)
        if rule.startswith('Letters spelled with hyphens'):
            for alias in re.findall(r'\b[A-Z](?:-[A-Z]){2,}\b', rule):
                replace(alias, alias.replace('-', ''), rule)
        if rule.startswith('team next to light/dark') and re.search(r'\b(?:light|dark|colours|colors|appearance)\b', quote, re.I):
            replace('team', 'theme', rule)
        if ' = ' not in rule:
            continue
        for part in rule.split(';'):
            if ' = ' not in part:
                continue
            aliases, target = part.split(' = ', 1)
            # Contextual/ordinary-word mappings require judgement, not substitution.
            if '(' in aliases or '(' not in target or target.strip().startswith('his '):
                continue
            canonical = target.split(' (', 1)[0].strip()
            for alias in aliases.split(','):
                alias = alias.strip()
                if not alias or alias.lower() == canonical.lower():
                    continue
                replace(alias, canonical, rule)
    return reading, hints


def _kind(text):
    if re.search(r'\b(?:plan|later|wait|pause|hold)\b', text, re.I):
        return 'plan'
    if re.search(r'\b(?:explain|tell|show|what|why|how|status)\b|\?', text, re.I):
        return 'explain'
    for kind, pattern in [('check', r'check|test|verify|inspect|review|research'),
                          ('fix', r'fix|repair|broken|ugly|redesign|improve'),
                          ('remove', r'remove|delete'), ('build', r'build|make|add|implement')]:
        if re.search(r'\b(?:' + pattern + r')\b', text, re.I):
            return kind
    return 'explain'


def compile_checklist(text, context):
    items, dropped, constraints, questions, references = [], [], [], [], []
    rules = profile()['rules']
    carry_negation = False
    for sentence_id, span in enumerate(sentences(text), 1):
        sentence = text[slice(*span)]
        if NEGATIVE.search(sentence):
            constraints.append(sentence)
        carry_here = carry_negation and bool(re.match(
            r'(?i)(?:please\s+)?(?:put|add|make|write|send|publish|remove|delete|use|run|open|show)\b',
            sentence))
        carry_negation = bool(re.search(r'(?i)\b(?:to\s+)?(?:do\s+)?not\s*[.!?]*$', sentence))
        for clause in _clauses(text, span):
            quote = text[slice(*clause)]
            if CHATTER.fullmatch(quote):
                dropped.append({'span': clause, 'quote': quote, 'why': 'non_actionable_chatter: greeting or filler'})
                continue
            reading, hints = _reading(quote, rules)
            if carry_here:
                hints.append({'heard': quote,
                              'reading': 'Possible dictation continuation: the preceding trailing "not" may negate this clause.',
                              'rule': 'uncertain negation; does not cancel any explicit ask'})
            number = len(items) + 1
            refs = resolve_references(text, clause, context)
            references.extend({'item': number, **ref} for ref in refs)
            # A single contextual candidate still is not an exact destructive
            # target. Candidate count must never invent authorization/certainty.
            risky = bool(RISK.search(quote) and refs
                         and not re.search(r'\b(?:never|do not|don\x27t|must not)\b', quote, re.I))
            if risky:
                questions.append(f'Which exact target does item {number} refer to?')
            items.append({'number': number, 'span': clause, 'sentence': sentence_id,
                          'ask': reading, 'quote': quote, 'kind': _kind(reading),
                          'doneWhen': f'Inspect evidence for item {number} in its stated scope; preserve its limits and later corrections.',
                          'status': 'pending', 'needsPaul': risky, 'readingHints': hints,
                          'actionability': 'explicit' if re.search(ACTION, quote, re.I) else 'retained_context',
                          'correction': bool(CORRECTION.search(quote))})
    checklist = {'items': items, 'dropped': dropped, 'questions': questions}
    coverage = check_coverage(text, checklist)
    return checklist, coverage, constraints, references


def check_coverage(text, checklist):
    """Recompute coverage from source, never trust a saved coverage boolean."""
    errors, spans, mappings = [], [], []
    allowed = {tuple(span) for sentence in sentences(text) for span in _clauses(text, sentence)}
    for bucket in ('items', 'dropped'):
        for index, row in enumerate(checklist.get(bucket, []), 1):
            span = row.get('span')
            if (not isinstance(span, list) or len(span) != 2 or any(type(v) is not int for v in span)
                    or not 0 <= span[0] < span[1] <= len(text) or text[slice(*span)] != row.get('quote')):
                errors.append(f'{bucket}:{index}:invalid_exact_span')
                continue
            if tuple(span) not in allowed:
                errors.append(f'{bucket}:{index}:merged_or_partial_clause')
                continue
            if bucket == 'items' and row.get('number') != index:
                errors.append(f'items:{index}:invalid_number')
            if bucket == 'items' and row.get('ask') != _reading(row['quote'], profile()['rules'])[0]:
                errors.append(f'items:{index}:rewritten_ask')
            if bucket == 'dropped' and (not CHATTER.fullmatch(row['quote']) or
                    not row.get('why', '').startswith('non_actionable_chatter:')):
                errors.append(f'dropped:{index}:unproven_chatter')
                continue
            spans.append((span[0], span[1], bucket, index))
    for number, (start, end) in enumerate(sentences(text), 1):
        linked = [row for row in spans if row[0] < end and row[1] > start]
        cursor = start
        for left, right, _, _ in sorted(linked):
            if text[cursor:max(cursor, left)].strip():
                errors.append(f'sentence:{number}:uncovered_span:{cursor}:{left}')
            cursor = max(cursor, right)
        if text[cursor:end].strip():
            errors.append(f'sentence:{number}:uncovered_span:{cursor}:{end}')
        mappings.append({'sentence': number, 'span': [start, end],
                         'items': [i for _, _, bucket, i in linked if bucket == 'items'],
                         'chatter': [i for _, _, bucket, i in linked if bucket == 'dropped']})
    return {'schema': 'neyvia.prompt-coverage.v1', 'ok': not errors,
            'offsetUnit': 'unicode_code_points', 'sentences': mappings, 'errors': errors}
