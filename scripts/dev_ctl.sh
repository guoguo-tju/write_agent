#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT_DIR/data"

BACKEND_PID_FILE="$DATA_DIR/backend-dev.pid"
FRONTEND_PID_FILE="$DATA_DIR/frontend-dev.pid"
BACKEND_LOG_FILE="$DATA_DIR/backend-dev.log"
FRONTEND_LOG_FILE="$DATA_DIR/frontend-dev.log"

BACKEND_URL="http://127.0.0.1:8000/"
FRONTEND_URL="http://127.0.0.1:5173/"

BACKEND_START_CMD=(
  env
  PYTHONPATH=src
  DATABASE_URL=sqlite:///./data/acceptance_write_agent.db
  .venv/bin/uvicorn
  write_agent.main:app
  --host
  127.0.0.1
  --port
  8000
)
FRONTEND_START_CMD=(npm run dev -- --host 127.0.0.1 --port 5173)

mkdir -p "$DATA_DIR"

usage() {
  cat <<'EOF'
Usage: bash scripts/dev_ctl.sh <command>

Commands:
  start            Start backend + frontend.
  stop             Stop backend + frontend.
  restart          Restart backend + frontend.
  status           Show process/port/url health status.
  logs backend     Show backend logs (last 120 lines).
  logs frontend    Show frontend logs (last 120 lines).
  logs all         Show both logs (last 120 lines each).
EOF
}

read_pid() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi
  local pid
  pid="$(tr -d '[:space:]' < "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" || ! "$pid" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  echo "$pid"
}

is_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

port_listener_pid() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n1
}

port_listener_pids() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | awk 'NF' | sort -u
}

pid_list_to_inline() {
  local pids="$1"
  if [[ -z "$pids" ]]; then
    echo "none"
    return 0
  fi
  echo "$pids" | tr '\n' ',' | sed 's/,$//'
}

kill_pid_gracefully() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  if ! is_alive "$pid"; then
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! is_alive "$pid"; then
      return 0
    fi
    sleep 0.2
  done
  kill -9 "$pid" 2>/dev/null || true
}

kill_listener_port() {
  local port="$1"
  local killed="no"
  local pids
  pids="$(port_listener_pids "$port" || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    kill_pid_gracefully "$pid"
    killed="yes"
  done <<< "$pids"
  if [[ "$killed" == "yes" ]]; then
    sleep 0.3
  fi
}

