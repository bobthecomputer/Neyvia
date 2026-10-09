"""Immutable public sidebar model assets; bounded lazy acquisition, no account."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.request
from urllib.parse import urlsplit
import uuid

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
FILES = {
    "config.json": (612, "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41"),
    "model.safetensors": (90868376, "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"),
    "special_tokens_map.json": (112, "303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3"),
    "tokenizer.json": (466247, "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"),
    "tokenizer_config.json": (350, "acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b"),
    "vocab.txt": (231508, "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"),
}
MAX_TOTAL_BYTES = 200_000_000
_lock = threading.Lock()


def model_path():
    return Path(os.environ.get("NEYVIA_SIDEBAR_EMBEDDING_MODEL") or
                Path(__file__).resolve().parents[2] / ".agent_control/t7/embedding-model").resolve()


def expected_receipt():
    return {"id": MODEL_ID, "revision": REVISION,
            "files": [{"file": name, "sha256": sha, "size": size} for name, (size, sha) in FILES.items()],
            "source": "public pinned Hugging Face model", "totalBytes": sum(size for size, _ in FILES.values())}


def validate(path):
    path = Path(path)
    receipt = json.loads((path / "receipt.json").read_text(encoding="utf-8"))
    if receipt != expected_receipt():
        raise ValueError("Sidebar model receipt differs from immutable file and revision pins")
    for name, (size, expected_sha) in FILES.items():
        digest = hashlib.sha256()
        count = 0
        with (path / name).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                count += len(chunk)
                if count > size:
                    raise ValueError("Sidebar model file exceeds pinned size: " + name)
                digest.update(chunk)
        if count != size or digest.hexdigest() != expected_sha:
            raise ValueError("Sidebar model integrity check failed: " + name)
    return receipt


def _base_url():
    # An explicitly configured loopback mirror supports air-gapped installs;
    # its bytes have the same immutable pins as the official public endpoint.
    mirror = os.environ.get("NEYVIA_SIDEBAR_ASSET_BASE_URL")
    if mirror:
        parsed = urlsplit(mirror)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port is None):
            raise ValueError("Sidebar asset mirror must be explicit-port loopback HTTP")
        return mirror.rstrip("/")
    return f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}"


def ensure_model(path=None):
    target = Path(path).resolve() if path is not None else model_path()
    if sum(size for size, _ in FILES.values()) > MAX_TOTAL_BYTES:
        raise ValueError("Sidebar model exceeds download cap")
    with _lock:
        if (target / "receipt.json").exists():
            validate(target)
            return target
        base = _base_url()
        from . import local_network_policy
        if local_network_policy.enabled() and not base.startswith("http://"):
            local_network_policy.refuse()
        target.mkdir(parents=True, exist_ok=True)
        for name, (expected_size, expected_sha) in FILES.items():
            destination = target / name
            if destination.exists():
                if destination.stat().st_size != expected_size or hashlib.sha256(destination.read_bytes()).hexdigest() != expected_sha:
                    raise ValueError("Existing sidebar asset differs from immutable pin: " + name)
                continue
            partial = target / (name + "." + uuid.uuid4().hex + ".part")
            digest = hashlib.sha256()
            count = 0
            request = urllib.request.Request(base + "/" + name,
                                            headers={"User-Agent": "Neyvia-pinned-sidebar-model"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response, partial.open("xb") as output:
                    while True:
                        chunk = response.read(min(1024 * 1024, expected_size - count + 1))
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > expected_size:
                            raise ValueError("Sidebar transfer exceeded pinned size: " + name)
                        output.write(chunk)
                        digest.update(chunk)
                if count != expected_size or digest.hexdigest() != expected_sha:
                    raise ValueError("Sidebar transfer failed immutable size/hash pin: " + name)
                os.replace(partial, destination)
            finally:
                partial.unlink(missing_ok=True)
        receipt = target / ("receipt." + uuid.uuid4().hex + ".part")
        receipt.write_text(json.dumps(expected_receipt(), indent=2) + "\n", encoding="utf-8")
        os.replace(receipt, target / "receipt.json")
        validate(target)
        return target
