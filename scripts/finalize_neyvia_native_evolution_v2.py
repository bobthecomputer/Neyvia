from __future__ import annotations

import ast
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


def patch_native_panel() -> None:
    path = "web/src/neyvia/NativeEvolutionPanel.jsx"
    text = read(path)
    anchor = '''  const selected = SETUP_PATHS[activePath];
  const ActiveIcon = selected.icon;
  const pathEntries = useMemo(() => Object.entries(SETUP_PATHS), []);
'''
    replacement = '''  const selected = SETUP_PATHS[activePath];
  const ActiveIcon = selected.icon;
  const pathEntries = useMemo(() => Object.entries(SETUP_PATHS), []);
  const effectiveSpawnTree = useMemo(() => {
    if (spawnTree) return spawnTree;
    if (typeof window === "undefined") return null;
    const previewEnabled = new URLSearchParams(window.location.search).get("preview-control") === "1";
    return previewEnabled ? window.__NEYVIA_PREVIEW_SPAWN_TREE__ ?? null : null;
  }, [spawnTree]);
'''
    text = replace_once(text, anchor, replacement, "preview spawn tree")
    text = text.replace(
        "      <SpawnedAgentLineage spawnTree={spawnTree} />\n",
        "      <SpawnedAgentLineage spawnTree={effectiveSpawnTree} />\n",
        1,
    )
    write(path, text)


def patch_screenshot_fixture() -> None:
    path = "scripts/capture_native_evolution.mjs"
    text = read(path)
    anchor = '''  const page = await browser.newPage({ viewportSize: viewport, reducedMotion: "reduce" });
'''
    addition = '''  await page.addInitScript(() => {
    window.__NEYVIA_PREVIEW_SPAWN_TREE__ = {
      parentSessionId: "neyvia-preview-parent",
      children: [
        {
          spawnId: "spawn-plan",
          parentSessionId: "neyvia-preview-parent",
          childSessionId: "neyvia-preview-parent.planner.a1",
          role: "planner",
          task: "Map the setup and responsive proof surface",
          model: "gpt-5.6-sol",
          effort: "high",
          allowMutations: false,
          status: "completed",
          receiptPath: "proof/spawn-plan.json",
        },
        {
          spawnId: "spawn-design",
          parentSessionId: "neyvia-preview-parent",
          childSessionId: "neyvia-preview-parent.designer.b2",
          role: "designer",
          task: "Render and critique computer, phone, and NAS onboarding",
          model: "design-route",
          effort: "high",
          allowMutations: false,
          status: "running",
          receiptPath: "",
        },
        {
          spawnId: "spawn-verify",
          parentSessionId: "neyvia-preview-parent",
          childSessionId: "neyvia-preview-parent.verifier.c3",
          role: "verifier",
          task: "Reject clipped compact controls and unproved completion",
          model: "gpt-5.6-sol",
          effort: "xhigh",
          allowMutations: false,
          status: "blocked",
          receiptPath: "proof/spawn-verify.json",
        },
      ],
    };
  });
'''
    text = insert_after(text, anchor, addition, "screenshot spawn fixture")
    write(path, text)


def patch_tests() -> None:
    path = "tests/test_spawned_agent_ui_contract.py"
    text = read(path)
    if "test_preview_fixture_is_explicitly_preview_only" not in text:
        text += '''


def test_preview_fixture_is_explicitly_preview_only() -> None:
    panel = (ROOT / "web" / "src" / "neyvia" / "NativeEvolutionPanel.jsx").read_text(encoding="utf-8")
    capture = (ROOT / "scripts" / "capture_native_evolution.mjs").read_text(encoding="utf-8")

    assert 'get("preview-control") === "1"' in panel
    assert "__NEYVIA_PREVIEW_SPAWN_TREE__" in panel
    assert "__NEYVIA_PREVIEW_SPAWN_TREE__" in capture
    assert "if (spawnTree) return spawnTree" in panel
'''
    write(path, text)


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution.py"))
    namespace["main"]()
    patch_native_panel()
    patch_screenshot_fixture()
    patch_tests()
    ast.parse(read("src/grant_agent/neyvia_agent.py"), filename="neyvia_agent.py")
    print("NEYVIA_NATIVE_FINALIZED_V2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
