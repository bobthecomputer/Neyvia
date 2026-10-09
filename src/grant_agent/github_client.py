"""A small GitHub HTTP client that spends as few API requests as it can.

Design ported from T3 Code (https://github.com/pingdotgg/t3code), re-implemented in Python.
The ideas taken: one credential resolver, plain HTTP instead of ``gh`` for reads, ETag/``If-None-Match``
revalidation (a 304 is free), batched GraphQL with a cost pre-debit and a reserve, a per-host pause that
honours ``retry-after`` / ``x-ratelimit-reset`` with an exponential fallback, and "read only what moved"
fingerprint-gated refreshes. Neyvia's agents never see the token: only product code in this module does.

T3 Code is licensed under the MIT License:

    MIT License

    Copyright (c) 2026 T3 Tools Inc.

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Callable

API_VERSION = "2022-11-28"
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_CONCURRENT_REQUESTS = 8
TOKEN_REUSE_SECONDS = 300.0       # a resolved token is reused for 5 minutes
TOKEN_MISSING_RETRY_SECONDS = 10.0  # a missing token is looked for again after 10 seconds
FALLBACK_COOLDOWN_SECONDS = 30.0
MAX_FALLBACK_COOLDOWN_SECONDS = 15 * 60.0
GRAPHQL_RESERVE_RATIO = 0.1
ALIASES_PER_REQUEST = 25
CONDITIONAL_CACHE_CAPACITY = 128
CONDITIONAL_TTL_SECONDS = 30 * 60.0
FRESH_REUSE_SECONDS = 15.0        # inside this window a repeated read makes no request at all
SAFETY_REREAD_SECONDS = 30 * 60.0  # a full re-read even if every fingerprint says "unchanged"
RATE_LIMIT_SELECTION = "rateLimit { cost limit remaining resetAt }"


class GitHubRateLimited(RuntimeError):
    """Raised without sending a request when the host is paused. ``retry_at`` is a unix time."""

    def __init__(self, host: str, retry_at: float):
        super().__init__(f"GitHub requests to {host} are paused until the rate limit resets.")
        self.host = host
        self.retry_at = retry_at


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- credentials

class TokenResolver:
    """One place that finds a GitHub token: explicit setting, then env, then ``gh auth token`` (last).

    The token is returned only to this module's transport. ``describe()`` is what UIs and agents may see.
    """

    def __init__(self, *, setting: Callable[[], str | None] | None = None, env: dict[str, str] | None = None,
                 gh_command: Callable[[], str | None] | None = None, clock: Callable[[], float] = time.monotonic,
                 use_gh: bool = True):
        self._setting = setting
        self._env = env
        self._gh_command = gh_command or self._default_gh
        self._clock = clock
        self._use_gh = use_gh
        self._lock = threading.Lock()
        self._cached: tuple[float, str | None, str] | None = None

    @staticmethod
    def _default_gh() -> str | None:
        try:
            done = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"], capture_output=True, text=True,
                                  timeout=15, stdin=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        value = done.stdout.strip()
        return value if done.returncode == 0 and value else None

    def _lookup(self) -> tuple[str | None, str]:
        if self._setting:
            value = (self._setting() or "").strip()
            if value:
                return value, "settings"
        env = self._env if self._env is not None else os.environ
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            value = (env.get(name) or "").strip()
            if value:
                return value, "env"
        if self._use_gh:
            value = (self._gh_command() or "").strip()
            if value:
                return value, "gh"
        return None, "none"

    def resolve(self) -> tuple[str | None, str]:
        now = self._clock()
        with self._lock:
            if self._cached:
                at, token, source = self._cached
                if now - at < (TOKEN_REUSE_SECONDS if token else TOKEN_MISSING_RETRY_SECONDS):
                    return token, source
        token, source = self._lookup()
        with self._lock:
            self._cached = (now, token, source)
        return token, source

    def fingerprint(self) -> str:
        token, _ = self.resolve()
        return hashlib.sha256(token.encode()).hexdigest()[:12] if token else "anonymous"

    def describe(self) -> dict[str, Any]:
        token, source = self.resolve()
        return {"present": bool(token), "source": source}


# ---------------------------------------------------------------- rate limit

def retry_at_from_headers(headers: dict[str, str], now: float) -> float | None:
    """``retry-after`` (seconds or HTTP date) wins, else ``x-ratelimit-reset`` (unix seconds)."""
    value = (headers.get("retry-after") or "").strip()
    if value:
        if value.isdigit():
            return now + int(value)
        try:
            when = parsedate_to_datetime(value).timestamp()
            return when if when > now else None
        except (TypeError, ValueError):
            pass
    reset = (headers.get("x-ratelimit-reset") or "").strip()
    if reset.isdigit():
        return float(reset)
    return None


def is_rate_limited(status: int, headers: dict[str, str]) -> bool:
    """Status plus headers, never status alone: a plain 403 can be a permission error."""
    if status not in (403, 429):
        return False
    return headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers or status == 429


class RateGate:
    """Per-host pause. Pauses only extend. Without a server time: 30 s, 60 s, 120 s ... capped at 15 min."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, float]] = {}

    def check(self, host: str, *, allow_paused: bool = False) -> None:
        with self._lock:
            entry = self._entries.get(host)
            if entry and entry["retry_at"] > self._clock() and not allow_paused:
                raise GitHubRateLimited(host, entry["retry_at"])

    def record_limit(self, host: str, retry_at: float | None) -> float:
        now = self._clock()
        with self._lock:
            entry = self._entries.setdefault(host, {"attempt": 0, "retry_at": 0.0})
            entry["attempt"] += 1
            fallback = min(FALLBACK_COOLDOWN_SECONDS * 2 ** (entry["attempt"] - 1), MAX_FALLBACK_COOLDOWN_SECONDS)
            entry["retry_at"] = max(entry["retry_at"], retry_at if retry_at and retry_at > now else now + fallback)
            return entry["retry_at"]

    def record_success(self, host: str) -> None:
        with self._lock:
            entry = self._entries.get(host)
            if entry and entry["retry_at"] <= self._clock():
                self._entries.pop(host, None)

    def paused_until(self, host: str) -> float | None:
        with self._lock:
            entry = self._entries.get(host)
            return entry["retry_at"] if entry and entry["retry_at"] > self._clock() else None


