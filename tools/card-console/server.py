#!/usr/bin/env python3
"""Card Console -- read-only bench dashboard for NFC/RFID hardware.

What it does:
  * auto-detects connected boards/readers (Chameleon Ultra, Flipper, PC/SC)
  * reads the Chameleon Ultra's hardware/firmware from the USB descriptor --
    no CLI, no commands typed
  * reports which local CLI tools are installed and their versions
  * NON-DESTRUCTIVE tag inventory (UID) against a PC/SC reader

What it deliberately does NOT do:
  * recover/attack keys
  * write or clone cards

Stdlib only. Run:
    python server.py
Then open http://127.0.0.1:7070

Config via env: CARD_CONSOLE_HOST, CARD_CONSOLE_PORT
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = os.environ.get("CARD_CONSOLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("CARD_CONSOLE_PORT", "7070"))
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# --------------------------------------------------------------------------
# Toolchain registry -- detection only.
# --------------------------------------------------------------------------
TOOLS = [
    {"id": "python",        "name": "Python",        "role": "runtime",                      "probe": ["python", "--version"]},
    {"id": "chameleon-cli", "name": "Chameleon CLI", "role": "Chameleon Ultra control",      "probe": ["chameleon-cli", "--version"]},
    {"id": "flipper",       "name": "Flipper CLI",   "role": "Flipper Zero control",         "probe": ["flipper", "--help"]},
    {"id": "qflipper",      "name": "qFlipper",      "role": "Flipper Zero GUI / update",    "probe": ["qFlipper", "--version"]},
    {"id": "ufbt",          "name": "uFBT",          "role": "Flipper firmware build",       "probe": ["ufbt", "--version"]},
    {"id": "mfoc",          "name": "mfoc",          "role": "MIFARE Classic key recovery (run manually, your cards)", "probe": ["mfoc", "--help"]},
    {"id": "socat",         "name": "socat",         "role": "serial bridge",                "probe": ["socat", "-V"]},
]

# Known USB IDs. Extend freely -- an unlisted device still shows up.
KNOWN_USB = {
    ("6868", "8686"): ("Chameleon Ultra", "chameleon"),      # confirmed on this bench
    ("0483", "5740"): ("Flipper Zero", "flipper"),
    ("0483", "DF11"): ("Flipper Zero (DFU)", "flipper-dfu"),
    ("03EB", "2045"): ("Chameleon Mini RevG (ATmega32U4)", "chameleon"),
}

NAME_HINTS = [
    ("chameleon", ("Chameleon", "chameleon")),
    ("flipper",   ("Flipper Zero", "flipper")),
    ("proxmark",  ("Proxmark", "proxmark")),
    ("acr",       ("ACS reader", "pcsc-reader")),
    ("acs ",      ("ACS reader", "pcsc-reader")),
]

VIDPID_RE = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")
CHAMELEON_HW_FW_RE = re.compile(r"hw_v?([0-9A-Za-z.]+)\s*[,;]?\s*fw_v?([0-9A-Za-z.]+)", re.I)

_DESC_CACHE = {"ts": 0.0, "data": None}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def classify(vid, pid, *texts):
    """Return {label, kind} for a device, or None when unknown."""
    if vid and pid:
        hit = KNOWN_USB.get((str(vid).upper(), str(pid).upper()))
        if hit:
            return {"label": hit[0], "kind": hit[1]}
    blob = " ".join(t for t in texts if t).lower()
    for needle, (label, kind) in NAME_HINTS:
        if needle in blob:
            return {"label": label, "kind": kind}
    return None


def parse_chameleon(desc):
    """Parse a Windows bus descriptor like 'ChameleonUltra: hw_v1, fw_v512'."""
    if not desc or "chameleon" not in desc.lower():
        return None
    hw = fw = None
    m = CHAMELEON_HW_FW_RE.search(desc)
    if m:
        hw, fw = m.group(1), m.group(2)
    model = "Chameleon Ultra" if "ultra" in desc.lower() else "Chameleon"
    return {"model": model, "hardware": hw, "firmware": fw, "raw": desc}


def _probe_version(cmd):
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=6,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:  # timeout, missing, permission
        return f"<{type(exc).__name__}>"
    text = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[0][:120] if lines else None


def tool_status():
    rows = []
    for spec in TOOLS:
        exe = shutil.which(spec["probe"][0])
        rows.append({
            "id": spec["id"],
            "name": spec["name"],
            "role": spec["role"],
            "present": bool(exe),
            "path": exe,
            "version": _probe_version(spec["probe"]) if exe else None,
        })
    return rows


def environment():
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "hostname": socket.gethostname(),
        "host": HOST,
        "port": PORT,
        "cwd": str(BASE_DIR),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------
# device enumeration
# --------------------------------------------------------------------------
def _devices_from_pyserial():
    from serial.tools import list_ports  # pyserial, optional

    serial_rows = []
    for p in list_ports.comports():
        vid = f"{p.vid:04X}" if p.vid is not None else None
        pid = f"{p.pid:04X}" if p.pid is not None else None
        serial_rows.append({
            "port": p.device,
            "description": p.description,
            "manufacturer": p.manufacturer,
            "product": p.product,
            "serial_number": p.serial_number,
            "vid": vid,
            "pid": pid,
            "hwid": p.hwid,
            "classification": classify(vid, pid, p.description or "", p.product or "", p.manufacturer or ""),
        })
    return {"source": "pyserial", "serial": serial_rows, "usb": [], "smartcard_readers": []}


def _devices_from_windows_pnp():
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$o=[ordered]@{serial=@();usb=@();readers=@()};"
        "$o.serial=@(Get-CimInstance Win32_SerialPort -EA SilentlyContinue | "
        "Select-Object DeviceID,Name,Description);"
        "$o.usb=@(Get-CimInstance Win32_PnPEntity -EA SilentlyContinue | "
        "Where-Object {$_.PNPClass -eq 'USB'} | Select-Object Name,DeviceID);"
        "$o.readers=@(Get-CimInstance Win32_PnPEntity -EA SilentlyContinue | "
        "Where-Object {$_.PNPClass -eq 'SmartCardReader'} | Select-Object Name,DeviceID);"
        "ConvertTo-Json -InputObject $o -Depth 4 -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=25,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        return {"source": f"windows-pnp-error:{type(exc).__name__}", "serial": [], "usb": [], "smartcard_readers": []}

    if not (proc.stdout or "").strip():
        return {"source": "windows-pnp-empty", "serial": [], "usb": [], "smartcard_readers": []}
    try:
        raw = json.loads(proc.stdout)
    except Exception:
        return {"source": "windows-pnp-parse-error", "serial": [], "usb": [], "smartcard_readers": []}

    serial_rows = []
    for s in _as_list(raw.get("serial")):
        if not isinstance(s, dict):
            continue
        serial_rows.append({
            "port": s.get("DeviceID"),
            "description": s.get("Name") or s.get("Description"),
            "manufacturer": None,
            "product": s.get("Description"),
            "serial_number": None,
            "vid": None, "pid": None, "hwid": None,
            "classification": classify(None, None, s.get("Name") or "", s.get("Description") or ""),
        })

    usb_rows = []
    for u in _as_list(raw.get("usb")):
        if not isinstance(u, dict):
            continue
        m = VIDPID_RE.search(u.get("DeviceID") or "")
        vid, pid = (m.group(1).upper(), m.group(2).upper()) if m else (None, None)
        usb_rows.append({"name": u.get("Name"), "vid": vid, "pid": pid,
                         "classification": classify(vid, pid, u.get("Name") or "")})

    reader_rows = []
    for r in _as_list(raw.get("readers")):
        if not isinstance(r, dict):
            continue
        m = VIDPID_RE.search(r.get("DeviceID") or "")
        vid, pid = (m.group(1).upper(), m.group(2).upper()) if m else (None, None)
        reader_rows.append({"name": r.get("Name"), "vid": vid, "pid": pid,
                            "classification": classify(vid, pid, r.get("Name") or "")})

    return {"source": "windows-pnp", "serial": serial_rows, "usb": usb_rows, "smartcard_readers": reader_rows}


def windows_descriptor_map(max_age=15.0):
    """Map {VID,PID} -> bus-reported device description, via PnP.

    The Chameleon Ultra reports 'ChameleonUltra: hw_v1, fw_v512' here, which is
    how we identify it and its firmware without opening the serial port.
    Cached briefly so the dashboard can poll without hammering PnP.
    """
    if platform.system() != "Windows":
        return {"by_instance": {}, "by_vidpid": {}}
    now = time.time()
    if _DESC_CACHE["data"] and (now - _DESC_CACHE["ts"]) < max_age:
        return _DESC_CACHE["data"]

    vids = "|".join(sorted({vid for (vid, _pid) in KNOWN_USB}))
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$r=@(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
        "Where-Object { $_.InstanceId -match 'VID_(" + vids + ")' } | ForEach-Object { "
        "$d=Get-PnpDeviceProperty -InstanceId $_.InstanceId "
        "-KeyName 'DEVPKEY_Device_BusReportedDeviceDesc' -ErrorAction SilentlyContinue; "
        "if($d -and $d.Data){[pscustomobject]@{InstanceId=$_.InstanceId;BusDesc=$d.Data}} });"
        "ConvertTo-Json -InputObject $r -Depth 3 -Compress"
    )
    result = {"by_instance": {}, "by_vidpid": {}}
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        out = (proc.stdout or "").strip()
        if out:
            for row in _as_list(json.loads(out)):
                if not isinstance(row, dict):
                    continue
                iid = row.get("InstanceId") or ""
                desc = row.get("BusDesc")
                result["by_instance"][iid] = desc
                m = VIDPID_RE.search(iid)
                if m:
                    result["by_vidpid"][(m.group(1).upper(), m.group(2).upper())] = desc
    except Exception:
        pass
    _DESC_CACHE["ts"] = now
    _DESC_CACHE["data"] = result
    return result


def devices_snapshot():
    by_vidpid = windows_descriptor_map().get("by_vidpid", {})

    try:
        snap = _devices_from_pyserial()
    except Exception:
        snap = None
    if snap is None:
        snap = _devices_from_windows_pnp() if platform.system() == "Windows" else {
            "source": "unsupported", "serial": [], "usb": [], "smartcard_readers": []}

    chameleon = None

    def enrich(row):
        nonlocal chameleon
        vid, pid = row.get("vid"), row.get("pid")
        if not (vid and pid):
            return
        busdesc = by_vidpid.get((str(vid).upper(), str(pid).upper()))
        if not busdesc:
            return
        row["bus_reported_desc"] = busdesc
        info = parse_chameleon(busdesc)
        if info:
            if not row.get("classification"):
                row["classification"] = {"label": info["model"], "kind": "chameleon"}
            if chameleon is None:
                info = dict(info)
                info["port"] = row.get("port")
                chameleon = info

    for row in snap.get("serial", []):
        enrich(row)
    for row in snap.get("usb", []):
        enrich(row)

    snap["chameleon"] = chameleon
    return snap


# --------------------------------------------------------------------------
# PC/SC: reader listing + non-destructive UID read
# --------------------------------------------------------------------------
def reader_snapshot():
    try:
        from smartcard.System import readers  # pyscard, optional
    except Exception:
        return {"available": False, "reason": "pyscard not installed (pip install pyscard)", "readers": []}
    try:
        return {"available": True, "reason": None, "readers": [str(r) for r in readers()]}
    except Exception as exc:
        return {"available": True, "reason": f"{type(exc).__name__}: {exc}", "readers": []}


def scan_tag(reader_index=0):
    """Read a presented tag's UID via the PC/SC pseudo-APDU FF CA 00 00 00.

    Non-destructive: identifier only. No authentication, no key recovery, no writes.
    """
    try:
        from smartcard.System import readers
        from smartcard.util import toHexString
    except Exception:
        return {"ok": False, "error": "pyscard_required", "hint": "pip install pyscard"}

    try:
        readers_list = readers()
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}

    if not readers_list:
        return {"ok": False, "error": "no_reader"}
    try:
        index = int(reader_index)
    except (TypeError, ValueError):
        index = 0
    if not 0 <= index < len(readers_list):
        return {"ok": False, "error": "reader_index_out_of_range", "count": len(readers_list)}

    try:
        conn = readers_list[index].createConnection()
        conn.connect()
        data, sw1, sw2 = conn.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}

    status = f"{sw1:02X}{sw2:02X}"
    result = {
        "ok": status == "9000" and bool(data),
        "reader": str(readers_list[index]),
        "uid": toHexString(data).replace(" ", "") if data else None,
        "status_word": status,
    }
    if not result["ok"]:
        result["hint"] = "No ISO14443-A tag present, or the tag needs a real read via your board's CLI."
    return result


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "CardConsole/0.2"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, obj, status=200):
        body = json.dumps(obj, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            return self._json({"error": "forbidden"}, 403)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            target = STATIC_DIR / "index.html"
        if not target.is_file():
            return self._json({"error": "not_found", "hint": "static/index.html missing"}, 404)
        ctype = {
            ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
            ".json": "application/json", ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/environment":
            return self._json(environment())
        if path == "/api/tools":
            return self._json({"tools": tool_status()})
        if path == "/api/devices":
            return self._json({"devices": devices_snapshot()})
        if path == "/api/readers":
            return self._json(reader_snapshot())
        if path == "/api/scan":
            return self._json({"error": "use POST for /api/scan"}, 405)
        return self._static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/scan":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except Exception:
                payload = {}
            return self._json(scan_tag(payload.get("reader_index", 0)))
        return self._json({"error": "not_found"}, 404)


def main():
    if not STATIC_DIR.is_dir():
        print(f"warning: static directory missing at {STATIC_DIR}", file=sys.stderr)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Card Console -> http://{HOST}:{PORT}")
    print("read-only: enumeration + UID inventory. no key recovery, no writes.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
