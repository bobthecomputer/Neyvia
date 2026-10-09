# Phone access to ASUSPSDLB — 2026-09-24

## Try it

1. Connect the iPhone to the same private Tailscale tailnet as ASUSPSDLB.
2. In Safari, open `https://asuspsdlb.example.invalid:8443/control?surface=agent`.
3. Sign in with the local Neyvia account. The account name is `admin`; its password remains in `.agent_control/neyvia_admin_password.txt` on ASUSPSDLB.
4. The Agent composer opens directly. Submit a small read-only task first. Use **Phone status** in the conversation menu to inspect connected devices.

This route reaches Neyvia's backend on ASUSPSDLB. The backend currently runs as a local process on port 47880, and Tailscale Serve privately forwards HTTPS port 8443 to it. The existing port 443 Serve route was preserved. No public Funnel was enabled. If this PC or backend is off, the phone link will not work.

The device list reads current Tailscale status. It currently reports ASUSPSDLB, iphone182, Example NAS, ZENPAUL, and ASUS-ROG-STRIX; online and expired state can change. Tailnet presence does not prove Neyvia pairing, generic desktop screen control, or physical phone interaction. The phone task button opens the Agent session hosted by this PC; local computer actions still depend on the selected tools and approvals.

## Verification

- Private URL: `/api/health` and `/control?surface=phone` returned HTTP 200. Unauthenticated `/api/backend` returned 401 and remote `/api/auth/local-session` returned 403.
- Tailscale ping received a response from iphone182 through DERP; no physical Safari session was observed.
- Local web and desktop backend bridge both returned host `ASUSPSDLB` from `get_connected_devices_command`.
- L-A-Y-A browser journeys passed for device details and Phone → Agent, one action each and zero model calls. The first Phone journey found a real desktop-width overlap; the banner was moved into the Phone grid and the unchanged route was replayed successfully.
- At 390 × 844 CSS pixels, Playwright confirmed the host banner, Agent composer, live device names, private phone link, no horizontal overflow, login form within the first viewport, and invalid-password rejection. Desktop width confirmed the task button is hit-testable and reaches the composer.

Evidence and screenshots are in `proof/phone-connect-20260924/`.

## Account login repair

The local `admin` account was rotated to the corrected password supplied in chat. The private password note was updated, and the local backend was restarted to load the new hash. The account helper now accepts passwords of 8–256 characters, so this choice can be saved through the normal rotation path. Historical Phase C scripts now read the ignored local note instead of embedding a credential in source.

Through the private phone URL, an incorrect password returned 401 and the corrected password returned 200. A mobile browser then showed the Phone workspace, retained the session after reload, and opened the Agent composer from **Send task to ASUSPSDLB**. The result and screenshots are in `phone-login-check.json`, `phone-login-success-390.png`, and `phone-login-agent-390.png` under the proof folder. L-A-Y-A independently replayed the Phone-to-Agent navigation with one executed action and a passing receipt in `laya-phone-agent-authfix-receipt.json`. Physical iPhone Safari remains unobserved.

Publication note: local account paths and network identifiers in this document are neutral examples.
