from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.web_backend import (
    ADMIN_CONFIG_RELATIVE_PATH,
    ADMIN_PASSWORD_RELATIVE_PATH,
    DEFAULT_PORT,
    add_or_reset_admin_user,
    ensure_admin_config,
)


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def command_version(command: str) -> str:
    resolved = which(command)
    if not resolved:
        return "missing"
    completed = subprocess.run(
        [resolved, "--version"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return output[0] if output else "installed"


def collect_add_users(add_user_values: list[str] | None, add_users_value: str) -> list[str]:
    candidates: list[str] = []
    candidates.extend(add_user_values or [])
    if add_users_value:
        candidates.extend(str(add_users_value).split(","))

    users: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for fragment in str(candidate).split(","):
            username = fragment.strip()
            if not username or username in seen:
                continue
            users.append(username)
            seen.add(username)
    fragments = [fragment.strip() for candidate in candidates for fragment in str(candidate).split(",") if fragment.strip()]
    if users != list(dict.fromkeys(fragments)):
        raise ValueError("Contract d.runtime.nas-setup.users: first-seen nonempty usernames must be retained exactly once")
    return users


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare Syntelos for NAS hosting.")
    parser.add_argument("--skip-npm", action="store_true", help="Do not install/build frontend assets.")
    parser.add_argument("--admin-user", default="admin", help="Backward-compatible alias for --account-user.")
    parser.add_argument("--account-user", default="", help="Username for the first local Syntelos account.")
    parser.add_argument("--display-name", default="", help="Display name for the created or reset local user.")
    parser.add_argument(
        "--add-user",
        action="append",
        default=[],
        help="Add or reset one additional local account without replacing existing users. Repeat this flag for multiple users.",
    )
    parser.add_argument(
        "--add-users",
        default="",
        help="Add or reset multiple users from a comma-separated list, for example theo,sam,alex.",
    )
    parser.add_argument(
        "--reset-admin-password",
        "--reset-account-password",
        action="store_true",
        dest="reset_admin_password",
        help="Generate a fresh ignored account password file.",
    )
    parser.add_argument(
        "--public-url",
        default="",
        help="Browser-facing base URL without /control, for example https://syntelos.<tailnet>.ts.net.",
    )
    args = parser.parse_args(argv)
    account_user = args.account_user or args.admin_user

    print("Syntelos NAS setup")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Node: {command_version('node')}")
    print(f"npm: {command_version('npm')}")

    add_users = collect_add_users(args.add_user, args.add_users)
    if add_users:
        if args.display_name and len(add_users) > 1:
            print(
                "Note: --display-name only applies to a single user. Multi-user add uses per-user default display names."
            )
        for username in add_users:
            display_name = args.display_name if len(add_users) == 1 else None
            _, _, user_password_path = add_or_reset_admin_user(
                ROOT,
                username=username,
                display_name=display_name or None,
                public_url=args.public_url or None,
            )
            print(f"User '{username}' is ready. Password file: {user_password_path}")
        print(f"Added {len(add_users)} local account(s).")
        open_url = (args.public_url.rstrip("/") if args.public_url else f"http://<NAS-IP>:{DEFAULT_PORT}") + "/control"
        print(f"Open after backend start: {open_url}")
        return 0

    _, generated = ensure_admin_config(
        ROOT,
        reset_password=args.reset_admin_password,
        username=account_user,
        display_name=args.display_name or None,
        public_url=args.public_url or None,
    )
    if not args.skip_npm:
        run(["npm", "ci"])
        run(["npm", "run", "frontend:build"])

    password_path = ROOT / ADMIN_PASSWORD_RELATIVE_PATH
    if generated:
        print(f"Account password generated at {password_path}")
    else:
        print(f"Account config already exists at {ROOT / ADMIN_CONFIG_RELATIVE_PATH}")
    print("")
    print("Start the NAS console:")
    start_command = f"python scripts/run_web_backend.py --host 0.0.0.0 --port {DEFAULT_PORT}"
    if args.public_url:
        start_command += f" --public-url {args.public_url.rstrip('/')}"
    print(f"  {start_command}")
    print("")
    print("Then open:")
    open_url = (args.public_url.rstrip("/") if args.public_url else f"http://<NAS-IP>:{DEFAULT_PORT}") + "/control"
    print(f"  {open_url}")
    if args.public_url and args.public_url.startswith("https://"):
        print("")
        print("DSM reverse proxy target:")
        print(f"  http://127.0.0.1:{DEFAULT_PORT}")
    print("")
    print("Direct NAS HTTPS certificate setup:")
    print(
        "  python scripts/setup_nas_https.py --host <NAS-DNS-or-IP> "
        "--alt-host <NAS-IP> --install-windows-current-user-root "
        "--enable-firefox-enterprise-roots"
    )
    print("")
    print("Packaged NAS runtime setup:")
    print("  python scripts/install_nas_runtime_stack.py --install-openclaw")
    print("  python scripts/nas_runtime_doctor.py")
    print("")
    print("Add another local account later:")
    print("  python scripts/nas_setup.py --skip-npm --add-user paul --display-name \"Paul\"")
    print("  python scripts/nas_setup.py --skip-npm --add-user theo --add-user sam")
    print("  python scripts/nas_setup.py --skip-npm --add-users theo,sam,alex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
