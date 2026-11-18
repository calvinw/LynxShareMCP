# Set up LYNX SHARE + the lynx-share MCP server

Instructions for an AI coding agent (Claude Code or Codex). Goal: install the LYNX SHARE DAW and the `lynx-share`
MCP server, so the agent can make music in LYNX SHARE. Work through the steps in order and report what you did.

- LYNX SHARE (the DAW): https://github.com/Ka1-S/LYNX-SHARE (releases: https://github.com/Ka1-S/LYNX-SHARE/releases)
- lynx-share MCP server: https://github.com/calvinw/LynxShareMCP (v0.2.0 or later)

Requirements: macOS or Linux, Git, Python 3.10+. Check them first (`git --version`, `python3 --version`) and tell the
user if one is missing.

## 1. Install LYNX SHARE (official release, no build needed)

Skip this step if `/Applications/LYNX.app` already exists and is version 0.1.28 or later.

All LYNX SHARE releases are marked pre-release, so GitHub's "latest" link does not find them; take the newest from
the releases list:

### macOS

```sh
DMG_URL=$(curl -s "https://api.github.com/repos/Ka1-S/LYNX-SHARE/releases?per_page=1" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)[0]; print(next(a["browser_download_url"] for a in r["assets"] if a["name"].endswith("macos-universal.dmg")))')
echo "$DMG_URL"
TMP=$(mktemp -d) && curl -L -o "$TMP/LYNX.dmg" "$DMG_URL"
hdiutil attach -nobrowse -readonly -mountpoint "$TMP/mnt" "$TMP/LYNX.dmg"
cp -R "$TMP/mnt/LYNX.app" /Applications/
hdiutil detach "$TMP/mnt"
xattr -dr com.apple.quarantine /Applications/LYNX.app
```

The app is not notarized by Apple (it is free software without an Apple Developer ID), which is why the last line
removes the quarantine flag. If that command is not allowed, ask the user to open LYNX once by Control-clicking it in
Applications and choosing Open (on macOS 15+: try to open it, then System Settings > Privacy & Security > Open Anyway).

The binary the MCP server needs is `/Applications/LYNX.app/Contents/MacOS/LYNX`.

### Linux

Download the newest `LYNX-<version>-x86_64.AppImage` the same way (match `x86_64.AppImage` instead of
`macos-universal.dmg`), put it at `~/Applications/LYNX.AppImage`, and `chmod +x` it. That file is the binary.

## 2. Install the MCP server

```sh
mkdir -p ~/develop && cd ~/develop
git clone https://github.com/calvinw/LynxShareMCP.git   # or `git pull` inside it if it already exists
cd LynxShareMCP
./install.sh                                            # macOS: finds /Applications/LYNX.app by itself
# Linux:  ./install.sh --lynx ~/Applications/LYNX.AppImage
```

`install.sh` makes a `.venv`, installs the server, and registers it as `lynx-share` (user scope) with Claude Code
and/or Codex, whichever is installed. Use `--claude` or `--codex` to pick only one. Check that it printed the right
LYNX path and that registration succeeded:

```sh
claude mcp list      # should list lynx-share
```

## 3. Finish

Tell the user to **restart Claude Code / Codex** so the `lynx-share` tools load. After the restart they can ask, for
example:

> Launch LYNX SHARE and make a 4-bar lo-fi beat at 85 BPM, then play it

`lynx_launch` opens LYNX with Remote Control on. If they open LYNX themselves instead, they turn on
**Settings > General > Remote control**.

Good to know, on an official release:
- The agent cannot save, pause, start a new project, play from a position or open the piano roll; those tools say
  so. Save with Cmd+S (Ctrl+S on Linux).
- Edits are refused while LYNX is playing; stop first.
- Every edit is one undo step (Cmd+Z).

## Troubleshooting

- **"Remote Control is not on"**: call `lynx_launch`, or turn on Settings > General > Remote control.
- **install.sh: "no LYNX SHARE binary found"**: rerun with `./install.sh --lynx /path/to/LYNX`.
- **macOS says LYNX "cannot be opened"**: quarantine flag; see step 1.
- More: https://github.com/calvinw/LynxShareMCP#troubleshooting
