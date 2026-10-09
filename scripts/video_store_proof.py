"""Evidence script (plan 28 Build 1): the video editors go through the MOD source-install path.

In a scratch workspace: the store lists the bundled video apps/mods, each installs switched
off with its manual, contracts, declared permissions and upstream credit; a disabled mod's
action is refused; enabling FilmCraft lets its real round trip run through the same dispatch;
turning it off again blocks it; EffectCraft gets the same on/verify/off
round trip. Writes scripts/evidence/VIDEO-store.json.
"""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.source_marketplace import SourceMarketplace  # noqa: E402
from grant_agent import module_plugins  # noqa: E402

IDS = ["hyperframes", "hyperframes-studio", "filmcraft", "effectcraft", "photocraft", "laya-video"]
VERIFIED = ["filmcraft", "effectcraft"]


def main():
    root = Path("D:/NeyviaRuns/video/track-video/store-ws") / str(time.time_ns())
    root.mkdir(parents=True)
    market = SourceMarketplace(root)
    listing = market.call("list", {})
    available = {row["id"]: row for row in listing["available"]}
    rows = {}
    for identity in IDS:
        row = {"listed": identity in available, "permissionsShown": bool(available.get(identity, {}).get("permissions")),
               "upstream": available.get(identity, {}).get("upstream")}
        installed = market.call("install", {"source": str(REPO / "apps" / identity)})["item"]
        read = market.call("read", {"id": identity})
        row.update(state=installed["state"], kind=installed["kind"], manualChars=len(read["manual"]),
                   contracts=read["contracts"].get("checks"), installedPermissions=installed["permissions"])
        rows[identity] = row
    service = SimpleNamespace(bus=SimpleNamespace(root=root))
    try:
        module_plugins.dispatch(service, "mod.filmcraft.commands", {"filter": "timeline.place"})
        refused_when_off = False
    except ValueError as error:
        refused_when_off = "disabled" in str(error)
    runs = {}
    for identity in VERIFIED:  # each editor: enable, run its real round trip through dispatch, switch off again
        market.call("set", {"id": identity, "enabled": True})
        started = time.perf_counter()
        result = module_plugins.dispatch(service, f"mod.{identity}.verify", {})
        seconds = time.perf_counter() - started
        market.call("set", {"id": identity, "enabled": False})
        try:
            module_plugins.dispatch(service, f"mod.{identity}.commands", {})
            refused = False
        except ValueError:
            refused = True
        runs[identity] = {"passed": result.get("passed"), "checks": result.get("checks"), "seconds": round(seconds, 1),
                          "outcome": result.get("outcome"), "refusedAfterOff": refused}
        rows[identity]["verified"] = bool(result.get("passed")) and refused
    verified, verify_seconds, refused_again = runs["filmcraft"], runs["filmcraft"]["seconds"], runs["filmcraft"]["refusedAfterOff"]
    blocked_dependency = None
    try:
        market.call("set", {"id": "laya-video", "enabled": True})
    except ValueError as error:
        blocked_dependency = str(error)
    proof = {"workspace": str(root), "items": rows,
             "allInstalledOff": all(r["state"] == "disabled" for r in rows.values()),
             "allListedWithPermissions": all(r["listed"] and r["permissionsShown"] for r in rows.values()),
             "manualsReadable": all(r["manualChars"] > 500 for r in rows.values()),
             "refusedWhileOff": refused_when_off, "filmcraftVerifyWhenOn": verified.get("passed"),
             "filmcraftVerifySeconds": verify_seconds, "filmcraftOutcome": verified.get("outcome"),
             "refusedAfterOff": refused_again, "dependencyGuard": blocked_dependency, "verifyRuns": runs,
             "verifiedInStore": sorted(i for i, r in rows.items() if r.get("verified"))}
    out = REPO / "scripts/evidence/VIDEO-store.json"
    out.write_text(json.dumps(proof, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in proof.items() if k != "items"}, indent=1))


if __name__ == "__main__":
    main()
