"""Local CPU sentence embeddings with explicit availability and bounded caches."""
from __future__ import annotations
import hashlib
import json
import threading

from .sidebar_model_assets import MODEL_ID, ensure_model, model_path, validate
_lock = threading.Lock()
_models = {}

def source_identity():
    """Return the current local model identity only after checking every byte."""
    path = model_path()
    receipt = validate(path)
    receipt_bytes = (path / 'receipt.json').read_bytes()
    identities = [(row['file'], row['size'], row['sha256']) for row in receipt['files']]
    identity = hashlib.sha256(json.dumps([str(path), hashlib.sha256(receipt_bytes).hexdigest(), identities],
                                         sort_keys=True).encode()).hexdigest()
    return path, receipt, identity


def encode(service, texts):
    ensure_model()
    path, receipt, identity = source_identity()
    cache_key = (str(path), identity)
    with _lock:
        if cache_key not in _models:
            # No remote code or download. Source bytes are bound to this cache entry.
            import torch
            from transformers import AutoModel, AutoTokenizer
            torch.set_num_threads(min(4, torch.get_num_threads()))
            _models[cache_key] = (AutoTokenizer.from_pretrained(path, local_files_only=True, token=False),
                                  AutoModel.from_pretrained(path, local_files_only=True, token=False, trust_remote_code=False).cpu().eval())
        tokenizer, model = _models[cache_key]
        import torch
        vectors = []
        for start in range(0, len(texts), 16):
            batch = tokenizer(texts[start:start + 16], padding=True, truncation=True, max_length=256, return_tensors='pt')
            with torch.inference_mode():
                output = model(**batch).last_hidden_state
                mask = batch['attention_mask'].unsqueeze(-1).float()
                pooled = (output * mask).sum(1) / mask.sum(1).clamp(min=1)
                vectors.extend(torch.nn.functional.normalize(pooled, p=2, dim=1).tolist())
    if source_identity()[2] != identity:
        raise ValueError('Sidebar model changed while encoding')
    return vectors, {'id': receipt['id'], 'revision': receipt['revision'], 'device': 'cpu',
                     'sourceDigest': identity}

def similarity(a, b):
    return sum(x*y for x, y in zip(a, b))
