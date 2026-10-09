"""Run a hash-verified GLM-OCR Transformers benchmark on one image.

This runner deliberately stays outside Neyvia's automatic OCR routing until a
candidate has produced measured local evidence.  It follows the official
GLM-OCR Transformers prompt and records the model load, generation latency,
token count, and CUDA peak memory in a reproducible JSON artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    arguments = parser.parse_args()

    model_path = arguments.model.resolve()
    image_path = arguments.image.resolve()
    weights_path = model_path / "model.safetensors"
    if not weights_path.is_file():
        raise FileNotFoundError(f"Missing GLM-OCR weights: {weights_path}")
    if not image_path.is_file():
        raise FileNotFoundError(f"Missing benchmark image: {image_path}")
    actual_sha256 = _sha256(weights_path)
    expected_sha256 = arguments.model_sha256.strip().lower()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            "GLM-OCR weights failed SHA-256 verification: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    import torch
    import transformers
    from transformers import AutoModelForImageTextToText, AutoProcessor

    if not torch.cuda.is_available():
        raise RuntimeError("This benchmark requires a healthy CUDA device")

    load_started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(
        model_path,
        local_files_only=True,
    )
    model = AutoModelForImageTextToText.from_pretrained(
        pretrained_model_name_or_path=model_path,
        torch_dtype="auto",
        device_map="auto",
        local_files_only=True,
    )
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "url": str(image_path)},
                {"type": "text", "text": "Text Recognition:"},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    inputs.pop("token_type_ids", None)

    torch.cuda.reset_peak_memory_stats()
    inference_started = time.perf_counter()
    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=arguments.max_new_tokens,
        )
    torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - inference_started
    prompt_tokens = int(inputs["input_ids"].shape[1])
    generated_tokens = int(generated_ids.shape[1] - prompt_tokens)
    output_text = processor.decode(
        generated_ids[0][prompt_tokens:],
        skip_special_tokens=False,
    )

    payload = {
        "schema": "neyvia.ocr_candidate_benchmark.v1",
        "candidateId": "glm-ocr",
        "backend": "transformers",
        "task": "text-recognition",
        "modelPath": str(model_path),
        "modelWeightsSha256": actual_sha256,
        "imagePath": str(image_path),
        "runtime": {
            "pythonTorch": torch.__version__,
            "transformers": transformers.__version__,
            "cuda": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "device": torch.cuda.get_device_name(0),
        },
        "measurements": {
            "modelLoadSeconds": round(load_seconds, 3),
            "inferenceSeconds": round(inference_seconds, 3),
            "promptTokens": prompt_tokens,
            "generatedTokens": generated_tokens,
            "peakVramMb": round(torch.cuda.max_memory_allocated() / 1024**2, 3),
            "reservedVramMb": round(torch.cuda.max_memory_reserved() / 1024**2, 3),
        },
        "text": output_text,
    }
    _write_json(arguments.output.resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
