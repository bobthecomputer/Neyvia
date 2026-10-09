"""Soft reference matching; literal validation is reserved for verbatim quotes.

Adapted from Jina AI node-DeepResearch build-ref.ts (Apache-2.0), commit
fd323b521a51264d497bec333bfb997da1bf3210. The upstream algorithm chunks
claims/pages, ranks similarity, and retains references above a threshold.
This port uses lexical coverage (no embedding service or model download).
Similarity is a retrieval signal, never an assertion of semantic entailment.
"""
from __future__ import annotations
import hashlib
import re

from .research_pipeline import CITATION, STR, captured_quote, schema
from .research_quotes import STOP, span_options

SOFT_CITATION = schema({**CITATION["properties"], "kind": {"enum": ["paraphrase", "verbatim"]}})
ANSWER = schema({"answer": STR, "explanation": STR,
                 "citations": {"type": "array", "items": SOFT_CITATION}})
THRESHOLD = 0.35
COMMON = STOP | set("a an are as at be been by can could did do had he her his if in is it its more of on or she so such to until were will would not than then they them these those there through very we you year years".split())


def terms(text):
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w
            for w in re.findall(r"\w{2,}", text.casefold()) if w not in COMMON}


def match(candidate, sources, receipt):
    citations, proof, allowance = [], [], {}
    for index, original in enumerate(candidate.get("citations", [])):
        citation = dict(original)
        source = next((s for s in sources if citation["url"] in {s["url"], s.get("requestedUrl")}), None)
        kind = citation.get("kind", "paraphrase")
        row, quote, score = None, "", 0.0
        if source:
            citation["url"] = source["url"]
            carriers = [source["fullText"], *[" ".join(r) for t in source["tables"] for r in t]]
            if kind == "verbatim":
                quote = next((q for text in carriers if (q := captured_quote(text, citation["quote"], minimum=1))), "")
                score = float(bool(quote))
            else:
                query = terms(citation["claim"])
                options = span_options(source, citation, limit=12)
                for option in options:
                    found = query & terms(option["surroundingContext"])
                    coverage = sum(3 if w.isdigit() else 1 for w in found) / max(1, sum(3 if w.isdigit() else 1 for w in query))
                    informative = {w for w in query if not w.isdigit()}
                    if len(found & informative) >= min(2, len(informative)) and informative and coverage > score:
                        row, score = option, coverage
                if row and score >= THRESHOLD:
                    quote = row["quote"]
        # Never present a paraphrase as a quotation. Copy only captured bytes.
        remaining = 25 - allowance.get(citation["url"], 0)
        words = list(re.finditer(r"\S+", quote))
        if len(words) > remaining:
            quote = quote[:words[remaining - 1].end()] if remaining > 0 and kind != "verbatim" else ""
        allowance[citation["url"]] = allowance.get(citation["url"], 0) + len(quote.split())
        citation["quote"] = quote
        citations.append(citation)
        proof.append({"citationId": index, "kind": kind, "url": citation["url"],
                      "status": "literal_verified" if quote and kind == "verbatim" else "lexical_match" if quote else "needs_more_evidence",
                      "score": round(score, 4), "threshold": 1.0 if kind == "verbatim" else THRESHOLD,
                      "sourceReceiptPath": source["receiptPath"] if source else None,
                      "spanId": row["spanId"] if row else None,
                      "quoteSha256": hashlib.sha256(quote.encode()).hexdigest() if quote else None})
    receipt["citationCapture"] = {"method": "Soft lexical coverage; exact captured spans only for verbatim quotations",
                                  "semanticEntailment": False, "references": proof,
                                  "accepted": bool(proof) and all(p["status"] != "needs_more_evidence" for p in proof)}
    return {**candidate, "citations": citations}
