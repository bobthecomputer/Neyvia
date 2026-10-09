"""Paul's seven-part course pack, generated and checked through the T14 owner."""
from __future__ import annotations

import copy
import json

PARTS = ('formula', 'when', 'write', 'pattern', 'course_example', 'your_exercise', 'variations_traps')
LABELS = ('FORMULA', 'WHEN?', 'WHAT DO I WRITE?', 'PATTERN', 'COURSE EXAMPLE', 'YOUR EXERCISE', 'VARIATIONS/TRAPS')
TEACH = set(PARTS) - {'your_exercise'}
GRADED = {'your_exercise', 'pattern_drill', 'exercise_variant'}
FORMAT = 'paul-seven-part.v1'


def schema():
    from .scroll_generation import STR, STRINGS, _object
    pattern = _object({'cue': STR, 'method': STR, 'exercise': STR, 'answer': STR,
                       'changedExercise': STR, 'changedAnswer': STR, 'trap': STR})
    example = _object({'title': STR, 'quote': STR, 'feature': STR,
                       'steps': {'type': 'array', 'minItems': 2, 'maxItems': 6,
                                 'items': _object({'text': STR, 'why': STR})}})
    item = _object({'concept': STR, 'formula': STR, 'conditions': STR, 'when': STR,
                    'writeLines': {'type': 'array', 'minItems': 3, 'maxItems': 6, 'items': STR},
                    'patterns': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': pattern},
                    'courseExample': example})
    return _object({'items': {'type': 'array', 'minItems': 1, 'items': item}})


def generate(root, pack, sources, selected, run, log, progress=None):
    from .scroll_generation import _decision, _card, _answer_check, _hash, _procedure_manifest
    result = copy.deepcopy(pack)
    cards = []
    for number, concept in enumerate(selected):
        if progress:
            progress('seven-part', number, len(selected))
        span = concept['source']
        text = sources['source_texts'][span['doc']][span['span'][0]:span['span'][1]]
        output_schema = schema()
        output_schema['properties']['items']['items']['properties']['concept'] = {'const': concept['id'], 'type': 'string'}
        def valid(answer):
            if len(answer['items']) != 1 or answer['items'][0]['concept'] != concept['id']:
                return False
            item = answer['items'][0]
            example = item['courseExample']
            return (example['quote'] in text and any(s['why'] for s in example['steps'])
                    and all(p['exercise'] != p['changedExercise'] for p in item['patterns'])
                    and len({p['cue'] for p in item['patterns']}) == len(item['patterns'])
                    and all(len(item[k].split()) <= 75 for k in ('formula', 'conditions', 'when')))
        answer, tier = _decision(root, result, sources, 'seven-part', run, log,
            "Create Paul's revision pack for exactly this maths/physics concept. Copy the concept id exactly into the concept field, never its name. Seven parts: FORMULA (compressed result plus conditions), WHEN? (recognition conditions), "
            "WHAT DO I WRITE? (exact first write -> compute -> conclude notation), PATTERN (If I see X -> try Y), COURSE EXAMPLE, YOUR EXERCISE, VARIATIONS/TRAPS. "
            "Include every importantly different pattern in this source (maximum three). One solved exercise per pattern and a genuinely changed exercise per pattern; "
            "change coefficients, evaluation points or representation, preserving the technique; recompute its answer. Keep answers explicit and correct. "
            "Course example MUST be an actual labelled course example in the supplied note, not an invented illustration. Copy one nonempty exact quote from this section "
            "that includes that example's question. Steps reproduce its correct solution; feature says which cue tells you the method. Generated exercises are adaptations, never course examples. "
            "Use plain text arithmetic (x^2, sin(x)); no HTML or LaTeX. No unsupported definitions. Keep each field concise (75 words max); writeLines exactly executable notation and a conclusion. "
            "If the concept has no relevant course example, do not invent one.\n" + json.dumps({'concept': concept, 'noteSection': text}, ensure_ascii=False),
            output_schema, valid, card_ids=[concept['id']])
        item = answer['items'][0]
        def card(kind, body, *, index=1, **fields):
            value = _card(concept, kind, run, tier, body=body, **fields)
            teaching = kind in TEACH
            value.update(id=f"{concept['id']}.{kind}.{index:02}",
                         concepts={'teaches': [concept['id']] if teaching else [],
                                   'tests': [] if teaching else [concept['id']],
                                   'requires': concept['prereqs']},
                         part=kind if kind in PARTS else 'pattern' if kind == 'pattern_drill' else 'variations_traps',
                         partIndex=PARTS.index(kind) if kind in PARTS else 3 if kind == 'pattern_drill' else 6,
                         phase='test' if kind in GRADED else 'teach', seconds=40)
            if kind in GRADED:
                value['requiresParts'] = ['formula', 'when', 'write', 'pattern', 'course_example']
            cards.append(value)
            return value
        card('formula', item['formula'] + '\nConditions: ' + item['conditions'])
        card('when', item['when'])
        card('write', '\n'.join(item['writeLines']))
        card('pattern', '\n'.join('If I see ' + p['cue'] + ' -> try ' + p['method'] for p in item['patterns']))
        example = item['courseExample']
        exact_at = sources['source_texts'][span['doc']].find(example['quote'], span['span'][0], span['span'][1])
        card('course_example', example['title'] + '\nRecognition cue: ' + example['feature'],
             title=example['title'], steps=example['steps'], fade=0,
             courseQuote=example['quote'], source={'doc': span['doc'], 'span': [exact_at, exact_at + len(example['quote'])]})
        for index, pattern in enumerate(item['patterns'], 1):
            card('your_exercise', pattern['exercise'], index=index, front=pattern['exercise'], back=pattern['answer'],
                 explanation=pattern['method'], generatedAdaptation=True, patternId=f"{concept['id']}.pattern.{index:02}")
        card('variations_traps', '\n'.join('Variation: ' + p['changedExercise'] + '\nTrap: ' + p['trap'] for p in item['patterns']),
             generatedAdaptation=True)
        for index, pattern in enumerate(item['patterns'], 1):
            card('pattern_drill', 'Recognise the type: ' + pattern['exercise'], index=index,
                 front='Which method fits ' + pattern['exercise'] + ', and what feature tells you?',
                 back=pattern['method'] + '; cue: ' + pattern['cue'], explanation=pattern['method'], patternId=f"{concept['id']}.pattern.{index:02}")
            card('exercise_variant', 'Generated variation: ' + pattern['changedExercise'], index=index,
                 front=pattern['changedExercise'], back=pattern['changedAnswer'], explanation=pattern['method'] + '; trap: ' + pattern['trap'],
                 generatedAdaptation=True, variantOf=f"{concept['id']}.your_exercise.{index:02}")
    affected = {c['id'] for c in selected}
    result['cards'] = [c for c in result['cards'] if not set(c['concepts']['teaches'] + c['concepts']['tests']) & affected] + cards
    if progress:
        progress('answer-check', len(selected), len(selected))
    _answer_check(root, result, sources, [c for c in cards if c['type'] in GRADED], run, log)
    result['meta']['studyFormat'] = FORMAT
    result['generation'].update(run=run, procedureManifestSha256=_hash(_procedure_manifest()),
                                 answerChecks={'checked': sum('answerCheck' in c for c in cards),
                                               'disagreements': sum(c.get('answerCheck', {}).get('disagreed', False) for c in cards)})
    return result


