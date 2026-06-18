#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"
STAMP_DIR="$VENV/.install-stamps"
MODE="${1:-crash}"

require_python() {
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: $PYTHON not found (need Python 3.11+)" >&2
    exit 1
  fi

  "$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(
        f"error: Python 3.11+ required (found {sys.version.split()[0]})"
    )
PY
}

setup_venv() {
  if [[ ! -x "$VENV/bin/python" ]]; then
    echo "Creating virtual environment in .venv"
    "$PYTHON" -m venv --clear "$VENV"
  fi

  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
}

configure_imports() {
  export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
}

require_pytest() {
  if ! python -m pytest --version >/dev/null 2>&1; then
    echo "Installing test dependencies in .venv"
    python -m pip install -q -e ".[dev]"
  fi
}

install_if_stale() {
  local stamp="$STAMP_DIR/dev"
  mkdir -p "$STAMP_DIR"
  if [[ ! -f "$stamp" || "$ROOT/pyproject.toml" -nt "$stamp" ]]; then
    echo "Updating test dependencies in .venv"
    python -m pip install -q -e ".[dev]"
    touch "$stamp"
  fi
}

run_demo() {
  case "$MODE" in
    crash)
      python "$ROOT/examples/crash_resume_demo.py"
      ;;
    inbox)
      python "$ROOT/examples/inbox_triage_demo.py"
      ;;
    readiness)
      python "$ROOT/examples/readiness_demo.py"
      ;;
    mcp)
      python "$ROOT/examples/mcp_demo.py"
      ;;
    test | tests)
      require_pytest
      install_if_stale
      python -m pytest "$ROOT/tests/" -v
      ;;
    help | -h | --help)
      cat <<'EOF'
Usage: ./start.sh [command]

Commands:
  crash   Run crash recovery demo (default)
  inbox   Run full inbox triage demo with interactive approval
  readiness Run agent readiness before/after report
  mcp     Run gated write demo over the mock legacy CRM server
  test    Run the test suite
  help    Show this message

Environment:
  PYTHON  Python interpreter to use (default: python3)
EOF
      ;;
    *)
      echo "error: unknown command '$MODE' (try: ./start.sh help)" >&2
      exit 1
      ;;
  esac
}

require_python
setup_venv
configure_imports
run_demo
