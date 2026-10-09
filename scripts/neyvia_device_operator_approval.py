from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.native_device_operator_authority import (
    OperatorAuthorizedDeviceCommandStore,
)
from grant_agent.native_device_operator_signing_wire import (
    deny_operator_approval,
    inspect_signing_request,
    prepare_signing_request,
    submit_operator_signature,
)


def _store(args: argparse.Namespace) -> OperatorAuthorizedDeviceCommandStore:
    return OperatorAuthorizedDeviceCommandStore(
        Path(args.root).resolve(),
        operator_public_key_path=args.public_key_path or None,
        operator_key_id=args.key_id or None,
    )


def _read_json(path_text: str) -> dict:
    path = Path(path_text).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Signing request file must contain one JSON object.")
    return payload


def _write_json(path_text: str, payload: dict) -> Path:
    path = Path(path_text).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _read_signature(args: argparse.Namespace) -> str:
    if args.signature_file:
        return Path(args.signature_file).expanduser().resolve().read_text(
            encoding="utf-8"
        ).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError(
        "Provide --signature-file or pipe the base64 Ed25519 signature on stdin."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and submit paired-device operator approvals without exposing "
            "the operator private key to NEYVIA."
        )
    )
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument(
        "--public-key-path",
        default=os.environ.get("NEYVIA_DEVICE_OPERATOR_PUBLIC_KEY_PATH", ""),
    )
    parser.add_argument(
        "--key-id",
        default=os.environ.get("NEYVIA_DEVICE_OPERATOR_KEY_ID", ""),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="Create exact server-prepared bytes for an external signer.",
    )
    prepare.add_argument("--approval-id", required=True)
    prepare.add_argument("--decided-by", required=True)
    prepare.add_argument("--note", default="")
    prepare.add_argument(
        "--output",
        default="",
        help="Optional JSON output path. Default prints to stdout.",
    )

    inspect = subparsers.add_parser(
        "inspect",
        help="Validate a signing-request file and print its human-review projection.",
    )
    inspect.add_argument("--request", required=True)

    approve = subparsers.add_parser(
        "approve",
        help=(
            "Submit a base64 Ed25519 signature over the exact decoded "
            "signingBytesBase64 bytes."
        ),
    )
    approve.add_argument("--request", required=True)
    approve.add_argument(
        "--signature-file",
        default="",
        help="File containing only the base64 signature; otherwise read stdin.",
    )

    deny = subparsers.add_parser(
        "deny",
        help="Fail-safe denial. This removes authority and never needs a signature.",
    )
    deny.add_argument("--approval-id", required=True)
    deny.add_argument("--decided-by", required=True)
    deny.add_argument("--note", default="")
    deny.add_argument(
        "--confirm",
        action="store_true",
        help="Required explicit acknowledgement for the host-side denial.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "inspect":
            inspected = inspect_signing_request(_read_json(args.request))
            print(
                json.dumps(
                    {
                        "schema": inspected["schema"],
                        "algorithm": inspected["algorithm"],
                        "keyId": inspected["keyId"],
                        "approvalId": inspected["approvalId"],
                        "signingRule": inspected["signingRule"],
                        "signingBytesSha256": inspected["signingBytesSha256"],
                        "review": inspected["review"],
                        "privateKeyRequiredByNeyvia": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        store = _store(args)
        if args.command == "prepare":
            request = prepare_signing_request(
                store,
                args.approval_id,
                decided_by=args.decided_by,
                note=args.note,
            )
            if args.output:
                path = _write_json(args.output, request)
                print(
                    json.dumps(
                        {
                            "status": "prepared",
                            "approvalId": request["approvalId"],
                            "signingBytesSha256": request["signingBytesSha256"],
                            "requestPath": str(path),
                            "privateKeyRequiredByNeyvia": False,
                        },
                        indent=2,
                    )
                )
            else:
                print(json.dumps(request, ensure_ascii=False, indent=2))
            return 0

        if args.command == "approve":
            request = _read_json(args.request)
            signature = _read_signature(args)
            receipt = submit_operator_signature(
                store,
                request,
                signature_base64=signature,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0

        if args.command == "deny":
            if not args.confirm:
                parser.error("deny requires --confirm")
            receipt = deny_operator_approval(
                store,
                args.approval_id,
                decided_by=args.decided_by,
                note=args.note,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0

        parser.error("unknown command")
    except (KeyError, PermissionError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
