"""Compose reader-walk viewport pixels without changing the browser viewport."""
import argparse
import json
from pathlib import Path
from PIL import Image

parser=argparse.ArgumentParser()
parser.add_argument('--manifest',required=True)
args=parser.parse_args()
manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
canvas=Image.new('RGB',(manifest['width'],manifest['height']),'white')
for tile in manifest['tiles']:
    with Image.open(tile['path']) as image:
        keep=min(image.height,manifest['height']-tile['y'])
        canvas.paste(image.crop((0,0,manifest['width'],keep)),(0,tile['y']))
canvas.save(manifest['output'])
