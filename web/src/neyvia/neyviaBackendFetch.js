// Browser transport for the product panels that call /api/backend directly.
//
// A phone reaches the PC over a tailnet: a request can stall, be reset, or find
// the host restarting. Reads are retried and bounded, and a network failure is
// reported in words instead of the browser's bare "Failed to fetch".

const READ_COMMAND = /^(get|list|has|search|probe)_/;
const RETRYABLE_STATUS = new Set([502, 504]);
const NETWORK_FAILURE = /failed to fetch|networkerror|load failed|network request failed|network error/i;

export const UNREACHABLE_MESSAGE = "Can't reach Neyvia right now. Check your connection to the PC and try again.";
export const TIMEOUT_MESSAGE = "Neyvia took too long to answer. Try again in a moment.";

export function isReadCommand(command) {
  return READ_COMMAND.test(String(command || ""));
}

export function isNetworkFailure(error) {
  return error?.name !== "AbortError" && NETWORK_FAILURE.test(String(error?.message || error || ""));
}

const GZIP_REQUEST_MIN_CHARS = 128 * 1024;

/**
 * Compress a large JSON request body. A phone saving a chat uploads every
 * transcript it holds, several MB, over a slow uplink. Browsers without
 * CompressionStream send it unchanged.
 */
export async function encodeJsonBody(text) {
  if (typeof CompressionStream !== "function" || String(text).length < GZIP_REQUEST_MIN_CHARS) {
    return { body: text, headers: {} };
  }
  try {
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
    return { body: await new Response(stream).arrayBuffer(), headers: { "Content-Encoding": "gzip" } };
  } catch {
    return { body: text, headers: {} };
  }
}

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

/**
 * fetch() where a read gets a deadline and a few retries. An action is
 * attempted once with no deadline: a reset can happen after the host acted,
 * and a run or a plan may legitimately take minutes.
 */
export async function fetchBackend(url, init = {}, options = {}) {
  const {
    command = "",
    // Reads are bounded. An action (a run, a plan) may legitimately take minutes.
    timeoutMs = isReadCommand(command) ? 60000 : 0,
    retries = isReadCommand(command) ? 2 : 0,
    backoffMs = 500,
    fetchImpl = globalThis.fetch,
    sleep = delay,
  } = options;
  let lastError = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const outer = init.signal;
    const onOuterAbort = () => controller.abort(outer.reason);
    if (outer?.aborted) throw outer.reason || new DOMException("Aborted", "AbortError");
    outer?.addEventListener?.("abort", onOuterAbort, { once: true });
    let timedOut = false;
    const timer = timeoutMs > 0 ? setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs) : 0;
    try {
      const response = await fetchImpl(url, { ...init, signal: controller.signal });
      if (RETRYABLE_STATUS.has(response.status) && attempt < retries) {
        lastError = new Error(`HTTP ${response.status}`);
      } else {
        return response;
      }
    } catch (error) {
      if (outer?.aborted) throw error;
      if (timedOut) {
        lastError = Object.assign(new Error(TIMEOUT_MESSAGE), { code: "timeout" });
      } else if (isNetworkFailure(error)) {
        lastError = Object.assign(new Error(UNREACHABLE_MESSAGE), { code: "unreachable" });
      } else {
        throw error;
      }
    } finally {
      if (timer) clearTimeout(timer);
      outer?.removeEventListener?.("abort", onOuterAbort);
    }
    if (attempt < retries) await sleep(backoffMs * 2 ** attempt);
  }
  throw lastError;
}
