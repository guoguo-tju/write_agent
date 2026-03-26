#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${XHS_MCP_RUN_DIR:-$ROOT_DIR/data/run}"
LOG_DIR="${XHS_MCP_LOG_DIR:-$ROOT_DIR/data/logs}"
PID_FILE="${XHS_MCP_PID_FILE:-$RUN_DIR/xhs-mcp.pid}"
LOG_FILE="${XHS_MCP_LOG_FILE:-$LOG_DIR/xhs-mcp.log}"

NPX_PACKAGE="${XHS_MCP_NPX_PACKAGE:-xhs-mcp@0.8.11}"
HOST="${XHS_MCP_HOST:-127.0.0.1}"
PORT="${XHS_MCP_PORT:-3000}"
LOGIN_TIMEOUT="${XHS_MCP_LOGIN_TIMEOUT:-120}"
LOGGING_FLAG="${XHS_ENABLE_LOGGING:-false}"
HEADLESS_FLAG="${XHS_HEADLESS:-true}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/xhs_mcp_ctl.sh <command> [args]

Commands:
  login         Open a visible browser for one-time QR login.
  start         Start xhs-mcp HTTP server in background (silent/headless by default).
  stop          Stop background xhs-mcp process.
  status        Show process, port and /health status.
  logs [lines]  Show recent logs (default: 80 lines).
EOF
}

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  if [[ -f "$PID_FILE" ]]; then
    tr -d '[:space:]' <"$PID_FILE" || true
  fi
}

port_listener_pid() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true
    return
  fi
  echo ""
}

health_check() {
  curl -fsS --max-time 3 "http://${HOST}:${PORT}/health"
}

login_cmd() {
  echo "Starting visible login with ${NPX_PACKAGE} (timeout=${LOGIN_TIMEOUT}s)..."
  (
    cd "$ROOT_DIR"
    XHS_HEADLESS=false \
      XHS_ENABLE_LOGGING="$LOGGING_FLAG" \
      npx -y "$NPX_PACKAGE" login --timeout "$LOGIN_TIMEOUT"
  )
}

start_cmd() {
  local existing_pid
  existing_pid="$(read_pid)"
  if is_pid_running "$existing_pid"; then
    echo "xhs-mcp already running (pid=${existing_pid})."
    status_cmd
    return 0
  fi

  local listener_pid
  listener_pid="$(port_listener_pid)"
  if [[ -n "$listener_pid" ]]; then
    echo "Port ${PORT} is already in use by pid=${listener_pid}. Please stop it first."
    return 1
  fi

  echo "Starting xhs-mcp in background: package=${NPX_PACKAGE}, host=${HOST}, port=${PORT}, headless=${HEADLESS_FLAG}"
  (
    cd "$ROOT_DIR"
    XHS_HEADLESS="$HEADLESS_FLAG" \
      XHS_ENABLE_LOGGING="$LOGGING_FLAG" \
      nohup npx -y "$NPX_PACKAGE" mcp --mode http --port "$PORT" >>"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
  )

  local pid
  pid="$(read_pid)"
  if ! is_pid_running "$pid"; then
    echo "Failed to start xhs-mcp. Check logs: $LOG_FILE"
    tail -n 40 "$LOG_FILE" 2>/dev/null || true
    return 1
  fi

  local health=""
  for _ in $(seq 1 20); do
    if health="$(health_check 2>/dev/null)"; then
      local listener_pid
      listener_pid="$(port_listener_pid)"
      if [[ -n "$listener_pid" ]]; then
        echo "$listener_pid" >"$PID_FILE"
        pid="$listener_pid"
      fi
      echo "xhs-mcp is healthy (pid=${pid})."
      echo "health: ${health}"
      return 0
    fi
    sleep 1
  done

  echo "xhs-mcp started (pid=${pid}), but /health check is not ready yet."
  echo "Use: bash scripts/xhs_mcp_ctl.sh logs"
}

stop_cmd() {
  local pid
  pid="$(read_pid)"
  if ! is_pid_running "$pid"; then
    rm -f "$PID_FILE"
    echo "xhs-mcp is not running."
    return 0
  fi

  echo "Stopping xhs-mcp (pid=${pid})..."
  kill "$pid" 2>/dev/null || true

  for _ in $(seq 1 20); do
    if ! is_pid_running "$pid"; then
      rm -f "$PID_FILE"
      echo "xhs-mcp stopped."
      return 0
    fi
    sleep 0.5
  done

  echo "Process still alive, sending SIGKILL to pid=${pid}."
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "xhs-mcp stopped."
}

status_cmd() {
  local pid
  pid="$(read_pid)"
  local listener_pid
  listener_pid="$(port_listener_pid)"

  echo "xhs-mcp config:"
  echo "  package: ${NPX_PACKAGE}"
  echo "  host:    ${HOST}"
  echo "  port:    ${PORT}"
  echo "  log:     ${LOG_FILE}"
  echo "  pidfile: ${PID_FILE}"
  echo "  headless:${HEADLESS_FLAG}"
  echo "  logging: ${LOGGING_FLAG}"

  if is_pid_running "$pid"; then
    echo "process: running (pid=${pid})"
  else
    echo "process: not running"
  fi

  if [[ -n "$listener_pid" ]]; then
    echo "port: listening (pid=${listener_pid})"
  else
    echo "port: not listening"
  fi

  local health=""
  if health="$(health_check 2>/dev/null)"; then
    echo "health: ok ${health}"
  else
    echo "health: unavailable"
  fi
}

logs_cmd() {
  local lines="${1:-80}"
  if [[ ! -f "$LOG_FILE" ]]; then
    echo "No log file found: $LOG_FILE"
    return 0
  fi
  tail -n "$lines" "$LOG_FILE"
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
  login)
    login_cmd
    ;;
  start)
    start_cmd
    ;;
  stop)
    stop_cmd
    ;;
  status)
    status_cmd
    ;;
  logs)
    logs_cmd "${2:-80}"
    ;;
  -h | --help | help | "")
    usage
    ;;
  *)
    echo "Unknown command: $cmd"
    usage
    return 1
    ;;
  esac
}

main "$@"
