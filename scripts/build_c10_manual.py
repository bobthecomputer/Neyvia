"""Generate and validate only the research-assistant executable manual."""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.neyvia_workspace_tools import tool_specs
from grant_agent.native_tools import NativeToolSpec
from grant_agent.neyvia_manuals import validate, render
from grant_agent.cl.manuals import manual_to_cl, cl_to_manual


class ResearchRegistry:
    """Validate against the same executable workspace tool specifications."""
    def __init__(self):
        self.specs = {spec.name: spec for spec in tool_specs(NativeToolSpec) if spec.name.startswith("neyvia.research.")}
        self._handlers = {name: self.dispatch for name in self.specs}

    def dispatch(self, workspace, name, args):
        return workspace.call(name.removeprefix("neyvia."), args)

    def describe(self, name):
        spec = self.specs[name]
        return {"inputSchema": spec.input_schema, "mutability_class": spec.mutability_class}


def main():
    registry = ResearchRegistry()
    schemas = {name: spec.input_schema for name, spec in registry.specs.items()}
    answer_schema = schemas["neyvia.research.answer"]
    path_schema = schemas["neyvia.research.receipt"]
    result = {"type": "object", "properties": {"receiptPath": {"type": "string", "minLength": 1}, "status": {"type": "string"},
        "claimGrounding": {"type": "object", "properties": {"accepted": {"type": "boolean"}}}}}
    chapter = {
        "title": "Public research with source and provider receipts",
        "state": {"saved": {"tool": "neyvia.research.receipt", "args": {"path": {"$input": "path"}}, "inputs": path_schema, "shape": result}},
        "actions": {
            "answer": {"tool": "neyvia.research.answer", "schema": "neyvia.research.answer", "returns": result,
                       "pre": "Public web research is authorized in the selected root; explicit Obscura port 48771-48779, configured providers and non-stealth runtime are available.",
                       "effect": "Use Sol-low keyword planning and live web search, C10b public-source Obscura/PDF capture with CPU LAYA advisory ranking, exact citation repair, and an independent Sol-low claim-grounding check; persist answers or explicit failures.", "reversible": False},
            "receipt": {"tool": "neyvia.research.receipt", "schema": "neyvia.research.receipt", "returns": result,
                        "pre": "The receipt path is inside the selected workspace and comes from its research run.", "effect": "Read the persisted receipt without running another model or web request.", "reversible": True}},
        "checks": {"grounded": {"tool": "neyvia.research.receipt", "args": {"path": {"$result": "research.receiptPath"}},
                                  "expect": {"path": "claimGrounding.accepted", "op": "eq", "value": True}}},
        "procedures": {
            "research": {"goal": "Answer an authorized public question and inspect its persisted completion receipt", "inputs": answer_schema,
                         "steps": [{"action": "answer", "args": {"question": {"$input": "question"}, "obscuraPort": {"$input": "obscuraPort"},
                             "rounds": 5, "timeoutSeconds": 600}, "save": "research", "check": "grounded"},
                                   {"judge": "support"}]},
            "inspect-receipt": {"goal": "Inspect source evidence and failures for an existing research run", "inputs": path_schema,
                                "steps": [{"action": "receipt", "args": {"path": {"$input": "path"}}, "save": "saved"}]}},
        "judge": {"support": {"question": "Do the retrieved passages support every material answer claim, with no contradiction or missing reasoning?", "options": ["supported", "needs-more-evidence", "contradicted"],
                              "constraints": "Completed status proves execution only. Inspect answer.citations and source receipts for entailment; quoted text existing in a source alone does not prove the claim. Preserve failed attempts and request further research if evidence is inadequate."}},
        "pitfalls": [{"failure": "Missing runtime, search CAPTCHA, unreadable source, provider timeout or unsupported output", "recovery": "Read the failed receipt and stage-specific errors; repair the underlying service or query, then run a fresh question without changing reference answers."},
                     {"failure": "Confusing reachable URLs or matching quotes with factual support", "recovery": "Read the surrounding source context and verify the actual claim and calculation; distinguish unsupported, contradicted and inaccessible evidence."}],
        "frontier": ["Open briefs and semantic accuracy require a frozen arm-blind judge; completed receipts alone are not accuracy judgments.", "Subscription token usage does not establish attributable monetary cost; unavailable cost remains unknown.", "General superiority and lower cost require a completed matched comparison; targeted repairs are development evidence."],
        "guidance": ["Pass an explicit assigned port; there is no default port and no stealth browsing.", "Only public questions and retrieved source content go to research models. Never provide benchmark gold answers or another arm's results.", "Read source receipts, model receipts, searches, cascade and elapsedMs before reporting what ran.", "Search records the actual engine and each transport attempt; an unavailable configured engine is never reported as having searched.", "Every live and data-only model step explicitly uses gpt-6.1-sol at low effort. Luna is never called by this research route. Sol preserves full relevant C10b source context; the independent checker verifies necessary relationships, temporal filters, calculations and every material answer claim. Reject a genuine quote attached to a false claim.", "A literal span repair copies one contiguous actual source span, preserving words, numbers and punctuation; it reconciles HTML whitespace or includes actual adjacent context for a short quote, and does not establish entailment.", "An explicit as-of day resolves Wikipedia revisions through the public API; month and year precision use the period's last day. Include a day when that boundary matters.", "PDF sources use native pypdf extraction with a 32-MiB response byte limit and 2,097,152-character extracted-text limit, separately labeled from DOM text. Metadata records actual SHA, pages and truncation. Encrypted, malformed, incomplete or oversized PDFs are refused; no OCR or invented text is used.", "Research arms receive only public prompts. Independent comparator outputs and reference answers never enter Neyvia context. Every model call has actual token receipts; evaluation overhead is separate.", "Retrieved text and captured table rows retain C10b context budgets. Source ranking is advisory, never factual evidence. No whole-panel accuracy or cost claim follows from a successful native answer.", "The request has a 600-second bounded model deadline. Missing providers, inaccessible sources, invalid quotes and rejected claims remain visible; no invented text or answer fallback.", "Existing owner browser runtimes are borrowed and must not be stopped by a research call."]}
    data = {"schema": "neyvia.manual.v1", "id": "research-assistant", "kind": "workflow", "schemas": schemas, "chapters": {"public-research": chapter}}
    checked = validate(data, registry)
    metadata = {name: {"mutability_class": spec.mutability_class} for name, spec in registry.specs.items()}
    source = manual_to_cl(data, metadata)
    if cl_to_manual(source) != data:
        raise ValueError("Research manual CL roundtrip changed semantics")
    (REPO / "manuals/research-assistant.manual.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (REPO / "manuals/cl/research-assistant.cl").write_text(source, encoding="utf-8")
    view = "<!-- Generated from manuals/cl/research-assistant.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->\n# research-assistant\n\n## public-research\n" + render(chapter, schemas, layer="research-assistant", source_version="1.1") + "\n"
    (REPO / "docs/manuals/research-assistant.md").write_text(view.rstrip() + "\n", encoding="utf-8")
    index_path = REPO / "config/neyvia_manuals.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not any(row["id"] == data["id"] for row in index["manuals"]):
        index["manuals"].append({"id": data["id"], "path": "manuals/research-assistant.manual.json", "description": "Public Search, Obscura, LAYA and validated research cascade with real source receipts", "clSource": "manuals/cl/research-assistant.cl"})
        index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(checked))


if __name__ == "__main__":
    main()
