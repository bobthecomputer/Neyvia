# LAYA service attachment

Neyvia includes the shipped `T15-r2` BrowserClient and typed contracts from
`C:/Users/example/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement/laya_system1`.
The two copied client files retain the original observation digest, revision,
freshness, secret omission and post-inference checks. No model weights are copied.

Set `NEYVIA_LAYA_URL` to the explicit loopback service URL in the backend process.
Without it, Browser reports `configuration_needed` and the cascade continues
through its existing checked routes. Never point this setting at the public backend.

For the isolated FIX2 checkout, start the existing shipped service on owned port
48684 using its existing compatible Python environment (system Python 3.13 has
Transformers 5, which cannot import this service's `no_init_weights` dependency):

```powershell
$env:PYTHONPATH = 'C:/Users/example/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement'
$env:CUDA_VISIBLE_DEVICES = ''
$env:LAYA_CUDA_GRAPHS = '0'
$env:LAYA_WEIGHT_DTYPE = 'float32'
& C:/Users/example/miniforge3/envs/whisper/python.exe -m laya_system1.service `
  --model C:/Users/example/Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english `
  --device cpu --port 48684 --database .agent_control/FIX2/laya/system1.sqlite `
  --question-sets C:/Users/example/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement/question_sets `
  --calibration C:/Users/example/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement/calibration/system1.json
```

In the backend shell, set `$env:NEYVIA_LAYA_URL='http://127.0.0.1:48684'`
before starting the backend with its explicit assigned port.
No download, GPU inference, service replacement or public restart is needed.

The native tool `neyvia.browser.decide`, backend `browser_decide_command`, generic
`browser_call_command` and owner HTTP browser route acquire fresh DOM outside the
decision lock and use the same attached client. Optional `context` holds task goal,
options, progress and receipts; it cannot override observation identity.
`browser.state` reports a two-second cached, bounded health observation.
Service failure returns `available=false` without a substitute model or action.

The production cascade's default System-1 provider translates Boolean and enum
schemas, including fully required flat objects, into LAYA typed questions. Other
schemas abstain. Exact digits/IDs/dates/UI values still bypass this stage. Accepted
answers require the existing 0.95 confidence gate plus schema and host semantic
checks; uncertainty escalates through the existing model routes. The actual
decision ID, CPU model identity, bindings and confidence are kept in its receipt.

Proof: `scripts/verify_fix2_laya.py` with explicit service/fixture/engine ports
48684/48685/48683 and the existing pinned Obscura executable. The receipt is
`scripts/evidence/fix2-laya.json`. Native DOM and service calls establish attachment,
freshness and fallback behavior; they do not establish general judgement accuracy.

Publication note: local account paths and network identifiers in this document are neutral examples.
