"""Real SDK/CL acceptance driver; contracts live in manuals/cl/modules.cl."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
wheel = REPO / ".agent_control/mod/sdk-wheel/neyvia_sdk-1.0.0-py3-none-any.whl"
if wheel.is_file():
    sys.path.insert(0, str(wheel))
from neyvia_sdk import NeyviaClient


def main():
    sdk = NeyviaClient("http://127.0.0.1:48911", timeout=180)
    sdk.sign_in()
    result = []
    def contract(lines):
        # Each acceptance case is an independent task with independent goals.
        owner = NeyviaClient(sdk.base_url, timeout=180)
        owner.sign_in()
        return owner.cl(lines)
    def record(name, value):
        result.append({"step": name, "result": value})
        print(json.dumps({"step": name, "ok": value.get("ok", True) if isinstance(value, dict) else True})[:500], flush=True)
    try:
        for identity in ("scroll-study", "hello-module"):
            record("install-" + identity, sdk.command("source_marketplace_install_command", {"source": str(REPO / "apps" / identity)}))
            lines = f'G: marketplace.get(id="{identity}").item.state == "active"\nrun modules.enable-source(id="{identity}")\ndone()'
            record("enable-" + identity, contract(lines))
        record("hello-contract", contract('G: mod.hello.greet(name="Paul").greeting == "Hello, Paul!"\nrun hello-module.verify-greeting()\ndone()'))
        record("disable-mod", contract('G: marketplace.get(id="hello-module").item.state == "disabled"\nrun modules.disable-source(id="hello-module")\ndone()'))
        try:
            sdk.tool("neyvia.mod.hello.greet", {"name": "Paul"})
        except Exception as error:
            record("disabled-mod-refused", {"ok": True, "error": str(error)})
        else:
            raise RuntimeError("Disabled mod action was admitted")
        record("reenable-mod", contract('G: marketplace.get(id="hello-module").item.state == "active"\nrun modules.enable-source(id="hello-module")\ndone()'))
        record("update-scroll", sdk.command("source_marketplace_update_command", {"id": "scroll-study"}))
        catalog = sdk.command("get_neyvia_application_registry_command")
        # Keep the report bounded to this app, not unrelated local accounts/apps.
        record("application-registry", {key: [row for row in value if row.get("applicationId") == "scroll-study"]
            for key, value in catalog.items() if isinstance(value, list)})
        application = next(row for row in catalog["ecosystemApplications"] if row["applicationId"] == "scroll-study")
        if not application["valid"] or not {"provider-routing", "memory", "sessions"}.issubset(application["services"]):
            raise RuntimeError("Scroll Study's shared services are missing from the real app registry")
        record("laya-boundary", sdk.verify(question="cl_route", candidate="modules", evidence={"query": "module map"}))
        record("map-contract", contract('G: modules.validate().ok == true\nrun modules.verify-map()\ndone()'))
    finally:
        (REPO / "scripts/evidence/MOD-sdk.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
