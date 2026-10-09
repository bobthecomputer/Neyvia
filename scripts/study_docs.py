"""Create, build, check, render and compare study documents on the neyvia-study class.

    python scripts/study_docs.py setup [--install]
    python scripts/study_docs.py new out.tex --variant course --title "Linear Algebra" --chapter "Sets" --chapter "Maps"
    python scripts/study_docs.py build doc.tex [--outdir D:/NeyviaRuns/docs/doc]
    python scripts/study_docs.py check doc.tex [--max-pages 60] [--require 13]
    python scripts/study_docs.py render doc.pdf --pages 1-3 [--dpi 110]
    python scripts/study_docs.py glance page.png ...      (LAYA hook; pending until attached)
    python scripts/study_docs.py port source.tex out.tex --chapter 1
    python scripts/study_docs.py compare original.pdf port.pdf --pair 1:1 --pair 3:3 --out dir

Every command prints one JSON object. Large outputs go to D:/NeyviaRuns/docs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent import study_docs  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup")
    setup.add_argument("--install", action="store_true", help="download Tectonic from its GitHub release if missing")
    new = sub.add_parser("new")
    new.add_argument("tex", type=Path)
    new.add_argument("--variant", choices=study_docs.VARIANTS, default="course")
    new.add_argument("--title", required=True)
    new.add_argument("--subtitle")
    new.add_argument("--chapter", action="append", required=True)
    new.add_argument("--source-prefix", default="")
    new.add_argument("--overwrite", action="store_true")
    build = sub.add_parser("build")
    build.add_argument("tex", type=Path)
    build.add_argument("--outdir", type=Path)
    check = sub.add_parser("check")
    check.add_argument("tex", type=Path)
    check.add_argument("--outdir", type=Path)
    check.add_argument("--max-pages", type=int)
    check.add_argument("--require", default="13", help="blocks every concept must have (default 13: definition and reflex)")
    render = sub.add_parser("render")
    render.add_argument("pdf", type=Path)
    render.add_argument("--pages", default="1-3")
    render.add_argument("--dpi", type=int, default=110)
    render.add_argument("--out", type=Path)
    glance = sub.add_parser("glance")
    glance.add_argument("pngs", type=Path, nargs="+")
    port = sub.add_parser("port")
    port.add_argument("source", type=Path)
    port.add_argument("out", type=Path)
    port.add_argument("--chapter", type=int, action="append")
    compare = sub.add_parser("compare")
    compare.add_argument("original", type=Path)
    compare.add_argument("port", type=Path)
    compare.add_argument("--pair", action="append", required=True, help="original:port page numbers")
    compare.add_argument("--out", type=Path, required=True)
    compare.add_argument("--dpi", type=int, default=80)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "setup":
        result = study_docs.toolchain(install=args.install)
    elif args.command == "new":
        result = study_docs.create(args.tex, args.variant, args.title, args.chapter, args.subtitle, args.source_prefix, args.overwrite)
    elif args.command == "build":
        result = study_docs.build(args.tex, args.outdir)
    elif args.command == "check":
        result = study_docs.check(args.tex, args.outdir, args.max_pages, args.require)
    elif args.command == "render":
        result = study_docs.render(args.pdf, args.out, args.pages, args.dpi)
    elif args.command == "glance":
        result = study_docs.glance(args.pngs)
    elif args.command == "port":
        result = study_docs.port(args.source, args.out, tuple(args.chapter or [1]))
    else:
        pairs = [tuple(int(part) for part in pair.split(":")) for pair in args.pair]
        result = study_docs.compare(args.original, args.port, pairs, args.out, args.dpi)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
