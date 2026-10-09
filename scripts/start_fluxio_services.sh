#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

BASE="${SYNTHELOS_BASE:-/volume1/Saclay/projects/syntelos}"
if [ ! -d "$BASE" ]; then
  printf 'Syntelos base directory is unavailable: %s\n' "$BASE" >&2
  exit 9
fi
BASE="$(cd "$BASE" && pwd -P)"

resolve_release() {
  release_value="$1"
  release_label="$2"
  if [ -L "$release_value" ]; then
    release_value="$(readlink -f "$release_value")"
  fi
  if [ ! -d "$release_value" ]; then
    printf '%s release is unavailable: %s\n' "$release_label" "$release_value" >&2
    return 9
  fi
  release_value="$(cd "$release_value" && pwd -P)"
  if [ "$(dirname "$release_value")" != "$BASE/releases" ]; then
    printf 'Refusing %s outside a direct immutable Syntelos release: %s\n' \
      "$release_label" "$release_value" >&2
    return 9
  fi
  printf '%s\n' "$release_value"
}

CUR="$(resolve_release "${SYNTHELOS_ROOT:-$BASE/current}" candidate)"
CONTROL_ROOT="${FLUXIO_CONTROL_PROJECT_ROOT:-/volume1/Saclay/projects/vibe-coding-platform}"
if [ ! -d "$CONTROL_ROOT" ]; then
  printf 'Persistent Fluxio control project is unavailable: %s\n' "$CONTROL_ROOT" >&2
  exit 10
