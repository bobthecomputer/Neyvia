"""Isolated installed-library reader; stdin and stdout are JSON, never provider data."""
from __future__ import annotations

import json
import re
import sys


def read(request):
    from pypdf import PdfReader
    reader = PdfReader(request["path"])
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs need an unlocked local copy")
    count = len(reader.pages)
    result = {"pages": count, "engine": "pypdf"}
    if request["action"] == "extract":
        page = int(request["page"])
        if not 1 <= page <= count:
            raise ValueError("Page is outside this PDF")
        text = reader.pages[page - 1].extract_text() or ""
        limit = int(request.get("maxChars", 20000))
        result.update(page=page, text=text[:limit], totalChars=len(text), truncated=len(text) > limit)
    elif request["action"] == "search":
        query = str(request["query"])
        limit = int(request.get("maxHits", 500))
        hits = []
        if query:
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                # Search original text: casefold can expand Unicode characters
                # and shift citation offsets (observed in real RFC PDFs).
                for match in re.finditer(re.escape(query), text, re.IGNORECASE):
                    at = match.start()
                    if len(hits) >= limit:
                        result.update(hits=hits, truncated=True)
                        return result
                    hits.append({"page": number, "offset": at,
                                 "text": text[max(0, at - 30):match.end() + 60]})
        result.update(hits=hits, truncated=False)
    return result


def main():
    return read(json.load(sys.stdin))


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
