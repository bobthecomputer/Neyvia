"""Persistent immutable fetched documents, bounded continuations and grounded citations."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


class WebDocuments:
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    # web.fetch admits PDFs up to 32 MiB; their original bytes stay retained.
    MAX_PDF_BYTES = 32 * 1024 * 1024

    def __init__(self, root: Path):
        self.path = root / ".agent_control" / "web_documents.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, url TEXT NOT NULL, fetched REAL NOT NULL, text TEXT NOT NULL, metadata TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS documents_url_time ON documents(url, fetched DESC)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, identity):
        if not re.fullmatch(r"doc_[a-f0-9]{64}", identity):
            raise ValueError("Use a returned document handle")
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("Unknown document handle in this workspace")
        return row["text"], json.loads(row["metadata"])

    def cached(self, url, max_age):
        with self.connect() as db:
            row = db.execute("SELECT id FROM documents WHERE url=? AND fetched>=? ORDER BY fetched DESC LIMIT 1",
                             (url, time.time() - max_age)).fetchone()
        return self.get(row["id"]) if row else None

    def save(self, url, text, metadata, data):
        limit = self.MAX_PDF_BYTES if data[:1024].find(b"%PDF-") != -1 and metadata.get("pdfExtraction") else self.MAX_RESPONSE_BYTES
        if not isinstance(data, bytes) or len(data) > limit:
            raise ValueError("Fetched response exceeds the native bounded body contract")
        content_hash = hashlib.sha256(data).hexdigest()
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        identity = "doc_" + hashlib.sha256((url + "\0" + content_hash + "\0" + text_hash).encode()).hexdigest()
        # Keep actual transport bytes, never a reconstruction of parsed text.
        # Exclusive publication preserves earlier observations and concurrent readers.
        directory = self.path.parent / "web_document_bodies"
        if directory.is_symlink() or directory.is_junction():
            raise ValueError("Fetched body owner must be an ordinary directory")
        directory.mkdir(exist_ok=True)
        destination = directory / (identity + ".bin")
        descriptor, temporary = tempfile.mkstemp(prefix=identity + ".", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if self.body(identity) != data:
                    raise ValueError("Immutable fetched response bytes have drifted")
        finally:
            Path(temporary).unlink(missing_ok=True)
        metadata = {**metadata, "document": identity, "contentSha256": content_hash,
                    "textSha256": text_hash, "characters": len(text), "fetchedAt": time.time()}
        with self.connect() as db:
            # Keep the first observation immutable; the URL cache timestamp can be refreshed.
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET fetched=excluded.fetched",
                       (identity, url, time.time(), text, json.dumps(metadata)))
        return self.get(identity)

    def body(self, identity):
        """Read bounded original HTTP bytes; legacy text-only records stay unproven."""
        if not re.fullmatch(r"doc_[a-f0-9]{64}", identity):
            raise ValueError("Use a returned document handle")
        directory = self.path.parent / "web_document_bodies"
        path = directory / (identity + ".bin")
        if directory.is_symlink() or directory.is_junction() or path.is_symlink() or path.is_junction():
            raise ValueError("Fetched response owner contains a redirected path")
        with path.open("rb") as source:
            data = source.read(self.MAX_PDF_BYTES + 1)
        if len(data) > (self.MAX_PDF_BYTES if data[:1024].find(b"%PDF-") != -1 else self.MAX_RESPONSE_BYTES):
            raise ValueError("Stored fetched response exceeds its observation bound")
        return data

    @staticmethod
    def citation(metadata, text, start, end):
        if not 0 <= start < end <= len(text) or end - start > 4000:
            raise ValueError("Citation must name a nonempty observed range up to 4000 characters")
        return {"document": metadata["document"], "url": metadata["finalUrl"],
                "title": metadata["title"], "contentSha256": metadata["contentSha256"],
                "textSha256": metadata["textSha256"], "start": start, "end": end,
                "quote": text[start:end]}

    def read(self, args):
        text, metadata = self.get(args["document"])
        offset = args.get("offset", 0)
        maximum = args.get("maxChars", 20000)
        if offset > len(text):
            raise ValueError("Continuation offset exceeds document length")
        end = min(len(text), offset + maximum)
        return {**metadata, "text": text[offset:end], "offset": offset,
                "nextOffset": end if end < len(text) else None, "truncated": end < len(text),
                "citation": self.citation(metadata, text, offset, end) if 0 < end - offset <= 4000 else None}

    def search(self, args):
        text, metadata = self.get(args["document"])
        query = args["query"].strip()
        if not query:
            raise ValueError("Passage search requires nonblank text")
        offset, limit, context = args.get("offset", 0), args.get("limit", 10), args.get("contextChars", 200)
        if offset > len(text):
            raise ValueError("Search offset exceeds document length")
        matches = []
        iterator = re.finditer(re.escape(query), text[offset:], flags=re.IGNORECASE)
        next_offset = None
        for match in iterator:
            if len(matches) == limit:
                next_offset = matches[-1]["matchEnd"]
                break
            start, end = offset + match.start(), offset + match.end()
            left, right = max(0, start - context), min(len(text), end + context)
            matches.append({"matchStart": start, "matchEnd": end,
                            **self.citation(metadata, text, left, right)})
        return {"document": metadata["document"], "query": query, "matches": matches,
                "count": len(matches), "nextOffset": next_offset, "complete": next_offset is None}

    def cite(self, args):
        text, metadata = self.get(args["document"])
        citation = self.citation(metadata, text, args["start"], args["end"])
        if "expectedText" in args and args["expectedText"] != citation["quote"]:
            raise ValueError("Citation quote does not match the cached source")
        return {"citation": citation}

    def dedupe(self, args):
        """Group identical observed text; keep every URL/hash observation.

        A shared URL alone is insufficient: its content can change. This is
        exact source deduplication, not semantic or near-duplicate matching.
        """
        groups = {}
        for identity in args["documents"]:
            text, metadata = self.get(identity)
            key = metadata["textSha256"] if text.strip() else identity
            group = groups.setdefault(key, {"document": identity, "textSha256": metadata["textSha256"], "members": []})
            group["members"].append({key: metadata[key] for key in
                ("document", "url", "finalUrl", "contentSha256", "textSha256")})
        return {"groups": list(groups.values()), "inputCount": len(args["documents"]),
                "uniqueCount": len(groups), "method": "exact-observed-text-sha256", "semanticMatching": False}


def tool_specs(spec_type):
    handle = {"type": "string", "pattern": "^doc_[a-f0-9]{64}$"}
    rows = [
        ("web.dedupe", "Group cached sources with identical observed text while preserving every source URL and content hash; no semantic matching.",
         {"documents": {"type": "array", "items": handle, "minItems": 1, "maxItems": 100}}, ["documents"]),
        ("web.read", "Continue a cached immutable web document without fetching again; offsets count Unicode characters.",
         {"document": handle, "offset": {"type": "integer", "minimum": 0},
          "maxChars": {"type": "integer", "minimum": 1, "maximum": 100000}}, ["document"]),
        ("web.passages", "Find literal text in a cached document and return bounded passages with source URL, hashes and exact citation ranges.",
         {"document": handle, "query": {"type": "string", "minLength": 1, "maxLength": 1000},
          "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50},
          "contextChars": {"type": "integer", "minimum": 0, "maximum": 1000}}, ["document", "query"]),
        ("web.cite", "Return an exact quote and source identity for a cached passage; optionally verify expectedText.",
         {"document": handle, "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1},
          "expectedText": {"type": "string", "maxLength": 4000}}, ["document", "start", "end"]),
    ]
    return [spec_type(name=name, description=description, category="web", mutability_class="read",
                      capabilities=("web.document", "web.citation"), input_schema={"type": "object",
                      "additionalProperties": False, "properties": properties, "required": required})
            for name, description, properties, required in rows]
