"""Preserve referenced public C10 attempts and account for observed model calls."""
import hashlib
import json
from pathlib import Path
import zipfile

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "scripts/evidence"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def allowed(path):
    return (path.is_relative_to(EVIDENCE) and path.suffix == ".json" and path.is_file()
            and any(part.startswith(("C10-runs", "C10-native")) for part in path.relative_to(EVIDENCE).parts)
            and "/.neyvia/browser/" not in path.as_posix())


def references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (key.endswith("Path") or key in {"receipt_path", "originalReceipt", "path"}):
                path = Path(item)
                if path.is_absolute() and allowed(path.resolve()):
                    yield path.resolve()
            yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def main():
    files = set()
    for directory in (EVIDENCE / "C10-runs").iterdir():
        if directory.is_dir():
            files.update(p.resolve() for p in directory.glob("*.json"))
            for owner in ("neyvia", "openai", "scores"):
                files.update(p.resolve() for p in (directory / owner).rglob("*.json"))
            files.update(p.resolve() for p in (directory / "citation-docs").glob("reuse-manifest.json"))
    files.update(p.resolve() for p in EVIDENCE.glob("C10-native*.json"))
    pending = list(files)
    while pending:
        for path in references(read(pending.pop())):
            if path not in files:
                files.add(path)
                pending.append(path)
    rates = read(REPO / "config/scroll-study-prices.json")
    calls = {}
    for path in files:
        receipt = read(path)
        for index, model in enumerate(receipt.get("models", [])):
            key = model.get("receiptPath") or f"{receipt.get('receiptPath', path)}:unknown:{index}"
            identity = json.dumps({k: model.get(k) for k in ("model", "tokens", "receiptPath")}, sort_keys=True)
            if key in calls and calls[key]["identity"] != identity:
                raise ValueError("Conflicting model-call accounting: " + key)
            tokens, rate = model.get("tokens"), rates.get(model.get("model"))
            usd = None
            if tokens and rate and all(isinstance(tokens.get(k), (int, float)) for k in ("input", "cachedInput", "output")):
                usd = ((tokens["input"] - tokens["cachedInput"]) * rate["input"] + tokens["cachedInput"] * rate["cached"] + tokens["output"] * rate["output"]) / 1e6
            calls[key] = {"identity": identity, "model": model.get("model"), "tokens": tokens, "usd": usd}
    manifest = {str(path.relative_to(REPO)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    archive = EVIDENCE / "C10-development-public.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(files):
            bundle.write(path, str(path.relative_to(REPO)).replace("\\", "/"))
        bundle.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name, expected in manifest.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == expected, name
    unknown = sum(call["usd"] is None for call in calls.values())
    report = {"schema": "neyvia.c10-development-archive.v1", "archive": str(archive.relative_to(REPO)),
              "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "archiveBytes": archive.stat().st_size,
              "publicFiles": len(files), "manifest": manifest, "modelCallsDeduplicated": len(calls),
              "unobservedUsageOrPriceCalls": unknown, "observedKnownApiEquivalentUsd": sum(c["usd"] or 0 for c in calls.values()),
              "completeApiEquivalentUsd": None if unknown else sum(c["usd"] for c in calls.values()),
              "costScope": "All referenced research/provider attempts, deduplicated by actual model receipt; evaluation judge overhead is separate; API equivalent is not an invoice",
              "boundary": "Public referenced JSON only; no browser profiles/cookies/storage, credentials, SQLite caches, binary PDFs or video; incomplete attempts remain incomplete"}
    (EVIDENCE / "C10-development.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}))


if __name__ == "__main__":
    main()