def validate_format(pack, source_texts):
    """Semantic format checks complement schema, DAG, spans and answer review."""
    errors = []
    def fail(card, rule, message):
        errors.append({'cardId': card, 'rule': rule, 'message': message})
    for concept in pack['concepts']:
        owned = [c for c in pack['cards'] if concept['id'] in c['concepts']['teaches'] + c['concepts']['tests']]
        parts = {c['type'] for c in owned}
        if not set(PARTS) <= parts:
            fail(None, 'seven-part', f"{concept['id']} is missing {', '.join(sorted(set(PARTS)-parts))}")
        for card in owned:
            kind = card['type']
            if kind == 'course_example':
                source = card['source']
                quote = card.get('courseQuote', '')
                if not quote or source_texts[source['doc']][slice(*source['span'])] != quote:
                    fail(card['id'], 'course-example', 'Course example must quote its exact source span.')
                if card.get('generatedAdaptation'):
                    fail(card['id'], 'course-example', 'Generated adaptations cannot be course examples.')
            if kind in GRADED and (card.get('phase') != 'test' or not card.get('back') or not card.get('requiresParts')):
                fail(card['id'], 'exercise', 'Delayed recall needs a solution and taught-part requirements.')
            if kind == 'pattern_drill' and not card.get('patternId'):
                fail(card['id'], 'pattern-drill', 'Recognition drill must identify its taught pattern.')
            if kind == 'exercise_variant':
                original = next((c for c in owned if c['id'] == card.get('variantOf')), None)
                if not original or card['front'] == original['front'] or not card.get('generatedAdaptation'):
                    fail(card['id'], 'exercise-variant', 'Variation must be a changed exercise with an original reference.')
            if kind in {'your_exercise', 'exercise_variant'} and card.get('answerCheck', {}).get('ok') is not True:
                fail(card['id'], 'answer-check', 'Exercise solution lacks independent accepted validation.')
    return errors
