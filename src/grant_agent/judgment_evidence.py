"""Judgment kinds and evidence binding.

A manual separates three kinds of decision:
  deterministic check  C lines / manual `checks`: a tool observation decides, nobody is asked.
  model judgment       J with kind "model": an autonomous critic answers, but only against current evidence.
  human decision       J with kind "human" (the default): an operator must choose.

A model judgment is evidence-bound: the answer carries `path#sha256` of a screenshot or artifact that
exists now, hashes to the stated value, and is not older than the outputs being judged. A recorded
answer alone (a J line, a decision option) never substitutes for that evidence.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

KINDS = ("human", "model")
EVIDENCE_KINDS = ("screenshot", "artifact")
SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_ref(ref) -> tuple[str, str]:
    """`path#sha256` (string) or {path, sha256} -> (path, sha256); ("", "") when malformed."""
    if isinstance(ref, dict):
        return str(ref.get("path") or ""), str(ref.get("sha256") or "")
    if isinstance(ref, str) and "#" in ref:
        path, _, digest = ref.rpartition("#")
        return path, digest
    return "", ""


def verify(ref, required, bases, outputs=()) -> tuple[bool, str]:
    """Is `ref` current evidence of one of the `required` kinds?

    bases: directories a relative evidence path may resolve against (the first match wins).
    outputs: files being judged; evidence older than any of them is stale."""
    path, digest = parse_ref(ref)
    if not path or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        return False, "evidence must be path#sha256 of a file that exists now"
    candidate = Path(path)
    resolved = candidate if candidate.is_absolute() else next((Path(b) / candidate for b in bases if (Path(b) / candidate).is_file()), None)
    if resolved is None or not Path(resolved).is_file():
        return False, "evidence file not found"
    if sha256_file(resolved) != digest.lower():
        return False, "evidence hash does not match the file"
    kinds = set(required or ())
    is_shot = Path(resolved).suffix.lower() in SCREENSHOT_SUFFIXES
    if kinds and not ((is_shot and "screenshot" in kinds) or ("artifact" in kinds)):
        return False, "evidence must be a " + "/".join(sorted(kinds))
    try:
        stamp = Path(resolved).stat().st_mtime
        if any(Path(out).stat().st_mtime > stamp + 1 for out in outputs if Path(out).exists() and Path(out).resolve() != Path(resolved).resolve()):
            return False, "evidence is older than the output it judges"
    except OSError:
        return False, "evidence cannot be read"
    return True, ""
