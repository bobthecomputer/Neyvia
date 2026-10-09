# Ask recovery and completion alerts

The observed native ask call failed because an option exceeded 200 characters.
The SDK stop-at-tool-name policy then finalized the error. Native ask now stops
only after a pending question has been stored; validation failures remain tool
feedback so the model can correct its call. Input limits are advertised in its
schema. The focused check exercises both the failure and durable success paths.

Chat completion now sends a generic Web Push alert after result persistence.
Delivery is nonfatal, deduplicated by turn and endpoint, and uses a two-second
HTTP timeout per endpoint. Its non-daemon worker survives short-lived desktop
bridge commands. Cancelled turns are skipped. Notification links open the chat.
Phone permission is requested before asynchronous backend work, and local
notifications prefer the service-worker API required on mobile.

Desktop chat transitions play a quiet two-tone completion sound after a user
gesture unlocks audio. Loaded history and cancelled turns do not play sounds.
Phone push setup exposes per-device registration and notification/sound tests.

Verification: native ask recovery check passed; two completion-sound Node tests
passed; push delivery's offline transport check passed for deduplication,
unsubscribe, cancellation and chat deep links. The real local Phone UI displayed
"Completion sound played." after its test button was clicked. The controls were
inspected at 390x844. This does not prove physical speaker audibility or iPhone
delivery. At setup time, the sender was configured with zero subscriptions.

The user's Tailscale HTTPS route on port 8443 proxies the local backend on 47881.
That private backend was refreshed and its HTTPS health endpoint returned 200.
The iPhone Home Screen app must grant permission and register its subscription.
Private sender keys remain in ignored local configuration and are not bundled.
