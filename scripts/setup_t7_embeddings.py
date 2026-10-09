"""Fetch one pinned, bounded embedding model; never install packages."""
import hashlib
import json
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
FILES = {'config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt'}

if __name__ == '__main__':
    info = HfApi().model_info(MODEL, revision=REVISION, files_metadata=True)
    selected = [f for f in info.siblings if f.rfilename in FILES]
    size = sum(f.size or 0 for f in selected)
    if len(selected) != len(FILES) or any(f.size is None for f in selected) or size > 200_000_000:
        raise RuntimeError('Model inventory missing or exceeds 200 MB')
    target = Path(__file__).resolve().parents[1] / '.agent_control/t7/embedding-model'
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for file in selected:
        path = Path(hf_hub_download(MODEL, file.rfilename, revision=info.sha, local_dir=target))
        rows.append({'file': file.rfilename, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    receipt = {'id': MODEL, 'revision': info.sha, 'bytes': size, 'files': rows}
    (target / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(target), **receipt}))
