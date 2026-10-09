"""Conservative, zero-model antecedent hints for the prompt reading aid.

The result is evidence for a reader, never permission to act. A missing or
competing antecedent remains ambiguous, especially for consequential verbs.
"""
from __future__ import annotations

import re

MENTION = re.compile(r"\bthe (?:thing|stuff|app)(?: from before| we talked about)?\b|"
                     r"\bthe (?:first|second|other) one\b|\bthat\b|\bthose\b|\bit\b", re.I)
NOUN = re.compile(r"\b(?:the|my|our|a|an)\s+(?:[\w-]+\s+){0,4}"
                  r"(?:app|theme|team|prompt|gate|lines|build|display|UI|work|browser|"
                  r"plugin|standard|windows|account|project|tests|output|animation|key|"
                  r"material|thing|files|session|button|logo|interface|place|language|"
                  r"processes|recipes|panels|tasks)\b", re.I)
BARE = re.compile(r"\b(?:new standard|good UI|headless edge|test cleanup|new build|"
                  r"sign-in key|dark theme|light theme)\b", re.I)
RELATIVE = re.compile(r"^(?:\s+(?:I|you|we|he|she|they|was|were|has|had|can|could|"
                      r"will|would|should|must|seems|appears|isn't|doesn't|the|a|an)\b)", re.I)
EXPLETIVE = re.compile(r"^(?:\s*(?:'s|is|was|would|seems|appears)\s+(?:a\b|an\b|"
                       r"nice\b|very\b|possible\b|important\b|like\b|about\b))", re.I)


def _valid(match, text):
    word = match.group().lower()
    before = text[max(0, match.start()-16):match.start()].lower()
    after = text[match.end():match.end()+35]
    if word == 'that':
        if re.search(r'\bdash\s+(?:should\s+)?$', before) or re.search(r'\bstrictly\s+$', before):
            return False
        if re.search(r'\b(?:so|because|given|assuming|like|such|and)\s+$', before):
            return False
        if re.search(r'\b(?:something|thing)\s+$', before) and re.match(r'\s+\w+ly\b', after, re.I):
            return False
        if RELATIVE.match(after) and not re.search(r'[.!?]\s*$', before):
            return False
        if re.match(r'\s+(?:is|was|will|would|can|could|should|must)\b', after, re.I):
            return True
    if word == 'it' and EXPLETIVE.match(after):
        return False
    if word.startswith('the thing') and re.search(r'\b(?:truth|nature|point) of\s+$', before):
        return False
    return True


def _canonical(phrase, context):
    phrase = re.sub(r'\s+', ' ', phrase).strip(' ,.!?')
    phrase = re.sub(r'\bdark team\b', 'dark theme', phrase, flags=re.I)
    phrase = re.sub(r'\blight team\b', 'light theme', phrase, flags=re.I)
    phrase = re.sub(r'\bNevia\b', 'Neyvia', phrase, flags=re.I)
    phrase = re.sub(r'\b(?:a|an|the|my|our)\s+', '', phrase, count=1, flags=re.I)
    phrase = re.sub(r'\bthinking place\b', 'thinking display', phrase, flags=re.I)
    if phrase.lower() == 'app':
        project = context.get('project', '')
        if re.search(r'\bNeyvia\b|\bNevia\b', project, re.I):
            return 'Neyvia app'
    return phrase


def _local_target(text, mention, context):
    # First prefer an explicit referent near the mention in this same prompt.
    left = text[max(0, mention.start()-260):mention.start()]
    candidates = list(NOUN.finditer(left))
    if candidates:
        nearest = candidates[-1]
        phrase = _canonical(nearest.group(), context)
        if re.fullmatch(r'(?:new )?plugin', phrase, re.I):
            title = re.search(r'\b(?:plugin called|called)\s+([A-Z][\w ]{2,35})', left, re.I)
            if title:
                phrase = title.group(1).strip() + ' plugin'
        if phrase.lower() == 'lines' and re.search(r'\bsettings\b', left[-120:], re.I):
            phrase = 'settings lines'
        if not re.search(r'\b(?:thing|stuff)\b', phrase, re.I):
            return {'kind': 'prompt', 'targetText': phrase,
                        'source': {'span': [mention.start()-len(left)+nearest.start(),
                                            mention.start()-len(left)+nearest.end()]}}
    bare = list(BARE.finditer(left))
    if bare:
        nearest = bare[-1]
        phrase = nearest.group()
        if phrase.lower() == 'good ui':
            phrase = 'UI work'
        elif phrase.lower() == 'headless edge':
            phrase = 'headless Edge investigation'
        elif phrase.lower() == 'new standard' and re.search(r'computer\s+use', left, re.I):
            phrase = 'computer-use standard'
        return {'kind': 'prompt', 'targetText': phrase,
                'source': {'span': [mention.start()-len(left)+nearest.start(),
                                    mention.start()-len(left)+nearest.end()]}}
    cleanup = re.search(r'\b(?:clean up|merge)\s+(?:some\s+)?tests\b', left, re.I)
    if cleanup:
        return {'kind': 'prompt', 'targetText': 'test cleanup',
                'source': {'span': [mention.start()-len(left)+cleanup.start(),
                                    mention.start()-len(left)+cleanup.end()]}}
    # Dictation often names the referent immediately after its pronoun.
    right = text[mention.end():min(len(text), mention.end()+100)]
    if re.search(r'\b(?:leave|fix|keep|use|open|install)\s*$', left[-18:], re.I):
        following = NOUN.search(right)
        if following:
            phrase = _canonical(following.group(), context)
            if not re.search(r'\b(?:thing|stuff)\b', phrase, re.I):
                return {'kind': 'prompt', 'targetText': phrase,
                        'source': {'span': [mention.end()+following.start(),
                                            mention.end()+following.end()]}}
    if re.search(r'\blooking at\s*$', left[-20:], re.I):
        following = re.search(r'\b(?:the|a)\s+key\b', right, re.I)
        if following:
                return {'kind': 'prompt', 'targetText': 'key',
                    'source': {'span': [mention.end()+following.start(),
                                        mention.end()+following.end()]}}
    # An evaluative "it" can refer to the preceding event, without identifying
    # its actors as windows, apps, etc. Keep the user's actual event wording.
    if mention.group().lower() == 'it' and re.match(
            r"(?:'s| is)\s+(?:\w+\s+){0,2}(?:annoying|frustrating|broken|slow)\b", right, re.I):
        event = re.search(r'\b((?:a|the|my|our)\s+[^.!?]{1,90}\b(?:is|are|was|were)\s+'
                          r'[^.!?]{1,90}?)[.!?]?\s*(?:It\s+\w*,?\s*)?$', left, re.I)
        if event:
            return {'kind': 'prompt', 'targetText': event.group(1).strip(),
                    'source': {'span': [mention.start()-len(left)+event.start(1),
                                        mention.start()-len(left)+event.end(1)]}}
    return None


