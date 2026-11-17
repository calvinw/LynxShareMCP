# lynx-share-mcp

An MCP server that lets an AI coding agent (Claude Code or Codex) make music in
[LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE), the open-source FL Studio-style DAW, while you watch: it reads the
project, adds channels (built-in instruments or plugins such as Serum 2), shapes plugin sounds through their
parameters, writes notes, builds patterns and the playlist, plays and undoes. Every edit is one undo step in the app,
so you can take back anything with Cmd+Z.

> **Uses LYNX SHARE's official Remote Control API** (`lynx-control/1`, LYNX SHARE 0.1.28 and later; see
> [docs/REMOTE_CONTROL.md](https://github.com/Ka1-S/LYNX-SHARE/blob/main/docs/REMOTE_CONTROL.md)). It is off by
> default: turn on **Settings > General > Remote control** in LYNX SHARE, or let `lynx_launch` start the app with it
> on. Earlier versions of this server needed the `control-socket` fork; this one does not.

## Requirements

- macOS or Linux (tested); Windows untested
- Python 3.10+
- LYNX SHARE 0.1.28 or later: an official release, or a build of upstream (CMake 3.22+, a C++20 compiler, Git; on
  Linux, LYNX SHARE's build dependencies first; see its README)
- Claude Code and/or Codex

## Install

Clone both repos side by side, build LYNX SHARE, then run the installer:

```sh
mkdir -p ~/develop && cd ~/develop
git clone --depth 1 https://github.com/Ka1-S/LYNX-SHARE.git   # --depth 1: skip the long history
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

> Clone github.com/Ka1-S/LYNX-SHARE (--depth 1) and github.com/calvinw/LynxShareMCP side by side in
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

It calls `lynx_launch`, which starts the app with its window and Remote Control on (`LYNX_CONTROL_ENABLED=1`). Or open
LYNX SHARE yourself and turn on Settings > General > Remote control; the server finds it through the app's private
discovery record (port and token) in LYNX's settings folder.

You can keep editing in the window too; every edit is checked against the project revision the agent last read, so
an edit planned on a stale view is refused instead of landing in the wrong place.

> Shape Serum 2 on the "Lead" channel: filter 1 on, low-pass, cutoff around 40%, and push Macro 1 up

The agent searches the plugin's parameters by name (`plugin_params`) and sets several at once as one undo step
(`set_plugin_params`). Values are normalized 0..1; each parameter's display value (e.g. `425`, `MG Low 12`, `On`)
says what it means. Switch and menu parameters snap to their steps (prefer the VST3 of a plugin: AUs often do not
report steps).

## Tools

| Group | Tools |
|---|---|
| App | `lynx_launch`, `lynx_status` |
| Reading | `get_project_state`, `get_notes`, `list_instruments` |
| Channels | `add_channel`, `set_channel`, `delete_channel` |
| Plugin sounds | `plugin_params`, `set_plugin_params` |
| Patterns and notes | `add_pattern`, `rename_pattern`, `delete_pattern`, `write_notes`, `clear_notes` |
| Playlist and mixer | `place_pattern`, `delete_clip`, `set_tempo`, `set_mixer_track` |
| Transport | `play`, `stop`, `transport_status`, `select` |
| History and raw | `undo`, `redo`, `remote_call` (any Remote Control operation, e.g. `effect.load`) |

Channels and patterns are named by id, name or index. Positions and lengths are in beats by default
(`unit="ticks"` for raw ticks).

What the Remote Control API cannot do yet, so neither can this server: save the project, pause, play from a given
position, open the piano roll or select a channel, shape the built-in Synth's sound, load samples, edit while playing.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LYNX_BIN` | a `LYNX-SHARE/build` next to this repo | the LYNX binary `lynx_launch` starts (set by `install.sh`) |
| `LYNX_CONTROL_DISCOVERY` | LYNX's settings folder | an absolute path to the app's discovery record (also passed to the app) |
| `LYNX_MCP_LOG_LEVEL` | `INFO` | server log level (logs go to stderr) |

The app's own output from `lynx_launch` goes to `$TMPDIR/lynx-share-mcp-app.log`.

## Troubleshooting

- **"Remote Control is not on"**: turn on Settings > General > Remote control, or ask the agent to call `lynx_launch`.
- **"stop playback ..."**: the API refuses edits while playing; stop first.
- **"Project changed since it was read"**: someone edited in the window in between; the agent reads again and retries.
- **A menu parameter is refused ("did not retain")**: the plugin did not accept a value between its steps; use the
  VST3 version of the plugin, which reports them.

## Test

The end-to-end tests open a LYNX window with Remote Control on in a throwaway settings profile (copying your plugin
scan, so Serum 2 is found on a Mac that has it) and close it at the end:

```sh
LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX .venv/bin/pytest -v   # macOS
LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX .venv/bin/pytest -v                           # Linux
```

## License

MIT for this server. LYNX SHARE is AGPL-3.0. The two are separate programs that talk over a local connection.
