#!/usr/bin/env bash
# Build the Python bridge binary for Tauri externalBin.
# Run from anywhere; the script locates the repo root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$DESKTOP_ROOT/.." && pwd)"
BINARIES_DIR="$DESKTOP_ROOT/src-tauri/binaries"

TARGET_TRIPLE="$(rustc --print host-tuple 2>/dev/null || true)"
if [[ -z "$TARGET_TRIPLE" ]]; then
  MACHINE="$(uname -m)"
  if [[ "$MACHINE" == "arm64" || "$MACHINE" == "aarch64" ]]; then
    TARGET_TRIPLE="aarch64-apple-darwin"
  else
    TARGET_TRIPLE="x86_64-apple-darwin"
  fi
fi

BRIDGE_NAME="mph-agent-bridge-${TARGET_TRIPLE}"
DIST_BIN="$PROJECT_ROOT/dist/mph-agent-bridge"
DEST_BIN="$BINARIES_DIR/$BRIDGE_NAME"

echo "Building Python bridge with PyInstaller..."
cd "$PROJECT_ROOT"

if command -v uv >/dev/null 2>&1; then
  echo "Using project env (uv run)..."
  uv pip install pyinstaller --quiet || true
  uv run python -m PyInstaller desktop/scripts/bridge.spec --noconfirm
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
  "$PYTHON_BIN" -m pip install pyinstaller --quiet
  "$PYTHON_BIN" -m PyInstaller desktop/scripts/bridge.spec --noconfirm
fi

if [[ ! -f "$DIST_BIN" ]]; then
  echo "PyInstaller did not produce: $DIST_BIN" >&2
  exit 1
fi

mkdir -p "$BINARIES_DIR"
cp "$DIST_BIN" "$DEST_BIN"
chmod +x "$DEST_BIN"
echo "Bridge built: $DEST_BIN"
