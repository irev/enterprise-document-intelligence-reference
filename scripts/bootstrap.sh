#!/usr/bin/env bash
# One-shot environment bootstrap for Linux/macOS.
# Creates .venv with Python 3.12+ and installs development dependencies.
# Windows equivalent: scripts\bootstrap.ps1
#
# Usage:
#   scripts/bootstrap.sh                     # create/update .venv + install deps
#   scripts/bootstrap.sh --check             # also run pytest and edi doctor
#   scripts/bootstrap.sh --force             # recreate .venv from scratch
#   scripts/bootstrap.sh --python /path/to/python3.12
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV=".venv"
CHECK=0
FORCE=0
PYTHON_ARG=""

usage() {
    cat <<'EOF'
Usage: scripts/bootstrap.sh [options]

  --check             Run `python -m pytest` and `edi doctor` after install.
  --force             Recreate .venv even if a valid one exists.
  --python PATH       Interpreter to use (must be Python >= 3.12).
  -h, --help          Show this help.

Environment: EDI_PYTHON is used as the interpreter when --python is absent.
Exit codes: 0 success, 2 interpreter/usage error, 1 install or check failure.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --check) CHECK=1 ;;
        --force) FORCE=1 ;;
        --python)
            if [ $# -lt 2 ]; then
                echo "bootstrap.sh: --python requires a path" >&2
                exit 2
            fi
            PYTHON_ARG="$2"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "bootstrap.sh: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

is_py312() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
        >/dev/null 2>&1
}

die_no_interpreter() {
    cat >&2 <<'EOF'
bootstrap.sh: no Python >= 3.12 interpreter found.
Install one, then re-run:
  Debian/Ubuntu:  sudo apt install python3.12 python3.12-venv
  Fedora:         sudo dnf install python3.12
  macOS:          brew install python@3.12
Or point at an existing interpreter:
  scripts/bootstrap.sh --python /path/to/python3.12
  EDI_PYTHON=/path/to/python3.12 scripts/bootstrap.sh
EOF
    exit 2
}

find_python() {
    local cand
    for cand in "$PYTHON_ARG" "${EDI_PYTHON:-}" python3.12 python3 python; do
        [ -n "$cand" ] || continue
        command -v "$cand" >/dev/null 2>&1 || {
            if [ "$cand" = "$PYTHON_ARG" ] || [ "$cand" = "${EDI_PYTHON:-}" ]; then
                echo "bootstrap.sh: interpreter not found: $cand" >&2
                exit 2
            fi
            continue
        }
        if is_py312 "$cand"; then
            printf '%s\n' "$cand"
            return 0
        fi
        if [ "$cand" = "$PYTHON_ARG" ] || [ "$cand" = "${EDI_PYTHON:-}" ]; then
            echo "bootstrap.sh: interpreter is older than Python 3.12: $cand" >&2
            exit 2
        fi
    done
    die_no_interpreter
}

venv_ok() {
    [ -f "$VENV/pyvenv.cfg" ] && [ -x "$VENV/bin/python" ] &&
        "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
            >/dev/null 2>&1
}

PYTHON="$(find_python)"

if [ "$FORCE" -eq 1 ]; then
    echo "bootstrap.sh: --force, recreating $VENV"
    rm -rf "$VENV"
elif [ -e "$VENV" ] && ! venv_ok; then
    echo "bootstrap.sh: existing $VENV is invalid or broken, recreating it"
    rm -rf "$VENV"
fi

if [ ! -e "$VENV" ]; then
    echo "bootstrap.sh: creating $VENV with $PYTHON ($("$PYTHON" -V 2>&1))"
    "$PYTHON" -m venv "$VENV"
else
    echo "bootstrap.sh: reusing existing $VENV"
fi

echo "bootstrap.sh: installing development dependencies"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r requirements-dev.txt

if [ "$CHECK" -eq 1 ]; then
    echo "bootstrap.sh: running test suite"
    "$VENV/bin/python" -m pytest -q
    echo "bootstrap.sh: host probe"
    "$VENV/bin/edi" doctor
fi

cat <<'EOF'
bootstrap.sh: done.
Next steps:
  source .venv/bin/activate     # or call .venv/bin/edi directly
  edi doctor
  edi config --wizard           # optional one-time defaults
EOF
