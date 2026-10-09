"""Benchmark an immutable GLM-OCR Ollama model through a loopback server."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Ollama returned a non-object response from {url}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _seconds(nanoseconds: object) -> float | None:
    if not isinstance(nanoseconds, (int, float)):
        return None
    return round(float(nanoseconds) / 1_000_000_000, 3)


def _repair_renderer_duplicate(value: str) -> tuple[str, dict[str, Any] | None]:
    marker = "\n```markdown\n"
    if marker not in value:
        return value, None
    before, after = value.split(marker, 1)
    expected = before.strip()
    repeated = after.lstrip()
    comparable = repeated[: min(128, len(repeated))]
    if len(comparable) < 32 or not expected.startswith(comparable):
        return value, None
    return expected, {
        "applied": True,
        "reason": (
            "Ollama's GLM-OCR renderer inserted a markdown fence followed by "
            "a demonstrable duplicate of the already emitted page prefix."
        ),
        "marker": marker.strip(),
        "removedCharacters": len(value) - len(expected),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:11435")
    parser.add_argument("--api", choices=("chat", "generate"), default="chat")
    parser.add_argument("--model", default="glm-ocr:bf16")
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--stop", action="append", default=["<|user|>"])
    arguments = parser.parse_args()

    endpoint = arguments.endpoint.rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("The benchmark endpoint must be loopback HTTP")
    image_path = arguments.image.resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Missing benchmark image: {image_path}")

    tags = _request_json(f"{endpoint}/api/tags", timeout=15)
    model_rows = tags.get("models")
    if not isinstance(model_rows, list):
        raise RuntimeError("Ollama /api/tags did not return a models array")
    model_row = next(
        (
            row
            for row in model_rows
            if isinstance(row, dict)
            and arguments.model in {row.get("name"), row.get("model")}
        ),
        None,
    )
    if model_row is None:
        raise RuntimeError(f"Ollama model is not installed: {arguments.model}")
    actual_digest = str(model_row.get("digest") or "").lower()
    expected_digest = arguments.model_digest.strip().lower()
    if actual_digest != expected_digest:
        raise RuntimeError(
            "Ollama model failed digest verification: "
            f"expected {expected_digest}, got {actual_digest}"
        )

    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    started = time.perf_counter()
    request_payload: dict[str, Any] = {
        "model": arguments.model,
        "stream": False,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "num_predict": arguments.max_new_tokens,
            "stop": arguments.stop,
        },
    }
    if arguments.api == "chat":
        request_payload["messages"] = [
            {
                "role": "user",
                "content": "Text Recognition:",
                "images": [image_base64],
            }
        ]
    else:
        request_payload.update(
            {
                "prompt": "Text Recognition:",
                "images": [image_base64],
            }
        )
    response = _request_json(
        f"{endpoint}/api/{arguments.api}",
        request_payload,
        timeout=arguments.timeout_seconds,
    )
    wall_seconds = time.perf_counter() - started
    if response.get("done") is not True:
        diagnostic = json.dumps(response, ensure_ascii=False)
        raise RuntimeError(
            "Ollama did not return a completed response: "
            f"{diagnostic[:4000]}"
        )

    if arguments.api == "chat":
        message = response.get("message")
        output_text = (
            str(message.get("content") or "")
            if isinstance(message, dict)
            else ""
        )
    else:
        output_text = str(response.get("response") or "")
    repaired_text, renderer_repair = _repair_renderer_duplicate(output_text)

    payload = {
        "schema": "neyvia.ocr_candidate_benchmark.v1",
        "candidateId": "glm-ocr",
        "backend": f"ollama-{arguments.api}",
        "task": "text-recognition",
        "endpoint": endpoint,
        "model": arguments.model,
        "modelDigest": actual_digest,
        "imagePath": str(image_path),
        "measurements": {
            "wallSeconds": round(wall_seconds, 3),
            "totalSeconds": _seconds(response.get("total_duration")),
            "loadSeconds": _seconds(response.get("load_duration")),
            "promptEvalSeconds": _seconds(response.get("prompt_eval_duration")),
            "inferenceSeconds": _seconds(response.get("eval_duration")),
            "promptTokens": response.get("prompt_eval_count"),
            "generatedTokens": response.get("eval_count"),
        },
        "doneReason": response.get("done_reason"),
        "rendererRepair": renderer_repair,
        "rawText": output_text,
        "text": repaired_text,
    }
    _write_json(arguments.output.resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
