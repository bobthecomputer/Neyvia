import { createNeyviaClient } from "/api/sdk/neyvia-sdk.js";
const sdk = createNeyviaClient({ appId: "example-app" });
let current = { connected: false };
async function connect() {
  const provider = await sdk.providerStatus("codex");
  current = { connected: true, provider };
  document.getElementById("state").textContent = "Connected through Neyvia";
  return current;
}
document.getElementById("connect").onclick = () => connect().catch(error => {
  document.getElementById("state").textContent = error.message;
});
window.neyviaApp = Object.freeze({
  state: () => current,
  describe: () => ({ instance: "example-app", actions: ["connect"] }),
  async act(action) { if (action !== "connect") throw Error("Unknown app action"); return connect(); },
});
