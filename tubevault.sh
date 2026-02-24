#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# Install/upgrade requirements if requirements.txt is newer than the venv marker
MARKER="$VENV_DIR/.requirements_installed"
if [ ! -f "$MARKER" ] || [ "$SCRIPT_DIR/requirements.txt" -nt "$MARKER" ]; then
  echo "Installing requirements..."
  "$VENV_DIR/bin/pip" install --quiet --upgrade pip
  "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
  touch "$MARKER"
fi

# Install deno if not present (required by yt-dlp for YouTube JS challenge solving)
if ! command -v deno &>/dev/null; then
  echo "Installing deno..."
  if command -v brew &>/dev/null; then
    brew install deno
  else
    curl -fsSL https://deno.land/install.sh | sh
    export DENO_INSTALL="$HOME/.deno"
    export PATH="$DENO_INSTALL/bin:$PATH"
  fi
fi

# Load Anthropic API key from credentials file
CREDENTIALS="$SCRIPT_DIR/credentials"
if [ -f "$CREDENTIALS" ]; then
  export ANTHROPIC_API_KEY="$(tr -d '[:space:]' < "$CREDENTIALS")"
else
  echo "Warning: credentials file not found at $CREDENTIALS" >&2
fi

# Run TubeVault, passing through any CLI arguments
exec "$VENV_DIR/bin/python" -m tubevault "$@"
