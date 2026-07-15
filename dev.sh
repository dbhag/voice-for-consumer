#!/usr/bin/env bash
# Single dev runner: fakeredis (TCP) -> uvicorn API -> arq worker -> dashboard,
# each started only once the previous one is actually ready, sharing one set
# of env vars. Ctrl+C tears everything down. See CLAUDE.md / README.md for
# what each piece is.
set -euo pipefail
set -m # background jobs get their own process group, so cleanup can kill each one's children too

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

log() { printf '[dev] %s\n' "$*"; }

# --mock / DEV_MOCK=1: force fake providers for a local dry run. Without
# this, a "smoke test" would use whatever .env says for
# VOICE_PLATFORM_PROVIDER / LLM_PROVIDER — which in this repo's .env is
# real Retell + real OpenAI, i.e. it would spend money and could place a
# real phone call. Real providers must be an explicit opt-in, never the
# default for `./dev.sh` with no args.
DEV_MOCK="${DEV_MOCK:-0}"
for arg in "$@"; do
  if [ "$arg" = "--mock" ]; then
    DEV_MOCK=1
  fi
done

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

FAKEREDIS_HOST="${FAKEREDIS_HOST:-127.0.0.1}"
FAKEREDIS_PORT="${FAKEREDIS_PORT:-6379}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-3000}"

# Override whatever REDIS_URL came from .env: dev.sh always talks to the
# fakeredis TCP server it starts below, never a real Redis.
export REDIS_URL="redis://${FAKEREDIS_HOST}:${FAKEREDIS_PORT}/0"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://${API_HOST}:${API_PORT}}"
# Derived from DASHBOARD_PORT, not hardcoded, so a custom port still gets a
# working CORS allowlist on the API (app/main.py's CORSMiddleware) instead
# of a silent "Failed to fetch" in the browser.
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:${DASHBOARD_PORT},http://127.0.0.1:${DASHBOARD_PORT}}"

if [ "$DEV_MOCK" = "1" ]; then
  export VOICE_PLATFORM_PROVIDER=mock
  export LLM_PROVIDER=fake
  log "--mock: forcing VOICE_PLATFORM_PROVIDER=mock, LLM_PROVIDER=fake (no real calls, no real LLM spend)"
fi

LOG_DIR="$ROOT_DIR/.dev-logs"
mkdir -p "$LOG_DIR"

log "ensuring postgres role/db/schema exist..."
"$ROOT_DIR/scripts/db_setup.sh"

PIDS=()
NAMES=()

start() {
  local name="$1" logfile="$2"
  shift 2
  log "starting $name..."
  "$@" >"$logfile" 2>&1 &
  PIDS+=("$!")
  NAMES+=("$name")
}

cleanup() {
  trap - EXIT INT TERM
  log "shutting down..."
  local i
  for ((i = ${#PIDS[@]} - 1; i >= 0; i--)); do
    local pid="${PIDS[$i]}"
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  log "all stopped."
}
trap cleanup EXIT INT TERM

wait_for_tcp() {
  local host="$1" port="$2" name="$3" tries=0
  until python3 -c "
import socket, sys
try:
    socket.create_connection(('$host', $port), timeout=1).close()
except OSError:
    sys.exit(1)
" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -ge 120 ]; then
      log "$name did not open $host:$port in time; see logs"
      exit 1
    fi
    sleep 0.5
  done
}

wait_for_http() {
  local url="$1" name="$2" tries=0
  until curl -sf -o /dev/null "$url"; do
    tries=$((tries + 1))
    if [ "$tries" -ge 120 ]; then
      log "$name did not answer $url in time; see logs"
      exit 1
    fi
    sleep 0.5
  done
}

# Waits for a log line to appear, and also checks the process is still alive — both at
# each poll and again just after the pattern shows up. A log line alone
# isn't proof of readiness if the process can crash right after printing it
# (that's exactly how the old "Starting worker for" gate went stale: arq
# prints that line, then crashes trying to reach fakeredis's unimplemented
# INFO command, and the gate still reported ready).
wait_for_log_and_alive() {
  local logfile="$1" pattern="$2" pid="$3" name="$4" tries=0
  until grep -q "$pattern" "$logfile" 2>/dev/null; do
    if ! kill -0 "$pid" 2>/dev/null; then
      log "$name process died before logging '$pattern'; see $logfile"
      exit 1
    fi
    tries=$((tries + 1))
    if [ "$tries" -ge 120 ]; then
      log "$name did not log '$pattern' in time; see $logfile"
      exit 1
    fi
    sleep 0.5
  done
  sleep 0.3
  if ! kill -0 "$pid" 2>/dev/null; then
    log "$name crashed immediately after reporting ready; see $logfile"
    exit 1
  fi
}

start "fakeredis" "$LOG_DIR/fakeredis.log" \
  python3 scripts/run_fakeredis.py "$FAKEREDIS_HOST" "$FAKEREDIS_PORT"
wait_for_tcp "$FAKEREDIS_HOST" "$FAKEREDIS_PORT" "fakeredis"
log "fakeredis ready on ${FAKEREDIS_HOST}:${FAKEREDIS_PORT}"

start "api" "$LOG_DIR/api.log" \
  uvicorn app.main:app --host "$API_HOST" --port "$API_PORT"
wait_for_http "http://${API_HOST}:${API_PORT}/health" "api"
log "api ready on http://${API_HOST}:${API_PORT}"

start "worker" "$LOG_DIR/worker.log" \
  arq app.queue.tasks.WorkerSettings
WORKER_PID="${PIDS[${#PIDS[@]}-1]}"
wait_for_log_and_alive "$LOG_DIR/worker.log" "worker startup complete" "$WORKER_PID" "worker"
log "worker ready"

start "dashboard" "$LOG_DIR/dashboard.log" \
  npm --prefix dashboard run dev -- -p "$DASHBOARD_PORT"
wait_for_tcp "127.0.0.1" "$DASHBOARD_PORT" "dashboard"
log "dashboard ready on http://localhost:${DASHBOARD_PORT}"

log "all services up. logs in $LOG_DIR. press Ctrl+C to stop everything."
wait
