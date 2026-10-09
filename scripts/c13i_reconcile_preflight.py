"""Preserve the unmatched old-checker experiment and restore a matched seed."""
from pathlib import Path
import hashlib
import json
import shutil
REPO=Path(__file__).resolve().parents[1]
PROOF=REPO/'proof/r12';RAW=Path('D:/NeyviaRuns/r12')


def main():
    receipt=[]
    for base,source,dest in [(RAW,RAW/'sol-alone/T2',RAW/'diagnostics/sol-T2-old-checker'),
                             (PROOF,PROOF/'sol-alone/T2',PROOF/'diagnostics/sol-T2-old-checker')]:
        source=source.resolve();dest=dest.resolve();boundary=base.resolve()
        if not source.is_relative_to(boundary) or not dest.is_relative_to(boundary) or source==boundary:
            raise ValueError('Archive must stay inside this task\'s exact R12 directories')
        if dest.exists():raise ValueError('Existing diagnostic archive cannot be overwritten')
        if source.exists():
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(source),str(dest));receipt.append({'from':str(source),'to':str(dest)})
    summary=PROOF/'baseline/T2/summary.json';backup=summary.with_name('preflight-summary.json')
    if not backup.exists():shutil.copyfile(summary,backup)
    seed=PROOF/'seed/rare-ui.html';work=PROOF/'sol-alone/T2/work/rare-ui.html'
    work.parent.mkdir(parents=True,exist_ok=True);work.write_bytes(seed.read_bytes())
    result={'archives':receipt,'restoredSeedSha256':hashlib.sha256(work.read_bytes()).hexdigest(),
            'matchedCriteria':'Both repair arms now use the same corrected font vocabulary.'}
    (PROOF/'preflight-reconciliation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
