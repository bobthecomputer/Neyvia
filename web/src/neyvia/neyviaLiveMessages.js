// Messages that were pending in this browser session. Only these reveal with
// motion when their reply lands; history loaded from storage renders at once.
const liveMessages = new Set();

export function noteLiveMessage(key) {
  if (key) liveMessages.add(String(key));
}

export function isLiveMessage(key) {
  return Boolean(key) && liveMessages.has(String(key));
}

export function forgetLiveMessage(key) {
  if (key) liveMessages.delete(String(key));
}
