"""Public-source research on shared Obscura tabs, with grounded cascade answers.

Search is the existing native web tool, not a second search service. Search's
MIT browser design is inherited through BrowserService's profiles/shared tabs;
the macOS Swift browser is not a Windows search provider. Pages remain untrusted.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from queue import Queue
from pathlib import Path
from urllib.parse import urlsplit

from .autopilot_model import decide
from .laya_service import browser_decide
from .native_tools import NativeToolRegistry
from .neyvia_browser import service_for
from .research_sources import explicit_as_of, resolve_wikipedia
from .transition_memory import atomic_json


def schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STR = {"type": "string"}
QUERIES = {"type": "array", "items": STR}
CITATION = schema({"url": {"type": "string", "maxLength": 2000}, "quote": {"type": "string", "maxLength": 1200},
                   "claim": {"type": "string", "maxLength": 1000}})
ANSWER = schema({"answer": STR, "explanation": STR, "citations": {"type": "array", "items": CITATION}})
PLAN = schema({"queries": QUERIES})
REVIEW = schema({"sufficient": {"type": "boolean"}, "missing": STR, "queries": QUERIES,
                 "facts": {"type": "array", "items": CITATION}})
CHECK = schema({"accepted": {"type": "boolean"}, "issues": STR})
QUOTE_FIX = schema({"citations": {"type": "array", "items": CITATION}})


def normalized(text):
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def source_access_problem(title, text):
    opening = normalized(str(title) + " " + text[:1500])
    if ("security verification" in opening and ("not a bot" in opening or "blocked" in opening)
            or "just a moment" in normalized(title) and "verif" in opening):
        return "Observed security verification page, not source content; use another accessible source"
    return None


def captured_quote(text, quote, *, minimum=12):
    """Recover a contiguous source span when HTML adds punctuation whitespace.

    Words, numbers, punctuation and their order must all match. Return actual
    source bytes as text; never assemble nonadjacent passages or paraphrases.
    """
    tokens = re.findall(r"\w+|[^\w\s]", quote)
    if len(normalized(quote)) < minimum or not tokens:
        return None
    pattern = []
    for index, token in enumerate(tokens):
        if index:
            previous = tokens[index - 1]
            pattern.append(r"\s+" if previous[-1].isalnum() and token[0].isalnum() else r"\s*")
        pattern.append(re.escape(token))
    expression = (r"\b" if tokens[0][0].isalnum() else "") + "".join(pattern)
    expression += r"\b" if tokens[-1][-1].isalnum() else ""
    match = re.search(expression, text, re.IGNORECASE)
    return match.group(0) if match else None


INFERENCE_RULES = (
    "Resolve attributes in the role and time named by the question: use the person's established public name "
    "in that role unless a birth name is explicitly requested. For sporting career records, use documented "
    "professional records unless the question explicitly includes amateur competition; distinguish unsupported anecdotes. "
    "Prefer primary biographies for birthplace and preserve their stated geographic granularity; do not invent a narrower locality. "
    "A dated law or status continues until a documented change; an as-of answer need not come from a page published on that exact day. "
    "For historical year-span questions, report the calendar-year difference first and separately explain any completed-anniversary age. "
    "Recompute each arithmetic expression and compare event month/day with the birthday; a correct final number does not excuse a contradictory derivation. "
    "Describe an assumed counting convention as an assumption, never as explicitly requested. "
)


def public_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    import ipaddress
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) sources without credentials are allowed")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        raise ValueError("Local sources are outside public research scope")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("Private network sources are outside public research scope")
    except ValueError as exc:
        if "Private network" in str(exc):
            raise
    if any(part in url.lower() for part in ("datasets/google/frames-benchmark", "c10-tasks", "simpleqa_verified.csv", "browsecomp_plus.json")):
        raise ValueError("Benchmark reference leakage refused")
    if "artificialanalysis.ai/microevals" in url.lower():
        raise ValueError("Benchmark answer mirror refused")
    return url


def passages(text, queries, limit=10000, *, ranked_first=False):
    """Retain the introduction and relevant adjacent paragraphs, in source order."""
    # Some headless sites expose the entire article as one text node. Sliding
    # windows keep late facts reachable instead of silently taking its prefix.
    chunks = [text[i:i + 1000] for i in range(0, len(text), 800)]
    terms = set(re.findall(r"\w{4,}", " ".join(queries).casefold()))
    ranked = sorted(range(len(chunks)), key=lambda i: sum(t in chunks[i].casefold() for t in terms), reverse=True)
    chosen = set(range(min(1, len(chunks))))
    used = sum(len(chunks[i]) for i in chosen)
    for index in ranked:
        if index in chosen or used + len(chunks[index]) > limit:
            continue
        chosen.add(index)
        used += len(chunks[index])
    order = [i for i in ranked if i in chosen] if ranked_first else sorted(chosen)
    return "\n\n".join(chunks[i] for i in order)[:limit]


def source_context(sources, question, *, byte_limit=80000):
    """Bound text and table excerpts together; retain full observations in receipts."""
    rows = []
    complete_table_budget = min(20000, byte_limit // 3)
    terms = set(re.findall(r"\w{4,}", question.casefold()))
    numbers = set(re.findall(r"\b\d+", question))
    for word, number in {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5"}.items():
        if re.search(r"\b" + word + r"\b", question, re.I):
            numbers.add(number)
    def relevance(source):
        observed = source.get("laya", {})
        decision = (observed.get("decision") or {}).get("answers", {}).get("relevance", {})
        value = decision.get("probabilities", {}).get("true") if observed.get("available") else None
        return value if isinstance(value, (int, float)) and 0 <= value <= 1 else .5
    # Advisory probabilities affect reading order only; no source is discarded
    # or accepted as factual because of an approximate System 1 judgment.
    for source in sorted(sources, key=relevance, reverse=True):
        tables = []
        for table in source["tables"]:
            if not table:
                continue
            def row_score(row):
                text = " ".join(row).casefold()
                return sum(word in text for word in terms) + 12 * bool(row and normalized(row[0]) in numbers)
            ordered = sorted(enumerate(table[1:], 1), key=lambda item: row_score(item[1]), reverse=True)
            table_bytes = len(json.dumps(table, ensure_ascii=False).encode())
            if table_bytes <= min(12000, complete_table_budget) and any(row_score(row) > 0 for row in table):
                tables.append({"header": table[0], "rows": table[1:], "rowIndices": list(range(1, len(table))),
                               "completeCapturedTable": True, "capturedRows": len(table)})
                complete_table_budget -= table_bytes
                continue
            selected, used = [], 0
            for index, row in ordered:
                if row_score(row) <= 0 or len(selected) >= 8:
                    continue
                if used + len(json.dumps(row, ensure_ascii=False)) > 1800:
                    continue
                selected.append((index, row)); used += len(json.dumps(row, ensure_ascii=False))
            tables.append({"header": table[0], "rows": [row for index, row in sorted(selected)],
                           "rowIndices": [index for index, row in sorted(selected)], "completeCapturedTable": False,
                           "capturedRows": len(table)})
        tables.sort(key=lambda t: sum(word in json.dumps(t, ensure_ascii=False).casefold() for word in terms)
                    + 12 * sum(bool(row and normalized(row[0]) in numbers) for row in t["rows"]), reverse=True)
        rows.append({"url": source["url"], "title": source["title"],
                     "text": passages(source["text"], [question], 6000, ranked_first=True), "tableExcerpts": tables[:2],
                     "excerpted": True, "sourceTruncated": source.get("truncated", True), "fullObservation": source["receiptPath"]})
        rows[-1]["advisoryRelevance"] = relevance(source)
    context = json.dumps(rows, ensure_ascii=False)
    while len(context.encode()) > byte_limit:
        largest = max(rows, key=lambda row: len(row["text"]))
        if len(largest["text"]) <= 300:
            raise ValueError("Observed source identities exceed the research context budget")
        largest["text"] = largest["text"][:max(300, len(largest["text"]) // 2)]
        context = json.dumps(rows, ensure_ascii=False)
    return context


def citation_context(sources, citations):
    """Give the checker actual surrounding text, including late article passages."""
    rows = []
    for citation in citations:
        source = next((s for s in sources if s["url"] == citation["url"]), None)
        if source is None:
            continue
        text, quote = normalized(source["fullText"]), normalized(citation["quote"])
        at = text.find(quote)
        tables = []
        for table in source["tables"]:
            for index, row in enumerate(table):
                if quote in normalized(" ".join(row)):
                    tables.append({"header": table[0], "rowIndex": index,
                                   "neighborRows": table[max(0, index - 1):index + 2]})
        rows.append({"url": source["url"], "claim": citation["claim"],
                     "actualSurroundingText": text[max(0, at - 1000):at + len(quote) + 1800] if at >= 0 else "",
                     "actualTableRows": tables[:2]})
    return json.dumps(rows, ensure_ascii=False)[:60000]


class ResearchPipeline:
    def __init__(self, root, *, obscura_port, rounds=5, sources_per_round=3, timeout=600):
        from .browser_obscura import proof_ports
        if type(obscura_port) is not int or obscura_port not in proof_ports():
            raise ValueError("Research Obscura must use an explicit port inside the caller-assigned NEYVIA_BROWSER_PROOF_PORTS range")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.source_binding = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                               for name in ("research_pipeline.py", "autopilot_model.py", "browser_obscura.py",
                                            "neyvia_browser.py", "public_web_search.py", "laya_service.py", "research_sources.py", "native_tools.py", "research_quotes.py")}
        self.registry = NativeToolRegistry(self.root)
        self.browser = service_for(self.root)
        self.rounds, self.sources_per_round, self.timeout = rounds, sources_per_round, timeout
        self.owns_runtime = self.browser.headless is None
        if not self.owns_runtime and self.browser.headless.status()["port"] != obscura_port:
            raise ValueError("Existing browser runtime has a different explicit port")
        self.runtime = self.browser.request("headless.start", {"port": obscura_port}, owner=True)
        if self.browser.laya_client is not None:
            # Research permits CPU advisory work to take longer than a UI click.
            self.browser.laya_client.hook.timeout_s = min(30, timeout)
            self.browser.laya_client.hook.max_age_ms = min(30000, timeout * 1000)
            self.browser.laya_health_timeout = min(30, timeout)
        self.slots = Queue()
        existing = self.browser.state["spaces"]
        for index in range(4):
            name = "Research worker " + str(index)
            space = next((row for row in existing if row["name"] == name), None)
            if space is None:
                profile = self.browser.request("profile.create", {"name": name}, owner=True)
                space = self.browser.request("space.create", {"name": name, "profileId": profile["id"]}, owner=True)
            self.slots.put(space["id"])

    def close(self):
        if self.owns_runtime:
            self.browser.request("headless.stop", owner=True)

    def acquire(self, url, profile, question, queries, destination, as_of=None):
        public_url(url)
        historical = resolve_wikipedia(self.registry, url, as_of)
        if historical["status"] == "unavailable":
            raise ValueError("Historical source unavailable: " + historical["reason"])
        opened = self.browser.request("tab.open", {"url": historical["url"], "engine": "obscura", "readerMode": True, "spaceId": profile}, owner=True)
        tab_id = opened["tabId"]
        try:
            observation = self.browser.request("observe", {"tabId": tab_id, "cached": False})
            text = observation.get("text", "")
            problem = source_access_problem(observation.get("title", ""), text)
            if problem:
                raise ValueError(problem)
            document = None
            if urlsplit(url).path.lower().endswith(".pdf") or text.lstrip().startswith("%PDF-"):
                fetched = self.registry.call("web.fetch", {"url": observation["url"], "maxChars": 100000})
                if not fetched.get("ok") or not fetched["result"].get("pdfExtraction"):
                    raise ValueError("PDF source has no bounded extracted text: " + str(fetched.get("error", "not a PDF")))
                data = fetched["result"]
                document = {"representation": "Native pypdf text; not browser DOM text", "receiptPath": fetched.get("receipt_path"),
                            "document": data["document"], "pdfExtraction": data["pdfExtraction"], "textSha256": data["textSha256"],
                            "truncated": data["truncated"], "obscuraTextSha256": hashlib.sha256(text.encode()).hexdigest()}
                text = data["text"]
            actual_question = question.rsplit("\n\n", 1)[-1].strip()
            if len(actual_question) > 80 and normalized(actual_question[:120]) in normalized(text):
                raise ValueError("Exact benchmark-question mirror refused before model context")
            evidence = passages(text, [question, *queries])
            # Real typed LAYA evidence. Low confidence never discards a source.
            try:
                judgment = browser_decide(self.browser, {"tabId": tab_id, "question": "relevance",
                                                        "context": {"goal": actual_question, "query": " ".join(queries),
                                                                    "result": {"title": observation["title"],
                                                                               "text": normalized(passages(text, [actual_question, *queries], 1800, ranked_first=True))}}})
            except ValueError as exc:
                judgment = {"available": False, "reason": str(exc), "status": "projection_refused"}
            if len(text.strip()) < 40:
                raise ValueError("Obscura returned no useful source text")
            compact = {key: observation.get(key) for key in
                       ("url", "title", "text", "tables", "truncated", "revision", "engine", "automation", "readyState")}
            compact["text"] = text
            if document:
                compact["documentExtraction"] = document
                compact["truncated"] = document["truncated"]
            atomic_json(destination, {"projection": compact, "laya": judgment, "historical": historical})
            return {"url": observation["url"], "requestedUrl": url, "title": observation["title"],
                    "text": evidence, "fullText": text, "tables": observation.get("tables", []), "revision": observation["revision"],
                    "receiptPath": str(destination), "laya": judgment, "historical": historical, "documentExtraction": document,
                    "truncated": compact["truncated"]}
        finally:
            self.browser.request("tab.close", {"tabId": tab_id}, owner=True)

    def run(self, question, *, request_id=None, resume_receipt=None, mode="grounded"):
        from .research_sol import run
        if resume_receipt is not None:
            raise ValueError("Use a fresh Sol seed; previous source/answer runs are not resumed")
        return run(self, question, request_id or uuid.uuid4().hex, mode=mode)


def call(workspace, name, args):
    root = Path(workspace.bus.root).resolve()
    if name == "research.receipt":
        path = Path(args["path"])
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(root) or path.name != "receipt.json" or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Choose a bounded research receipt in the selected workspace")
        return json.loads(path.read_text(encoding="utf-8"))
    if name == "research.journey":
        from .research_journey import run
        return run(root, args["question"], obscura_port=args.get("obscuraPort"), max_sources=args.get("maxSources", 4),
                   vertical=args.get("vertical", "web"), answer_model=args.get("answerModel", "extractive"),
                   timeout_seconds=args.get("timeoutSeconds", 120), request_id=args.get("requestId"))
    pipeline = ResearchPipeline(root, obscura_port=args["obscuraPort"], rounds=args.get("rounds", 3),
                                timeout=args.get("timeoutSeconds", 600))
    try:
        return pipeline.run(args["question"])
    finally:
        pipeline.close()
