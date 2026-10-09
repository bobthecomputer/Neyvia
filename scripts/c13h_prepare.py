"""Acquire bounded, licensed local taste assets; no credentials or global installs."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / '.agent_control/c13h-assets'
LIMIT = 200_000_000


def fetch(url, path, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            size = int(response.headers.get('Content-Length') or 0)
            if size > LIMIT or expected and expected > LIMIT:
                raise ValueError('Download above 200 MB refused')
            temporary = path.with_suffix(path.suffix + '.partial')
            count = 0
            with temporary.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > LIMIT:
                        raise ValueError('Stream above 200 MB refused')
                    output.write(chunk)
            if expected and count != expected:
                raise ValueError('Unexpected asset length')
            temporary.replace(path)
    return {'url': url, 'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    entries = []
    sources = [
        ('clip/LICENSE', 'https://raw.githubusercontent.com/openai/CLIP/main/LICENSE', 'MIT', None),
        ('clip/README.md', 'https://huggingface.co/Xenova/clip-vit-base-patch32/raw/main/README.md', 'MIT (upstream CLIP)', None),
        ('clip/vision.onnx', 'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx', 'MIT (upstream CLIP)', 89117001),
        ('public/uicrit-README.md', 'https://raw.githubusercontent.com/google-research-datasets/uicrit/main/README.md', 'CC-BY-4.0', None),
        ('public/uicrit.csv', 'https://raw.githubusercontent.com/google-research-datasets/uicrit/main/uicrit_public.csv', 'CC-BY-4.0', 4929452),
        ('public/enrico-LICENSE', 'https://raw.githubusercontent.com/luileito/enrico/master/LICENSE', 'MIT', None),
        ('public/enrico-README.md', 'https://raw.githubusercontent.com/luileito/enrico/master/README.md', 'MIT', None),
        ('public/enrico-issues.csv', 'https://raw.githubusercontent.com/luileito/enrico/master/issues.csv', 'MIT', None),
        ('public/enrico-topics.csv', 'https://raw.githubusercontent.com/luileito/enrico/master/design_topics.csv', 'MIT', None),
        ('public/enrico-screenshots.zip', 'https://userinterfaces.aalto.fi/enrico/resources/screenshots.zip', 'MIT', None),
    ]
    # Read and retain notices before downloading dictionaries and weights.
    for lang in ('en', 'fr'):
        base = 'https://raw.githubusercontent.com/wooorm/dictionaries/main/dictionaries/' + lang + '/'
        sources.insert(0, (f'dictionaries/{lang}/license', base + 'license', 'SCOWL notices' if lang == 'en' else 'MPL-2.0', None))
        for suffix in ('aff', 'dic'):
            sources.append((f'dictionaries/{lang}/index.{suffix}', base + 'index.' + suffix,
                            'SCOWL notices' if lang == 'en' else 'MPL-2.0', None))
    for name, url, license_name, size in sources:
        receipt = fetch(url, ASSETS / name, size)
        entries.append({**receipt, 'license': license_name})
        print(name, receipt['bytes'], flush=True)
    target = ROOT / 'proof/r11/assets.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'schema': 'neyvia.taste-assets.v1', 'assets': entries,
        'excluded': [{'name': 'UIClip', 'bytes': 605156676, 'reason': 'Above 200 MB'},
                     {'name': 'JitterWeb', 'reason': 'No dataset license in published card; not inferred from model MIT'},
                     {'name': 'UI-Lens', 'reason': 'CC-BY-4.0, gated access requires owner acceptance'},
                     {'name': 'UI-Defect-Benchmark', 'reason': 'Noncommercial license'}]}, indent=2))


if __name__ == '__main__':
    main()
