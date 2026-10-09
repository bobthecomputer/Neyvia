"""Public search transports, with observed provider attribution and failures.

Order for general web search: an operator-configured SearXNG or Brave key
(optional), then DuckDuckGo's no-key HTML endpoint, then the narrower
Wikipedia index and the installed DDGS Yandex engine. Verticals use free,
no-key public APIs: OpenAlex and arXiv for scholarly work, GitHub for code
and Wikipedia for encyclopedia articles. Every attempt is recorded. A human
verification page is reported as such and never solved or bypassed.
"""
import html
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ElementTree
from urllib.parse import quote, urlencode, urlsplit

AGENT = "NeyviaAgent/1.0 (Automation; Public Research)"
VERTICALS = ("web", "scholarly", "code", "encyclopedia")
_DDG_LOCK = threading.Lock()
_DDG_LAST = [0.0]
_DDG_BLOCKED_UNTIL = [0.0]
_CHALLENGE = re.compile(r"anomaly-modal|bots use DuckDuckGo too|challenge-form|Unfortunately, bots", re.I)


def _engine_results(backend, query, limit):
    # DDGS.text silently falls back to auto for a disabled backend and its
    # optional network cache omits backend identity. Call the actual installed
    # engine so attribution never depends on the requested backend string.
    if backend == "yandex":
        from ddgs.engines.yandex import Yandex as Engine
    else:
        from ddgs.engines.bing import Bing as Engine
    if getattr(Engine, "disabled", False):
        raise RuntimeError("Installed DDGS engine is disabled; implicit auto fallback refused")
    engine = Engine(timeout=10)
    rows = engine.search(query) or []
    return [{"title": row.title, "url": row.href, "snippet": row.body}
            for row in rows if row.href][:limit]


def _ddg_interval():
    try:
        return max(0.0, float(os.environ.get("NEYVIA_DDG_MIN_INTERVAL_MS", "2500")) / 1000)
    except ValueError:
        return 2.5


def _duckduckgo(query, limit, request, parser_type):
    """One paced POST to the no-key HTML endpoint, honest agent identity.

    Requests from this process are spaced so a research burst stays within the
    endpoint's tolerance. A served verification page pauses the transport for
    this process; it is reported, never answered.
    """
    with _DDG_LOCK:
        now = time.monotonic()
        if now < _DDG_BLOCKED_UNTIL[0]:
            raise PermissionError("DuckDuckGo verification page served recently; transport paused, not bypassed")
        wait = _DDG_LAST[0] + _ddg_interval() - now
        if wait > 0:
            time.sleep(wait)
        try:
            data, _ = request("https://html.duckduckgo.com/html/", headers={
                "User-Agent": AGENT, "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html"}, body=urlencode({"q": query, "kl": "wt-wt"}).encode())
        finally:
            _DDG_LAST[0] = time.monotonic()
        page = data.decode("utf-8", errors="replace")
        if _CHALLENGE.search(page):
            _DDG_BLOCKED_UNTIL[0] = time.monotonic() + 60
            raise PermissionError("DuckDuckGo served a human-verification page; not solved or bypassed")
    parser = parser_type()
    parser.feed(page)
    rows, seen = [], set()
    for row in parser.results:
        url = row.get("url", "")
        host = urlsplit(url).netloc.lower()
        # Sponsored results redirect through DuckDuckGo's ad click endpoint.
        if not url.startswith(("http://", "https://")) or host.endswith("duckduckgo.com") or url in seen:
            continue
        seen.add(url)
        rows.append({"title": row.get("title", ""), "url": url, "snippet": row.get("snippet", "")})
    return rows[:limit]