fi
CONTROL_ROOT="$(cd "$CONTROL_ROOT" && pwd -P)"
case "$CONTROL_ROOT" in
  "$BASE"/releases/*)
    printf 'Refusing to store mutable Fluxio state in a release: %s\n' "$CONTROL_ROOT" >&2
    exit 10
    ;;
esac

CONTROL_DIR="$CONTROL_ROOT/.agent_control"
PYTHON="${FLUXIO_BACKEND_PYTHON:-$BASE/.venv/bin/python}"
PORT="${FLUXIO_WEB_PORT:-47880}"
PUBLIC_URL="${FLUXIO_PUBLIC_URL:-https://nas.example.invalid:$PORT}"
RUNTIME_ROOT="$BASE/runtime"
RUNTIME_BIN_DIR="${FLUXIO_RUNTIME_BIN_DIR:-$RUNTIME_ROOT/bin}"
OPENCLAW="$RUNTIME_BIN_DIR/openclaw"
OPENCLAW_STATE_DIR="$RUNTIME_ROOT/home/.openclaw"
BASE_PYTHONPATH="${PYTHONPATH:-}"
LOCK_DIR="$CONTROL_DIR/start_fluxio_services.lock"
LOCK_OWNER_FILE="$LOCK_DIR/owner.pid"
BACKEND_PID_FILE="$CONTROL_DIR/web_backend_${PORT}.pid"
WORKER_PID_FILE="$CONTROL_DIR/worker.pid"
WATCHDOG_PID_FILE="$CONTROL_DIR/mission_watchdog.pid"
GATEWAY_PID_FILE="$CONTROL_DIR/openclaw_gateway.pid"
WORKER_STATE_FILE="$CONTROL_DIR/worker_state.json"
WATCHDOG_STATE_FILE="$CONTROL_DIR/mission_watchdog_supervisor.json"
WORKER_GATE_FILE="$CONTROL_DIR/worker_startup_gate"

DESIRED_GATEWAY="${FLUXIO_OPENCLAW_GATEWAY_ENABLED:-1}"
DESIRED_WORKER="${FLUXIO_CLUSTER_WORKER_ENABLED:-1}"
PREVIOUS_BACKEND_LIVE=0
PREVIOUS_LIVE_RELEASE=""
ROLLBACK_RELEASE=""
PREVIOUS_GATEWAY_LIVE=0
PREVIOUS_GATEWAY_PID=""
PREVIOUS_WORKER_LIVE=0
PREVIOUS_WORKER_PID=""
PREVIOUS_WORKER_PAUSED=0
PREVIOUS_WATCHDOG_LIVE=0
PREVIOUS_WATCHDOG_PID=""
LOCK_HELD=0
TRANSACTION_ACTIVE=0
TRANSACTION_COMMITTED=0
CANDIDATE_BACKEND_ATTEMPTED=0
CANDIDATE_GATEWAY_STARTED=0
CANDIDATE_WORKER_STARTED=0
CANDIDATE_WATCHDOG_STARTED=0
WORKER_GATE_CREATED=0
LAST_STARTED_PID=""
LAST_STARTED_EPOCH="0"
HEALTH_HOST=""
HEALTH_URL=""
HEALTH_RESOLVE=""

mkdir -p "$CONTROL_DIR" "$BASE/logs"

export SYNTHELOS_BASE="$BASE"
export PYTHONDONTWRITEBYTECODE=1
export PATH="$RUNTIME_BIN_DIR:$PATH"
export HOME="$RUNTIME_ROOT/home"
export FLUXIO_WORKSPACE_ROOT="$CONTROL_ROOT"
export FLUXIO_CONTROL_PROJECT_ROOT="$CONTROL_ROOT"
export FLUXIO_CLUSTER_ROOT="${FLUXIO_CLUSTER_ROOT:-$CONTROL_ROOT}"
export FLUXIO_RUNTIME_HOME="$HOME"
export SYNTELOS_RUNTIME_HOME="$HOME"
export FLUXIO_RUNTIME_BIN_DIR="$RUNTIME_BIN_DIR"
export FLUXIO_RUNTIME_AUTO_UPDATE="${FLUXIO_RUNTIME_AUTO_UPDATE:-0}"
export NPM_CONFIG_CACHE="$HOME/.npm"
export OPENCLAW_STATE_DIR
export OPENCLAW_SUPERVISOR_MODE="${OPENCLAW_SUPERVISOR_MODE:-external}"
export OPENCLAW_SERVICE_REPAIR_POLICY="${OPENCLAW_SERVICE_REPAIR_POLICY:-external}"
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

load_clipproxy_api_key() {
  if [ "${CLIPROXY_API_KEY+x}" = x ]; then
    export CLIPROXY_API_KEY
    return 0
  fi

  secret_env_file="${FLUXIO_RUNTIME_SECRET_ENV_FILE:-$HOME/.fluxio_cliproxy_env}"
  if [ ! -e "$secret_env_file" ] && [ ! -L "$secret_env_file" ]; then
    return 0
  fi
  if ! cliproxy_value="$("$PYTHON" - "$secret_env_file" <<'PY'
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
except FileNotFoundError:
    raise SystemExit(0)
except OSError:
    raise SystemExit(1)

if (
    stat.S_ISLNK(metadata.st_mode)
    or not stat.S_ISREG(metadata.st_mode)
    or metadata.st_uid != os.getuid()
    or stat.S_IMODE(metadata.st_mode) & 0o077
):
    raise SystemExit(1)

try:
    raw = path.read_bytes()
except OSError:
    raise SystemExit(1)
if b"\0" in raw:
    raise SystemExit(1)
try:
    contents = raw.decode("utf-8")
except UnicodeDecodeError:
    raise SystemExit(1)

assignment_pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)")
values = []
for line in contents.splitlines():
    if not line or line.startswith("#"):
        continue
    assignment = assignment_pattern.fullmatch(line)
    if assignment is None:
        raise SystemExit(1)
    name, value = assignment.groups()
    if name == "CLIPROXY_API_KEY":
        values.append(value)

if len(values) > 1 or (values and not values[0]):
    raise SystemExit(1)
if values:
    sys.stdout.write(values[0])
PY
)"; then
    printf 'Refusing unsafe Fluxio runtime secret env file.\n' >&2
    return 11
  fi
  if [ -n "$cliproxy_value" ]; then
    export CLIPROXY_API_KEY="$cliproxy_value"
  fi
}

load_clipproxy_api_key

if [ -n "${CLIPROXY_API_KEY:-}" ]; then
  if [ "${NEYVIA_AUTH_BROKER_MODE+x}" != x ]; then
    export NEYVIA_AUTH_BROKER_MODE="codex-oauth"
  fi
  if [ "${OPENAI_BASE_URL+x}" != x ]; then
    export OPENAI_BASE_URL="http://127.0.0.1:8317/v1"
  fi
  if [ "${OPENAI_API_KEY+x}" != x ]; then
    export OPENAI_API_KEY="$CLIPROXY_API_KEY"
  fi
fi

activate_release_env() {
  active_release="$1"
  PYTHON="${FLUXIO_BACKEND_PYTHON:-$BASE/.venv/bin/python}"
  if [ -z "${FLUXIO_BACKEND_PYTHON:-}" ] && [ -f "$active_release/scripts/resolve_release_python.py" ]; then
    PYTHON="$("$PYTHON" "$active_release/scripts/resolve_release_python.py" "$BASE" "$active_release")"
  fi
  export SYNTHELOS_ROOT="$active_release"
  export FLUXIO_STATIC_ROOT="$active_release/web/dist"
  export PYTHONPATH="$active_release/src${BASE_PYTHONPATH:+:$BASE_PYTHONPATH}"
}

resolve_backend_launcher() {
  launcher_value="$1"
  if [ -L "$launcher_value" ] || [ ! -f "$launcher_value" ]; then
    printf 'Fluxio backend launcher override is unavailable or is a symlink: %s\n' "$launcher_value" >&2
    return 11
  fi
  launcher_directory="$(cd "$(dirname "$launcher_value")" && pwd -P)" || return 11
  launcher_path="$launcher_directory/$(basename "$launcher_value")"
  launcher_release="$(dirname "$launcher_directory")"
  if [ "$(basename "$launcher_path")" != "start_fluxio_backend.sh" ] || \
    [ "$(basename "$launcher_directory")" != "scripts" ] || \
    [ "$(dirname "$launcher_release")" != "$BASE/releases" ]; then
    printf 'Refusing backend launcher outside a direct immutable Syntelos release: %s\n' \
      "$launcher_path" >&2
    return 11
  fi
  printf '%s\n' "$launcher_path"
}

BACKEND_LAUNCHER="$(resolve_backend_launcher \
  "${FLUXIO_BACKEND_LAUNCHER:-$CUR/scripts/start_fluxio_backend.sh}")"

validate_positive_integer() {
  variable_name="$1"
  variable_value="$2"
  case "$variable_value" in
    ''|*[!0-9]*|0)
      printf '%s must be a positive integer: %s\n' "$variable_name" "$variable_value" >&2
      return 11
      ;;
  esac
}

validate_release_assets() {
  release_root="$1"
  for required_path in \
    "$release_root/scripts/run_web_backend.py" \
    "$release_root/web/dist/index.html" \
    "$release_root/src/grant_agent/worker.py" \
    "$release_root/src/grant_agent/cli.py"; do
    if [ ! -f "$required_path" ]; then
      printf 'Release preflight is missing required asset: %s\n' "$required_path" >&2
      return 11
    fi
  done
}

acquire_launcher_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    :
  else
    lock_owner="$(cat "$LOCK_OWNER_FILE" 2>/dev/null || true)"
    case "$lock_owner" in
      ''|*[!0-9]*)
        printf 'Fluxio launcher lock is present without a trustworthy owner: %s\n' "$LOCK_DIR" >&2
        return 16
        ;;
    esac
    if kill -0 "$lock_owner" 2>/dev/null; then
      printf 'Another Fluxio launcher transaction is active as PID %s.\n' "$lock_owner" >&2
      return 16
    fi
    rm -f "$LOCK_OWNER_FILE"
    if ! rmdir "$LOCK_DIR" 2>/dev/null || ! mkdir "$LOCK_DIR" 2>/dev/null; then
      printf 'Could not safely reclaim the stale Fluxio launcher lock: %s\n' "$LOCK_DIR" >&2
      return 16
    fi
  fi
  if ! printf '%s\n' "$$" > "$LOCK_OWNER_FILE.tmp" || \
    ! mv -f "$LOCK_OWNER_FILE.tmp" "$LOCK_OWNER_FILE"; then
    rm -f "$LOCK_OWNER_FILE.tmp" "$LOCK_OWNER_FILE"
    rmdir "$LOCK_DIR" 2>/dev/null || true
    printf 'Could not persist Fluxio launcher lock ownership.\n' >&2
    return 16
  fi
  LOCK_HELD=1
}

release_launcher_lock() {
  if [ "$LOCK_HELD" != "1" ]; then
    return 0
  fi
  lock_owner="$(cat "$LOCK_OWNER_FILE" 2>/dev/null || true)"
  if [ "$lock_owner" = "$$" ]; then
    rm -f "$LOCK_OWNER_FILE"
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
  LOCK_HELD=0
}

backend_release_for_pid() {
  owned_pid="$1"
  "$PYTHON" - "$owned_pid" "$BASE" "$CONTROL_ROOT" "$PORT" <<'PY'
from pathlib import Path
import sys

pid, base, control_root, port = sys.argv[1:]
try:
    arguments = [
        item.decode("utf-8", errors="surrogateescape")
        for item in (Path("/proc") / pid / "cmdline").read_bytes().split(b"\0")
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
runners = [Path(item).resolve() for item in arguments if item.endswith("/scripts/run_web_backend.py")]
static_value = value_after("--static-root")
if len(runners) != 1 or not static_value:
    raise SystemExit(1)
runner = runners[0]
static_root = Path(static_value).resolve()
release = runner.parent.parent
if (
    runner.parent.name != "scripts"
    or static_root.name != "dist"
    or static_root.parent.name != "web"
    or static_root.parent.parent != release
    or release.parent != releases_root
    or Path(value_after("--root")).resolve() != Path(control_root).resolve()
    or value_after("--port") != port
):
    raise SystemExit(1)
print(release)
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

owns_service_pid() {
  owned_pid="$1"
  service_kind="$2"
  "$PYTHON" - "$owned_pid" "$CONTROL_ROOT" "$service_kind" "$RUNTIME_ROOT" "$OPENCLAW_STATE_DIR" <<'PY'
from pathlib import Path
import sys

pid, control_root, service_kind, runtime_root, state_dir = sys.argv[1:]
proc = Path("/proc") / pid
try:
    arguments = [
        item.decode("utf-8", errors="surrogateescape")
        for item in (proc / "cmdline").read_bytes().split(b"\0")
        if item
    ]
except OSError:
    raise SystemExit(1)

def has_sequence(*expected: str) -> bool:
    width = len(expected)
    return any(arguments[index : index + width] == list(expected) for index in range(len(arguments)))

def has_pair(flag: str, expected: str) -> bool:
    return has_sequence(flag, expected)

if service_kind == "gateway":
    try:
        environment = dict(
            item.decode("utf-8", errors="surrogateescape").split("=", 1)
            for item in (proc / "environ").read_bytes().split(b"\0")
            if b"=" in item
        )
    except OSError:
        raise SystemExit(1)
    runtime_path = Path(runtime_root).resolve()
    runtime_prefix = str(runtime_path) + "/"
    try:
        executable = (proc / "exe").resolve(strict=True)
        executable.relative_to(runtime_path)
        executable_is_runtime_owned = True
    except (OSError, ValueError):
        executable_is_runtime_owned = False
    legacy_signature = has_sequence("gateway", "run") and any(
        argument.startswith(runtime_prefix) for argument in arguments
    )
    titled_signature = (
        arguments == ["openclaw-gateway"] and executable_is_runtime_owned
    )
    known = (
        (legacy_signature or titled_signature)
        and str(Path(environment.get("OPENCLAW_STATE_DIR", "")).resolve())
        == str(Path(state_dir).resolve())
        and str(Path(environment.get("HOME", "")).resolve())
        == str((runtime_path / "home").resolve())
        and environment.get("OPENCLAW_SUPERVISOR_MODE") == "external"
        and environment.get("OPENCLAW_SERVICE_REPAIR_POLICY") == "external"
    )
elif service_kind == "worker":
    known = has_sequence("-m", "grant_agent.worker") and has_pair("--root", control_root)
else:
    known = (
        has_sequence("-m", "grant_agent.cli", "mission-watchdog")
        and has_pair("--root", control_root)
        and "--loop" in arguments
    )
if not known:
    raise SystemExit(1)
PY
}

find_owned_service_pids() {
  service_kind="$1"
  "$PYTHON" - "$CONTROL_ROOT" "$service_kind" "$RUNTIME_ROOT" "$OPENCLAW_STATE_DIR" <<'PY'
from pathlib import Path
import sys

control_root, service_kind, runtime_root, state_dir = sys.argv[1:]

def matches(proc: Path) -> bool:
    try:
        arguments = [
            item.decode("utf-8", errors="surrogateescape")
            for item in (proc / "cmdline").read_bytes().split(b"\0")
            if item
        ]
    except OSError:
        return False

    def has_sequence(*expected: str) -> bool:
        width = len(expected)
        return any(arguments[index : index + width] == list(expected) for index in range(len(arguments)))

    def has_pair(flag: str, expected: str) -> bool:
        return has_sequence(flag, expected)

    if service_kind == "worker":
        return has_sequence("-m", "grant_agent.worker") and has_pair("--root", control_root)
    if service_kind == "watchdog":
        return (
            has_sequence("-m", "grant_agent.cli", "mission-watchdog")
            and has_pair("--root", control_root)
            and "--loop" in arguments
        )
    try:
        environment = dict(
            item.decode("utf-8", errors="surrogateescape").split("=", 1)
            for item in (proc / "environ").read_bytes().split(b"\0")
            if b"=" in item
        )
    except OSError:
        return False
    runtime_path = Path(runtime_root).resolve()
    runtime_prefix = str(runtime_path) + "/"
    try:
        executable = (proc / "exe").resolve(strict=True)
        executable.relative_to(runtime_path)
        executable_is_runtime_owned = True
    except (OSError, ValueError):
        executable_is_runtime_owned = False
    legacy_signature = has_sequence("gateway", "run") and any(
        argument.startswith(runtime_prefix) for argument in arguments
    )
    titled_signature = (
        arguments == ["openclaw-gateway"] and executable_is_runtime_owned
    )
    return (
        (legacy_signature or titled_signature)
        and str(Path(environment.get("OPENCLAW_STATE_DIR", "")).resolve())
        == str(Path(state_dir).resolve())
        and str(Path(environment.get("HOME", "")).resolve())
        == str((runtime_path / "home").resolve())
        and environment.get("OPENCLAW_SUPERVISOR_MODE") == "external"
        and environment.get("OPENCLAW_SERVICE_REPAIR_POLICY") == "external"
    )

for proc in Path("/proc").iterdir():
    if proc.name.isdigit() and matches(proc):
        print(proc.name)
PY
}

tracked_service_pid() {
  pid_file="$1"
  service_kind="$2"
  if ! discovered="$(find_owned_service_pids "$service_kind")"; then
    printf 'Could not safely discover existing Fluxio %s processes.\n' "$service_kind" >&2
    return 2
  fi
  discovered_count=0
  discovered_pid=""
  while IFS= read -r found_pid; do
    [ -n "$found_pid" ] || continue
    discovered_count=$((discovered_count + 1))
    discovered_pid="$found_pid"
  done <<< "$discovered"
  if [ "$discovered_count" -gt 1 ]; then
    printf 'Refusing startup: %s owned Fluxio %s processes were discovered.\n' \
      "$discovered_count" "$service_kind" >&2
    return 2
  fi
  if [ ! -f "$pid_file" ]; then
    if [ "$discovered_count" -ne 0 ]; then
      printf 'Refusing untracked live Fluxio %s PID %s; explicit migration is required.\n' \
        "$service_kind" "$discovered_pid" >&2
      return 2
    fi
    return 1
  fi
  tracked_pid="$(cat "$pid_file" 2>/dev/null || true)"
  case "$tracked_pid" in
    ''|*[!0-9]*)
      printf 'Refusing an invalid %s PID file: %s\n' "$service_kind" "$pid_file" >&2
      return 2
      ;;
  esac
  if ! kill -0 "$tracked_pid" 2>/dev/null; then
    if [ "$discovered_count" -ne 0 ]; then
      printf 'Refusing Fluxio %s: PID file is stale but owned PID %s is untracked.\n' \
        "$service_kind" "$discovered_pid" >&2
      return 2
    fi
    return 1
  fi
  if ! owns_service_pid "$tracked_pid" "$service_kind"; then
    printf 'Refusing live PID %s because it is not the owned Fluxio %s.\n' \
      "$tracked_pid" "$service_kind" >&2
    return 2
  fi
  if [ "$discovered_count" -ne 1 ] || [ "$discovered_pid" != "$tracked_pid" ]; then
    printf 'Fluxio %s PID tracking disagrees with live process discovery.\n' "$service_kind" >&2
    return 2
  fi
  printf '%s\n' "$tracked_pid"
}

capture_service_snapshot() {
  live_variable="$1"
  pid_variable="$2"
  pid_file="$3"
  service_kind="$4"
  if captured_pid="$(tracked_service_pid "$pid_file" "$service_kind")"; then
    printf -v "$live_variable" '%s' 1
    printf -v "$pid_variable" '%s' "$captured_pid"
    return 0
  else
    capture_status=$?
  fi
  if [ "$capture_status" -eq 1 ]; then
    printf -v "$live_variable" '%s' 0
    printf -v "$pid_variable" '%s' ""
    return 0
  fi
  return "$capture_status"
}

capture_previous_backend() {
  if [ -f "$BACKEND_PID_FILE" ]; then
    previous_pid="$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)"
    case "$previous_pid" in
      ''|*[!0-9]*)
        printf 'Refusing an invalid Fluxio backend PID file: %s\n' "$BACKEND_PID_FILE" >&2
        return 12
        ;;
    esac
    if kill -0 "$previous_pid" 2>/dev/null; then
      if ! PREVIOUS_LIVE_RELEASE="$(backend_release_for_pid "$previous_pid")"; then
        printf 'Refusing live backend PID %s because its release ownership is unverified.\n' \
          "$previous_pid" >&2
        return 12
      fi
      if ! backend_pid_owns_port_listener "$previous_pid"; then
        printf 'Refusing destructive rollout: verified backend PID %s does not exclusively own every listening socket on port %s.\n' \
          "$previous_pid" "$PORT" >&2
        return 15
      fi
      PREVIOUS_BACKEND_LIVE=1
      return 0
    fi
  fi
  if port_accepts_connection; then
    printf 'Refusing Fluxio launch: port %s answers without a live verified backend PID. Run the explicit legacy migration first.\n' \
      "$PORT" >&2
    return 15
  fi
  PREVIOUS_BACKEND_LIVE=0
  PREVIOUS_LIVE_RELEASE=""
}

worker_has_active_execution() {
  release_root="$1"
  worker_pid="$2"
  PYTHONPATH="$release_root/src${BASE_PYTHONPATH:+:$BASE_PYTHONPATH}" \
    "$PYTHON" - "$CONTROL_ROOT" "$worker_pid" <<'PY'
from pathlib import Path
import sqlite3
import sys

root = Path(sys.argv[1]).resolve()
worker_pid = int(sys.argv[2])
db_path = root / ".agent_control" / "cluster_registry.sqlite3"
try:
    if db_path.exists():
        connection = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=0.1,
        )
        try:
            connection.execute("PRAGMA busy_timeout=100")
            active = connection.execute(
                """
                SELECT process_id, parent_process_id, job_id
                FROM managed_processes
                WHERE status IN ('registered', 'launching', 'running')
                ORDER BY updated_at DESC LIMIT 1000
                """
            ).fetchall()
        finally:
            connection.close()
    else:
        active = []
except Exception as exc:
    print(f"could not inspect managed worker processes: {exc}", file=sys.stderr)
    raise SystemExit(2)
for process in active:
    process_id, parent_process_id, job_id = process
    if int(process_id or 0) == worker_pid or int(parent_process_id or 0) == worker_pid:
        print(f"managed process {process_id} for job {job_id}", file=sys.stderr)
        raise SystemExit(0)

parents: dict[int, int] = {}
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    try:
        for line in (proc / "status").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PPid:"):
                parents[int(proc.name)] = int(line.split()[1])
                break
    except (OSError, ValueError, IndexError):
        continue
for pid in parents:
    current = pid
    seen: set[int] = set()
    while current in parents and current not in seen:
        seen.add(current)
        parent = parents[current]
        if parent == worker_pid:
            print(f"descendant process {pid}", file=sys.stderr)
            raise SystemExit(0)
        current = parent
raise SystemExit(1)
PY
}

drain_previous_worker() {
  release_root="$1"
  worker_pid="$2"
  drain_timeout="${FLUXIO_WORKER_DRAIN_TIMEOUT_SECONDS:-300}"
  : > "$WORKER_GATE_FILE"
  WORKER_GATE_CREATED=1
  drain_started="$(date +%s)"
  while [ "$(($(date +%s) - drain_started))" -lt "$drain_timeout" ]; do
    if ! kill -0 "$worker_pid" 2>/dev/null || ! owns_service_pid "$worker_pid" worker; then
      printf 'Captured Fluxio worker changed identity while draining: %s\n' "$worker_pid" >&2
      return 18
    fi
    if worker_has_active_execution "$release_root" "$worker_pid" 2>/dev/null; then
      sleep 1
      continue
    else
      worker_activity_status=$?
      if [ "$worker_activity_status" -ne 1 ]; then
        sleep 1
        continue
      fi
    fi
    if ! kill -STOP "$worker_pid" 2>/dev/null; then
      printf 'Captured Fluxio worker exited before it could be paused: %s\n' "$worker_pid" >&2
      return 18
    fi
    PREVIOUS_WORKER_PAUSED=1
    if worker_has_active_execution "$release_root" "$worker_pid" 2>/dev/null; then
      kill -CONT "$worker_pid" 2>/dev/null || true
      PREVIOUS_WORKER_PAUSED=0
      sleep 1
      continue
    else
      worker_activity_status=$?
      if [ "$worker_activity_status" -eq 1 ]; then
        return 0
      fi
    fi
    kill -CONT "$worker_pid" 2>/dev/null || true
    PREVIOUS_WORKER_PAUSED=0
    sleep 1
  done
  printf 'Fluxio worker did not drain within %s seconds; leaving current work running.\n' \
    "$drain_timeout" >&2
  return 18
}

resume_previous_worker() {
  if [ "$PREVIOUS_WORKER_PAUSED" = "1" ]; then
    if kill -0 "$PREVIOUS_WORKER_PID" 2>/dev/null && \
      owns_service_pid "$PREVIOUS_WORKER_PID" worker; then
      kill -CONT "$PREVIOUS_WORKER_PID" 2>/dev/null || true
    fi
    PREVIOUS_WORKER_PAUSED=0
  fi
}

stop_service_pid() {
  pid_file="$1"
  service_kind="$2"
  release_root="${3:-$CUR}"
  if [ ! -f "$pid_file" ]; then
    return 0
  fi
  owned_pid="$(cat "$pid_file" 2>/dev/null || true)"
  case "$owned_pid" in
    ''|*[!0-9]*)
      printf 'Refusing an invalid %s PID file: %s\n' "$service_kind" "$pid_file" >&2
      return 12
      ;;
  esac
  if ! kill -0 "$owned_pid" 2>/dev/null; then
    rm -f "$pid_file"
    return 0
  fi
  if ! owns_service_pid "$owned_pid" "$service_kind"; then
    printf 'Refusing to stop PID %s because it is not the owned Fluxio %s.\n' \
      "$owned_pid" "$service_kind" >&2
    return 12
  fi
  if [ "$service_kind" = "worker" ]; then
    if ! kill -STOP "$owned_pid" 2>/dev/null; then
      rm -f "$pid_file"
      return 0
    fi
    if worker_has_active_execution "$release_root" "$owned_pid"; then
      kill -CONT "$owned_pid" 2>/dev/null || true
      printf 'Refusing to interrupt Fluxio worker PID %s while a managed job process is active.\n' \
        "$owned_pid" >&2
      return 18
    else
      worker_activity_status=$?
      if [ "$worker_activity_status" -ne 1 ]; then
        kill -CONT "$owned_pid" 2>/dev/null || true
        printf 'Could not prove Fluxio worker PID %s is idle; refusing termination.\n' \
          "$owned_pid" >&2
        return 18
      fi
    fi
    kill -TERM "$owned_pid" 2>/dev/null || true
    kill -CONT "$owned_pid" 2>/dev/null || true
  else
    kill -TERM "$owned_pid" 2>/dev/null || true
  fi
  waited=0
  stop_timeout="${FLUXIO_SERVICE_STOP_TIMEOUT_SECONDS:-30}"
  while kill -0 "$owned_pid" 2>/dev/null && [ "$waited" -lt "$stop_timeout" ]; do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$owned_pid" 2>/dev/null; then
    if [ "$service_kind" = "worker" ]; then
      printf 'Fluxio worker did not drain within %s seconds; refusing SIGKILL to avoid orphaning jobs.\n' \
        "$stop_timeout" >&2
      return 18
    fi
    if ! owns_service_pid "$owned_pid" "$service_kind"; then
      printf 'Fluxio %s PID ownership changed while stopping: %s\n' "$service_kind" "$owned_pid" >&2
      return 12
    fi
    kill -KILL "$owned_pid" 2>/dev/null || true
    sleep 1
  fi
  if kill -0 "$owned_pid" 2>/dev/null; then
    printf 'Owned Fluxio %s did not stop: %s\n' "$service_kind" "$owned_pid" >&2
    return 12
  fi
  rm -f "$pid_file"
}

gateway_health() {
  "$PYTHON" - "$OPENCLAW" "${FLUXIO_OPENCLAW_HEALTH_TIMEOUT_SECONDS:-45}" <<'PY'
import json
import os
import selectors
import signal
import subprocess
import sys
import time

cli, timeout = sys.argv[1:]

def healthy_payload(output):
    if isinstance(output, (bytes, bytearray)):
        output = bytes(output).decode("utf-8", errors="replace")
    try:
        payload = json.loads(output or "{}")
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("ok") is True

def stop_process(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    process.wait()

try:
    process = subprocess.Popen(
        [cli, "gateway", "health", "--json"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
except (OSError, ValueError):
    raise SystemExit(1)

output = bytearray()
healthy = False
deadline = time.monotonic() + max(1, int(timeout))
selector = selectors.DefaultSelector()
selector.register(process.stdout, selectors.EVENT_READ)
try:
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        events = selector.select(timeout=min(1, max(0, remaining)))
        if not events:
            if process.poll() is not None:
                break
            continue
        for key, _mask in events:
            try:
                chunk = os.read(key.fileobj.fileno(), 65536)
            except OSError:
                chunk = b""
            if not chunk:
                try:
                    selector.unregister(key.fileobj)
                except KeyError:
                    pass
                continue
            output.extend(chunk)
            if len(output) > 1024 * 1024:
                break
            if healthy_payload(output):
                healthy = True
                break
        if healthy or len(output) > 1024 * 1024:
            break
finally:
    selector.close()
    stop_process(process)

if not healthy:
    raise SystemExit(1)
PY
}

gateway_health_preflight() {
  attempt=1
  while [ "$attempt" -le 3 ]; do
    if gateway_health; then
      return 0
    fi
    if [ "$attempt" -lt 3 ]; then
      sleep 1
    fi
    attempt=$((attempt + 1))
  done
  return 1
}

backend_health() {
  curl --silent --show-error --fail --noproxy '*' --max-time 10 \
    --resolve "$HEALTH_RESOLVE" "$HEALTH_URL"
}

worker_state_ready() {
  worker_pid="$1"
  started_epoch="$2"
  "$PYTHON" - "$WORKER_STATE_FILE" "$worker_pid" "$CONTROL_ROOT" "$started_epoch" <<'PY'
from datetime import datetime
import json
from pathlib import Path
import sys

from grant_agent.cluster import ClusterRegistry

state_path, pid, root, started_epoch = sys.argv[1:]
try:
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
except (OSError, ValueError, TypeError):
    raise SystemExit(1)
if int(state.get("pid") or 0) != int(pid):
    raise SystemExit(1)
if state.get("status") == "degraded" or state.get("lastError"):
    raise SystemExit(1)
if state.get("healthy") is True and state.get("readyAt"):
    raise SystemExit(0)
if state.get("status") not in {"ready", "idle", "working"}:
    raise SystemExit(1)
host_id = str(state.get("hostId") or "")
host = ClusterRegistry(Path(root)).get_host(host_id) if host_id else {}
heartbeat = str(host.get("lastHeartbeatAt") or "")
try:
    heartbeat_epoch = datetime.fromisoformat(heartbeat.replace("Z", "+00:00")).timestamp()
except ValueError:
    raise SystemExit(1)
if not host.get("online") or heartbeat_epoch < float(started_epoch):
    raise SystemExit(1)
PY
}

watchdog_state_ready() {
  watchdog_pid="$1"
  "$PYTHON" - "$WATCHDOG_STATE_FILE" "$watchdog_pid" <<'PY'
import json
from pathlib import Path
import sys

path, pid = sys.argv[1:]
try:
    state = json.loads(Path(path).read_text(encoding="utf-8"))
except (OSError, ValueError, TypeError):
    raise SystemExit(1)
if (
    int(state.get("processPid") or 0) != int(pid)
    or not state.get("supervisorActive")
    or int(state.get("runsCompleted") or 0) < 1
    or not state.get("lastRunAt")
):
    raise SystemExit(1)
PY
}

wait_for_service_ready() {
  service_kind="$1"
  service_pid="$2"
  started_epoch="$3"
  case "$service_kind" in
    gateway) ready_timeout="${FLUXIO_OPENCLAW_GATEWAY_START_TIMEOUT_SECONDS:-45}" ;;
    worker) ready_timeout="${FLUXIO_WORKER_START_TIMEOUT_SECONDS:-45}" ;;
    *) ready_timeout="${FLUXIO_WATCHDOG_START_TIMEOUT_SECONDS:-300}" ;;
  esac
  waited=0
  while [ "$waited" -lt "$ready_timeout" ]; do
    if ! kill -0 "$service_pid" 2>/dev/null; then
      return 1
    fi
    # A newly spawned process can still expose the short-lived nohup command
    # line before exec(2) installs its final service identity. Keep waiting for
    # the exact owned identity instead of treating that transition as failure.
    if owns_service_pid "$service_pid" "$service_kind"; then
      case "$service_kind" in
        gateway) gateway_health && return 0 ;;
        worker) worker_state_ready "$service_pid" "$started_epoch" && return 0 ;;
        watchdog) watchdog_state_ready "$service_pid" && return 0 ;;
      esac
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

start_gateway_process() {
  : > "$CONTROL_DIR/openclaw_gateway.out.log"
  : > "$CONTROL_DIR/openclaw_gateway.err.log"
  LAST_STARTED_EPOCH="$("$PYTHON" -c 'import time; print(time.time())')"
  nohup "$OPENCLAW" gateway run \
    > "$CONTROL_DIR/openclaw_gateway.out.log" \
    2> "$CONTROL_DIR/openclaw_gateway.err.log" < /dev/null &
  LAST_STARTED_PID=$!
  printf '%s\n' "$LAST_STARTED_PID" > "$GATEWAY_PID_FILE.tmp"
  mv -f "$GATEWAY_PID_FILE.tmp" "$GATEWAY_PID_FILE"
}

start_worker_process() {
  release_root="$1"
  gated="$2"
  activate_release_env "$release_root"
  rm -f "$WORKER_STATE_FILE"
  worker_gate_args=()
  if [ "$gated" = "1" ]; then
    if "$PYTHON" -m grant_agent.worker --help 2>&1 | grep -Fq -- '--startup-gate-file'; then
      : > "$WORKER_GATE_FILE"
      WORKER_GATE_CREATED=1
      worker_gate_args=(--startup-gate-file "$WORKER_GATE_FILE")
    else
      printf 'Fluxio worker release %s predates startup gates; using compatible rollback startup.\n' \
        "$release_root" >&2
    fi
  fi
  LAST_STARTED_EPOCH="$("$PYTHON" -c 'import time; print(time.time())')"
  nohup "$PYTHON" -m grant_agent.worker \
    --root "$CONTROL_ROOT" \
    --host-id "${FLUXIO_WORKER_HOST_ID:-nas.example.invalid}" \
    --poll-seconds "${FLUXIO_WORKER_POLL_SECONDS:-5}" \
    --max-jobs "$FLUXIO_WORKER_MAX_JOBS" \
    "${worker_gate_args[@]}" \
    > "$CONTROL_DIR/worker.out.log" 2> "$CONTROL_DIR/worker.err.log" < /dev/null &
  LAST_STARTED_PID=$!
  printf '%s\n' "$LAST_STARTED_PID" > "$WORKER_PID_FILE.tmp"
  mv -f "$WORKER_PID_FILE.tmp" "$WORKER_PID_FILE"
}

start_watchdog_process() {
  release_root="$1"
  activate_release_env "$release_root"
  LAST_STARTED_EPOCH="$("$PYTHON" -c 'import time; print(time.time())')"
  nohup "$PYTHON" -m grant_agent.cli mission-watchdog \
    --root "$CONTROL_ROOT" \
    --loop \
    --max-runs 0 \
    --interval-seconds "${FLUXIO_WATCHDOG_INTERVAL_SECONDS:-120}" \
    --fake-running-minutes "${FLUXIO_FAKE_RUNNING_MINUTES:-30}" \
    > "$CONTROL_DIR/mission_watchdog.out.log" \
    2> "$CONTROL_DIR/mission_watchdog.err.log" < /dev/null &
  LAST_STARTED_PID=$!
  printf '%s\n' "$LAST_STARTED_PID" > "$WATCHDOG_PID_FILE.tmp"
  mv -f "$WATCHDOG_PID_FILE.tmp" "$WATCHDOG_PID_FILE"
}

start_backend_release() {
  release_root="$1"
  SYNTHELOS_ROOT="$release_root" \
    FLUXIO_BACKEND_PREFLIGHT_ONLY=0 \
    FLUXIO_BACKEND_STOP_ONLY=0 \
    bash "$BACKEND_LAUNCHER"
}

stop_backend_release() {
  release_root="$1"
  SYNTHELOS_ROOT="$release_root" \
    FLUXIO_BACKEND_PREFLIGHT_ONLY=0 \
    FLUXIO_BACKEND_STOP_ONLY=1 \
    bash "$BACKEND_LAUNCHER"
}

preflight_release() {
  release_root="$1"
  validate_release_assets "$release_root"
  doctor_output="$(PYTHONPATH="$release_root/src${BASE_PYTHONPATH:+:$BASE_PYTHONPATH}" \
    "$PYTHON" -m grant_agent.worker \
      --root "$CONTROL_ROOT" \
      --host-id "${FLUXIO_WORKER_HOST_ID:-nas.example.invalid}" \
      --max-jobs "$FLUXIO_WORKER_MAX_JOBS" \
      --doctor)"
  "$PYTHON" - "$doctor_output" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if payload.get("schema") != "fluxio.worker_doctor.v1" or payload.get("status") != "ready":
    raise SystemExit(1)
PY
  PYTHONPATH="$release_root/src${BASE_PYTHONPATH:+:$BASE_PYTHONPATH}" \
    "$PYTHON" -c 'import grant_agent.cli' >/dev/null
  SYNTHELOS_ROOT="$release_root" \
    FLUXIO_BACKEND_PREFLIGHT_ONLY=1 \
    FLUXIO_BACKEND_STOP_ONLY=0 \
    bash "$BACKEND_LAUNCHER" >/dev/null
}

ensure_gateway_ready() {
  release_root="$1"
  activate_release_env "$release_root"
  if gateway_pid="$(tracked_service_pid "$GATEWAY_PID_FILE" gateway)"; then
    gateway_health
    return
  else
    gateway_status=$?
  fi
  [ "$gateway_status" -eq 1 ] || return "$gateway_status"
  start_gateway_process
  wait_for_service_ready gateway "$LAST_STARTED_PID" "$LAST_STARTED_EPOCH"
}

ensure_worker_ready() {
  release_root="$1"
  if worker_pid="$(tracked_service_pid "$WORKER_PID_FILE" worker)"; then
    activate_release_env "$release_root"
    worker_state_ready "$worker_pid" 0
    return
  else
    worker_status=$?
  fi
  [ "$worker_status" -eq 1 ] || return "$worker_status"
  start_worker_process "$release_root" 0
  wait_for_service_ready worker "$LAST_STARTED_PID" "$LAST_STARTED_EPOCH"
}

ensure_watchdog_ready() {
  release_root="$1"
  if watchdog_pid="$(tracked_service_pid "$WATCHDOG_PID_FILE" watchdog)"; then
    activate_release_env "$release_root"
    watchdog_state_ready "$watchdog_pid"
    return
  else
    watchdog_status=$?
  fi
  [ "$watchdog_status" -eq 1 ] || return "$watchdog_status"
  start_watchdog_process "$release_root"
  wait_for_service_ready watchdog "$LAST_STARTED_PID" "$LAST_STARTED_EPOCH"
}

rollback_transaction() {
  TRANSACTION_ACTIVE=0
  rollback_failed=0
  set +e
  printf 'Fluxio candidate startup failed; restoring captured release %s.\n' \
    "${ROLLBACK_RELEASE:-none}" >&2
  if [ "$CANDIDATE_WATCHDOG_STARTED" = "1" ]; then
    stop_service_pid "$WATCHDOG_PID_FILE" watchdog "$CUR" || rollback_failed=1
  fi
  if [ "$CANDIDATE_WORKER_STARTED" = "1" ]; then
    if stop_service_pid "$WORKER_PID_FILE" worker "$CUR"; then
      if [ "$WORKER_GATE_CREATED" = "1" ]; then
        rm -f "$WORKER_GATE_FILE"
        WORKER_GATE_CREATED=0
      fi
    else
      rollback_failed=1
    fi
  elif [ "$WORKER_GATE_CREATED" = "1" ]; then
    rm -f "$WORKER_GATE_FILE"
    WORKER_GATE_CREATED=0
  fi
  if [ "$CANDIDATE_GATEWAY_STARTED" = "1" ]; then
    stop_service_pid "$GATEWAY_PID_FILE" gateway "$CUR" || rollback_failed=1
  fi
  if [ "$PREVIOUS_BACKEND_LIVE" = "1" ]; then
    start_backend_release "$ROLLBACK_RELEASE" || rollback_failed=1
    backend_health >/dev/null || rollback_failed=1
  elif [ "$CANDIDATE_BACKEND_ATTEMPTED" = "1" ]; then
    stop_backend_release "$CUR" || rollback_failed=1
  fi
  if [ "$PREVIOUS_GATEWAY_LIVE" = "1" ]; then
    ensure_gateway_ready "$ROLLBACK_RELEASE" || rollback_failed=1
  fi
  if [ "$PREVIOUS_WORKER_LIVE" = "1" ]; then
    ensure_worker_ready "$ROLLBACK_RELEASE" || rollback_failed=1
  fi
  if [ "$PREVIOUS_WATCHDOG_LIVE" = "1" ]; then
    ensure_watchdog_ready "$ROLLBACK_RELEASE" || rollback_failed=1
  fi
  set -e
  if [ "$rollback_failed" -ne 0 ]; then
    printf 'FATAL: Fluxio rollback did not restore the complete captured cohort.\n' >&2
    return 1
  fi
  printf 'Fluxio rollback restored release=%s gateway=%s worker=%s watchdog=%s.\n' \
    "${ROLLBACK_RELEASE:-none}" "$PREVIOUS_GATEWAY_LIVE" \
    "$PREVIOUS_WORKER_LIVE" "$PREVIOUS_WATCHDOG_LIVE" >&2
  return 0
}

on_exit() {
  exit_status=$?
  trap - EXIT INT TERM
  if [ "$exit_status" -ne 0 ] && [ "$TRANSACTION_ACTIVE" = "1" ] && [ "$TRANSACTION_COMMITTED" != "1" ]; then
    if ! rollback_transaction; then
      exit_status=70
    fi
  fi
  if [ "$exit_status" -ne 0 ]; then
    resume_previous_worker
    if [ "$TRANSACTION_ACTIVE" != "1" ] && [ "$WORKER_GATE_CREATED" = "1" ]; then
      rm -f "$WORKER_GATE_FILE"
      WORKER_GATE_CREATED=0
    fi
  fi
  release_launcher_lock
  exit "$exit_status"
}

main() {
  if [ ! -x "$PYTHON" ]; then
    printf 'Fluxio backend Python is not executable: %s\n' "$PYTHON" >&2
    return 11
  fi
  if [ ! -f "$BACKEND_LAUNCHER" ]; then
    printf 'Hardened Fluxio backend launcher is missing from candidate release: %s\n' \
      "$BACKEND_LAUNCHER" >&2
    return 11
  fi
  if ! command -v curl >/dev/null 2>&1; then
    printf 'curl is required for certificate-valid Fluxio health checks.\n' >&2
    return 11
  fi
  case "$PORT" in
    ''|*[!0-9]*) printf 'FLUXIO_WEB_PORT must be numeric: %s\n' "$PORT" >&2; return 11 ;;
  esac
  if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    printf 'FLUXIO_WEB_PORT must be between 1 and 65535: %s\n' "$PORT" >&2
    return 11
  fi
  for timeout_pair in \
    "FLUXIO_SERVICE_STOP_TIMEOUT_SECONDS:${FLUXIO_SERVICE_STOP_TIMEOUT_SECONDS:-30}" \
    "FLUXIO_OPENCLAW_GATEWAY_START_TIMEOUT_SECONDS:${FLUXIO_OPENCLAW_GATEWAY_START_TIMEOUT_SECONDS:-45}" \
    "FLUXIO_OPENCLAW_HEALTH_TIMEOUT_SECONDS:${FLUXIO_OPENCLAW_HEALTH_TIMEOUT_SECONDS:-45}" \
    "FLUXIO_WORKER_DRAIN_TIMEOUT_SECONDS:${FLUXIO_WORKER_DRAIN_TIMEOUT_SECONDS:-300}" \
    "FLUXIO_WORKER_START_TIMEOUT_SECONDS:${FLUXIO_WORKER_START_TIMEOUT_SECONDS:-45}" \
    "FLUXIO_WATCHDOG_START_TIMEOUT_SECONDS:${FLUXIO_WATCHDOG_START_TIMEOUT_SECONDS:-300}"; do
    validate_positive_integer "${timeout_pair%%:*}" "${timeout_pair#*:}"
  done
  case "$DESIRED_GATEWAY:$DESIRED_WORKER" in
    0:0|0:1|1:0|1:1) ;;
    *) printf 'Fluxio service enable flags must be 0 or 1.\n' >&2; return 11 ;;
  esac

  acquire_launcher_lock
  trap on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

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
      return 11
    }
  fi
  HEALTH_URL="https://$HEALTH_HOST:$PORT/health"
  HEALTH_RESOLVE="$HEALTH_HOST:$PORT:127.0.0.1"

  validate_release_assets "$CUR"
  capture_previous_backend
  capture_service_snapshot PREVIOUS_GATEWAY_LIVE PREVIOUS_GATEWAY_PID "$GATEWAY_PID_FILE" gateway
  capture_service_snapshot PREVIOUS_WORKER_LIVE PREVIOUS_WORKER_PID "$WORKER_PID_FILE" worker
  capture_service_snapshot PREVIOUS_WATCHDOG_LIVE PREVIOUS_WATCHDOG_PID "$WATCHDOG_PID_FILE" watchdog
  if [ "$PREVIOUS_BACKEND_LIVE" != "1" ] && \
    { [ "$PREVIOUS_GATEWAY_LIVE" = "1" ] || [ "$PREVIOUS_WORKER_LIVE" = "1" ] || [ "$PREVIOUS_WATCHDOG_LIVE" = "1" ]; }; then
    printf 'Refusing rollout from a partial unowned cohort without a verified live backend release.\n' >&2
    return 17
  fi

  rollback_value="${FLUXIO_ROLLBACK_RELEASE:-}"
  if [ "$PREVIOUS_BACKEND_LIVE" = "1" ]; then
    [ -n "$rollback_value" ] || rollback_value="$PREVIOUS_LIVE_RELEASE"
    ROLLBACK_RELEASE="$(resolve_release "$rollback_value" rollback)"
    if [ "$ROLLBACK_RELEASE" != "$PREVIOUS_LIVE_RELEASE" ]; then
      printf 'FLUXIO_ROLLBACK_RELEASE does not match the release captured from live backend PID: %s != %s\n' \
        "$ROLLBACK_RELEASE" "$PREVIOUS_LIVE_RELEASE" >&2
      return 17
    fi
  elif [ -n "$rollback_value" ]; then
    ROLLBACK_RELEASE="$(resolve_release "$rollback_value" rollback)"
  fi

  preflight_release "$CUR"
  if [ -n "$ROLLBACK_RELEASE" ]; then
    preflight_release "$ROLLBACK_RELEASE"
  fi
  if { [ "$DESIRED_GATEWAY" = "1" ] || [ "$PREVIOUS_GATEWAY_LIVE" = "1" ]; } && [ ! -x "$OPENCLAW" ]; then
    printf 'OpenClaw gateway runtime is required but unavailable: %s\n' "$OPENCLAW" >&2
    return 6
  fi
  if [ "$PREVIOUS_BACKEND_LIVE" = "1" ] && ! backend_health >/dev/null; then
    printf 'Captured rollback backend is not certificate-valid and healthy; refusing destructive rollout.\n' >&2
    return 17
  fi
  if [ "$PREVIOUS_GATEWAY_LIVE" = "1" ]; then
    activate_release_env "$PREVIOUS_LIVE_RELEASE"
  fi
  if [ "$PREVIOUS_GATEWAY_LIVE" = "1" ] && ! gateway_health_preflight; then
    printf 'Captured rollback gateway is unhealthy; refusing destructive rollout.\n' >&2
    return 17
  fi
  if [ "$PREVIOUS_WORKER_LIVE" = "1" ]; then
    activate_release_env "$PREVIOUS_LIVE_RELEASE"
    if ! worker_state_ready "$PREVIOUS_WORKER_PID" 0; then
      printf 'Captured rollback worker has no healthy state/cluster heartbeat; refusing destructive rollout.\n' >&2
      return 17
    fi
  fi
  if [ "$PREVIOUS_WATCHDOG_LIVE" = "1" ] && \
    ! watchdog_state_ready "$PREVIOUS_WATCHDOG_PID"; then
    printf 'Captured rollback watchdog has no completed live supervisor pass; refusing destructive rollout.\n' >&2
    return 17
  fi
  if [ "$PREVIOUS_WORKER_LIVE" = "1" ]; then
    drain_previous_worker "$PREVIOUS_LIVE_RELEASE" "$PREVIOUS_WORKER_PID"
  fi

  TRANSACTION_ACTIVE=1
  if [ "$PREVIOUS_WORKER_LIVE" = "1" ]; then
    stop_service_pid "$WORKER_PID_FILE" worker "$PREVIOUS_LIVE_RELEASE"
    PREVIOUS_WORKER_PAUSED=0
  fi
  if [ "$PREVIOUS_WATCHDOG_LIVE" = "1" ]; then
    stop_service_pid "$WATCHDOG_PID_FILE" watchdog "$PREVIOUS_LIVE_RELEASE"
  fi
  if [ "$PREVIOUS_GATEWAY_LIVE" = "1" ]; then
    stop_service_pid "$GATEWAY_PID_FILE" gateway "$PREVIOUS_LIVE_RELEASE"
  fi

  CANDIDATE_BACKEND_ATTEMPTED=1
  start_backend_release "$CUR"
  backend_health >/dev/null

  if [ "$DESIRED_GATEWAY" = "1" ]; then
    CANDIDATE_GATEWAY_STARTED=1
    activate_release_env "$CUR"
    start_gateway_process
    activate_release_env "$CUR"
    wait_for_service_ready gateway "$LAST_STARTED_PID" "$LAST_STARTED_EPOCH" || {
      printf 'OpenClaw gateway did not become ready. See %s\n' \
        "$CONTROL_DIR/openclaw_gateway.err.log" >&2
      return 6
    }
  fi

  if [ "$DESIRED_WORKER" = "1" ]; then
    CANDIDATE_WORKER_STARTED=1
    start_worker_process "$CUR" 1
    wait_for_service_ready worker "$LAST_STARTED_PID" "$LAST_STARTED_EPOCH" || {
      printf 'Fluxio worker did not publish a healthy startup heartbeat. See %s\n' \
        "$CONTROL_DIR/worker.err.log" >&2
      return 3
    }
  fi

  CANDIDATE_WATCHDOG_STARTED=1
  start_watchdog_process "$CUR"
  wait_for_service_ready watchdog "$LAST_STARTED_PID" "$LAST_STARTED_EPOCH" || {
    printf 'Fluxio watchdog did not complete its first supervised pass. See %s\n' \
      "$CONTROL_DIR/mission_watchdog.err.log" >&2
    return 4
  }

  health="$(backend_health)"
  case "$health" in
    *'"ok": true'*|*'"ok":true'*) ;;
    *) printf 'Fluxio backend returned an invalid health payload: %s\n' "$health" >&2; return 5 ;;
  esac

  trap '' INT TERM
  if ! rm -f "$WORKER_GATE_FILE"; then
    trap 'exit 130' INT
    trap 'exit 143' TERM
    printf 'Could not release the candidate worker startup gate.\n' >&2
    return 19
  fi
  WORKER_GATE_CREATED=0
  TRANSACTION_COMMITTED=1
  trap 'exit 130' INT
  trap 'exit 143' TERM
  activate_release_env "$CUR"
  printf 'Fluxio services ready: release=%s backend=%s gateway=%s worker=%s watchdog=%s max_jobs=%s\n' \
    "$CUR" \
    "$(cat "$BACKEND_PID_FILE" 2>/dev/null || printf unknown)" \
    "$(cat "$GATEWAY_PID_FILE" 2>/dev/null || printf disabled)" \
    "$(cat "$WORKER_PID_FILE" 2>/dev/null || printf disabled)" \
    "$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || printf unknown)" \
    "$FLUXIO_WORKER_MAX_JOBS"
  printf '%s\n' "$health"
}

main "$@"