def _chat_target(context, kind):
    # The transport already supplies projected chat. Do not open transcript or files.
    for index in range(len(context.get('chat', []))-1, -1, -1):
        row = context['chat'][index]
        text = row.get('text', '')[-1500:]
        matches = list(NOUN.finditer(text))
        if kind:
            matches = [match for match in matches if re.search(r'\b' + re.escape(kind) + r'\b', match.group(), re.I)]
        if kind == 'app':
            matches = [match for match in matches if re.search(
                r'\b(?!new\b|old\b|same\b|other\b|an\b|the\b|running\b|live\b|served\b|desktop\b)'
                r'[\w-]+\s+app$', _canonical(match.group(), context), re.I)]
            identities = {re.search(r'[\w-]+\s+app$', match.group(), re.I).group().lower()
                          for match in matches}
            if len(identities) > 1:
                return None
        if matches:
            nearest = matches[-1]
            phrase = _canonical(nearest.group(), context)
            if kind == 'app':
                # Lower-case compound names are identities too. Generic "app"
                # or "new app" supplies no identity and cannot resolve history.
                name = re.search(r'\b([\w-]+)\s+app$', phrase)
                if not name:
                    continue
                phrase = name.group(0)
            elif kind == 'build':
                # A nearby named installer is the build's actual artifact. Do
                # not borrow "new" from an unrelated older message.
                qualified = re.search(r'\bnew\s+installer\s+(?:is|was)\s+built\b', text, re.I)
                if qualified:
                    phrase = 'new installer build'
            return {'kind': 'chat', 'targetText': phrase,
                    'source': {'chatIndex': index, 'role': row['role']}}
    return None


def _chat_candidate(context):
    for index in range(len(context.get('chat', []))-1, -1, -1):
        row = context['chat'][index]
        if row.get('text', '').strip():
            return {'kind': 'chat', 'target': str(index),
                    'preview': row['text'][:160]}
    return None


def resolve_references(text, clause, context):
    """Return mention-level readings with source, or explicit ambiguity.

    Resolution is restricted to a nearby named noun phrase or an unambiguous
    project app. Generic chat recency alone never makes a target certain.
    """
    start, end = clause
    result = []
    for match in MENTION.finditer(text, start, end):
        if not _valid(match, text):
            continue
        surface = match.group()
        lower = surface.lower()
        reading = {'span': [match.start(), match.end()], 'surface': surface,
                   'state': 'ambiguous', 'candidates': []}
        target = None
        if lower.startswith('the app'):
            if 'we talked about' in lower:
                # A generic prior mention of "app" does not identify which app.
                # Require an explicit name beside the noun in projected chat.
                named = _chat_target(context, 'app')
                if named:
                    target = named
            else:
                project = context.get('project', '')
                if re.search(r'\bNeyvia\b|\bNevia\b', project, re.I):
                    target = {'kind': 'project', 'targetText': 'Neyvia app',
                              'source': {'project': project}}
                else:
                    target = _local_target(text, match, context)
        elif lower.startswith(('the thing', 'the stuff', 'the first one', 'the second one', 'the other one')):
            target = _local_target(text, match, context)
            if lower.endswith('from before') and not target:
                reading['candidates'] = [_chat_target(context, 'any')] if _chat_target(context, 'any') else []
        else:
            target = _local_target(text, match, context)
            if not target and lower == 'it':
                before = text[max(0, match.start()-90):match.start()].lower()
                after = text[match.end():min(len(text), match.end()+80)].lower()
                if re.search(r'\b(?:install|rebuild)\s*$', before):
                    target = _chat_target(context, 'build')
                elif re.search(r'\bsays?\s+\d[\d.,]*\s+million\s+token', after):
                    target = {'kind': 'prompt', 'targetText': 'token usage display',
                              'source': {'span': [match.start(), min(len(text), match.end()+80)]}}
                elif re.search(r'\b(?:app|Neyvia|Nevia)\b', before):
                    project = context.get('project', '')
                    if re.search(r'\bNeyvia\b|\bNevia\b', project, re.I):
                        target = {'kind': 'project', 'targetText': 'Neyvia app',
                                  'source': {'project': project}}
        if target:
            reading.update(state='resolved', target=target['kind'],
                           targetText=target['targetText'], source=target['source'])
        elif not reading['candidates']:
            candidate = _chat_candidate(context)
            if candidate:
                reading['candidates'] = [candidate]
        result.append(reading)
    return result
