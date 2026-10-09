from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def insert_after(text: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: anchor not found")
    return text.replace(anchor, anchor + addition, 1)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "apply_neyvia_native_runtime_hooks_v2.py"))
    namespace["main"]()

    component_path = ROOT / "web" / "src" / "neyvia" / "NativeEvolutionPanel.jsx"
    component = component_path.read_text(encoding="utf-8")
    component = insert_after(
        component,
        'import "./nativeEvolutionPanel.css";\n',
        'import SpawnedAgentLineage from "./SpawnedAgentLineage";\n',
        "lineage import",
    )
    component = replace_once(
        component,
        "export function NativeEvolutionPanel() {\n",
        "export function NativeEvolutionPanel({ spawnTree }) {\n",
        "component props",
    )
    lineage = '''
      <SpawnedAgentLineage spawnTree={spawnTree} />
'''
    component = insert_after(
        component,
        "      ) : null}\n",
        lineage,
        "lineage rendering",
    )
    component_path.write_text(component, encoding="utf-8")

    surface_path = ROOT / "web" / "src" / "neyvia" / "HarnessesSurface.jsx"
    surface = surface_path.read_text(encoding="utf-8")
    if "<NativeEvolutionPanel />" in surface:
        expression = ""
        for variable in ("selectedJob", "selectedRun", "selectedHarnessJob", "activeJob"):
            if variable in surface:
                expression = (
                    f"<NativeEvolutionPanel spawnTree={{{variable}?.receipt?.spawnTree ?? "
                    f"{variable}?.receipt?.spawn_tree ?? {variable}?.spawnTree}} />"
                )
                break
        if expression:
            surface = surface.replace("<NativeEvolutionPanel />", expression, 1)
    surface_path.write_text(surface, encoding="utf-8")
    print("NEYVIA_SPAWNED_AGENT_UI_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
