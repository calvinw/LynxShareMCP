# lynx-share-mcp

An MCP server that lets an AI coding agent (Claude Code or Codex) make music in
[LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE), the open-source FL Studio-style DAW, while you watch: it reads the
project, adds channels (built-in instruments or plugins such as Serum 2), writes notes, builds patterns and the
playlist, plays, undoes and saves. Every edit is one undo step in the app, so you can take back anything with Cmd+Z.

> **Needs a LYNX SHARE build with a control socket.** Official LYNX SHARE releases cannot be controlled from outside.
> The `control-socket` branch of [calvinw/LYNX-SHARE](https://github.com/calvinw/LYNX-SHARE/tree/control-socket) adds
> a small local socket (`--control`) and nothing else; it is kept up to date by merging upstream. If LYNX SHARE ships an official
> control API, this server will move to it.

## Requirements

- macOS or Linux (the socket is a Unix socket; no Windows yet)
- Python 3.10+
- To build LYNX SHARE: CMake 3.22+, a C++20 compiler (Xcode command line tools on macOS) and Git. On Linux, LYNX
  SHARE's build dependencies first; see its README.
- Claude Code and/or Codex

## Install

Clone both repos side by side, build LYNX SHARE, then run the installer:

```sh
mkdir -p ~/develop && cd ~/develop
git clone --depth 1 -b control-socket https://github.com/calvinw/LYNX-SHARE.git   # --depth 1: skip upstream's long history
git clone https://github.com/calvinw/LynxShareMCP.git

cd LYNX-SHARE
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target LYNX -j        # the first build takes a while

cd ../LynxShareMCP
./install.sh
```

`install.sh` creates `.venv`, finds the LYNX binary (a `LYNX-SHARE` clone next to this folder or in `~/develop`), and
registers the server as `lynx-share` with every client it finds:

```sh
./install.sh                    # Claude Code and Codex, whichever are installed
./install.sh --claude           # only Claude Code (user scope: all your projects)
./install.sh --codex            # only Codex (~/.codex/config.toml)
./install.sh --lynx /path/to/LYNX
```

Restart the client afterwards so it loads the tools. Run `./install.sh` again after moving either folder.

**Or let your agent do it.** Paste this into Claude Code or Codex, then restart it when it is done:

> Clone github.com/calvinw/LYNX-SHARE (control-socket branch, --depth 1) and github.com/calvinw/LynxShareMCP side by side in
> ~/develop, build LYNX SHARE following LynxShareMCP's README, and run ./install.sh.

### Registering by hand

```sh
claude mcp add --scope user --transport stdio lynx-share \
  -e LYNX_BIN=/path/to/LYNX -- /path/to/LynxShareMCP/.venv/bin/python -m lynx_share_mcp

codex mcp add lynx-share --env LYNX_BIN=/path/to/LYNX -- /path/to/LynxShareMCP/.venv/bin/python -m lynx_share_mcp
```

On macOS the binary is inside the app bundle: `LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX`.
On Linux it is `LYNX-SHARE/build/LYNX_artefacts/Release/LYNX`.

## Use

Ask the agent to start LYNX SHARE, optionally with a project:

> Launch LYNX SHARE and open ~/Music/song.lynx

> Make a 4-bar lo-fi beat at 85 BPM with a kick, snare, hats and a Rhodes-style chord pattern, then play it

> The bass clashes with the chords in bar 3, fix it

It calls `lynx_launch`, which starts the app with its window and the socket. You can also start the app yourself;
the project must be the first argument:

```sh
LYNX /abs/path/song.lynx --control /tmp/lynx.sock
```

You can keep editing in the window too; the agent reads the project when it needs the current ids. It saves only
when you ask it to.

## Tools

| Group | Tools |
|---|---|
| App | `lynx_launch`, `lynx_status` |
| Reading | `get_project_state`, `get_notes`, `list_plugins`, `get_history` |
| Channels | `add_channel`, `set_channel`, `set_synth`, `delete_channel` |
| Patterns and notes | `add_pattern`, `rename_pattern`, `delete_pattern`, `write_notes`, `clear_notes` |
| Playlist | `place_pattern`, `delete_clip`, `set_tempo` |
| Transport | `play`, `pause`, `stop`, `transport_status`, `select` |
| History and file | `undo`, `redo`, `save_project`, `apply_commands` (several raw edits as one undo step) |

Positions and lengths are in beats by default (`unit="ticks"` for raw ticks). The socket protocol underneath is in
[docs/PROTOCOL.md](docs/PROTOCOL.md).

Not yet: plugin parameters and presets, mixer effects and routing, moving or resizing clips, loading samples,
rendering to audio.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LYNX_BIN` | a `LYNX-SHARE/build` next to this repo | the LYNX binary `lynx_launch` starts (set by `install.sh`) |
| `LYNX_SOCKET` | `/tmp/lynx.sock` | the control socket path |
| `LYNX_MCP_LOG_LEVEL` | `INFO` | server log level (logs go to stderr) |

The app's own output from `lynx_launch` goes to `$TMPDIR/lynx-share-mcp-app.log`.

## Troubleshooting

- **"LYNX SHARE is not listening"**: the app is not running with `--control`; ask the agent to call `lynx_launch`.
- **"did not start listening within 20 s"**: `LYNX_BIN` probably points at an official LYNX SHARE release, which has
  no socket. Point it at your build of the `control-socket` branch.
- **The demo song opened instead of my project**: the project path must be absolute and come before `--control`.

## Test

The end-to-end tests open a LYNX window on a temporary socket and close it at the end:

```sh
LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX .venv/bin/pytest -v   # macOS
LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX .venv/bin/pytest -v                           # Linux
```

## License

MIT for this server. LYNX SHARE, including the control-socket fork, is AGPL-3.0. The two are separate programs that
talk over a local socket.
