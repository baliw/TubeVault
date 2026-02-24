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

# Load Anthropic API key from credentials file
CREDENTIALS="$SCRIPT_DIR/credentials"
if [ -f "$CREDENTIALS" ]; then
  export ANTHROPIC_API_KEY="$(tr -d '[:space:]' < "$CREDENTIALS")"
else
  echo "Warning: credentials file not found at $CREDENTIALS" >&2
fi

# Run TubeVault, passing through any CLI arguments
exec "$VENV_DIR/bin/python" -m tubevault "$@"
