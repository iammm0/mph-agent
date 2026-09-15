#!/usr/bin/env bash
# One-click macOS Apple Silicon installer build:
# - Python bridge (PyInstaller)
# - Bundled Java 11
# - Tauri DMG
#
# Run from the repo root:
#   bash scripts/build-installer.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script builds the macOS installer. On Windows use scripts/build-installer.ps1." >&2
  exit 1
fi

echo "========================================"
echo "  mph-agent installer build (macOS)"
echo "========================================"

echo "[1/3] Build bridge (PyInstaller)..."
bash "$PROJECT_ROOT/desktop/scripts/build-bridge.sh"

echo "[2/3] Prepare bundled Java 11..."
bash "$PROJECT_ROOT/desktop/scripts/download-jdk11.sh"

echo "[3/3] Build desktop app & DMG (Tauri)..."
cd "$PROJECT_ROOT/desktop"
npm run tauri -- build --bundles dmg

BUNDLE_DIR="$PROJECT_ROOT/desktop/src-tauri/target/release/bundle"
echo
echo "Build done"
echo "Installer output: $BUNDLE_DIR"
if [[ -d "$BUNDLE_DIR" ]]; then
  find "$BUNDLE_DIR" -type f \( -name "*.dmg" -o -name "*.app" \) -print
fi
echo
echo "Installer contains:"
echo "  - Python bridge (mph-agent-bridge)"
echo "  - Desktop app (Tauri + React)"
echo "  - Bundled Java 11 runtime"
