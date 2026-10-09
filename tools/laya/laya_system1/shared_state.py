"""CPU shared-state typed evidence network; no runtime transformer or downloads.

Projected frozen lexical embeddings encode each state chunk once. Tiny typed
heads condition on question, option, selected evidence and a shared latent.
Retrieval holds independent training cases only, never benchmark corrections.
"""
from __future__ import annotations
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
from tokenizers import Tokenizer
from .contracts import labels, native_answer, digest

KINDS = {'choice': 0, 'score': 1, 'noul': 2}
STOP = set('a an the of to for is are was were and or in on with by it this that be as at from'.split())

def words(text):
    return {w for w in re.findall(r'[a-z0-9]+', str(text).lower()) if w not in STOP}

def chunks(state):
    if isinstance(state, dict):
        out = []
        def visit(value, path):
            if isinstance(value, dict):
                for key, child in value.items(): visit(child, path + [str(key)])
            elif isinstance(value, list):
                for i, child in enumerate(value): visit(child, path + [str(i)])
            else: out.append('.'.join(path) + ': ' + str(value))
        visit(state, [])
        return out or ['{}']
    # Bounded pieces retain both beginning and end; no question-specific truncation.
    parts = re.split(r'\n+|(?<=[.!?])\s+', str(state))
    result = [part[i:i+512] for part in parts for i in range(0, len(part), 512) if part[i:i+512].strip()]
    return result or ['']

def option_texts(q):
    keys = labels(q)
    if q['type'] == 'noul':
        return keys, ['false no not satisfied', 'true yes satisfied']
    if q['type'] == 'choice':
        return keys, [key.replace('_', ' ') + ' ' + str(q['criteria'][key]) for key in keys]
    return keys, [str(c) for c in q['criteria']]

def unit(x):
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-6)

def softmax(x):
    y = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return y / y.sum(axis=-1, keepdims=True)

