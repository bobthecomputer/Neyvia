"""Bounded DOM locators backed only by Neyvia's native browser receipts."""
from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urlsplit


def validate_dom_query(args):
    """One bounded selector/attribute contract for native and headless tabs."""
    import re
    selector, attributes, limit = args.get("selector"), args.get("attributes", []), args.get("limit", 100)
    if not isinstance(selector, str) or not selector or len(selector) > 2048 or "\0" in selector:
        raise ValueError("Supply a nonempty bounded CSS selector")
    if (type(limit) is not int or not 1 <= limit <= 100 or not isinstance(attributes, list)
            or len(attributes) > 20 or any(not isinstance(a, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_:.-]{0,127}", a)
                or re.search(r"password|token|secret|credential", a, re.I) for a in attributes)):
        raise ValueError("Bounded non-secret attribute names and match limit required")
    return {"selector": selector, "attributes": attributes, "limit": limit}


def read_headless_dom(page, args):
    """Observe actual selector matches on the owned engine, without a fetch."""
    query = validate_dom_query(args)
    return page.evaluate(r"""a => {
      const protectedFields='input[type="password"],input[autocomplete="one-time-code"],input[autocomplete="cc-number"],input[autocomplete="cc-csc"]';
      const secrets=[...document.querySelectorAll(protectedFields)].map(e=>e.value).filter(Boolean);
      const clean=value=>secrets.reduce((text,secret)=>text.split(secret).join('[redacted]'),String(value||'')).slice(0,4000);
      const matches=[...document.querySelectorAll(a.selector)];
      return {url:location.href,readyState:document.readyState,truncated:matches.length>a.limit,
        elements:matches.slice(0,a.limit).map(e=>{
          const style=getComputedStyle(e), rect=e.getBoundingClientRect();
          return {visible:rect.width>0 && rect.height>0 && style.display!=='none' && style.visibility!=='hidden',
            innerText:clean(e.matches(protectedFields)?'':e.innerText),
            attributes:Object.fromEntries(a.attributes.map(name=>[name,e.matches(protectedFields)&&name==='value'?null:(e.hasAttribute(name)?clean(e.getAttribute(name)):null)]))};
        })};
    }""", query)


class DOMObservationError(RuntimeError):
    pass


