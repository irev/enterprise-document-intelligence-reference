#!/usr/bin/env bash
# Run the deterministic test suite inside Docker (works on WSL/Linux hosts).
#
# Usage:
#   scripts/test-docker.sh                      # python -m pytest
#   scripts/test-docker.sh python -m ruff check src tests
#   scripts/test-docker.sh python -m mypy src/edi_reference
#
# From Windows via WSL:
#   wsl -d Ubuntu-22.04 -- bash /mnt/<drive>/repo/<repo>/scripts/test-docker.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

IMAGE="${EDI_TEST_IMAGE:-edi-reference-test}"

docker build -t "$IMAGE" .
if [ "$#" -gt 0 ]; then
    docker run --rm "$IMAGE" "$@"
else
    docker run --rm "$IMAGE"
fi
