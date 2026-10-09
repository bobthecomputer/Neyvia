# delivery_receipt

Provides backend / delivery_receipt in Neyvia.

- **Public API:** `acknowledge_delivery_receipt`, `delivery_receipt_from_event`, `delivery_receipts_path`, `generate_web_push_vapid_config`, `load_delivery_receipts`, `load_receipts`, `load_web_push_subscriptions`, `ntfy_settings_path`, `ntfy_status`, `record_browser_delivery_receipt`, `record_delivery_receipt`, `record_web_push_subscription`, `send_approval_escalation_receipt`, `send_chat_completion_web_push`, `send_ntfy_delivery_receipt`, `send_telegram_delivery_receipt`, `send_watchdog_delivery_receipt`, `send_watchdog_ntfy_delivery_receipt`, `send_web_push_delivery_receipts`, `web_push_status`, `web_push_subscriptions_path`, `web_push_vapid_path`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `delivery.ack`, `delivery.append`, `delivery.browser`, `delivery.message`, `delivery.observe`, `delivery.skipped`, `delivery.tail-update`, `delivery.update`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.models](../backend.models/README.md), [backend.proofs_b_desktop](../backend.proofs_b_desktop/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/delivery_receipt.py](../../src/grant_agent/delivery_receipt.py).
