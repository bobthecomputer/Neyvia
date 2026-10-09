# Neyvia OCR Runtime and Benchmark

Status: verified primary runtime with remaining performance work  
Baseline: 2026-07-23 and 2026-07-24 local verification  
Hardware: NVIDIA RTX 3090, 24 GiB VRAM, compute capability 8.6

## Decision

Tesseract is not Neyvia's primary OCR engine. The production route is hybrid:

1. extract native PDF text when present;
2. use PP-OCRv6 medium for ordinary printed or scanned text;
3. use PaddleOCR-VL 1.6 for layout, tables, formulas, charts, seals, handwriting,
   distortion, photographed pages, and structured document parsing; and
4. use Tesseract 5.5.2 only for CPU recovery or an explicitly requested legacy
   output such as hOCR, TSV, ALTO, or searchable PDF.

This avoids paying VLM generation cost for simple pages while retaining modern
document understanding when page structure requires it.

## Current research shortlist

Permissively licensed benchmark candidates:

- [PP-OCRv6](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html)
  for low-hallucination multilingual text detection and recognition;
- [PaddleOCR-VL 1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6)
  for structured document parsing;
- [GLM-OCR](https://github.com/zai-org/GLM-OCR) as the first 0.9B challenger;
- [DeepSeek-OCR](https://github.com/deepseek-ai/DeepSeek-OCR) as a heavier
  vLLM/Transformers challenger;
- [dots.ocr](https://github.com/rednote-hilab/dots.ocr) for multilingual,
  screen, scene, chart, and SVG evaluation; and
- [olmOCR](https://github.com/allenai/olmocr) as a heavier math, table, and
  multi-column challenger.

Default exclusions are recorded in `config/ocr_model_candidates.json`.
HunyuanOCR is excluded in France because its upstream license excludes the
European Union. Chandra and Surya use modified OpenRAIL terms with broader
commercial restrictions. MinerU has an Apache-derived custom license with extra
conditions, so it is not a clean permissive default.

## Exact installed runtime

- PaddleOCR 3.7.0
- PaddleX 3.7.2
- PaddlePaddle GPU 3.3.1
- CUDA runtime 12.9
- cuDNN runtime 9.9.0
- Python 3.12.6 isolated under `D:\Neyvia\runtimes\ocr-paddle\3.7.0`
- model cache under `D:\Neyvia\models\paddlex\3.7.2`

The official CUDA 12.6 Paddle wheels declared cuDNN 9.5 but reported that the
framework was compiled against cuDNN 9.9 during real inference. Neyvia therefore
did not certify that runtime. The official CUDA 12.9 wheel pins cuDNN 9.9, passes
Paddle's GPU self-check, and runs PP-OCRv6 without the compatibility warning.
The exact wheel SHA-256, Python executable SHA-256, model revisions, local model
tree hashes, and byte counts are in `config/tool_suite_lock.json`.

## Real adapter proofs

Reference image:

`.agent_control/capability_os/qa/libreoffice-portable-proof-v6/pages/page-01.png`

PP-OCRv6 medium:

- 27 detected and recognized regions;
- correct visible text on the reference page;
- 1.84 seconds initialization and 0.827 seconds inference in the direct warm proof;
- structured region JSON with confidence, polygons, boxes, and word boxes; and
- persisted adapter artifact SHA-256
  `419e73e5485474f501e5a95901996ddbe26414af232b141cdc5d01fc633235eb`.

PaddleOCR-VL 1.6:

- 21 ordered semantic blocks;
- headings and body text preserved as structured content;
- approximately 54 seconds in a new adapter process; and
- persisted adapter artifact SHA-256
  `d8d1b88ccfc2a0397f490d6375490b38b94ff783b752083098b6b2064fff9998`.

The VLM result is correct but fresh-process startup is too slow for the interactive
default.

The official GGUF route is now benchmarked through pinned llama.cpp `b10098`
(`0278d8362d78c5de291bc03b76016f7f74b2ab77`) on localhost. It preserved the same
21 semantic blocks and reduced VLM inference from about 54.0 seconds to 7.4
seconds. A fresh client still spent 16.4 seconds loading the layout model, for a
23.8-second end-to-end result. The remaining performance task is a managed
demand-start service that keeps both the layout client and VLM server resident.
Custom kernels come only after profiling proves a dominant bottleneck and
equivalence tests protect OCR quality.

## Benchmark contract

`src/grant_agent/ocr_benchmark.py` provides dependency-free:

- Unicode-aware character error rate;
- word error rate;
- reading-order inversion error;
- block-count error;
- latency and peak-VRAM aggregation; and
- deterministic native-text, PP-OCRv6, VLM, or Tesseract-fallback routing.

The corpus must cover English and French printing, scan/skew/warp/lighting,
screen photos, handwriting, tables, formulas, charts, multi-column pages, low
resolution, and mixed languages. Promotion requires local quality and performance
results, not upstream leaderboard claims alone.

### Deterministic v2 evidence manifest

`config/ocr_benchmark_manifest.schema.json` defines the machine-readable v2
contract. `config/ocr_benchmark_manifest.sample.json` is a coverage example
grounded only in repository evidence. It deliberately leaves cases `unproven`
or `missing-model`; it is not a performance result.

Each representative case records language, layout, content, and handwriting
tags. A `measured` observation must point to separate reference and hypothesis
JSON artifacts and record:

- the selected engine, automatic/manual decision, reason, and input signals;
- startup and inference latency, peak memory, throughput, cold/warm cache mode,
  and deterministic temperature;
- model revision/digest, quantization format and precision, and cache
  provenance; and
- character/word error, reading order, blocks, table cells, normalized formula
  exactness, omission, and hallucination.

Measured evidence is fail-closed. The evaluator verifies SHA-256 bindings for
the source page, reference, hypothesis, and collector evidence before reading
them; rejects empty normalized text, oversized artifacts, non-finite metrics,
unknown measured-proof fields, and a route not explicitly bound to the pinned
model identity. Installed models require a non-placeholder source and revision
plus a 64-hex weights/content digest.

Hashing and parsing use the same single byte snapshot of each file. The source,
reference, hypothesis, and collector paths must be distinct. The installed
model is also anchored to hash-pinned candidate-registry and tool-lock content;
their exact entry hashes, revision, upstream source, tool identity, and model
weights digest must agree.

Each file is capped at 100 MiB and all reads in one run share a strict 512 MiB
cumulative budget. Source, reference, hypothesis, and collector bytes are
released as soon as their observation is scored; the run retains only bounded
digests, matched identity metadata, and compact scores.

Candidate-registry and tool-lock whole-document anchors use canonical parsed
JSON hashes rather than raw file hashes. Key order, indentation, and CRLF/LF
line endings therefore do not change model identity. Entry hashes use the same
canonical representation. Source documents and proof artifacts remain bound to
their exact raw bytes.

Collector evidence uses `neyvia.ocr_benchmark_collector_evidence.v1` and binds
the benchmark and case IDs, source hash, candidate and model identity,
reference/hypothesis hashes, full route decision, and exact performance values.
Changing and re-hashing one relation does not make the receipt valid.

Performance values remain self-declared collector evidence even when their
artifact integrity hashes match. Receipts therefore expose
`classification: self-declared`, `integrityBindingsVerified: true`, and
`cryptographicallyTrusted: false`. A matching SHA-256 proves artifact integrity,
not that the collector or timing claim was independently trusted.

Downstream claims are deliberately split:

- `qualityClaimStatus: measured-integrity-only`;
- `performanceClaimStatus: self-declared`;
- `claimStatus: integrity-bound-local-self-declared`; and
- `promotionEligible: false`.

Rows marked `unproven` or `missing-model` require a reason, receive no numeric
quality result, and are excluded from aggregates. This prevents a missing model,
an upstream claim, or a historical receipt from silently becoming a local
benchmark score.

Run an already prepared manifest without downloading anything:

```powershell
python scripts/benchmark_neyvia_ocr.py `
  config/ocr_benchmark_manifest.sample.json `
  --output output/ocr-benchmark-run.json
```

The CLI writes JSON atomically. GLM-OCR collection remains hash/digest-verified
through `benchmark_glm_ocr_transformers.py` and
`benchmark_glm_ocr_ollama.py`; their outputs only become `measured` v2 rows when
paired with explicit ground truth.
