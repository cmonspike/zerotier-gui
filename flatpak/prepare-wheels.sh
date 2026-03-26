#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHEEL_DIR="$ROOT_DIR/flatpak/wheels"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$WHEEL_DIR"
rm -f "$WHEEL_DIR"/*.whl

# Prefer local virtualenv pip when available.
if [ -x "$ROOT_DIR/.venv/bin/pip" ]; then
  PIP_CMD=("$ROOT_DIR/.venv/bin/pip")
else
  PIP_CMD=("$PYTHON_BIN" -m pip)
fi

# Base deps (abi3 / pure-python wheels).
"${PIP_CMD[@]}" download --dest "$WHEEL_DIR" \
  pyqt6==6.10.2 \
  pyqt6-qt6==6.10.2 \
  requests==2.33.0 \
  idna==3.11 \
  urllib3==2.6.3 \
  certifi==2026.2.25

# Runtime-specific wheels for Flatpak's Python 3.11.
"${PIP_CMD[@]}" download --dest "$WHEEL_DIR" \
  --only-binary=:all: \
  --python-version 311 \
  --implementation cp \
  --abi cp311 \
  --platform manylinux1_x86_64 \
  pyqt6-sip==13.11.1

"${PIP_CMD[@]}" download --dest "$WHEEL_DIR" \
  --only-binary=:all: \
  --python-version 311 \
  --implementation cp \
  --abi cp311 \
  --platform manylinux2014_x86_64 \
  charset-normalizer==3.4.6

echo "Prepared wheels in: $WHEEL_DIR"