# ---------------------------------------------------------------- graphql budget

class GraphQlBudget:
    """Pre-debits ``max(1, last observed cost)`` per host/credential; background reads keep a 10 % reserve."""

    def __init__(self, gate: RateGate, clock: Callable[[], float] = time.time):
        self._gate = gate
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, float]] = {}

    def append_selection(self, document: str) -> str:
        if "rateLimit" in document:
            return document
        stripped = document.rstrip()
        if stripped.endswith("}"):
            return stripped[:-1] + " " + RATE_LIMIT_SELECTION + " }"
        return document

    def reserve(self, key: str, host: str, *, allow_reserve: bool) -> None:
        with self._lock:
            state = self._state.get(key)
            if not state:
                return
            now = self._clock()
            if state["reset_at"] <= now:  # window rolled over; forget the stale balance
                self._state.pop(key, None)
                return
            cost = max(1.0, state["cost"])
            floor = 0.0 if allow_reserve else state["limit"] * GRAPHQL_RESERVE_RATIO
            if state["remaining"] - cost < floor:
                raise GitHubRateLimited(host, state["reset_at"])
            state["remaining"] -= cost

    def observe(self, key: str, raw: Any) -> None:
        info = ((raw or {}).get("data") or {}).get("rateLimit") if isinstance(raw, dict) else None
        if not isinstance(info, dict):
            return
        try:
            cost, limit, remaining = float(info["cost"]), float(info["limit"]), float(info["remaining"])
            reset_at = _iso_to_unix(str(info["resetAt"]))
        except (KeyError, TypeError, ValueError):
            return
        if cost < 0 or limit <= 0 or remaining < 0:
            return
        with self._lock:
            state = self._state.get(key)
            # Keep the conservative balance but adopt the observed cost.
            balance = min(remaining, state["remaining"]) if state and state["reset_at"] == reset_at else remaining
            self._state[key] = {"cost": cost, "limit": limit, "remaining": balance, "reset_at": reset_at}

    def snapshot(self, key: str) -> dict[str, float] | None:
        with self._lock:
            return dict(self._state[key]) if key in self._state else None


def _iso_to_unix(text: str) -> float:
    from datetime import datetime, timezone
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


