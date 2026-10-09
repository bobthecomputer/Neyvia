// Example runs for the tour's "Watch an agent work" chapter. Nothing here is a recording of a real
// run: two made-up agents on two made-up apps, so the real "Agents at work" cards can be shown on a
// PC where no agent is running. nxAgentViewApi.js serves these only while the tour scene holds them
// (useExampleRuns), and never for a real run key.

const svg = body => `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 400" width="640" height="400" font-family="Segoe UI, Arial, sans-serif">${body}</svg>`)}`;

const TITLEBAR = (title, fill = "#e9edf1") => `<rect x="0" y="0" width="640" height="28" fill="${fill}"/><circle cx="16" cy="14" r="5" fill="#ff6b5f"/><circle cx="34" cy="14" r="5" fill="#ffc542"/><circle cx="52" cy="14" r="5" fill="#3fc95a"/><text x="76" y="19" font-size="12" fill="#3a4350">${title}</text>`;

const SHOP = svg(`<rect width="640" height="400" fill="#f6f7f9"/>${TITLEBAR("Pocket Garden · Checkout")}
<rect x="40" y="52" width="560" height="38" rx="6" fill="#ffffff" stroke="#d6dbe1"/><text x="56" y="76" font-size="13" fill="#6b7480">pocketgarden.example/checkout</text>
<text x="40" y="128" font-size="22" font-weight="600" fill="#1d242c">Checkout</text>
<rect x="40" y="146" width="330" height="170" rx="10" fill="#ffffff" stroke="#d6dbe1"/>
<text x="58" y="174" font-size="12" fill="#6b7480">Email</text><rect x="58" y="182" width="294" height="30" rx="5" fill="#f1f3f6" stroke="#cfd5dc"/><text x="68" y="202" font-size="13" fill="#1d242c">maya@example.com</text>
<text x="58" y="234" font-size="12" fill="#6b7480">Card</text><rect x="58" y="242" width="294" height="30" rx="5" fill="#fff" stroke="#3b8f5a" stroke-width="2"/><text x="68" y="262" font-size="13" fill="#1d242c">4242 4242 4242 4242</text>
<rect x="58" y="284" width="110" height="26" rx="13" fill="#2f7d4f"/><text x="82" y="302" font-size="12" font-weight="600" fill="#fff">Pay 24.00</text>
<rect x="394" y="146" width="206" height="170" rx="10" fill="#ffffff" stroke="#d6dbe1"/><text x="412" y="174" font-size="13" font-weight="600" fill="#1d242c">Your order</text>
<text x="412" y="200" font-size="12" fill="#3a4350">Basil seeds x2</text><text x="560" y="200" font-size="12" fill="#3a4350" text-anchor="end">8.00</text>
<text x="412" y="222" font-size="12" fill="#3a4350">Mint cuttings</text><text x="560" y="222" font-size="12" fill="#3a4350" text-anchor="end">12.00</text>
<text x="412" y="244" font-size="12" fill="#3a4350">Delivery</text><text x="560" y="244" font-size="12" fill="#3a4350" text-anchor="end">4.00</text>
<line x1="412" y1="256" x2="582" y2="256" stroke="#d6dbe1"/><text x="412" y="280" font-size="13" font-weight="600" fill="#1d242c">Total</text><text x="582" y="280" font-size="13" font-weight="600" fill="#1d242c" text-anchor="end">24.00</text>
<rect x="470" y="332" width="130" height="30" rx="6" fill="#fff6dc" stroke="#e8c76a"/><text x="484" y="351" font-size="12" fill="#6b5410">Codex is typing here</text>`);

const PAD = svg(`<rect width="640" height="400" fill="#f6f7f9"/>${TITLEBAR("release-notes.txt · Notepad", "#eef0f3")}
<rect x="0" y="28" width="640" height="24" fill="#fafbfc"/><text x="14" y="45" font-size="12" fill="#3a4350">File     Edit     View</text>
<rect x="0" y="52" width="640" height="348" fill="#ffffff"/>
<text x="24" y="86" font-size="15" font-weight="600" fill="#1d242c">Pocket Garden 1.4</text>
<text x="24" y="116" font-size="14" fill="#2b333c">- Sign-in returns you to the page you came from</text>
<text x="24" y="140" font-size="14" fill="#2b333c">- Photos upload about 10x smaller on slow Wi-Fi</text>
<text x="24" y="164" font-size="14" fill="#2b333c">- The weekly plan no longer loses unsaved edits</text>
<rect x="24" y="178" width="2" height="18" fill="#1d242c"/>
<rect x="470" y="352" width="150" height="30" rx="6" fill="#e5f3ea" stroke="#9bcdb0"/><text x="484" y="371" font-size="12" fill="#1f5a39">Claude Code is writing</text>`);

const FRAMES = { "tour:codex": SHOP, "tour:claude": PAD };

/** The keyframe picture for an example run, or null when the run is not an example. */
export const exampleKeyframe = key => FRAMES[key] || null;

const iso = seconds => new Date(Date.now() - seconds * 1000).toISOString();

export function exampleRuns() {
  return [
    {
      key: "tour:codex", title: "Check the checkout page", status: "working", agent: { name: "Codex", app: "codex" },
      surfaces: [{ id: "s1", label: "Pocket Garden checkout", kind: "browser" }], lastKeyframe: "k1", counts: { actions: 6, keyframes: 4, feedback: 0 },
      focus: null, startedAt: iso(140), updatedAt: iso(2),
      recent: [
        { kind: "action", tool: "navigate", surface: "s1", say: { url: "https://pocketgarden.example/checkout" }, at: iso(120) },
        { kind: "action", tool: "fill", surface: "s1", say: { value: "maya@example.com" }, element: { role: "textbox", label: "Email" }, at: iso(60) },
        { kind: "action", tool: "fill", surface: "s1", say: { value: "4242 4242 4242 4242" }, element: { role: "textbox", label: "Card" }, at: iso(8) },
      ],
    },
    {
      key: "tour:claude", title: "Write the release notes", status: "working", agent: { name: "Claude Code", app: "claude" },
      surfaces: [{ id: "s2", label: "Notepad", kind: "app" }], lastKeyframe: "k2", counts: { actions: 3, keyframes: 2, feedback: 0 },
      focus: null, startedAt: iso(90), updatedAt: iso(5),
      recent: [
        { kind: "action", tool: "launch_app", surface: "s2", say: { name: "Notepad" }, at: iso(80) },
        { kind: "action", tool: "type_text", surface: "s2", say: { text: "Pocket Garden 1.4" }, element: { role: "document", label: "Text editor" }, at: iso(30) },
      ],
    },
  ];
}
