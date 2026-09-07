#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This bootstrap script targets macOS."
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required."
  exit 1
fi

brew install rust pkg-config meson ninja

echo "WebRTC APM build tools ready."
echo "Run: uv run python scripts/check_webrtc_apm.py"
