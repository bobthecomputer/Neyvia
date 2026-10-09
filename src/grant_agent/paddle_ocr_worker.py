"""Isolated PaddleOCR worker used by the bounded Neyvia adapter.

The worker writes its protocol response to a file so upstream framework logs
cannot corrupt the structured result on stdout.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
import traceback
from pathlib import Path
from typing import Any


def _json_result(item: Any) -> dict[str, Any]:
    value = item.json
    if callable(value):
        value = value()
    if isinstance(value, dict) and isinstance(value.get("res"), dict):
        return dict(value["res"])
    if isinstance(value, dict):
        return dict(value)
    raise RuntimeError("PaddleOCR returned an unsupported result shape")


def _ppocr_page(result: dict[str, Any], fallback_page: int) -> dict[str, Any]:
    texts = list(result.get("rec_texts") or [])
    scores = list(result.get("rec_scores") or [])
    polygons = list(result.get("rec_polys") or [])
    boxes = list(result.get("rec_boxes") or [])
    word_boxes = list(result.get("text_word_boxes") or [])
    regions = []
    for index, text in enumerate(texts):
        regions.append(
            {
                "region": index + 1,
                "text": str(text),
                "confidence": float(scores[index])
                if index < len(scores)
                else None,
                "polygon": polygons[index] if index < len(polygons) else None,
                "box": boxes[index] if index < len(boxes) else None,
                "wordBoxes": word_boxes[index]
                if index < len(word_boxes)
                else None,
            }
        )
    return {
        "page": int(result.get("page_index") or fallback_page - 1) + 1,
        "text": "\n".join(str(value) for value in texts),
        "regionCount": len(regions),
        "regions": regions,
    }


def _vl_page(result: dict[str, Any], fallback_page: int) -> dict[str, Any]:
    raw_blocks = list(result.get("parsing_res_list") or [])
    blocks = []
    for index, value in enumerate(raw_blocks):
        if not isinstance(value, dict):
            continue
        blocks.append(
            {
                "blockId": value.get("block_id", index),
                "order": value.get("block_order", index),
                "label": value.get("block_label"),
                "content": str(value.get("block_content") or ""),
                "bbox": value.get("block_bbox"),
                "polygon": value.get("block_polygon_points"),
                "groupId": value.get("group_id"),
            }
        )
    blocks.sort(key=lambda value: (int(value.get("order") or 0), str(value["blockId"])))
    text = "\n\n".join(block["content"] for block in blocks if block["content"])
    return {
        "page": int(result.get("page_index") or fallback_page - 1) + 1,
        "width": result.get("width"),
        "height": result.get("height"),
        "text": text,
        "blockCount": len(blocks),
        "blocks": blocks,
    }


def _health() -> dict[str, Any]:
    import paddle
    import paddleocr
    import paddlex

    return {
        "ok": True,
        "operation": "health",
        "python": platform.python_version(),
        "paddle": paddle.__version__,
        "paddleocr": paddleocr.__version__,
        "paddlex": paddlex.__version__,
        "compiledWithCuda": paddle.device.is_compiled_with_cuda(),
        "gpuCount": paddle.device.cuda.device_count(),
        "device": paddle.device.get_device(),
        "cudnnRuntime": paddle.device.get_cudnn_version(),
    }


def _run(request: dict[str, Any]) -> dict[str, Any]:
    operation = str(request.get("operation") or "extract_text").strip().lower()
    if operation == "health":
        return _health()
    source = Path(str(request.get("sourcePath") or request.get("path") or "")).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    requested_paths = request.get("paths") or [str(source)]
    if not isinstance(requested_paths, list) or not requested_paths:
        raise ValueError("paths must contain at least one source image")
    paths = [Path(str(value)).resolve() for value in requested_paths]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    first_page = max(1, int(request.get("firstPage") or 1))
    engine = str(request.get("engine") or "pp-ocrv6-medium").strip().lower()
    device = str(request.get("device") or "gpu:0").strip()
    started = time.perf_counter()
    if engine == "pp-ocrv6-medium":
        from paddleocr import PaddleOCR

        pipeline = PaddleOCR(
            text_detection_model_name="PP-OCRv6_medium_det",
            text_recognition_model_name="PP-OCRv6_medium_rec",
            use_doc_orientation_classify=bool(request.get("classifyOrientation", False)),
            use_doc_unwarping=bool(request.get("unwarp", False)),
            use_textline_orientation=bool(request.get("textlineOrientation", False)),
            return_word_box=True,
            device=device,
        )
        pages = []
        for page_number, path in enumerate(paths, start=first_page):
            pages.extend(
                _ppocr_page(_json_result(item), page_number)
                for item in pipeline.predict(str(path))
            )
        structure = "regions"
    elif engine == "paddleocr-vl-1.6":
        from paddleocr import PaddleOCRVL

        backend = str(request.get("vlBackend") or "paddle").strip().lower()
        backend_arguments: dict[str, Any] = {}
        if backend == "llama-cpp-server":
            backend_arguments = {
                "vl_rec_backend": "llama-cpp-server",
                "vl_rec_server_url": str(request.get("vlServerUrl") or ""),
                "vl_rec_max_concurrency": max(
                    1, min(4, int(request.get("vlMaxConcurrency") or 1))
                ),
            }
        elif backend != "paddle":
            raise ValueError(f"Unsupported PaddleOCR-VL backend: {backend}")
        pipeline = PaddleOCRVL(
            pipeline_version="v1.6",
            use_doc_orientation_classify=bool(request.get("classifyOrientation", False)),
            use_doc_unwarping=bool(request.get("unwarp", False)),
            use_layout_detection=True,
            use_chart_recognition=bool(request.get("recognizeCharts", True)),
            use_seal_recognition=bool(request.get("recognizeSeals", True)),
            format_block_content=True,
            merge_layout_blocks=True,
            device=device,
            **backend_arguments,
        )
        pages = []
        for page_number, path in enumerate(paths, start=first_page):
            pages.extend(
                _vl_page(_json_result(item), page_number)
                for item in pipeline.predict(str(path))
            )
        structure = "blocks"
    else:
        raise ValueError(f"Unsupported Paddle OCR engine: {engine}")
    return {
        "ok": True,
        "operation": operation,
        "engine": engine,
        "sourcePath": str(source),
        "pageCount": len(pages),
        "text": "\n\f\n".join(page["text"] for page in pages),
        "structure": structure,
        "backend": (
            str(request.get("vlBackend") or "paddle").strip().lower()
            if engine == "paddleocr-vl-1.6"
            else "paddle"
        ),
        "pages": pages,
        "latencyMs": round((time.perf_counter() - started) * 1000.0, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    arguments = parser.parse_args()
    response_path = Path(arguments.response).resolve()
    try:
        request = json.loads(
            Path(arguments.request).read_text(encoding="utf-8")
        )
        response = _run(request)
    except Exception as exc:
        response = {
            "ok": False,
            "error": str(exc),
            "errorType": type(exc).__name__,
            "traceback": traceback.format_exc(limit=8),
        }
    response_path.write_text(
        json.dumps(response, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
