"""Executable R3 descendants with conditional, distilled typed heads."""
from __future__ import annotations
import time
import numpy as np
from .shared_state import SharedState, softmax
from .contracts import native_answer


class EvolvedState(SharedState):
    def __init__(self, directory, genes):
        super().__init__(directory, 'head', cache_capacity=0)
        self.genes = genes
        self.manifest['chunk_cap'] = int(genes['chunk_cap'])
        self.identity.update(model='laya/evolved-state-r4', genes=genes)

    def predict(self, state, questions, cache=False):
        started = time.perf_counter()
        answers, features, paths = {}, {}, {}
        for qid, question in questions.items():
            observed = {k: state.get(k) for k in question['view']} if question.get('view') and isinstance(state, dict) else state
            encoded, _ = self.state(observed, cache=False)
            mix = float(self.genes['lexical_mix'])
            keys, base, global_state, _, _, lexical = self.features(encoded, question, include_head=mix < 1)
            cheap = softmax(lexical)
            margin = float(np.sort(cheap)[-1] - np.sort(cheap)[-2])
            if mix == 1 or margin >= float(self.genes['early_exit_margin']):
                probabilities, path = cheap, 'shared_lexical'
            else:
                head = softmax(self.head(base, global_state))
                probabilities = mix * cheap + (1 - mix) * head
                path = 'conditional_distilled_head'
            probs = dict(zip(keys, map(float, probabilities)))
            answers[qid] = {**native_answer(question, probs), 'confidence': float(probabilities.max()),
                            'confidence_kind': 'distilled_not_calibrated'}
            features[qid] = np.tile(global_state, (len(keys), 1)).copy()
            paths[qid] = path
        return {'model': self.identity['model'], 'answers': answers,
                'runtime': {'total_ms': (time.perf_counter() - started) * 1000,
                            'paths': paths, 'execution': 'cpu-only-r4'}}, features
