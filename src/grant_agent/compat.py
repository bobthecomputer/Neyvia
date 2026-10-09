"""Which Neyvia API and SDK each installed mod or app was written for.

Neyvia publishes two numbers a mod or app can depend on:

* ``NEYVIA_API``: the host surface (tool names, module actions, command payloads). Minor
  versions only add; a major version may remove or change things.
* ``SDK_ABI``: the browser SDK (``packages/neyvia-sdk``). Whole numbers; only a new ABI breaks.

A descriptor (``neyvia.module.json`` / ``neyvia.app.json``) declares ranges::

    "requires": {"neyviaApi": ">=1.0 <2", "sdk": ">=1 <2"}

A range is space-separated comparators (``>= > <= < ==``), or ``*``. Apps written before this
field existed carry ``"sdk": 1``, which still counts as an exact SDK ABI declaration.
The loader refuses an item outside a declared range and says which side is out of date.
"""
from __future__ import annotations

import re
from typing import Any

NEYVIA_API = "1.0.0"
SDK_ABI = 1

_COMPARATOR = re.compile(r"^(>=|<=|==|>|<)?\s*(\d+(?:\.\d+){0,2})$")


def _tuple(text: str) -> tuple[int, int, int]:
    parts = [int(p) for p in text.split(".")][:3]
    return (parts + [0, 0, 0])[:3]  # type: ignore[return-value]


def satisfies(version: str, wanted: str) -> bool:
    """True when ``version`` meets every comparator in ``wanted``. Raises ValueError on a malformed range."""
    wanted = str(wanted).strip()
    if wanted in {"", "*"}:
        return True
    have = _tuple(str(version))
    for piece in wanted.replace(",", " ").split():
        match = _COMPARATOR.match(piece)
        if not match:
            raise ValueError(f"Not a version range: {wanted!r}")
        op, number = match.group(1) or "==", _tuple(match.group(2))
        if not {">=": have >= number, "<=": have <= number, ">": have > number, "<": have < number, "==": have == number}[op]:
            return False
    return True


def declared(descriptor: dict[str, Any]) -> dict[str, str]:
    """The ranges an item declares, with the legacy ``"sdk": 1`` folded in."""
    requires = descriptor.get("requires") if isinstance(descriptor.get("requires"), dict) else {}
    ranges = {key: str(requires[key]) for key in ("neyviaApi", "sdk") if requires.get(key) not in (None, "")}
    legacy = descriptor.get("sdk")
    if "sdk" not in ranges and isinstance(legacy, int) and not isinstance(legacy, bool):
        ranges["sdk"] = f"=={legacy}"
    return ranges


def check(descriptor: dict[str, Any], *, api: str | None = None, sdk: int | None = None) -> dict[str, Any]:
    """``status`` is compatible, undeclared or incompatible; ``message`` is plain words for the person."""
    api = NEYVIA_API if api is None else api  # read at call time so a narrower build is honoured at once
    sdk = SDK_ABI if sdk is None else sdk
    ranges = declared(descriptor)
    if not ranges:
        return {"status": "undeclared", "ranges": {}, "neyviaApi": api, "sdkAbi": sdk,
                "message": 'It does not say which Neyvia it works with. Add "requires": {"neyviaApi": ">=1.0 <2"} to its descriptor.'}
    problems = []
    try:
        if "neyviaApi" in ranges and not satisfies(api, ranges["neyviaApi"]):
            problems.append(f"it needs Neyvia API {ranges['neyviaApi']}, this Neyvia provides {api}")
        if "sdk" in ranges and not satisfies(str(sdk), ranges["sdk"]):
            problems.append(f"it needs SDK ABI {ranges['sdk']}, this Neyvia provides {sdk}")
    except ValueError as exc:
        return {"status": "incompatible", "ranges": ranges, "neyviaApi": api, "sdkAbi": sdk, "message": str(exc)}
    if problems:
        return {"status": "incompatible", "ranges": ranges, "neyviaApi": api, "sdkAbi": sdk,
                "message": "Not loaded: " + "; ".join(problems) + ". Update the item, or Neyvia, until the ranges overlap."}
    return {"status": "compatible", "ranges": ranges, "neyviaApi": api, "sdkAbi": sdk, "message": "Works with this Neyvia."}