class SharedState:
    def __init__(self, directory, variant='head', cache_capacity=32, verify=True):
        if variant not in {'lexical','head-only','latent','head','retrieval-only','retrieval','conditional','int8'}:
            raise ValueError('Unknown shared-state architecture variant')
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory/'manifest.json').read_text(encoding='utf-8'))
        if verify:
            if not self.manifest.get('fitting_decisions') or self.manifest.get('source_split') != 'train':
                raise ValueError('A completed train-only model manifest is required')
            for name, expected in self.manifest['artifact_sha256'].items():
                path = (self.directory/name).resolve()
                if path.parent != self.directory.resolve() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError('Model artifact identity mismatch: '+name)
        self.tokenizer = Tokenizer.from_file(str(self.directory/'tokenizer.json'))
        self.embedding = np.load(self.directory/'embedding.npy', mmap_mode='r')
        headfile = 'head-only.npz' if variant == 'head-only' else 'latent.npz' if variant == 'latent' else 'head.npz'
        self.weights = dict(np.load(self.directory/headfile)) if variant not in {'lexical','retrieval-only'} else {}
        self.variant, self.capacity = variant, cache_capacity
        self.state_cache, self.text_cache = OrderedDict(), OrderedDict()
        needs_index = variant == 'retrieval-only' or (variant in {'retrieval','conditional','int8'} and self.manifest['retrieval_weight'] > 0)
        self.retrieval = dict(np.load(self.directory/'retrieval.npz')) if needs_index else None
        self.identity = {'model': 'laya/shared-state-r3', 'architecture': 'shared-state-typed-evidence',
                         'variant': variant, 'manifest_sha256': hashlib.sha256((self.directory/'manifest.json').read_bytes()).hexdigest(),
                         'device': 'cpu', 'training_split': 'typed-decisions/train only', 'confidence_kind': 'distilled_not_calibrated'}
        self.quantized = None
        if variant == 'int8':
            import torch
            torch.set_num_threads(1)
            torch.backends.quantized.engine = 'x86'
            modules = []
            for i in (1,2,3):
                w, b = self.weights[f'w{i}'], self.weights[f'b{i}']
                layer = torch.nn.Linear(w.shape[1], w.shape[0])
                layer.weight.data.copy_(torch.from_numpy(w)); layer.bias.data.copy_(torch.from_numpy(b))
                modules.append(layer)
                if i < 3: modules.append(torch.nn.ReLU())
            self.quantized = torch.ao.quantization.quantize_dynamic(torch.nn.Sequential(*modules).eval(), {torch.nn.Linear}, dtype=torch.qint8)
            self.torch = torch
            for i in (1,2,3):
                del self.weights[f'w{i}'], self.weights[f'b{i}']

    def encode(self, text):
        # Bound instruction/option cache memory as well as the entry count.
        if len(text)>8192:
            raise ValueError('A question or option text exceeds the 8192-character CPU budget')
        if text in self.text_cache:
            self.text_cache.move_to_end(text); return self.text_cache[text]
        ids = self.tokenizer.encode(text, add_special_tokens=False).ids
        if not ids: ids = [0]
        value = unit(np.mean(self.embedding[ids], axis=0)).astype(np.float32)
        self.text_cache[text] = value
        if len(self.text_cache) > 512: self.text_cache.popitem(last=False)
        return value

    def state(self, state, cache=True):
        key = digest(state)
        if cache and key in self.state_cache:
            self.state_cache.move_to_end(key); return self.state_cache[key], True
        texts = chunks(state)
        # Fixed head/tail cap, bound memory/compute, disclose clipped pieces.
        cap = int(self.manifest['chunk_cap'])
        clipped = max(0, len(texts)-cap)
        if clipped: texts = texts[:cap//2] + texts[-(cap-cap//2):]
        vectors = np.stack([self.encode(t) for t in texts])
        value = (texts, vectors, unit(vectors.mean(axis=0)).astype(np.float32), clipped)
        if cache:
            self.state_cache[key] = value
            if len(self.state_cache) > self.capacity: self.state_cache.popitem(last=False)
        return value, False

    def features(self, encoded, question, include_head=True):
        texts, state_vectors, global_state, _ = encoded
        keys, descriptions = option_texts(question)
        q = self.encode(question['instructions']); opts = np.stack([self.encode(t) for t in descriptions])
        state_words = [words(t) for t in texts]; qw = words(question['instructions'])
        ow = [words(t) for t in descriptions]
        overlap = np.asarray([[len(sw & w)/max(1,len(w)) for sw in state_words] for w in ow], dtype=np.float32)
        semantic = unit(opts + q[None,:]) @ state_vectors.T
        lexical = 2*overlap.max(axis=1) + semantic.max(axis=1) + opts@global_state
        if not include_head:
            return keys, None, global_state, q, opts, lexical.astype(np.float32)
        attention = softmax(4*semantic + 2*overlap)
        evidence = attention @ state_vectors
        extra = []
        for i,(w,desc) in enumerate(zip(ow,descriptions)):
            best = int(np.argmax(semantic[i]+overlap[i])); sw = state_words[best]
            nums = {v for v in w if v.isdigit()}
            extra.append([overlap[i].max(), semantic[i].max(), float(opts[i]@global_state), float(q@global_state),
                          len(sw&qw)/max(1,len(qw)), len(nums&sw)/max(1,len(nums)),
                          float(desc.lower() in ' '.join(texts).lower()), float(bool(sw&{'no','not','never','without'})),
                          i/max(1,len(keys)-1) if question['type']=='score' else 0.,
                          len(texts)/256., float(len(w))/64., float(question['type']=='noul' and i==1)])
        typevec = np.tile(np.eye(3,dtype=np.float32)[KINDS[question['type']]], (len(keys),1))
        base = np.concatenate([np.tile(q,(len(keys),1)), opts, evidence, evidence*opts, np.abs(evidence-opts),
                               q[None,:]*opts, np.asarray(extra,dtype=np.float32), typevec], axis=1)
        return keys, base, global_state, q, opts, lexical.astype(np.float32)

    def head(self, base, global_state):
        latent = np.tanh(global_state @ self.weights['sw'].T + self.weights['sb'])
        x = np.concatenate([base,np.tile(latent,(len(base),1))],axis=1).astype(np.float32)
        if self.quantized is not None:
            with self.torch.inference_mode(): return self.quantized(self.torch.from_numpy(x)).numpy().reshape(-1)
        for i in (1,2,3):
            x = x @ self.weights[f'w{i}'].T + self.weights[f'b{i}']
            if i<3: x = np.maximum(x,0)
        return x.reshape(-1)

    def retrieve(self, q, state, options, kind, exclude_case=None):
        data = self.retrieval
        if data is None: return np.full(len(options),1/len(options),dtype=np.float32), 0.
        sims = .55*(data['q']@q) + .45*(data['state']@state)
        valid = data['kind'] == KINDS[kind]
        if exclude_case is not None: valid &= data['case'] != exclude_case
        sims = np.where(valid,sims,-10.)
        indices = np.argsort(sims)[-4:][::-1]
        confidence = max(0.,float(sims[indices[0]]))
        result = np.zeros(len(options),dtype=np.float32)
        weights = softmax(8*sims[indices])
        for weight,index in zip(weights,indices):
            n = int(data['n'][index]); src = data['options'][index,:n]
            if kind in {'noul','score'} and n==len(options): mapped = data['p'][index,:n]
            else: mapped = softmax(8*(options@src.T)) @ data['p'][index,:n]
            result += weight * mapped / max(mapped.sum(),1e-6)
        return result/max(result.sum(),1e-6), confidence

    def predict(self, state, questions, cache=True):
        started=time.perf_counter(); answers={}; features={}; hits=0; clipped=0; paths={}
        for qid, question in questions.items():
            observed={k:state.get(k) for k in question['view']} if question.get('view') and isinstance(state,dict) else state
            encoded,hit=self.state(observed,cache); hits+=hit; clipped+=encoded[3]
            cheap_only = self.variant in {'lexical','conditional','retrieval-only'}
            keys, base, global_state, q, opts, lexical = self.features(encoded,question,include_head=not cheap_only)
            cheap = softmax(lexical); margin = np.sort(cheap)[-1]-np.sort(cheap)[-2]
            early = self.variant=='conditional' and margin >= self.manifest['early_exit_margin']
            if self.variant=='lexical' or early: p=cheap; path='shared_lexical'
            elif self.variant=='retrieval-only':
                p,_=self.retrieve(q,global_state,opts,question['type']);path='train_case_retrieval'
            else:
                if base is None:
                    keys, base, global_state, q, opts, lexical = self.features(encoded,question)
                logits=self.head(base,global_state)
                if self.variant in {'retrieval','conditional','int8'}:
                    rp, confidence=self.retrieve(q,global_state,opts,question['type'])
                    alpha=self.manifest['retrieval_weight'] * max(0.,(confidence-self.manifest['retrieval_gate'])/max(1e-6,1-self.manifest['retrieval_gate']))
                    logits=logits + alpha*np.log(np.maximum(rp,1e-6))
                p=softmax(logits); path='typed_head_int8' if self.variant=='int8' else 'typed_head'
            probs=dict(zip(keys,map(float,p)))
            answers[qid]={**native_answer(question,probs),'confidence':float(p.max()), 'confidence_kind':'distilled_not_calibrated'}
            # Preserve the existing Engine feature contract for scoped correction memory.
            features[qid]=np.tile(global_state,(len(keys),1)).copy(); paths[qid]=path
        return {'model':self.identity['model'],'answers':answers,'usage':{'input_tokens':0,'output_tokens':0},
                'runtime':{'total_ms':(time.perf_counter()-started)*1000,'execution':self.variant,'state_cache_hits':hits,
                           'truncated_state_chunks':clipped,'truncated_state_tokens':0,'paths':paths}},features