# ---------------------------------------------------------------- transport

@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    from_cache: bool = False

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None


Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, dict[str, str], bytes]]


def urllib_transport(method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: float):
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            body = reply.read(MAX_RESPONSE_BYTES + 1)
            status, received = reply.status, {k.lower(): v for k, v in reply.headers.items()}
    except urllib.error.HTTPError as error:
        body = error.read(MAX_RESPONSE_BYTES + 1) if error.fp else b""
        status, received = error.code, {k.lower(): v for k, v in error.headers.items()}
    if len(body) > MAX_RESPONSE_BYTES:
        raise GitHubError(0, "GitHub response exceeded the 8 MB limit.")
    return status, received, body


def api_urls(host: str = "github.com") -> tuple[str, str]:
    host = host.strip().lower()
    if host == "github.com":
        return "https://api.github.com", "https://api.github.com/graphql"
    return f"https://{host}/api/v3", f"https://{host}/api/graphql"


@dataclass
class _Validator:
    etag: str
    body: bytes
    stored_at: float


class GitHubClient:
    """REST with conditional requests, GraphQL with a budget, one rate gate. ``anonymous=True`` never sends a token."""

    def __init__(self, *, host: str = "github.com", resolver: TokenResolver | None = None, anonymous: bool = False,
                 transport: Transport = urllib_transport, clock: Callable[[], float] = time.time):
        self.host = host.strip().lower()
        self.resolver = resolver or TokenResolver()
        self.anonymous = anonymous
        self._transport = transport
        self._clock = clock
        self.gate = RateGate(clock)
        self.budget = GraphQlBudget(self.gate, clock)
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        self._cache: dict[tuple[str, str], _Validator] = {}
        self._cache_lock = threading.Lock()
        self.stats = {"requests": 0, "responses_200": 0, "responses_304": 0, "cache_fresh": 0, "rate_limited": 0,
                      "paused_skips": 0, "graphql": 0}
        self.last_rate: dict[str, str] = {}

    # -- plumbing
    def _scope(self) -> str:
        return "anonymous" if self.anonymous else self.resolver.fingerprint()

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION,
                   "User-Agent": "Neyvia-github-client"}
        if not self.anonymous:
            token, _ = self.resolver.resolve()
            if token:
                headers["Authorization"] = "Bearer " + token
        headers.update(extra or {})
        return headers

    def _send(self, method: str, url: str, headers: dict[str, str], data: bytes | None, *, allow_paused: bool = False) -> Response:
        try:
            self.gate.check(self.host, allow_paused=allow_paused)
        except GitHubRateLimited:
            self.stats["paused_skips"] += 1
            raise
        with self._slots:
            self.stats["requests"] += 1
            status, received, body = self._transport(method, url, headers, data, REQUEST_TIMEOUT_SECONDS)
        for name in ("x-ratelimit-remaining", "x-ratelimit-limit", "x-ratelimit-reset"):
            if name in received:
                self.last_rate[name] = received[name]
        if is_rate_limited(status, received):
            self.stats["rate_limited"] += 1
            retry_at = self.gate.record_limit(self.host, retry_at_from_headers(received, self._clock()))
            raise GitHubRateLimited(self.host, retry_at)
        if status < 500:
            self.gate.record_success(self.host)
        return Response(status, received, body)

    # -- REST
    def rest(self, path: str, *, conditional: bool = True, max_age: float = 0.0) -> Response:
        """GET with ETag revalidation. A 304 returns the stored body (``from_cache=True``) and costs no quota.

        ``max_age`` > 0 reuses a stored body younger than that many seconds without any request.
        """
        rest_base, _ = api_urls(self.host)
        url = path if path.startswith("http") else rest_base + "/" + path.lstrip("/")
        key = (self._scope(), url)
        now = self._clock()
        with self._cache_lock:
            known = self._cache.get(key)
            if known and now - known.stored_at > CONDITIONAL_TTL_SECONDS:
                self._cache.pop(key, None)
                known = None
        if known and max_age and now - known.stored_at < max_age:
            self.stats["cache_fresh"] += 1
            return Response(200, {"etag": known.etag}, known.body, from_cache=True)
        extra = {"If-None-Match": known.etag} if conditional and known else {}
        reply = self._send("GET", url, self._headers(extra), None)
        if reply.status == 304 and known:
            self.stats["responses_304"] += 1
            with self._cache_lock:
                known.stored_at = self._clock()
            return Response(200, reply.headers, known.body, from_cache=True)
        if reply.status == 200:
            self.stats["responses_200"] += 1
            etag = reply.headers.get("etag")
            if conditional and etag:
                with self._cache_lock:
                    if len(self._cache) >= CONDITIONAL_CACHE_CAPACITY:
                        self._cache.pop(min(self._cache, key=lambda k: self._cache[k].stored_at), None)
                    self._cache[key] = _Validator(etag, reply.body, self._clock())
            return reply
        if reply.status in (404, 410, 422):
            return reply
        raise GitHubError(reply.status, _error_text(reply))

    def forget(self, path_fragment: str = "") -> int:
        """Event-driven invalidation: after a push, an agent turn or ``pr create``."""
        with self._cache_lock:
            doomed = [key for key in self._cache if path_fragment in key[1]]
            for key in doomed:
                del self._cache[key]
            return len(doomed)

    # -- GraphQL
    def graphql(self, document: str, variables: dict[str, Any] | None = None, *, allow_reserve: bool = False) -> dict[str, Any]:
        if self.anonymous:
            raise GitHubError(401, "GitHub GraphQL needs a signed-in token.")
        _, graphql_url = api_urls(self.host)
        scope = self._scope()
        key = f"{self.host}\0{scope}"
        self.gate.check(self.host, allow_paused=allow_reserve)
        self.budget.reserve(key, self.host, allow_reserve=allow_reserve)
        payload = json.dumps({"query": self.budget.append_selection(document), "variables": variables or {}}).encode()
        self.stats["graphql"] += 1
        reply = self._send("POST", graphql_url, self._headers({"Content-Type": "application/json"}), payload,
                           allow_paused=allow_reserve)
        data = reply.json() if reply.status == 200 else None
        if isinstance(data, dict):
            self.budget.observe(key, data)
            for error in data.get("errors") or []:
                if isinstance(error, dict) and error.get("type") == "RATE_LIMITED":
                    retry_at = self.gate.record_limit(self.host, retry_at_from_headers(reply.headers, self._clock()))
                    raise GitHubRateLimited(self.host, retry_at)
            return data
        raise GitHubError(reply.status, _error_text(reply))

    def pull_requests_batch(self, repo: str, numbers: list[int], *, allow_reserve: bool = False) -> dict[int, dict[str, Any] | None]:
        """Many pull requests in aliased GraphQL documents: 25 per request, one document per chunk."""
        owner, name = repo.split("/", 1)
        out: dict[int, dict[str, Any] | None] = {}
        for start in range(0, len(numbers), ALIASES_PER_REQUEST):
            chunk = numbers[start:start + ALIASES_PER_REQUEST]
            fields = " ".join(
                f"p{n}: pullRequest(number: {int(n)}) {{ number title state url headRefOid "
                f"commits(last: 1) {{ nodes {{ commit {{ statusCheckRollup {{ state }} }} }} }} }}" for n in chunk)
            document = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {fields} }} }}"
            data = self.graphql(document, {"owner": owner, "name": name}, allow_reserve=allow_reserve)
            repository = ((data.get("data") or {}).get("repository")) or {}
            for n in chunk:
                out[n] = repository.get(f"p{n}")
        return out


