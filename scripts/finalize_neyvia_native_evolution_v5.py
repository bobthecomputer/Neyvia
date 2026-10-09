from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, value: str) -> None:
    path = ROOT / relative
    normalized = value.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    path.write_text(normalized, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def insert_after(text: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: anchor not found")
    return text.replace(anchor, anchor + addition, 1)


def patch_rpc() -> None:
    path = "src/grant_agent/neyvia_native_rpc.py"
    text = read(path)
    text = insert_after(
        text,
        "from .native_learning import NativeLearningStore\n",
        "from .native_pairing import NativePairingStore\n",
        "pairing import",
    )
    text = insert_after(
        text,
        "        self.goals = NativeGoalStore(self.root)\n",
        "        self.pairing = NativePairingStore(self.root)\n",
        "pairing store",
    )
    method_anchor = '''            "native.goals.due": self.goal_due,
'''
    method_addition = '''            "native.pairing.create": self.pairing_create,
            "native.pairing.redeem": self.pairing_redeem,
            "native.pairing.list": self.pairing_list,
            "native.pairing.revoke": self.pairing_revoke,
'''
    text = insert_after(text, method_anchor, method_addition, "pairing RPC methods")
    handler_anchor = "    def checkpoint_create(self, params: dict[str, Any]) -> dict[str, Any]:\n"
    handlers = '''    def pairing_create(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.pairing.create(
            str(params.get("target") or ""),
            scopes=[str(item) for item in params.get("scopes") or []] or None,
            ttl_seconds=int(params.get("ttlSeconds") or 600),
            base_url=str(params.get("baseUrl") or ""),
        )

    def pairing_redeem(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.pairing.redeem(
            str(params.get("pairingId") or ""),
            str(params.get("pairingToken") or ""),
            str(params.get("displayName") or ""),
        )

    def pairing_list(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        return {"devices": self.pairing.list_devices()}

    def pairing_revoke(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.pairing.revoke(str(params.get("deviceId") or ""))

'''
    text = text.replace(handler_anchor, handlers + handler_anchor, 1)
    write(path, text)


def patch_panel() -> None:
    path = "web/src/neyvia/NativeEvolutionPanel.jsx"
    text = read(path)
    text = text.replace(
        '"Serve the existing PWA behind HTTPS, add it to the home screen, and retain mission, proof, and route truth without copying provider secrets into the browser.",',
        '"Serve the existing PWA behind HTTPS, create a one-time scoped pairing link, add Neyvia to the home screen, and retain mission, proof, and route truth without copying provider secrets into the browser.",',
        1,
    )
    text = text.replace(
        '["Start the private web route", "Open through HTTPS", "Choose Add Neyvia"]',
        '["Start the private web route", "Create a one-time pairing link", "Choose Add Neyvia"]',
        1,
    )
    text = text.replace(
        '"The setup script creates local account state and the web backend. Candidate promotion remains hash checked and reversible rather than copying into current blindly.",',
        '"The setup script creates local account state and the web backend. Pair the NAS with runtime.connect and device.health scopes; candidate promotion remains hash checked and reversible.",',
        1,
    )
    write(path, text)


def patch_docs() -> None:
    path = "docs/NEYVIA_CONNECT_COMPUTER_PHONE_NAS.md"
    text = read(path)
    if "## One-time pairing" not in text:
        text += '''

## One-time pairing

The strict Native RPC exposes `native.pairing.create`, `native.pairing.redeem`,
`native.pairing.list`, and `native.pairing.revoke`. Pairing links expire in 1–60 minutes,
are redeemed once, and grant only named scopes. Provider credentials are not embedded.
Neyvia stores salted digests of both the pairing token and the resulting device secret.

Example request:

```json
{"jsonrpc":"2.0","id":1,"method":"native.pairing.create","params":{"target":"phone","scopes":["mission.read","proof.read","device.health"],"baseUrl":"https://neyvia.example"}}
```
'''
    write(path, text)


def patch_package_and_gates() -> None:
    package_path = ROOT / "package.json"
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload.setdefault("scripts", {})["verify:native-pairing"] = "python -m pytest -q tests/test_native_pairing.py tests/test_neyvia_native_rpc.py"
    package_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    gates_path = ROOT / "GATES.md"
    gates = gates_path.read_text(encoding="utf-8")
    if "- [ ] G50:" not in gates:
        gates = gates.rstrip() + '''

- [ ] G50: Computer, phone, tablet, NAS, and worker pairing uses one-time expiring high-entropy tokens, explicit scopes, salted digests at rest, one-time device credentials, revocation, and no provider-secret transfer.
  CHECK: python -m pytest -q tests/test_native_pairing.py tests/test_neyvia_native_rpc.py && echo NEYVIA_SCOPED_DEVICE_PAIRING_OK
  EXPECT: NEYVIA_SCOPED_DEVICE_PAIRING_OK
  EVIDENCE: pending
'''
    gates_path.write_text(gates + "\n", encoding="utf-8")


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution_v4.py"))
    namespace["main"]()
    patch_rpc()
    patch_panel()
    patch_docs()
    patch_package_and_gates()
    for relative in (
        "src/grant_agent/native_pairing.py",
        "src/grant_agent/neyvia_native_rpc.py",
    ):
        ast.parse(read(relative), filename=relative)
    print("NEYVIA_NATIVE_FINALIZED_V5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
