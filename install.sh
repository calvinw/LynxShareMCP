#!/usr/bin/env bash
# Installs lynx-share-mcp into .venv and registers it with Claude Code.
# Usage: ./install.sh [path/to/LYNX]
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "$(uname)" = Darwin ]; then
  DEFAULT_BIN="$HOME/develop/LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX"
else
  DEFAULT_BIN="$HOME/develop/LYNX-SHARE/build/LYNX_artefacts/Release/LYNX"
fi
BIN="${1:-${LYNX_BIN:-$DEFAULT_BIN}}"
[ -x "$BIN" ] || echo "Warning: LYNX binary not found at $BIN (lynx_launch needs it; build LYNX-SHARE or pass the path)."

PYTHON="$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10+ needed"; exit 1; }

echo "Setting up .venv with $PYTHON..."
"$PYTHON" -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -e "$DIR[test]"
echo "  ✓ lynx-share-mcp installed"

if command -v claude >/dev/null; then
  claude mcp remove --scope user lynx-share 2>/dev/null || true
  claude mcp add --scope user --transport stdio lynx-share -e "LYNX_BIN=$BIN" -- "$DIR/.venv/bin/python" -m lynx_share_mcp
  echo "  ✓ registered with Claude Code as 'lynx-share'"
else
  echo "Claude Code not found. Register it yourself:"
  echo "  claude mcp add --scope user --transport stdio lynx-share -e LYNX_BIN=$BIN -- $DIR/.venv/bin/python -m lynx_share_mcp"
fi

echo
echo "Start LYNX with:  $BIN [/abs/path/project.lynx] --control /tmp/lynx.sock   (project first)"
echo "(or ask Claude to call lynx_launch)."