def _error_text(reply: Response) -> str:
    try:
        parsed = reply.json()
        if isinstance(parsed, dict) and parsed.get("message"):
            return f"GitHub answered {reply.status}: {str(parsed['message'])[:200]}"
    except (ValueError, UnicodeDecodeError):
        pass
    return f"GitHub answered {reply.status}."


# ---------------------------------------------------------------- pull request watch

_REMOTE = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.I)


def repo_from_remote(url: str) -> str | None:
    match = _REMOTE.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def summarize_checks(runs: list[dict[str, Any]], statuses: list[dict[str, Any]] | None = None) -> str | None:
    failing = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "error"}
    state = "passing"
    seen = False
    for run in runs:
        seen = True
        if run.get("status") != "completed":
            state = "pending"
        elif str(run.get("conclusion") or "").lower() in failing:
            return "failing"
    for status in statuses or []:
        seen = True
        value = str(status.get("state") or "").lower()
        if value in ("failure", "error"):
            return "failing"
        if value == "pending":
            state = "pending"
    return state if seen else None


class PullRequestWatch:
    """Branch to pull request state with the fewest requests.

    One poll is: PR list for the branch (ETag, 304 free), and only if the head SHA moved or the safety window
    passed, the check runs for that SHA (ETag again). With nothing changed, a poll inside ``FRESH_REUSE_SECONDS``
    makes no request, and past it makes one conditional request that costs no quota.
    """

    def __init__(self, client: GitHubClient, *, clock: Callable[[], float] = time.time):
        self.client = client
        self._clock = clock
        self._last: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def read(self, repo: str, branch: str, *, force: bool = False) -> dict[str, Any]:
        key = (repo, branch)
        now = self._clock()
        with self._lock:
            last = self._last.get(key)
        if last and not force and now - last["at"] < FRESH_REUSE_SECONDS:
            return dict(last["value"], source="memory")
        owner = repo.split("/", 1)[0]
        listing = self.client.rest(f"repos/{repo}/pulls?head={owner}:{branch}&state=all&per_page=1")
        pulls = listing.json() if listing.status == 200 else []
        if not pulls:
            value = {"pullRequest": None, "source": "etag" if listing.from_cache else "network"}
            self._remember(key, value, None)
            return value
        pull = pulls[0]
        sha = (pull.get("head") or {}).get("sha") or ""
        unchanged = bool(last and last["sha"] == sha and last["state"] == pull.get("state")
                         and now - last["full_at"] < SAFETY_REREAD_SECONDS)
        if unchanged and listing.from_cache:
            checks = last["value"]["pullRequest"]["checks"]
            source = "etag"
            full_at = last["full_at"]
        else:
            runs = self.client.rest(f"repos/{repo}/commits/{sha}/check-runs?per_page=100")
            run_list = (runs.json() or {}).get("check_runs", []) if runs.status == 200 else []
            checks = summarize_checks(run_list)
            source = "network"
            full_at = now
        value = {"pullRequest": {"number": pull.get("number"), "title": pull.get("title"), "url": pull.get("html_url"),
                                 "state": "merged" if pull.get("merged_at") else str(pull.get("state") or "").lower() or None,
                                 "checks": checks}, "source": source}
        self._remember(key, value, sha, full_at, pull.get("state"))
        return value

    def _remember(self, key, value, sha, full_at=None, state=None):
        with self._lock:
            self._last[key] = {"at": self._clock(), "value": value, "sha": sha, "state": state,
                               "full_at": full_at if full_at is not None else self._clock()}

    def invalidate(self, repo: str | None = None) -> None:
        """Push, turn end, ``pr create``: the next read goes to the network (still conditional)."""
        with self._lock:
            for key in [k for k in self._last if repo is None or k[0] == repo]:
                self._last[key]["at"] = 0.0