class NeyviaDOMPage:
    """Read a selected native tab; the caller owns authenticated transport.

    ``request`` calls BrowserService through its ordinary owner boundary. No
    JavaScript, provider substitution, browser process or profile is launched.
    """
    def __init__(self, request: Callable[[str, dict[str, Any]], dict[str, Any]], tab_id: str,
                 *, timeout: float = 15, allowed_origin: str = '') -> None:
        if not isinstance(tab_id, str) or not tab_id or len(tab_id) > 256:
            raise ValueError('Choose one explicit Neyvia browser tab')
        if not 0 < timeout <= 30:
            raise ValueError('DOM observation timeout must be 0–30 seconds')
        self._request, self.tab_id, self.timeout = request, tab_id, timeout
        self.allowed_origin = allowed_origin
        self.observations: list[dict[str, Any]] = []

    def _completed(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        receipt = self._request(op, {'tabId': self.tab_id, **args})
        deadline = time.monotonic() + self.timeout
        action_id = receipt.get('actionId')
        while action_id and receipt.get('status') not in {'done', 'failed'}:
            if time.monotonic() >= deadline:
                raise DOMObservationError('Neyvia DOM operation timed out; no observation is admitted')
            time.sleep(.025)
            receipt = self._request('action.get', {'actionId': action_id})
        if receipt.get('status') == 'failed' or receipt.get('ok') is False:
            raise DOMObservationError('Neyvia native DOM operation failed: ' + str(receipt.get('error', 'unavailable'))[:300])
        result = receipt.get('result', receipt)
        if not isinstance(result, dict):
            raise DOMObservationError('Neyvia native DOM receipt has no structured result')
        return result

    def _query(self, selector: str, attributes: tuple[str, ...] = ()) -> dict[str, Any]:
        if not selector or len(selector) > 2048 or selector.startswith('xpath='):
            raise ValueError('Neyvia DOM selectors must be bounded CSS selectors')
        if len(attributes) > 20 or any(not name or len(name) > 128 for name in attributes):
            raise ValueError('Neyvia DOM attribute selection exceeds its bound')
        result = self._completed('dom', {'selector': selector, 'attributes': list(attributes), 'limit': 100})
        elements = result.get('elements')
        if not isinstance(elements, list) or len(elements) > 100:
            raise DOMObservationError('Neyvia returned no bounded native DOM observation')
        if result.get('tabId', self.tab_id) != self.tab_id:
            raise DOMObservationError('Neyvia DOM receipt changed the selected tab')
        url = result.get('url')
        if self.allowed_origin:
            if not isinstance(url, str) or not url:
                raise DOMObservationError('Neyvia DOM observation has no origin receipt')
            parsed = urlsplit(str(url))
            if f'{parsed.scheme}://{parsed.netloc}' != self.allowed_origin:
                raise DOMObservationError('Neyvia DOM observation escaped its explicit origin')
        self.observations.append({'selector': selector, 'tabId': self.tab_id, 'elementCount': len(elements),
                                  'url': url, 'revision': result.get('revision'), 'native': True})
        self.observations = self.observations[-256:]
        return result

    def locator(self, selector: str) -> 'NeyviaDOMLocator':
        return NeyviaDOMLocator(self, selector)

    def goto(self, url: str, *, timeout: int = 15000, wait_until: str = 'domcontentloaded') -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('Neyvia DOM navigation requires an explicit HTTP URL')
        if self.allowed_origin and f'{parsed.scheme}://{parsed.netloc}' != self.allowed_origin:
            raise ValueError('Neyvia DOM navigation escaped its explicit origin')
        self._completed('tab.navigate', {'url': url})
        deadline = time.monotonic() + min(self.timeout, max(0.1, timeout / 1000))
        while True:
            result = self._query('body')
            if result.get('url') == url and result['elements']:
                return
            if time.monotonic() >= deadline:
                raise DOMObservationError('Neyvia navigation did not return its current native document')
            time.sleep(.025)


class NeyviaDOMLocator:
    def __init__(self, page: NeyviaDOMPage, selector: str, index: int | None = None) -> None:
        self.page, self.selector, self.index = page, selector, index

    @property
    def first(self) -> 'NeyviaDOMLocator':
        return self.nth(0)

    def nth(self, index: int) -> 'NeyviaDOMLocator':
        if type(index) is not int or not 0 <= index < 100:
            raise ValueError('Neyvia DOM locator index must be 0–99')
        return NeyviaDOMLocator(self.page, self.selector, index)

    def _elements(self, attributes: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        elements = self.page._query(self.selector, attributes)['elements']
        if not all(isinstance(row, dict) and type(row.get('visible')) is bool for row in elements):
            raise DOMObservationError('Native DOM visibility is missing; no visibility is inferred')
        return elements if self.index is None else elements[self.index:self.index + 1]

    def count(self) -> int:
        return len(self._elements())

    def is_visible(self) -> bool:
        elements = self._elements()
        return bool(elements) and elements[0]['visible']

    def inner_text(self, *, timeout: int = 2000) -> str:
        elements = self._elements()
        if not elements or not isinstance(elements[0].get('innerText'), str):
            raise DOMObservationError('Native DOM text is unavailable')
        return elements[0]['innerText']

    def get_attribute(self, name: str) -> str | None:
        elements = self._elements((name,))
        if not elements:
            return None
        attributes = elements[0].get('attributes')
        if not isinstance(attributes, dict):
            raise DOMObservationError('Native DOM attributes are unavailable')
        value = attributes.get(name)
        if value is not None and not isinstance(value, str):
            raise DOMObservationError('Native DOM attribute has an invalid shape')
        return value