def _wikipedia(query, limit, request):
    data, _ = request("https://en.wikipedia.org/w/api.php?" + urlencode(
        {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": limit}),
        headers={"User-Agent": AGENT})
    rows = json.loads(data.decode("utf-8"))["query"]["search"]
    return [{"title": row["title"], "url": "https://en.wikipedia.org/wiki/" + quote(row["title"].replace(" ", "_")),
             "snippet": html.unescape(re.sub("<[^>]+>", "", row["snippet"]))} for row in rows]


def _openalex(query, limit, request):
    data, _ = request("https://api.openalex.org/works?" + urlencode(
        {"search": query, "per-page": limit, "select": "id,doi,title,publication_year,abstract_inverted_index,primary_location"}),
        headers={"User-Agent": AGENT, "Accept": "application/json"})
    rows = []
    for work in json.loads(data.decode("utf-8")).get("results", []):
        index = work.get("abstract_inverted_index") or {}
        words = sorted((position, word) for word, positions in index.items() for position in positions)
        landing = ((work.get("primary_location") or {}).get("landing_page_url") or work.get("doi") or work.get("id") or "")
        if landing:
            rows.append({"title": str(work.get("title") or ""), "url": landing,
                         "snippet": " ".join(word for _, word in words)[:400],
                         "year": work.get("publication_year"), "doi": work.get("doi")})
    return rows[:limit]


def _arxiv(query, limit, request):
    data, _ = request("https://export.arxiv.org/api/query?" + urlencode(
        {"search_query": "all:" + query, "max_results": limit}), headers={"User-Agent": AGENT})
    atom = "{http://www.w3.org/2005/Atom}"
    rows = []
    for entry in ElementTree.fromstring(data).findall(atom + "entry"):
        url = (entry.findtext(atom + "id") or "").strip()
        if url:
            rows.append({"title": " ".join((entry.findtext(atom + "title") or "").split()), "url": url,
                         "snippet": " ".join((entry.findtext(atom + "summary") or "").split())[:400]})
    return rows[:limit]


def _github(query, limit, request):
    data, _ = request("https://api.github.com/search/repositories?" + urlencode({"q": query, "per_page": limit}),
                      headers={"User-Agent": AGENT, "Accept": "application/vnd.github+json"})
    return [{"title": row.get("full_name", ""), "url": row.get("html_url", ""), "snippet": str(row.get("description") or "")}
            for row in json.loads(data.decode("utf-8")).get("items", []) if row.get("html_url")][:limit]


def search(args, *, request, parser_type):
    started = time.monotonic()
    attempts = []
    def finish(provider, results, **extra):
        return {"query": query, "vertical": vertical, "provider": provider, "results": results,
                "elapsedMs": round((time.monotonic() - started) * 1000),
                "transportAttempts": attempts, **extra}
    def attempt(provider, function):
        before = time.monotonic()
        try:
            results = function()
        except Exception as exc:
            reason = str(exc) if isinstance(exc, PermissionError) else provider + " failed: " + type(exc).__name__ + ": " + str(exc)[:160]
            attempts.append({"provider": provider, "elapsedMs": round((time.monotonic() - before) * 1000),
                             "status": "challenge" if isinstance(exc, PermissionError) else "failed", "resultCount": 0, "reason": reason})
            failures.append(reason)
            return None
        attempts.append({"provider": provider, "elapsedMs": round((time.monotonic() - before) * 1000),
                         "status": "completed" if results else "empty", "resultCount": len(results)})
        if not results:
            failures.append(provider + " returned no results")
        return results or None
    query = str(args["query"]).strip()
    if not query:
        raise ValueError("Search needs a nonblank query")
    limit = max(1, min(int(args.get("limit") or 8), 20))
    vertical = str(args.get("vertical") or "web")
    if vertical not in VERTICALS:
        raise ValueError("Choose vertical web, scholarly, code or encyclopedia")
    failures = []
    if vertical == "scholarly":
        merged = []
        for provider, function in (("openalex", lambda: _openalex(query, limit, request)),
                                   ("arxiv", lambda: _arxiv(query, limit, request))):
            rows = attempt(provider, function) or []
            merged.extend({**row, "provider": provider} for row in rows)
        if not merged:
            raise RuntimeError("Scholarly search unavailable: " + "; ".join(failures))
        # Interleave so neither index monopolizes the first results.
        first = [row for row in merged if row["provider"] == "openalex"]
        second = [row for row in merged if row["provider"] == "arxiv"]
        ordered = [row for pair in zip(first, second) for row in pair] + first[len(second):] + second[len(first):]
        return finish("openalex+arxiv", ordered[:limit], transportFailures=failures)
    if vertical == "code":
        rows = attempt("github-repositories", lambda: _github(query, limit, request))
        if not rows:
            raise RuntimeError("Code search unavailable: " + "; ".join(failures))
        return finish("github-repositories", rows, transportFailures=failures)
    if vertical == "encyclopedia":
        rows = attempt("wikipedia-public-index", lambda: _wikipedia(query, limit, request))
        if not rows:
            raise RuntimeError("Encyclopedia search unavailable: " + "; ".join(failures))
        return finish("wikipedia-public-index", rows, scope="Encyclopedia only", transportFailures=failures)
    searxng = str(os.environ.get("NEYVIA_SEARXNG_URL") or os.environ.get("FLUXIO_SEARXNG_URL") or "").rstrip("/")
    if searxng:
        def via_searxng():
            data, _ = request(f"{searxng}/search?{urlencode({'q': query, 'format': 'json'})}", headers={"Accept": "application/json"})
            payload = json.loads(data.decode("utf-8", errors="replace"))
            return [{"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", "")}
                    for item in list(payload.get("results") or [])[:limit]]
        rows = attempt("searxng", via_searxng)
        if rows:
            return finish("searxng", rows, transportFailures=failures)
    brave_key = str(os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if brave_key:
        def via_brave():
            data, _ = request(f"https://api.search.brave.com/res/v1/web/search?{urlencode({'q': query, 'count': limit})}",
                              headers={"Accept": "application/json", "X-Subscription-Token": brave_key})
            payload = json.loads(data.decode("utf-8", errors="replace"))
            return [{"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("description", "")}
                    for item in list(payload.get("web", {}).get("results") or [])[:limit]]
        rows = attempt("brave", via_brave)
        if rows:
            return finish("brave", rows, transportFailures=failures)
    else:
        attempts.append({"provider": "brave", "status": "not_configured", "resultCount": 0, "elapsedMs": 0,
                         "reason": "Optional paid key BRAVE_SEARCH_API_KEY is not set; no-key transports used"})
    rows = attempt("duckduckgo-html", lambda: _duckduckgo(query, limit, request, parser_type))
    if rows:
        return finish("duckduckgo-html", rows, transportFailures=failures)
    # A public encyclopedia index is a narrower, attributed retrieval route.
    # It supplies actual article URLs, never a generated answer or gold data.
    rows = attempt("wikipedia-public-index", lambda: _wikipedia(query, limit, request))
    if rows:
        return finish("wikipedia-public-index", rows, scope="Encyclopedia only; general web transport unavailable",
                      transportFailures=failures)
    rows = attempt("ddgs-yandex", lambda: _engine_results("yandex", query, limit))
    if rows:
        return finish("ddgs-yandex", rows, transportFailures=failures)
    raise RuntimeError("Public search unavailable: " + "; ".join(failures))
