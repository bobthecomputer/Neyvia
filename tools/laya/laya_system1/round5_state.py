"""Train-bound R5 CPU heads, solved-case retrieval and frozen R2 corrections."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .contracts import digest, labels, native_answer, transfer_signature
from .evolved_state import EvolvedState
from .memory import Memory
from .shared_state import KINDS, softmax


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1048576), b''): h.update(block)
    return h.hexdigest()


def quantize_weights(weights):
    """Per-output-channel symmetric int8; biases remain float32."""
    result = {}
    for key, value in weights.items():
        value = np.asarray(value, dtype=np.float32)
        if key in {'sw', 'w1', 'w2', 'w3'}:
            scale = np.maximum(np.abs(value).max(axis=1, keepdims=True) / 127., 1e-12)
            result[key] = np.rint(value / scale).clip(-127, 127).astype(np.int8)
            result[key + '_scale'] = scale.reshape(-1).astype(np.float32)
        else:
            result[key] = value
    return result


def int8_linear(x, weights, key, bias):
    x = np.asarray(x, dtype=np.float32)
    scale = np.maximum(np.abs(x).max(axis=-1, keepdims=True) / 127., 1e-12)
    activation = np.rint(x / scale).clip(-127, 127).astype(np.int32)
    products = activation @ weights[key].astype(np.int32).T
    return products.astype(np.float32) * scale * weights[key + '_scale'] + weights[bias]


def score_head(weights, base, state, quantized=False):
    if quantized:
        latent = np.tanh(int8_linear(state[None, :], weights, 'sw', 'sb')).reshape(-1)
    else:
        latent = np.tanh(state @ weights['sw'].T + weights['sb'])
    x = np.concatenate([base, np.tile(latent, (len(base), 1))], axis=1).astype(np.float32)
    for i in (1, 2, 3):
        x = int8_linear(x, weights, f'w{i}', f'b{i}') if quantized else x @ weights[f'w{i}'].T + weights[f'b{i}']
        if i < 3: x = np.maximum(x, 0)
    return x.reshape(-1)


def correction_binding(question):
    return digest({'question': question, 'option_order': labels(question), 'scope': 'r5-fitting-only'})


class FrozenCorrections:
    """Reuse R2 admission/conflict/contrast rules without opening a mutable DB."""
    def __init__(self, groups):
        self.groups = groups

    def rows(self, binding=None):
        # Store one shared vector per record, expand only the queried schema.
        return [{**row, 'features': np.tile(np.asarray(row['global_state'], dtype=np.float32),
                                         (len(row['labels']), 1))}
                for row in self.groups.get(binding, [])]

    apply = Memory.apply


class Round5State(EvolvedState):
    def __init__(self, directory, genes):
        super().__init__(directory, genes)
        self.is_quantized = bool(genes.get('quantization', False))
        self.heads = {}
        self.extra_identities = {}
        self.fit_ids = set(self.manifest['fitting_case_ids'])
        self.panels_path = Path(__file__).resolve().parents[1] / 'evidence/r4/panels.json'
        self.panels = json.loads(self.panels_path.read_text(encoding='utf-8'))
        if self.fit_ids != set(self.panels['fitting_case_ids']):
            raise ValueError('Primary head violates frozen R4 fitting boundary')
        self.type_heads = dict(genes.get('type_heads', {}))
        if set(self.type_heads) - set(KINDS): raise ValueError('Unknown question type head')
        ensemble = genes.get('ensemble_models', [])
        if not isinstance(ensemble, list) or len(ensemble) > 8: raise ValueError('At most eight ensemble heads')
        self.ensemble = [str(Path(p).resolve()) for p in ensemble]
        self.primary = str(Path(directory).resolve())
        for path in set([self.primary] + self.ensemble + list(self.type_heads.values())):
            normalized = str(Path(path).resolve())
            self.heads[normalized] = self._load_head(Path(path))
        # Do not retain two copies of the primary floating point head.
        self.weights = {}
        self.retrieval = None
        self.corrections = None
        self.memory_identity = None
        memory_path = genes.get('memory_model') or genes.get('retrieval_model') or genes.get('correction_model')
        if memory_path:
            self._load_memory(Path(memory_path))
        elif genes.get('retrieval_weight', 0) or genes.get('correction_weight', 0):
            raise ValueError('Memory operator requires a verified train-only memory_model')
        self.identity.update(model='laya/round5-state', head_artifacts=self.extra_identities,
                             memory_artifact=self.memory_identity, quantization=self.is_quantized)

    def _load_head(self, directory):
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('source_split') != 'train' or set(manifest['fitting_case_ids']) != self.fit_ids:
            raise ValueError('Head violates original R4 fitting boundary')
        if manifest.get('version', 1) >= 2:
            tuning = set(manifest.get('tuning_case_ids', []))
            if not tuning or not tuning <= set(self.panels['tuning_case_ids']):
                raise ValueError('Head tuning includes frozen reserved panels or unknown cases')
        for name, expected in manifest['artifact_sha256'].items():
            target = (directory / name).resolve()
            if target.parent != directory.resolve() or sha(target) != expected:
                raise ValueError('Head artifact identity mismatch: ' + name)
        if manifest['artifact_sha256']['embedding.npy'] != self.manifest['artifact_sha256']['embedding.npy']:
            raise ValueError('Ensemble feature basis differs from primary head')
        if manifest['artifact_sha256']['tokenizer.json'] != self.manifest['artifact_sha256']['tokenizer.json']:
            raise ValueError('Ensemble tokenizer differs from primary head')
        quantized_artifact = self.is_quantized and 'head-int8.npz' in manifest['artifact_sha256']
        with np.load(directory / ('head-int8.npz' if quantized_artifact else 'head.npz')) as archive:
            weights = dict(archive)
        if self.is_quantized and not quantized_artifact: weights = quantize_weights(weights)
        effective = hashlib.sha256()
        for key, value in sorted(weights.items()):
            effective.update(key.encode()); effective.update(value.tobytes())
        self.extra_identities[str(directory.resolve())] = {
            'manifest_sha256': sha(directory / 'manifest.json'),
            'head_sha256': manifest['artifact_sha256']['head.npz'],
            'effective_weights_sha256': effective.hexdigest(),
            'quantized_artifact': bool(quantized_artifact)}
        return weights

    def _load_memory(self, directory):
        manifest = json.loads((directory / 'memory-manifest.json').read_text(encoding='utf-8'))
        if manifest.get('source_split') != 'train' or set(manifest['fitting_case_ids']) != self.fit_ids:
            raise ValueError('Memory violates original fitting boundary')
        if manifest.get('panels_sha256') != sha(self.panels_path):
            raise ValueError('Memory frozen panel binding changed')
        for name, expected in manifest['artifact_sha256'].items():
            path = (directory / name).resolve()
            if path.parent != directory.resolve() or sha(path) != expected:
                raise ValueError('Memory artifact mismatch: ' + name)
        if manifest['embedding_sha256'] != self.manifest['artifact_sha256']['embedding.npy']:
            raise ValueError('Memory uses a different feature basis')
        with np.load(directory / 'solved-cases.npz') as archive: self.retrieval = dict(archive)
        case_ids = set(map(str, self.retrieval['case']))
        if not case_ids <= self.fit_ids: raise ValueError('Nonfitting retrieval case')
        groups = json.loads((directory / 'corrections.json').read_text(encoding='utf-8'))
        for records in groups.values():
            for record in records:
                if record['case_id'] not in self.fit_ids or record['correct'] not in record['labels']:
                    raise ValueError('Invalid fitting correction')
        self.corrections = FrozenCorrections(groups)
        self.memory_identity = {'manifest_sha256': sha(directory / 'memory-manifest.json'), **manifest['artifact_sha256']}

    def retrieve(self, q, state, options, kind, exclude_case=None):
        data = self.retrieval
        if data is None: return np.full(len(options), 1 / len(options), dtype=np.float32), 0.
        valid = data['kind'] == KINDS[kind]
        # Panel inference cannot retrieve its own case, even if a train-like ID is supplied.
        if exclude_case is not None: valid &= data['case'] != exclude_case
        candidates = np.flatnonzero(valid)
        if not len(candidates): return np.full(len(options), 1 / len(options), dtype=np.float32), 0.
        sims = .55 * (data['q'][candidates] @ q) + .45 * (data['state'][candidates] @ state)
        k = min(int(self.genes.get('retrieval_neighbors', 4)), len(candidates))
        k = max(1, min(k, 8))
        selected = np.argsort(sims)[-k:][::-1]
        confidence = max(0., float(sims[selected[0]]))
        result = np.zeros(len(options), dtype=np.float32)
        for weight, item in zip(softmax(8 * sims[selected]), candidates[selected]):
            n = int(data['n'][item]); src = data['options'][item, :n]
            if kind in {'noul', 'score'} and n == len(options): mapped = data['p'][item, :n]
            else: mapped = softmax(8 * (options @ src.T)) @ data['p'][item, :n]
            result += weight * mapped / max(mapped.sum(), 1e-6)
        return result / max(result.sum(), 1e-6), confidence

    def predict(self, state, questions, cache=False):
        started = time.perf_counter(); answers = {}; features = {}; paths = {}; correction_events = {}
        for qid, question in questions.items():
            observed = {k: state.get(k) for k in question['view']} if question.get('view') and isinstance(state, dict) else state
            encoded, _ = self.state(observed, cache=False)
            mix = float(self.genes['lexical_mix'])
            keys, base, global_state, q, opts, lexical = self.features(encoded, question, include_head=mix < 1)
            cheap = softmax(lexical); ordered = np.sort(cheap)
            margin = float(ordered[-1] - ordered[-2])
            paths[qid] = ['shared_lexical']
            if mix == 1 or margin >= float(self.genes['early_exit_margin']): probabilities = cheap
            else:
                initial = self.type_heads.get(question['type'], self.primary)
                head_paths = list(dict.fromkeys([str(Path(initial).resolve())] + self.ensemble))
                head = np.mean([softmax(score_head(self.heads[p], base, global_state, self.is_quantized)) for p in head_paths], axis=0)
                probabilities = mix * cheap + (1 - mix) * head
                paths[qid].append('typed_head' if question['type'] in self.type_heads else 'distilled_head')
                if len(head_paths) > 1: paths[qid].append('ensemble')
                if self.is_quantized: paths[qid].append('int8')
            retrieval_weight = float(self.genes.get('retrieval_weight', 0))
            if retrieval_weight:
                retrieved, confidence = self.retrieve(q, global_state, opts, question['type'])
                gate = float(self.genes.get('retrieval_gate', .7))
                alpha = np.clip(retrieval_weight * max(0., (confidence - gate) / max(1e-6, 1 - gate)), 0., 1.)
                probabilities = (1 - alpha) * probabilities + alpha * retrieved
                paths[qid].append('nearest_solved_case')
            values = dict(zip(keys, map(float, probabilities)))
            feats = np.tile(global_state, (len(keys), 1)).copy()
            if self.corrections is not None and float(self.genes.get('correction_weight', 0)):
                record = {'binding': correction_binding(question), 'view_digest': digest(observed),
                          'transfer_digest': transfer_signature(question, observed), 'labels': keys}
                corrected, event = self.corrections.apply(record, values, feats)
                alpha = np.clip(float(self.genes['correction_weight']), 0., 1.)
                values = {key: (1 - alpha) * values[key] + alpha * corrected[key] for key in keys}
                correction_events[qid] = {key: event[key] for key in ('source', 'conflict', 'confidence_kind')}
                paths[qid].append('r2_correction_' + event['source'])
            answers[qid] = {**native_answer(question, values), 'confidence': max(values.values()),
                            'confidence_kind': 'distilled_not_calibrated'}
            features[qid] = feats
        return {'model': self.identity['model'], 'answers': answers,
                'usage': {'input_tokens': 0, 'output_tokens': 0},
                'runtime': {'total_ms': (time.perf_counter() - started) * 1000, 'paths': paths,
                            'correction_events': correction_events, 'state_cache_hits': 0,
                            'truncated_state_tokens': 0,
                            'execution': 'cpu-only-r5'}}, features
