#!/usr/bin/env bash
# Installs lynx-share-mcp into .venv and registers it with Claude Code and/or Codex.
#
# Usage: ./install.sh [--claude] [--codex] [--lynx /path/to/LYNX]
#   --claude, --codex   register with only these clients (default: every one that is installed)
#   --lynx PATH         the LYNX SHARE binary built from the control-socket branch
#                       (default: $LYNX_BIN, else a LYNX-SHARE clone next to this folder or in ~/develop)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
NAME="lynx-share"
WANT_CLAUDE=0 WANT_CODEX=0 BIN="${LYNX_BIN:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --claude) WANT_CLAUDE=1 ;;
    --codex)  WANT_CODEX=1 ;;
    --lynx)   shift; BIN="${1:?--lynx needs a path}" ;;
    -h|--help) sed -n 2,7p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)"; exit 1 ;;
  esac
  shift
done
if [ $WANT_CLAUDE = 0 ] && [ $WANT_CODEX = 0 ]; then
  command -v claude >/dev/null && WANT_CLAUDE=1
  command -v codex  >/dev/null && WANT_CODEX=1
fi

# ---- find LYNX SHARE ------------------------------------------------------------------------------------------
if [ "$(uname)" = Darwin ]; then REL="build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX"
else REL="build/LYNX_artefacts/Release/LYNX"; fi
if [ -z "$BIN" ]; then
  for root in "$DIR/../LYNX-SHARE" "$HOME/develop/LYNX-SHARE"; do
    if [ -x "$root/$REL" ]; then BIN="$(cd "$root" && pwd)/$REL"; break; fi
  done
fi
if [ -n "$BIN" ] && [ -x "$BIN" ]; then
  echo "LYNX SHARE: $BIN"
else
  echo "Warning: no LYNX SHARE binary found${BIN:+ at $BIN}."
  echo "  Build the control-socket branch of https://github.com/calvinw/LYNX-SHARE (see README.md),"
  echo "  then run ./install.sh --lynx /path/to/LYNX again. lynx_launch will not work until then."
  BIN="${BIN:-$DIR/../LYNX-SHARE/$REL}"
fi

# ---- Python environment ---------------------------------------------------------------------------------------
PYTHON="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3 || true)"
[ -n "$PYTHON" ] && "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10+ is needed"; exit 1; }
echo "Setting up .venv with $PYTHON..."
"$PYTHON" -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -e "$DIR[test]"
echo "  ✓ lynx-share-mcp installed"
PY="$DIR/.venv/bin/python"

# ---- register -------------------------------------------------------------------------------------------------
if [ $WANT_CLAUDE = 1 ]; then
  if command -v claude >/dev/null; then
    claude mcp remove --scope user "$NAME" >/dev/null 2>&1 || true
    if claude mcp add --scope user --transport stdio "$NAME" -e "LYNX_BIN=$BIN" -- "$PY" -m lynx_share_mcp; then
      echo "  ✓ registered with Claude Code as '$NAME' (all projects)"
    else
      echo "  ✗ Claude Code registration failed; run this yourself:"
      echo "    claude mcp add --scope user --transport stdio $NAME -e LYNX_BIN=$BIN -- $PY -m lynx_share_mcp"
    fi
  else
    echo "  Claude Code not found; to register later:"
    echo "    claude mcp add --scope user --transport stdio $NAME -e LYNX_BIN=$BIN -- $PY -m lynx_share_mcp"
  fi
fi
if [ $WANT_CODEX = 1 ]; then
  if command -v codex >/dev/null; then
    codex mcp remove "$NAME" >/dev/null 2>&1 || true
    if codex mcp add "$NAME" --env "LYNX_BIN=$BIN" -- "$PY" -m lynx_share_mcp; then
      echo "  ✓ registered with Codex as '$NAME'"
    else
      echo "  ✗ Codex registration failed; run this yourself:"
      echo "    codex mcp add $NAME --env LYNX_BIN=$BIN -- $PY -m lynx_share_mcp"
    fi
  else
    echo "  Codex not found; to register later:"
    echo "    codex mcp add $NAME --env LYNX_BIN=$BIN -- $PY -m lynx_share_mcp"
  fi
fi
if [ $WANT_CLAUDE = 0 ] && [ $WANT_CODEX = 0 ]; then
  echo "Neither Claude Code nor Codex was found. Register the server in your MCP client as:"
  echo "  command: $PY   args: -m lynx_share_mcp   env: LYNX_BIN=$BIN"
fi

echo
echo "Restart your client, then ask it to launch LYNX SHARE (the lynx_launch tool)."