wait_http_ready() {
  local url="$1"
  local retries="$2"
  local i=0
  while (( i < retries )); do
    if curl -fsS --max-time 1 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

start_backend() {
  local existing_pid
  existing_pid="$(read_pid "$BACKEND_PID_FILE" || true)"
  if [[ -n "$existing_pid" ]] && is_alive "$existing_pid"; then
    echo "Backend already running (pid=$existing_pid)."
    return 0
  fi

  if [[ -n "$existing_pid" ]]; then
    rm -f "$BACKEND_PID_FILE"
  fi

  local listener_pid
  listener_pid="$(port_listener_pid 8000 || true)"
  if [[ -n "$listener_pid" ]]; then
    if wait_http_ready "$BACKEND_URL" 2; then
      echo "$listener_pid" > "$BACKEND_PID_FILE"
      echo "Backend already running (adopted pid=$listener_pid)."
      return 0
    fi
    echo "Backend port 8000 is occupied by stale pid=$listener_pid. Cleaning up..."
    kill_listener_port 8000
  fi

  (
    cd "$ROOT_DIR"
    nohup "${BACKEND_START_CMD[@]}" < /dev/null > "$BACKEND_LOG_FILE" 2>&1 &
  )

  if ! wait_http_ready "$BACKEND_URL" 30; then
    echo "Backend started, but health check is not ready."
    echo "Check log: $BACKEND_LOG_FILE"
    return 1
  fi

  local pid
  pid="$(port_listener_pid 8000 || true)"
  if [[ -z "$pid" ]]; then
    echo "Backend health check passed, but listener pid is missing."
    return 1
  fi
  echo "$pid" > "$BACKEND_PID_FILE"
  echo "Backend started (pid=$pid)."
}

start_frontend() {
  local existing_pid
  existing_pid="$(read_pid "$FRONTEND_PID_FILE" || true)"
  if [[ -n "$existing_pid" ]] && is_alive "$existing_pid"; then
    echo "Frontend already running (pid=$existing_pid)."
    return 0
  fi

  if [[ -n "$existing_pid" ]]; then
    rm -f "$FRONTEND_PID_FILE"
  fi

  local listener_pid
  listener_pid="$(port_listener_pid 5173 || true)"
  if [[ -n "$listener_pid" ]]; then
    if wait_http_ready "$FRONTEND_URL" 2; then
      echo "$listener_pid" > "$FRONTEND_PID_FILE"
      echo "Frontend already running (adopted pid=$listener_pid)."
      return 0
    fi
    echo "Frontend port 5173 is occupied by stale pid=$listener_pid. Cleaning up..."
    kill_listener_port 5173
  fi

  (
    cd "$ROOT_DIR/frontend"
    nohup "${FRONTEND_START_CMD[@]}" < /dev/null > "$FRONTEND_LOG_FILE" 2>&1 &
  )

  if ! wait_http_ready "$FRONTEND_URL" 30; then
    echo "Frontend started, but URL check is not ready."
    echo "Check log: $FRONTEND_LOG_FILE"
    return 1
  fi

  local pid
  pid="$(port_listener_pid 5173 || true)"
  if [[ -z "$pid" ]]; then
    echo "Frontend URL check passed, but listener pid is missing."
    return 1
  fi
  echo "$pid" > "$FRONTEND_PID_FILE"
  echo "Frontend started (pid=$pid)."
}

stop_component() {
  local name="$1"
  local pid_file="$2"
  local port="$3"

  local pid
  pid="$(read_pid "$pid_file" || true)"
  if [[ -n "$pid" ]] && is_alive "$pid"; then
    kill_pid_gracefully "$pid"
    echo "$name stopped (pid=$pid)."
  else
    echo "$name is not running via pid file."
  fi
  rm -f "$pid_file"

  local listener_pids
  listener_pids="$(port_listener_pids "$port" || true)"
  if [[ -n "$listener_pids" ]]; then
    echo "Cleaning remaining listeners on port $port: $(pid_list_to_inline "$listener_pids")"
    kill_listener_port "$port"
    listener_pids="$(port_listener_pids "$port" || true)"
    if [[ -n "$listener_pids" ]]; then
      echo "Note: port $port still occupied by pid=$(pid_list_to_inline "$listener_pids")."
    fi
  fi
}

status_component() {
  local name="$1"
  local pid_file="$2"
  local port="$3"
  local url="$4"
  local pid
  local listener_pid
  local listener_pids
  local alive="no"
  local healthy="no"

  pid="$(read_pid "$pid_file" || true)"
  if [[ -n "$pid" ]] && is_alive "$pid"; then
    alive="yes"
  fi

  listener_pid="$(port_listener_pid "$port" || true)"
  listener_pids="$(port_listener_pids "$port" || true)"
  if curl -fsS --max-time 1 "$url" >/dev/null 2>&1; then
    healthy="yes"
  fi

  echo "$name:"
  echo "  pid_file: ${pid_file}"
  echo "  pid: ${pid:-none}"
  echo "  process_alive: $alive"
  echo "  port_${port}_listener: ${listener_pid:-none}"
  echo "  port_${port}_listeners: $(pid_list_to_inline "$listener_pids")"
  echo "  url_ok: $healthy"
}

logs_cmd() {
  local target="${1:-all}"
  local lines="${2:-120}"
  case "$target" in
    backend)
      echo "=== backend log: $BACKEND_LOG_FILE ==="
      tail -n "$lines" "$BACKEND_LOG_FILE" 2>/dev/null || echo "(no backend log)"
      ;;
    frontend)
      echo "=== frontend log: $FRONTEND_LOG_FILE ==="
      tail -n "$lines" "$FRONTEND_LOG_FILE" 2>/dev/null || echo "(no frontend log)"
      ;;
    all)
      logs_cmd backend "$lines"
      echo
      logs_cmd frontend "$lines"
      ;;
    *)
      echo "Unknown logs target: $target"
      usage
      return 1
      ;;
  esac
}

start_all() {
  start_backend
  start_frontend
  echo
  status_all
}

stop_all() {
  stop_component "Frontend" "$FRONTEND_PID_FILE" 5173
  stop_component "Backend" "$BACKEND_PID_FILE" 8000
}

status_all() {
  status_component "Backend" "$BACKEND_PID_FILE" 8000 "$BACKEND_URL"
  echo
  status_component "Frontend" "$FRONTEND_PID_FILE" 5173 "$FRONTEND_URL"
}

command="${1:-}"
case "$command" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  logs)
    logs_cmd "${2:-all}" "${3:-120}"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unknown command: $command"
    usage
    exit 1
    ;;
esac
