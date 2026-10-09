# Neyvia SDK, ABI 1

This package is a small, same-origin browser client for Neyvia's existing owner-authenticated backend. Python apps use `from neyvia_sdk import NeyviaClient` with an explicit localhost service URL. The browser package exports `createNeyviaClient`. Both return the backend's `data` value and raise on HTTP or `{ok:false}` failures. `NeyviaError` exposes `code` and `status`.

Install the standalone Python package with `python -m pip install ./src/neyvia_sdk`; it has no runtime dependencies on Neyvia internals. JS consumers can use a local file dependency on `packages/neyvia-sdk`, or use the shared hosted URL below. Set `appId` to your marketplace instance ID so disabled apps are refused. `applications()` reads the existing app registry.

```js
import { createNeyviaClient } from "/api/sdk/neyvia-sdk.js";
const neyvia = createNeyviaClient();
await neyvia.signIn(); // only succeeds for this PC's Neyvia owner
const auth = await neyvia.providerStatus("codex");
const options = await neyvia.providers("codex");
const remembered = await neyvia.recall({ intent: "study this article" });
const started = await neyvia.modelCall({ app: "codex", cwd: "/study/project", message: "Explain this section", requestId: crypto.randomUUID() });
// Read the returned session id when the run finishes, or follow Neyvia's run events.
const page = await neyvia.modelResult(started.sessionId);
```

```python
from neyvia_sdk import NeyviaClient
client = NeyviaClient("http://127.0.0.1:48911")
client.sign_in()  # this PC's Neyvia owner session; the service may refuse
status = client.provider_status("codex")
matches = client.recall({"intent": "study this article"})
run = client.model_call(app="codex", cwd="/study/project", message="Explain this section", request_id="study-001")
```

`sign_in` / `signIn` asks Neyvia for this PC's owner session; the service can refuse. `sign_in_provider` / `signInProvider` starts Neyvia's existing provider flow; it does not copy provider credentials into the app. Owner sign-in is one Neyvia session that brokers already-connected providers, not a universal provider credential. Provider refusal, model refusal, login required, missing service, and CL check failures are returned as errors. There is no implicit provider fallback.

`remember` needs a stable `requestId`, `key`, and `content`, and writes local-only memory to the authenticated project. Pass a Neyvia `sessionId` when memory must use a selected chat's project. `recall` accepts cue fields in `situation` and an optional `budget` (0–1024). Memory stays under Neyvia's authenticated scope; apps never supply a user or state root. `modelCall` starts a connected session with `permissionMode: "read-only"` by default; it does not wait for model completion. The caller observes Neyvia run events or calls `modelResult(sessionId)`. `verify` calls `neyvia.efficiency.laya_verify` with `question`, `candidate`, and `evidence`; `manual` and `cl` use Neyvia's CL tools. `registerApp` sends an application ID, name, service names, summary, version, and permission list to the existing registry.

Host a web app through Neyvia's application registry and import the SDK from `/api/sdk/neyvia-sdk.js` on that origin. The package does not hold tokens, API keys, provider passwords, or a separate model or memory implementation. Apps should not log prompts, cookies, memory contents, or provider auth responses.

## Compatibility

`SDK_ABI` (whole number) and `NEYVIA_API` (the host surface) are exported. Declare what your app or mod was written for in its descriptor: `"requires": {"neyviaApi": ">=1.0 <2", "sdk": ">=1 <2"}`. Neyvia refuses to install or enable an item outside its declared range and says which side is out of date. Within ABI 1 the exported functions only gain optional fields; removing or changing one needs ABI 2.
