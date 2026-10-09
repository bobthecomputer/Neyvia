"""Redo a conflicted Git three-way text merge with normalized temporary inputs."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.agent_control/int2/merge'

def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for name in sys.argv[1:]:
        target = (ROOT / name).resolve()
        if not target.is_relative_to(ROOT):
            raise ValueError(name)
        inputs = []
        for stage in (2, 1, 3):
            data = subprocess.check_output(['git', 'show', f':{stage}:{name}'], cwd=ROOT)
            path = SCRATCH / (name.replace('/', '_') + f'.{stage}')
            path.write_bytes(data.replace(b'\r\n', b'\n'))
            inputs.append(str(path))
        result = subprocess.run(['git', 'merge-file', '-p', '-L', 'ours', '-L', 'base', '-L', 'theirs', *inputs],
                                cwd=ROOT, capture_output=True)
        if result.returncode not in range(128):
            raise RuntimeError(result.stderr.decode(errors='replace'))
        target.write_bytes(result.stdout)
        print(f'{name}: {result.returncode} conflict blocks')

if __name__ == '__main__':
    main()
