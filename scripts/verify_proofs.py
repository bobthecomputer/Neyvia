"""neyvia verify: production contracts and isolated manual self-checks."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))


def main(argv=None):
    # JSON receipts include actual rendered text. Keep the transport independent
    # of the Windows console code page, including redirected worker streams.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--area-worker", help=argparse.SUPPRESS)
    parser.add_argument("--area-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--area", action="append")
    parser.add_argument('--adapter-chapter', action='append', choices=('git','handoff','html','ocr','publication','sync','release'),
                        help='Selected B adapter chapters only; cannot establish startup completeness')
    parser.add_argument("--fixture-ports", help="Comma-separated assigned loopback ports; at least six distinct ports, never 47881")
    parser.add_argument("--skip-manuals", action="store_true", help="Only area contracts; does not prove startup completeness")
    parser.add_argument("--allow-frontier", action="store_true", help="Exit successfully for passing migrated contracts; report remains incomplete")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=900,
                        help="Maximum wait for all isolated real self-checks; default 900, override for slower hosts")
    args = parser.parse_args(argv)
    if args.fixture_ports:
        from grant_agent.proof_ports import configure_ports
        try:
            configure_ports([int(port) for port in args.fixture_ports.split(",")])
        except ValueError as error:
            parser.error(str(error))
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.worker and __import__("os").environ.get("NEYVIA_PROOF_LOW_PRIORITY") == "1":
        # Background self-check: area workers inherit this, so the user's PC stays responsive.
        try:
            if sys.platform == "win32":
                import ctypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.GetCurrentProcess.restype = ctypes.c_void_p
                kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL, inherited by area workers
            else:
                __import__("os").nice(10)
        except Exception:
            pass
    from grant_agent.proof_credential_guard import install
    install(args.root)
    if __import__('os').environ.get('NEYVIA_C8_SOURCE'):
        # An explicitly scoped C8 backend can admit these original host-only
        # runners. Their child interpreters retain the same write/socket fence.
        selected_host = set(args.area or ([args.area_worker] if args.area_worker else []))
        if selected_host and selected_host <= {'proofs-b-engine', 'proofs-b-harness'}:
            from grant_agent.neyvia_inception import _declared_run_root
            args.root.resolve().relative_to(_declared_run_root() or REPO / '.agent_control/proofs/C8')
            from c8_scope import install as install_c8_scope, assigned_ports
            install_c8_scope(allow_children=True, writable_root=args.root)
            from grant_agent.proof_ports import configure_ports
            declared = args.fixture_ports or __import__('os').environ.get('NEYVIA_C8_PROOF_PORTS', '48751,48753,48754,48755,48756,48759')
            ports = [int(value) for value in declared.split(',')]
            if not set(ports) <= assigned_ports():
                parser.error('C8 proof fixtures must stay inside the declared C8 port set')
            configure_ports(ports)
    from grant_agent.proof_verifier import run_verification, _run_verification, _run_area, ADAPTERS, RUNNERS
    if args.area_worker:
        if args.area_worker not in ADAPTERS.keys() | RUNNERS.keys() or args.area_root is None:
            parser.error("Unknown host-owned proof area or missing disposable root")
        area_root = args.area_root.resolve()
        # The proofs directory may be relocated through a junction (large outputs kept off C:).
        area_root.relative_to((args.root.resolve() / ".agent_control/proofs").resolve())
        if not area_root.is_dir():
            parser.error("Proof area root was not prepared by its supervisor")
        trace_stream = None
        if __import__("os").environ.get("NEYVIA_PROOF_PROGRESS") == "1":
            import faulthandler
            trace_stream = (area_root / "worker-stacks.log").open("w", encoding="utf-8")
            faulthandler.dump_traceback_later(120, repeat=True, file=trace_stream)
        try:
            report = _run_area(args.area_worker, area_root, adapter_chapters=args.adapter_chapter)
            print(json.dumps(report, ensure_ascii=False))
            return int(not report.get("ok"))
        finally:
            if trace_stream is not None:
                faulthandler.cancel_dump_traceback_later()
                trace_stream.close()
    runner = _run_verification if args.worker else run_verification
    options = {} if args.worker else {"timeout_seconds": args.timeout_seconds}
    report = runner(args.root, areas=args.area, include_manuals=not args.skip_manuals,
                    adapter_chapters=args.adapter_chapter, **options)
    if args.output:
        from grant_agent.durability import atomic_write_json
        atomic_write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] or (args.allow_frontier and report["contractsOk"]) else 1 if not report["contractsOk"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
