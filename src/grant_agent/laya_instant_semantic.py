"""Explicit, pinned optional CPU sentence encoder; no network or auto-download."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np


@lru_cache(maxsize=1)
def preload():
    directory = Path(os.environ['NEYVIA_INSTANT_SEMANTIC'])
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name in ('onnx/model_quantized.onnx', 'tokenizer.json'):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest['files'][name]['sha256']:
            raise ValueError('Sentence encoder bytes changed: ' + name)
    from .taste_vision import DEPS
    if str(DEPS) not in sys.path:
        sys.path.insert(0, str(DEPS))
    import onnxruntime as ort
    from tokenizers import Tokenizer
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(directory / 'onnx/model_quantized.onnx'), options,
                                   providers=['CPUExecutionProvider'])
    tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
    tokenizer.enable_truncation(256)
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return tokenizer, session, 'minilm-quantized:' + identity


def encode(text):
    tokenizer, session, identity = preload()
    tokens = tokenizer.encode(text)
    inputs = {'input_ids': np.asarray([tokens.ids], dtype=np.int64),
              'attention_mask': np.asarray([tokens.attention_mask], dtype=np.int64),
              'token_type_ids': np.asarray([tokens.type_ids], dtype=np.int64)}
    outputs = session.run(None, {i.name: inputs[i.name] for i in session.get_inputs()})
    hidden = outputs[0]
    mask = inputs['attention_mask'][..., None]
    vector = (hidden * mask).sum(axis=1)[0] / max(float(mask.sum()), 1)
    vector = np.asarray(vector, dtype=np.float32)
    return vector / max(float(np.linalg.norm(vector)), 1e-9), identity
