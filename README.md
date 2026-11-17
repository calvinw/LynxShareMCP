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
- Python 3.10+ and Git
- LYNX SHARE 0.1.28 or later (an official release is fine)
- Claude Code and/or Codex

## Install

**1. Install LYNX SHARE.** Download the latest release from
[Ka1-S/LYNX-SHARE releases](https://github.com/Ka1-S/LYNX-SHARE/releases) (on a Mac, `LYNX-…-macos-universal.dmg`)
and drag LYNX SHARE into Applications. The app is not notarized, so the first time Control-click it and choose
**Open** (on macOS 15+, try once, then System Settings > Privacy & Security > **Open Anyway**), or run
`xattr -dr com.apple.quarantine /Applications/LYNX.app`.

**2. Install this server:**

```sh
mkdir -p ~/develop && cd ~/develop
git clone https://github.com/calvinw/LynxShareMCP.git
cd LynxShareMCP
./install.sh
```

`install.sh` creates `.venv`, finds the LYNX binary (a `LYNX-SHARE` build next to this folder or in `~/develop`,
else `/Applications/LYNX.app`), and registers the server as `lynx-share` with every client it finds:

```sh
./install.sh                    # Claude Code and Codex, whichever are installed
./install.sh --claude           # only Claude Code (user scope: all your projects)
./install.sh --codex            # only Codex (~/.codex/config.toml)
./install.sh --lynx /path/to/LYNX
```

Restart the client afterwards so it loads the tools. Run `./install.sh` again after moving either folder.

**Or let your agent do it.** After installing LYNX SHARE, paste this into Claude Code or Codex, then restart it when
it is done:

> Clone github.com/calvinw/LynxShareMCP into ~/develop and run its ./install.sh.

### Building LYNX SHARE yourself

On Linux, or to get the `remote-api-ui` additions (see [Tools](#tools)), build from source (CMake 3.22+, a C++20
compiler; on Linux, LYNX SHARE's build dependencies first; see its README) next to this folder, then run
`./install.sh` again:

```sh
cd ~/develop
git clone --depth 1 https://github.com/Ka1-S/LYNX-SHARE.git   # or: -b remote-api-ui https://github.com/calvinw/LYNX-SHARE.git
cd LYNX-SHARE
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target LYNX -j        # the first build takes a while
```

### Registering by hand

```sh
claude mcp add --scope user --transport stdio lynx-share \
  -e LYNX_BIN=/path/to/LYNX -- /path/to/LynxShareMCP/.venv/bin/python -m lynx_share_mcp

codex mcp add lynx-share --env LYNX_BIN=/path/to/LYNX -- /path/to/LynxShareMCP/.venv/bin/python -m lynx_share_mcp
```

On macOS the binary is inside the app bundle: `/Applications/LYNX.app/Contents/MacOS/LYNX` for a release,
`LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX` for a build.
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
| Transport | `play`, `pause`, `stop`, `transport_status`, `select` |
| Project | `save_project`, `new_project`, `undo`, `redo`, `remote_call` (any Remote Control operation, e.g. `effect.load`) |

Channels and patterns are named by id, name or index. Positions and lengths are in beats by default
(`unit="ticks"` for raw ticks).

`save_project`, `new_project`, `pause`, `play(from_position=...)` and `select(channel=..., piano_roll=True)` need five
small additions to the API (`project.save`, `project.new`, `transport.pause`, `ui.select`, and `transport.play`'s
`mode`/`pattern`/`fromTicks`) that are on the
[`remote-api-ui` branch](https://github.com/calvinw/LYNX-SHARE/tree/remote-api-ui) of calvinw/LYNX-SHARE (upstream
`main` plus those operations). With a stock release those tools say they are unavailable and everything else works;
on a stock build `select` can still change the current pattern and the mode, as an undo step.

Not possible through the API yet: shaping the built-in Synth's sound, loading samples, editing while playing, and
setting a plugin parameter from text such as "800 Hz".

[docs/REMOTE_API.md](docs/REMOTE_API.md) maps each tool to the API operations behind it and collects what we learned
about plugin parameters (Serum 2's 2,600 parameters, menu steps, AU vs VST3, renamed macros).

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
- **A search for "macro" finds nothing**: the preset renamed Serum 2's macros (e.g. `HPF CUTOFF`, `REVERB`); search
  for those names instead.
- **"... cannot save / pause through Remote Control"**: a stock LYNX SHARE; save with Cmd+S, or use a build of the
  `remote-api-ui` branch.

## Test

The end-to-end tests open a LYNX window with Remote Control on in a throwaway settings profile (copying your plugin
scan, so Serum 2 is found on a Mac that has it) and close it at the end:

```sh
LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX.app/Contents/MacOS/LYNX .venv/bin/pytest -v   # macOS
LYNX_BIN=../LYNX-SHARE/build/LYNX_artefacts/Release/LYNX .venv/bin/pytest -v                           # Linux
```

With a stock build, the test of save, pause and select is skipped; with a `remote-api-ui` build all four run.

## License

MIT for this server. LYNX SHARE is AGPL-3.0. The two are separate programs that talk over a local connection.