# ---------------------------------------------------------------- drop-in for the workspace pull request read

_SHARED: dict[str, Any] = {}
_SHARED_LOCK = threading.Lock()


def shared_watch() -> PullRequestWatch:
    """One client, one gate and one cache for the whole process (so every poller shares the rate limit)."""
    with _SHARED_LOCK:
        if "watch" not in _SHARED:
            _SHARED["watch"] = PullRequestWatch(GitHubClient())
        return _SHARED["watch"]


def pull_request_state(remote_url: str, branch: str, *, refresh: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    """Same answer shape as ``workspace._pull_request``: ``(pull | None, error | None)``.

    ``pull`` is ``{number, title, url, state, checks}``. ``refresh=True`` is for events (push, agent turn end,
    ``pr create``): the next read goes to the network, still as a conditional request.
    """
    repo = repo_from_remote(remote_url or "")
    if not repo or not branch:
        return None, None
    watch = shared_watch()
    if refresh:
        watch.invalidate(repo)
    try:
        return watch.read(repo, branch)["pullRequest"], None
    except GitHubRateLimited as paused:
        when = time.strftime("%H:%M", time.localtime(paused.retry_at))
        return None, f"GitHub is limiting requests from this PC. Pull request status resumes at {when}."
    except GitHubError as failure:
        return None, str(failure)[:300]
    except (OSError, ValueError) as failure:
        return None, f"GitHub could not be reached ({type(failure).__name__})."
