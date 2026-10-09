"""Workspace tools for Paul's study documents (manuals/cl/documents.cl).

documents.create writes a new .tex on the neyvia-study class; build compiles it
with Tectonic; check runs the outcome checks on the produced PDF, log and aux;
render writes page PNGs; glance hands those PNGs to the pluggable LAYA judge.
Builds and renders go to D:/NeyviaRuns/docs, never into the workspace.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import study_docs

TEXT = {"type": "string", "minLength": 1}
PATH = {"path": TEXT}
DEFINITIONS = [
    ("documents.create", "Create a study document on Paul's neyvia-study template: course (six blocks per concept) or sheet (formula, method, reflex); one chapter per title.",
     {**PATH, "variant": {"type": "string", "enum": list(study_docs.VARIANTS)}, "title": TEXT,
      "chapters": {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 40}, "subtitle": TEXT,
      "sourcePrefix": {"type": "string"}, "overwrite": {"type": "boolean"}}, ["path", "variant", "title", "chapters"]),
    ("documents.build", "Compile a study document with Tectonic (XeTeX, Inter bundled); returns the PDF, log, seconds and page count.", PATH, ["path"]),
    ("documents.check", "Run the outcome checks on a built study document: compiles, references, overfull boxes, Inter embedded, block order and source tags, page count.",
     {**PATH, "maxPages": {"type": "integer", "minimum": 1, "maximum": 2000},
      "require": {"type": "string", "pattern": "^[1-6]{1,6}$"}}, ["path"]),
    ("documents.render", "Render pages of a built study document to PNG files on D:/NeyviaRuns/docs.",
     {**PATH, "pages": {"type": "string", "pattern": "^(all|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*)$"},
      "dpi": {"type": "integer", "minimum": 40, "maximum": 300}}, ["path"]),
    ("documents.glance", "Ask the attached LAYA page-glance judge whether rendered pages look broken; reports not available until a judge is attached.",
     {**PATH, "pages": {"type": "string", "pattern": "^(all|[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*)$"}}, ["path"]),
]
READ = {"documents.check", "documents.glance"}


def tex_path(root, value) -> Path:
    path = Path(value).expanduser()
    path = (Path(root) / path) if not path.is_absolute() else path
    path = path.resolve()
    protected = Path(r"C:\Users\user\Projects\Neyvia").resolve()
    if path == protected or protected in path.parents:
        raise ValueError("The live Neyvia tree is protected")
    if path.suffix != ".tex":
        raise ValueError("Study documents are .tex files")
    return path


def outdir(tex: Path) -> Path:
    """One build folder per document path, so equal names never share outputs."""
    digest = hashlib.sha256(str(tex).casefold().encode()).hexdigest()[:8]
    return study_docs.RUNS / f"{tex.stem}-{digest}"


def run(root, name, args):
    from jsonschema import Draft202012Validator
    definition = next((row for row in DEFINITIONS if row[0] == name), None)
    if definition is None:
        raise ValueError("Unknown documents operation")
    error = next(Draft202012Validator({"type": "object", "properties": definition[2], "required": definition[3],
                                       "additionalProperties": False}).iter_errors(args), None)
    if error:
        raise ValueError("Invalid documents argument " + ".".join(map(str, error.absolute_path)) + ": " + error.message)
    tex = tex_path(root, args["path"])
    if name == "documents.create":
        return study_docs.create(tex, args["variant"], args["title"], args["chapters"], args.get("subtitle"),
                                 args.get("sourcePrefix", ""), bool(args.get("overwrite")))
    if name == "documents.build":
        return study_docs.build(tex, outdir(tex))
    if name == "documents.check":
        return study_docs.check(tex, outdir(tex), args.get("maxPages"), args.get("require", "13"))
    pdf = outdir(tex) / (tex.stem + ".pdf")
    if not pdf.is_file():
        raise FileNotFoundError("Build the document before rendering it")
    if name == "documents.render":
        return study_docs.render(pdf, outdir(tex) / "pages", args.get("pages", "1-3"), args.get("dpi", 110))
    rendered = study_docs.render(pdf, outdir(tex) / "glance", args.get("pages", "1-3"), 80)
    return study_docs.glance(rendered["pngs"])


def call(service, name, args):
    return run(service.bus.root, name, args)
