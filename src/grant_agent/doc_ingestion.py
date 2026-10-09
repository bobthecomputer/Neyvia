from __future__ import annotations

import json
import os
import hashlib
import threading
import uuid
from functools import wraps
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from .proofs_b_desktop import checked


@dataclass
class DocEvidence:
    source: str
    kind: str
    status: str
    chars: int
    excerpt: str
    error: str = ""


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _excerpt(text: str, max_chars: int = 500) -> str:
    return text[:max_chars].replace("\n", " ").strip()


def _read_url(source: str, timeout_seconds: int = 10) -> DocEvidence:
    request = Request(source, headers={"User-Agent": "grant-agent-harness/0.1"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            raw = response.read(20000)
        text = raw.decode("utf-8", errors="ignore")
        return DocEvidence(
            source=source,
            kind="url",
            status="ok",
            chars=len(text),
            excerpt=_excerpt(text),
        )
    except (URLError, TimeoutError, OSError) as exc:
        return DocEvidence(
            source=source,
            kind="url",
            status="error",
            chars=0,
            excerpt="",
            error=str(exc),
        )


def _read_file(source: str, repo_path: Path) -> DocEvidence:
    path = Path(source)
    if not path.is_absolute():
        path = (repo_path / source).resolve()
    try:
        text = path.read_text(encoding="utf-8")
        return DocEvidence(
            source=str(path),
            kind="file",
            status="ok",
            chars=len(text),
            excerpt=_excerpt(text),
        )
    except OSError as exc:
        return DocEvidence(
            source=str(path),
            kind="file",
            status="error",
            chars=0,
            excerpt="",
            error=str(exc),
        )


@checked("desktop.docs.evidence")
def ingest_docs(docs: list[str], repo_path: Path, session_path: Path) -> list[DocEvidence]:
    records: list[DocEvidence] = []
    for source in docs:
        if _is_url(source):
            records.append(_read_url(source))
        else:
            records.append(_read_file(source, repo_path=repo_path))

    evidence_path = session_path / "docs_evidence.json"
    temporary = evidence_path.with_name(f".{evidence_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps([asdict(item) for item in records], indent=2), encoding="utf-8")
        os.replace(temporary, evidence_path)
    finally:
        temporary.unlink(missing_ok=True)
    return records


_EVIDENCE_LOCKS = tuple(threading.RLock() for _ in range(64))


def _serialized_evidence(function):
    @wraps(function)
    def invoke(docs, repo_path, session_path):
        from .harness_jobs import _exclusive_job_lock
        path = Path(session_path).resolve() / "docs_evidence.json"
        identity = os.path.normcase(str(path)).encode("utf-8")
        shard = int.from_bytes(hashlib.sha256(identity).digest()[:2], "big") % len(_EVIDENCE_LOCKS)
        # Keep admission and the existing durable postcondition under the same
        # lease. Readers never see a partially written JSON document, including
        # readers in another process; a stopped writer releases its OS guard.
        with _EVIDENCE_LOCKS[shard], _exclusive_job_lock(path, timeout_seconds=30):
            return function(docs, repo_path, session_path)
    return invoke


ingest_docs = _serialized_evidence(ingest_docs)
