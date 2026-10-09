"""Calibrate the C13 frozen text judge without model calls or downloads."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from grant_agent.taste_judge import calibrate

parser = argparse.ArgumentParser()
parser.add_argument('--pairs', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
model = calibrate(args.pairs)
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(model, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps({'modelSha256': model['modelSha256'], 'dataSha256': model['dataSha256'],
                  **{k: v for k, v in model['calibration'].items() if k != 'folds'}}))
