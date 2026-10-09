#!/usr/bin/env bash
set -Eeuo pipefail

# This launcher is part of every immutable release. Runtime state, credentials,
# logs, and PID ownership always stay in the persistent control project.
umask 077

BASE="${SYNTHELOS_BASE:-/volume1/Saclay/projects/syntelos}"
if [ ! -d "$BASE" ]; then
  printf 'Syntelos base directory is unavailable: %s\n' "$BASE" >&2
  exit 9
fi
BASE="$(cd "$BASE" && pwd -P)"

CUR="${SYNTHELOS_ROOT:-$BASE/current}"
if [ -L "$CUR" ]; then
  CUR="$(readlink -f "$CUR")"
fi
if [ ! -d "$CUR" ]; then
  printf 'Active Syntelos release is unavailable: %s\n' "$CUR" >&2
  exit 9
fi
CUR="$(cd "$CUR" && pwd -P)"
if [ "$(dirname "$CUR")" != "$BASE/releases" ]; then
  printf 'Refusing to start outside a direct immutable Syntelos release: %s\n' "$CUR" >&2
  exit 9
fi

CONTROL_ROOT="${FLUXIO_CONTROL_PROJECT_ROOT:-/volume1/Saclay/projects/vibe-coding-platform}"
if [ ! -d "$CONTROL_ROOT" ]; then
  printf 'Persistent Neyvia control project is unavailable: %s\n' "$CONTROL_ROOT" >&2
  exit 10
