from __future__ import annotations

import argparse
import configparser
import ipaddress
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CERT_DIR = ROOT / ".agent_control" / "certs"
CA_NAME = "syntelos-local-root-ca"
ENTERPRISE_ROOTS_PREF = 'user_pref("security.enterprise_roots.enabled", true);'


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return cleaned or "syntelos-nas"


def unique_values(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip().rstrip(".")
        if not cleaned or cleaned in seen:
            continue
        output.append(cleaned)
        seen.add(cleaned)
    return output


def split_hosts(values: list[str]) -> tuple[list[str], list[str]]:
    dns_names: list[str] = []
    ip_addresses: list[str] = []
    for value in unique_values(values):
        try:
            ipaddress.ip_address(value)
        except ValueError:
            dns_names.append(value)
        else:
            ip_addresses.append(value)
    if len(dns_names) != len(set(dns_names)) or len(ip_addresses) != len(set(ip_addresses)) or set(dns_names) & set(ip_addresses):
        raise ValueError("Contract d.runtime.nas-setup.hosts: DNS/IP identities must be unique and disjoint")
    for value in ip_addresses:
        ipaddress.ip_address(value)
    for value in dns_names:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            continue
        raise ValueError("Contract d.runtime.nas-setup.hosts: IP host appeared in DNS identities")
    if set(dns_names + ip_addresses) != set(unique_values(values)):
        raise ValueError("Contract d.runtime.nas-setup.hosts: normalization lost a host")
    return dns_names, ip_addresses


def find_openssl(explicit: str = "") -> str:
    candidates = [
        explicit,
        os.environ.get("OPENSSL_BIN", ""),
        shutil.which("openssl") or "",
        str(Path.home() / "miniforge3" / "Library" / "bin" / "openssl.exe"),
        str(Path.home() / "anaconda3" / "Library" / "bin" / "openssl.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit(
        "OpenSSL was not found. Install OpenSSL or pass --openssl-bin with the executable path."
    )


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def write_openssl_config(cert_dir: Path) -> Path:
    cert_dir.mkdir(parents=True, exist_ok=True)
    path = cert_dir / "openssl.cnf"
    if not path.exists():
        path.write_text(
            "\n".join(
                [
                    "[req]",
                    "distinguished_name = req_distinguished_name",
                    "prompt = no",
                    "",
                    "[req_distinguished_name]",
                    "CN = Syntelos Local",
                    "O = Syntelos Local",
                    "",
                ]
            ),
            encoding="ascii",
        )
    return path


def ensure_local_ca(openssl: str, cert_dir: Path, *, days: int = 3650) -> tuple[Path, Path]:
    config_path = write_openssl_config(cert_dir)
    ca_key = cert_dir / f"{CA_NAME}.key"
    ca_cert = cert_dir / f"{CA_NAME}.crt"
    if ca_key.exists() and ca_cert.exists():
        return ca_cert, ca_key
    run(
        [
            openssl,
            "req",
            "-x509",
            "-new",
            "-nodes",
            "-newkey",
            "rsa:4096",
            "-sha256",
            "-days",
            str(days),
            "-config",
            str(config_path),
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
            "-subj",
            "/CN=Syntelos Local Development Root CA/O=Syntelos Local",
        ]
    )
    return ca_cert, ca_key


def write_server_ext(path: Path, dns_names: list[str], ip_addresses: list[str]) -> None:
    lines = [
        "authorityKeyIdentifier=keyid,issuer",
        "basicConstraints=CA:FALSE",
        "keyUsage = digitalSignature, keyEncipherment",
        "extendedKeyUsage = serverAuth",
        "subjectAltName = @alt_names",
        "",
        "[alt_names]",
    ]
    for index, ip_value in enumerate(ip_addresses, start=1):
        lines.append(f"IP.{index} = {ip_value}")
    for index, dns_value in enumerate(dns_names, start=1):
        lines.append(f"DNS.{index} = {dns_value}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def issue_server_certificate(
    openssl: str,
    cert_dir: Path,
    *,
    host: str,
    dns_names: list[str],
    ip_addresses: list[str],
    days: int = 396,
) -> tuple[Path, Path]:
    config_path = write_openssl_config(cert_dir)
    ca_cert, ca_key = ensure_local_ca(openssl, cert_dir)
    cert_name = sanitize_name(host)
    server_key = cert_dir / f"{cert_name}.key"
    server_csr = cert_dir / f"{cert_name}.csr"
    server_cert = cert_dir / f"{cert_name}.crt"
    server_ext = cert_dir / f"{cert_name}.ext"
    write_server_ext(server_ext, dns_names, ip_addresses)
    subject_cn = dns_names[0] if dns_names else ip_addresses[0]
    run(
        [
            openssl,
            "req",
            "-new",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-config",
            str(config_path),
            "-keyout",
            str(server_key),
            "-out",
            str(server_csr),
            "-subj",
            f"/CN={subject_cn}/O=Syntelos NAS",
        ]
    )
    run(
        [
            openssl,
            "x509",
            "-req",
            "-in",
            str(server_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_cert),
            "-days",
            str(days),
            "-sha256",
            "-extfile",
            str(server_ext),
        ]
    )
    return server_cert, server_key


def windows_import_current_user_root(ca_cert: Path) -> None:
    if os.name != "nt":
        raise SystemExit("--install-windows-current-user-root is only supported on Windows.")
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        raise SystemExit("PowerShell was not found, so the Windows root store cannot be updated.")
    cert_path = str(ca_cert).replace("'", "''")
    run(
        [
            powershell,
            "-NoProfile",
            "-Command",
            (
                "Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue; "
                "Import-Module PKI -ErrorAction SilentlyContinue; "
                f"$certPath = '{cert_path}'; "
                "if (-not (Get-PSDrive -Name Cert -ErrorAction SilentlyContinue)) "
                "{ throw 'PowerShell Cert: drive is unavailable.' }; "
                "Import-Certificate "
                "-FilePath $certPath "
                "-CertStoreLocation Cert:\\CurrentUser\\Root | Out-Null"
            ),
        ]
    )


def discover_firefox_like_profiles(appdata: Path) -> list[Path]:
    profiles: list[Path] = []
    for base in [appdata / "zen", appdata / "Mozilla" / "Firefox"]:
        profiles_ini = base / "profiles.ini"
        if not profiles_ini.exists():
            continue
        parser = configparser.ConfigParser()
        parser.read(profiles_ini, encoding="utf-8")
        for section in parser.sections():
            if not section.lower().startswith("profile"):
                continue
            raw_path = parser.get(section, "Path", fallback="")
            if not raw_path:
                continue
            is_relative = parser.get(section, "IsRelative", fallback="1") == "1"
            profile_path = base / raw_path if is_relative else Path(raw_path)
            if profile_path.exists():
                profiles.append(profile_path)
    return profiles


def enable_firefox_enterprise_roots(profile: Path) -> bool:
    profile.mkdir(parents=True, exist_ok=True)
    user_js = profile / "user.js"
    existing = user_js.read_text(encoding="utf-8") if user_js.exists() else ""
    if ENTERPRISE_ROOTS_PREF in existing:
        return False
    block = "\n".join(
        [
            "",
            "// Syntelos local HTTPS trust. Lets Firefox/Zen trust Windows enterprise roots.",
            ENTERPRISE_ROOTS_PREF,
            "",
        ]
    )
    user_js.write_text(existing.rstrip() + block, encoding="utf-8")
    return True


def public_url_for(host: str, port: int) -> str:
    return f"https://{host}:{port}"


def backend_start_command(public_url: str, cert: Path, key: Path, port: int) -> str:
    command = (
        f"python scripts/run_web_backend.py --host 0.0.0.0 --port {port} "
        f"--public-url {public_url} "
        f"--tls-cert-file {cert} --tls-key-file {key}"
    )
    if any(value not in command for value in (f"--port {port}", f"--public-url {public_url}", f"--tls-cert-file {cert}", f"--tls-key-file {key}")):
        raise ValueError("Contract d.runtime.nas-setup.tls-command: explicit port, public URL and TLS pair must survive command construction")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create packaged Syntelos NAS HTTPS certificates and optional local trust settings."
    )
    parser.add_argument("--host", required=True, help="Primary browser-facing NAS host or Tailscale DNS name.")
    parser.add_argument("--alt-host", action="append", default=[], help="Additional DNS name or IP SAN.")
    parser.add_argument("--port", type=int, default=47880)
    parser.add_argument("--cert-dir", type=Path, default=DEFAULT_CERT_DIR)
    parser.add_argument("--openssl-bin", default="")
    parser.add_argument(
        "--install-windows-current-user-root",
        action="store_true",
        help="Trust the generated Syntelos root CA in the Windows CurrentUser root store.",
    )
    parser.add_argument(
        "--enable-firefox-enterprise-roots",
        action="store_true",
        help="Set Firefox/Zen profiles to trust Windows enterprise roots.",
    )
    args = parser.parse_args(argv)

    all_hosts = unique_values([args.host, *args.alt_host])
    dns_names, ip_addresses = split_hosts(all_hosts)
    if not dns_names and not ip_addresses:
        raise SystemExit("At least one host or IP address is required.")

    openssl = find_openssl(args.openssl_bin)
    ca_cert, _ = ensure_local_ca(openssl, args.cert_dir)
    server_cert, server_key = issue_server_certificate(
        openssl,
        args.cert_dir,
        host=args.host,
        dns_names=dns_names,
        ip_addresses=ip_addresses,
    )

    if args.install_windows_current_user_root:
        windows_import_current_user_root(ca_cert)

    modified_profiles: list[Path] = []
    if args.enable_firefox_enterprise_roots:
        appdata = Path(os.environ.get("APPDATA", ""))
        for profile in discover_firefox_like_profiles(appdata):
            if enable_firefox_enterprise_roots(profile):
                modified_profiles.append(profile)

    url = public_url_for(args.host, args.port)
    print(f"Root CA: {ca_cert}")
    print(f"Server certificate: {server_cert}")
    print(f"Server key: {server_key}")
    if modified_profiles:
        print("Updated Firefox/Zen profiles:")
        for profile in modified_profiles:
            print(f"  {profile}")
    print("")
    print("Start command:")
    print(f"  {backend_start_command(url, server_cert, server_key, args.port)}")
    print("")
    print("Open:")
    print(f"  {url}/control")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
