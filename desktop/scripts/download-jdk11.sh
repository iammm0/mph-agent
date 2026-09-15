#!/usr/bin/env bash
# Download Adoptium JDK 11 for the current macOS/Linux arch into
# src-tauri/resources/runtime/java so Tauri can bundle it.
# Run from the desktop directory: bash scripts/download-jdk11.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$DESKTOP_ROOT/src-tauri/resources/runtime/java"

OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
MACHINE="$(uname -m)"
if [[ "$OS_NAME" == "darwin" ]]; then
  ADOPTIUM_OS="mac"
else
  ADOPTIUM_OS="linux"
fi
if [[ "$MACHINE" == "arm64" || "$MACHINE" == "aarch64" ]]; then
  ADOPTIUM_ARCH="aarch64"
else
  ADOPTIUM_ARCH="x64"
fi

if [[ -x "$TARGET_DIR/bin/java" ]]; then
  echo "JDK 11 already present at $TARGET_DIR, skip download."
  exit 0
fi

URL="https://api.adoptium.net/v3/binary/latest/11/ga/${ADOPTIUM_OS}/${ADOPTIUM_ARCH}/jdk/hotspot/normal/eclipse?project=jdk&archive_type=tar.gz"
TMP_TGZ="$(mktemp -t mph-agent-jdk11.XXXXXX).tar.gz"
TMP_EXTRACT="$(mktemp -d -t mph-agent-jdk11-extract.XXXXXX)"

cleanup() {
  rm -f "$TMP_TGZ"
  rm -rf "$TMP_EXTRACT"
}
trap cleanup EXIT

echo "Downloading JDK 11 from Adoptium (${ADOPTIUM_OS}/${ADOPTIUM_ARCH})..."
curl -fsSL -A "mph-agent" -o "$TMP_TGZ" "$URL"

echo "Extracting..."
tar -xzf "$TMP_TGZ" -C "$TMP_EXTRACT"
TOP_LEVEL=""
for dir in "$TMP_EXTRACT"/*; do
  if [[ -d "$dir" ]]; then
    TOP_LEVEL="$dir"
    break
  fi
done
if [[ -z "$TOP_LEVEL" ]]; then
  echo "Unexpected archive structure: expected one top-level directory." >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
shopt -s dotglob
for item in "$TOP_LEVEL"/*; do
  name="$(basename "$item")"
  rm -rf "$TARGET_DIR/$name"
  mv "$item" "$TARGET_DIR/$name"
done
shopt -u dotglob

if [[ ! -x "$TARGET_DIR/bin/java" ]]; then
  echo "After extract, bin/java not found under $TARGET_DIR" >&2
  exit 1
fi

echo "JDK 11 ready at $TARGET_DIR"