fi
CONTROL_ROOT="$(cd "$CONTROL_ROOT" && pwd -P)"
case "$CONTROL_ROOT" in
  "$BASE"/releases/*)
    printf 'Refusing to store mutable Neyvia state in a release: %s\n' "$CONTROL_ROOT" >&2
    exit 10
    ;;
esac

PYTHON="${FLUXIO_BACKEND_PYTHON:-$BASE/.venv/bin/python}"
if [ -z "${FLUXIO_BACKEND_PYTHON:-}" ] && [ -f "$CUR/scripts/resolve_release_python.py" ]; then
  PYTHON="$("$PYTHON" "$CUR/scripts/resolve_release_python.py" "$BASE" "$CUR")"
fi
RUNNER="$CUR/scripts/run_web_backend.py"
STATIC_ROOT="$CUR/web/dist"
RUNTIME_HOME="${FLUXIO_RUNTIME_HOME:-$BASE/runtime/home}"
RUNTIME_BIN_DIR="${FLUXIO_RUNTIME_BIN_DIR:-$BASE/runtime/bin}"
HOST="${FLUXIO_WEB_HOST:-0.0.0.0}"
PORT="${FLUXIO_WEB_PORT:-47880}"
PUBLIC_URL="${FLUXIO_PUBLIC_URL:-https://nas.example.invalid:$PORT}"
TLS_CERT_FILE="${FLUXIO_TLS_CERT_FILE:-$BASE/certs/nas.example.invalid.crt}"
TLS_KEY_FILE="${FLUXIO_TLS_KEY_FILE:-$BASE/certs/nas.example.invalid.key}"

case "$PORT" in
  ''|*[!0-9]*)
    printf 'FLUXIO_WEB_PORT must be numeric: %s\n' "$PORT" >&2
    exit 11
    ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  printf 'FLUXIO_WEB_PORT must be between 1 and 65535: %s\n' "$PORT" >&2
  exit 11
fi
for timeout_pair in \
  "FLUXIO_BACKEND_STOP_TIMEOUT_SECONDS:${FLUXIO_BACKEND_STOP_TIMEOUT_SECONDS:-15}" \
  "FLUXIO_BACKEND_START_TIMEOUT_SECONDS:${FLUXIO_BACKEND_START_TIMEOUT_SECONDS:-45}"; do
  timeout_value="${timeout_pair#*:}"
  case "$timeout_value" in
    ''|*[!0-9]*|0)
      printf '%s must be a positive integer: %s\n' "${timeout_pair%%:*}" "$timeout_value" >&2
      exit 11
      ;;
  esac
done
if [ ! -x "$PYTHON" ]; then
  printf 'Neyvia backend Python is not executable: %s\n' "$PYTHON" >&2
  exit 11
fi
if [ ! -f "$RUNNER" ]; then
  printf 'Versioned Neyvia backend entry point is missing: %s\n' "$RUNNER" >&2
  exit 11
fi
if [ ! -f "$STATIC_ROOT/index.html" ]; then
  printf 'Versioned Neyvia web build is missing: %s\n' "$STATIC_ROOT/index.html" >&2
  exit 11
fi
if [ ! -f "$TLS_CERT_FILE" ] || [ ! -f "$TLS_KEY_FILE" ]; then
  printf 'Neyvia TLS certificate pair is unavailable: %s / %s\n' "$TLS_CERT_FILE" "$TLS_KEY_FILE" >&2
  exit 11
fi
if ! command -v curl >/dev/null 2>&1; then
  printf 'curl is required for the Neyvia backend health check.\n' >&2
  exit 11
fi

HEALTH_HOST="${FLUXIO_BACKEND_HEALTH_HOST:-}"
if [ -z "$HEALTH_HOST" ]; then
  HEALTH_HOST="$("$PYTHON" - "$PUBLIC_URL" <<'PY'
from urllib.parse import urlparse
import sys

parsed = urlparse(sys.argv[1])
if parsed.scheme != "https" or not parsed.hostname:
    raise SystemExit(1)
print(parsed.hostname)
PY
  )" || {
    printf 'FLUXIO_PUBLIC_URL must be an HTTPS URL with a hostname: %s\n' "$PUBLIC_URL" >&2
    exit 11
  }
fi
case "$HEALTH_HOST" in
  ''|*[!A-Za-z0-9._:-]*)
    printf 'Neyvia backend health hostname is invalid: %s\n' "$HEALTH_HOST" >&2
    exit 11
    ;;
esac
HEALTH_URL="https://$HEALTH_HOST:$PORT/health"
HEALTH_RESOLVE="$HEALTH_HOST:$PORT:127.0.0.1"

if ! "$PYTHON" - "$TLS_CERT_FILE" "$TLS_KEY_FILE" "$HEALTH_HOST" <<'PY'
import ssl
import sys

certificate_path, key_path, hostname = sys.argv[1:]
server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
server_context.load_cert_chain(certfile=certificate_path, keyfile=key_path)
client_context = ssl.create_default_context()

client_incoming = ssl.MemoryBIO()
client_outgoing = ssl.MemoryBIO()
server_incoming = ssl.MemoryBIO()
server_outgoing = ssl.MemoryBIO()
client = client_context.wrap_bio(
    client_incoming,
    client_outgoing,
    server_side=False,
    server_hostname=hostname,
)
server = server_context.wrap_bio(
    server_incoming,
    server_outgoing,
    server_side=True,
)

client_ready = False
server_ready = False
for _ in range(1000):
    progress = False
    if not client_ready:
        try:
            client.do_handshake()
            client_ready = True
            progress = True
        except ssl.SSLWantReadError:
            pass
    if not server_ready:
        try:
            server.do_handshake()
            server_ready = True
            progress = True
        except ssl.SSLWantReadError:
            pass
    while client_outgoing.pending:
        server_incoming.write(client_outgoing.read())
        progress = True
    while server_outgoing.pending:
        client_incoming.write(server_outgoing.read())
        progress = True
    if client_ready and server_ready:
        break
    if not progress:
        raise RuntimeError("TLS certificate handshake stalled")
else:
    raise RuntimeError("TLS certificate handshake exceeded its bounded work limit")
PY
then
  printf 'Neyvia TLS certificate/key preflight failed for hostname %s.\n' "$HEALTH_HOST" >&2
  exit 11
fi

CONTROL_DIR="$CONTROL_ROOT/.agent_control"
PID_FILE="$CONTROL_DIR/web_backend_${PORT}.pid"
OUT_LOG="$CONTROL_DIR/web_backend_${PORT}.out.log"
ERR_LOG="$CONTROL_DIR/web_backend_${PORT}.err.log"
mkdir -p "$CONTROL_DIR" "$RUNTIME_HOME"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$CUR/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$RUNTIME_BIN_DIR:$PATH"
export HOME="$RUNTIME_HOME"
export FLUXIO_WORKSPACE_ROOT="$CONTROL_ROOT"
export FLUXIO_CONTROL_PROJECT_ROOT="$CONTROL_ROOT"
export FLUXIO_STATIC_ROOT="$STATIC_ROOT"
export FLUXIO_RUNTIME_HOME="$RUNTIME_HOME"
export SYNTELOS_RUNTIME_HOME="$RUNTIME_HOME"
export FLUXIO_RUNTIME_BIN_DIR="$RUNTIME_BIN_DIR"
export FLUXIO_RUNTIME_AUTO_UPDATE="${FLUXIO_RUNTIME_AUTO_UPDATE:-0}"
export NPM_CONFIG_CACHE="$RUNTIME_HOME/.npm"
export OPENCLAW_STATE_DIR="$RUNTIME_HOME/.openclaw"
export FLUXIO_WATCHDOG_AUTOSTART=0
export FLUXIO_ALLOW_NAS_RUNTIME_FALLBACK="${FLUXIO_ALLOW_NAS_RUNTIME_FALLBACK:-1}"
export FLUXIO_NAS_EXECUTION_POLICY="${FLUXIO_NAS_EXECUTION_POLICY:-efficient}"
export FLUXIO_MISSION_DISPATCH_MODE="${FLUXIO_MISSION_DISPATCH_MODE:-cluster_worker}"
export FLUXIO_MISSION_WORKER_HOST_ID="${FLUXIO_MISSION_WORKER_HOST_ID:-${FLUXIO_WORKER_HOST_ID:-nas.example.invalid}}"
# Zero is the wire-compatible sentinel for unlimited concurrency. Older
# rollback workers can still parse it even though they treat it conservatively.
export FLUXIO_WORKER_MAX_JOBS="${FLUXIO_WORKER_MAX_JOBS:-0}"
export FLUXIO_RUNTIME_AUTH_PREFLIGHT_TIMEOUT_SECONDS="${FLUXIO_RUNTIME_AUTH_PREFLIGHT_TIMEOUT_SECONDS:-45}"
export FLUXIO_RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS="${FLUXIO_RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS:-180}"

backend_release_for_pid() {
  owned_pid="$1"
  "$PYTHON" - "$owned_pid" "$BASE" "$CONTROL_ROOT" "$PORT" <<'PY'
from pathlib import Path
import sys

pid, base, control_root, port = sys.argv[1:]
proc_cmdline = Path("/proc") / pid / "cmdline"
try:
    arguments = [
        item.decode("utf-8", errors="surrogateescape")
        for item in proc_cmdline.read_bytes().split(b"\0")
        if item
    ]
except OSError:
    raise SystemExit(1)

def value_after(flag: str) -> str:
    for index in range(len(arguments) - 1):
        if arguments[index] == flag:
            return arguments[index + 1]
    return ""

releases_root = (Path(base) / "releases").resolve()
runner_arguments = [
    Path(argument).resolve()
    for argument in arguments
    if argument.endswith("/scripts/run_web_backend.py")
]
static_value = value_after("--static-root")
if len(runner_arguments) != 1 or not static_value:
    raise SystemExit(1)
runner = runner_arguments[0]
static_root = Path(static_value).resolve()
runner_release = runner.parent.parent
static_release = static_root.parent.parent
if (
    runner.name != "run_web_backend.py"
    or runner.parent.name != "scripts"
    or static_root.name != "dist"
    or static_root.parent.name != "web"
    or runner_release != static_release
    or runner_release.parent != releases_root
    or Path(value_after("--root")).resolve() != Path(control_root).resolve()
    or value_after("--port") != port
):
    raise SystemExit(1)
print(runner_release)
PY
}

owns_backend_pid() {
  backend_release_for_pid "$1" >/dev/null
}

backend_pid_owns_port_listener() {
  listener_pid="$1"
  "$PYTHON" - "$listener_pid" "$PORT" /proc <<'PY'
from pathlib import Path
import os
import re
import sys

pid, port_value, proc_root_value = sys.argv[1:]
try:
    port = int(port_value)
except ValueError:
    raise SystemExit(1)
proc_root = Path(proc_root_value)


def listener_inodes(table: Path, *, required: bool) -> set[str]:
    try:
        lines = table.read_text(encoding="ascii").splitlines()
    except FileNotFoundError:
        if required:
            raise SystemExit(1)
        return set()
    except OSError:
        raise SystemExit(1)
    discovered: set[str] = set()
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 10:
            raise SystemExit(1)
        if fields[3] != "0A":
            continue
        try:
            local_port = int(fields[1].rsplit(":", 1)[1], 16)
        except (IndexError, ValueError):
            raise SystemExit(1)
        if local_port != port:
            continue
        inode = fields[9]
        if not inode.isdecimal() or int(inode) < 1:
            raise SystemExit(1)
        discovered.add(inode)
    return discovered


listeners = listener_inodes(proc_root / "net" / "tcp", required=True)
listeners.update(listener_inodes(proc_root / "net" / "tcp6", required=False))
if not listeners:
    raise SystemExit(1)

socket_pattern = re.compile(r"socket:\[(\d+)\]")


def socket_inodes_for_process(process_pid: str) -> set[str]:
    try:
        descriptors = list((proc_root / process_pid / "fd").iterdir())
    except OSError:
        raise SystemExit(1)
    inodes: set[str] = set()
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        except OSError:
            raise SystemExit(1)
        match = socket_pattern.fullmatch(target)
        if match:
            inodes.add(match.group(1))
    return inodes


if not listeners.issubset(socket_inodes_for_process(pid)):
    raise SystemExit(1)

# A shared inherited descriptor is unusual, but an observed second holder is
# still ambiguous ownership and must fail closed just like SO_REUSEPORT.
try:
    process_directories = list(proc_root.iterdir())
except OSError:
    raise SystemExit(1)
for process_directory in process_directories:
    other_pid = process_directory.name
    if other_pid == pid or not other_pid.isdecimal():
        continue
    try:
        descriptors = list((process_directory / "fd").iterdir())
    except OSError:
        continue
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        match = socket_pattern.fullmatch(target)
        if match and match.group(1) in listeners:
            raise SystemExit(1)
PY
}

port_accepts_connection() {
  "$PYTHON" - "$PORT" <<'PY'
import socket
import sys

try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1.0):
        pass
except OSError:
    raise SystemExit(1)
PY
}

stop_owned_backend() {
  if [ ! -f "$PID_FILE" ]; then
    return 0
  fi
  owned_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$owned_pid" in
    ''|*[!0-9]*)
      printf 'Refusing an invalid Neyvia backend PID file: %s\n' "$PID_FILE" >&2
      return 12
      ;;
  esac
  if ! kill -0 "$owned_pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    return 0
  fi
  if ! owns_backend_pid "$owned_pid"; then
    printf 'Refusing to stop PID %s because it is not the owned Neyvia backend for %s on port %s.\n' \
      "$owned_pid" "$CONTROL_ROOT" "$PORT" >&2
    return 12
  fi
  if ! backend_pid_owns_port_listener "$owned_pid"; then
    printf 'Refusing to stop PID %s because it does not exclusively own every listening socket on port %s.\n' \
      "$owned_pid" "$PORT" >&2
    return 15
  fi

  kill "$owned_pid"
  waited=0
  while kill -0 "$owned_pid" 2>/dev/null && [ "$waited" -lt "${FLUXIO_BACKEND_STOP_TIMEOUT_SECONDS:-15}" ]; do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$owned_pid" 2>/dev/null; then
    if ! owns_backend_pid "$owned_pid"; then
      printf 'Neyvia backend PID ownership changed while stopping: %s\n' "$owned_pid" >&2
      return 12
    fi
    kill -KILL "$owned_pid"
    sleep 1
  fi
  if kill -0 "$owned_pid" 2>/dev/null; then
    printf 'Owned Neyvia backend did not stop: %s\n' "$owned_pid" >&2
    return 12
  fi
  rm -f "$PID_FILE"
}

existing_backend_pid=""
existing_backend_release=""
if [ -f "$PID_FILE" ]; then
  existing_backend_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$existing_backend_pid" in
    ''|*[!0-9]*)
      printf 'Refusing an invalid Neyvia backend PID file: %s\n' "$PID_FILE" >&2
      exit 12
      ;;
  esac
  if kill -0 "$existing_backend_pid" 2>/dev/null; then
    if ! existing_backend_release="$(backend_release_for_pid "$existing_backend_pid")"; then
      printf 'Refusing to replace live PID %s because it is not the owned Neyvia backend.\n' \
        "$existing_backend_pid" >&2
      exit 12
    fi
    if ! backend_pid_owns_port_listener "$existing_backend_pid"; then
      printf 'Refusing destructive backend action: verified PID %s does not exclusively own every listening socket on port %s.\n' \
        "$existing_backend_pid" "$PORT" >&2
      exit 15
    fi
  else
    existing_backend_pid=""
  fi
fi

if [ -z "$existing_backend_pid" ] && port_accepts_connection; then
  printf 'Refusing to launch Neyvia: port %s already answers without a verified owned backend PID. Run the explicit legacy migration first.\n' \
    "$PORT" >&2
  exit 15
fi

if [ "${FLUXIO_BACKEND_PREFLIGHT_ONLY:-0}" = "1" ]; then
  printf 'Neyvia backend preflight passed: release=%s previous=%s health=%s\n' \
    "$CUR" "${existing_backend_release:-none}" "$HEALTH_URL"
  exit 0
fi

if [ "${FLUXIO_BACKEND_STOP_ONLY:-0}" = "1" ]; then
  stop_owned_backend
  if port_accepts_connection; then
    printf 'Neyvia backend PID stopped but port %s is still accepting connections; refusing unsafe reuse.\n' "$PORT" >&2
    exit 15
  fi
  printf 'Neyvia backend stopped: previous=%s\n' "${existing_backend_release:-none}"
  exit 0
fi

stop_owned_backend
if port_accepts_connection; then
  printf 'Neyvia backend stop completed but port %s is still accepting connections; refusing unsafe reuse.\n' "$PORT" >&2
  exit 15
fi

: > "$OUT_LOG"
: > "$ERR_LOG"
cd "$CUR"
nohup "$PYTHON" "$RUNNER" \
  --host "$HOST" \
  --port "$PORT" \
  --root "$CONTROL_ROOT" \
  --static-root "$STATIC_ROOT" \
  --public-url "$PUBLIC_URL" \
  --tls-cert-file "$TLS_CERT_FILE" \
  --tls-key-file "$TLS_KEY_FILE" \
  --skip-runtime-auto-update \
  > "$OUT_LOG" 2> "$ERR_LOG" < /dev/null &
backend_pid=$!
printf '%s\n' "$backend_pid" > "$PID_FILE.tmp"
mv -f "$PID_FILE.tmp" "$PID_FILE"
sleep 1
if ! kill -0 "$backend_pid" 2>/dev/null; then
  printf 'Neyvia backend exited during startup. See %s\n' "$ERR_LOG" >&2
  rm -f "$PID_FILE"
  exit 13
fi
if ! owns_backend_pid "$backend_pid"; then
  printf 'New Neyvia backend lost PID ownership during startup; terminating the exact spawned PID %s.\n' \
    "$backend_pid" >&2
  kill -TERM "$backend_pid" 2>/dev/null || true
  sleep 1
  kill -KILL "$backend_pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  exit 13
fi

health=""
waited=0
while [ "$waited" -lt "${FLUXIO_BACKEND_START_TIMEOUT_SECONDS:-45}" ]; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    printf 'Neyvia backend exited during startup. See %s\n' "$ERR_LOG" >&2
    rm -f "$PID_FILE"
    exit 13
  fi
  health="$(curl --silent --show-error --fail --noproxy '*' --max-time 5 \
    --resolve "$HEALTH_RESOLVE" "$HEALTH_URL" 2>/dev/null || true)"
  case "$health" in
    *'"ok": true'*|*'"ok":true'*) break ;;
  esac
  sleep 1
  waited=$((waited + 1))
done

case "$health" in
  *'"ok": true'*|*'"ok":true'*)
    if ! kill -0 "$backend_pid" 2>/dev/null || \
      ! owns_backend_pid "$backend_pid" || \
      ! backend_pid_owns_port_listener "$backend_pid"; then
      printf 'Neyvia health was answered without the owned backend process remaining live.\n' >&2
      rm -f "$PID_FILE"
      exit 13
    fi
    ;;
  *)
    printf 'Neyvia backend did not become healthy within %s seconds. See %s\n' "$waited" "$ERR_LOG" >&2
    stop_owned_backend || true
    exit 14
    ;;
esac

printf 'Neyvia backend ready: pid=%s code=%s state=%s static=%s health=%s\n' \
  "$backend_pid" "$CUR" "$CONTROL_ROOT" "$STATIC_ROOT" "$HEALTH_URL"
printf '%s\n' "$health"
